"""Strict validation for the checked-in retrieval gold manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LoadedManifest:
    data: dict[str, Any]
    source_path: Path
    source_bytes: bytes
    manifest_bytes: bytes


def load_manifest(
    manifest_path: Path,
    repo_root: Path,
    *,
    selection_path: Path | None = None,
) -> LoadedManifest:
    """Load one hash-verified PDF from the frozen selection registry and validate gold shape."""
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Cannot read JSON manifest {manifest_path}: {type(exc).__name__}.") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError("Unsupported retrieval evaluation manifest schema.")
    source = manifest.get("source")
    cases = manifest.get("cases")
    if not isinstance(source, dict) or not isinstance(cases, list) or not cases:
        raise ValueError("Manifest must contain a source and at least one case.")
    relative = source.get("path")
    digest = source.get("sha256")
    physical_pages = source.get("physical_pages")
    if (
        not isinstance(relative, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or type(physical_pages) is not int
        or physical_pages < 1
    ):
        raise ValueError("Manifest source path, SHA-256, or physical page count is invalid.")
    source_path = _checked_source(repo_root, relative)
    selection_file = selection_path or repo_root / "docs/eval_pdf_selection.json"
    selection = _read_json(selection_file)
    selected_files = _validate_selection_registry(selection)
    matching = [entry for entry in selected_files if entry["path"] == relative and entry["sha256"] == digest]
    if len(matching) != 1:
        raise ValueError("Manifest source must match exactly one path and SHA-256 in eval_pdf_selection.json.")
    source_bytes = source_path.read_bytes()
    if matching[0]["bytes"] != len(source_bytes):
        raise ValueError(f"Selected PDF byte count disagrees with eval_pdf_selection.json for {relative}.")
    actual_digest = hashlib.sha256(source_bytes).hexdigest()
    if actual_digest != digest:
        raise ValueError(f"Selected PDF SHA-256 mismatch for {relative}.")
    if not source_bytes.startswith(b"%PDF-"):
        raise ValueError("Selected source does not have a PDF header.")
    _validate_cases(cases, physical_pages)
    return LoadedManifest(manifest, source_path, source_bytes, manifest_bytes)


def _validate_selection_registry(selection: Any) -> list[dict[str, Any]]:
    """Validate registry v1 before treating its file list as the corpus allowlist."""
    required = {
        "schema_version",
        "selected_on",
        "purpose",
        "corpus",
        "candidate_count",
        "selection_method",
        "seed",
        "candidate_paths_sha256",
        "files",
    }
    if not isinstance(selection, dict) or set(selection) != required:
        raise ValueError("PDF selection registry has missing or unknown fields.")
    if (
        type(selection.get("schema_version")) is not int
        or selection["schema_version"] != 1
        or not isinstance(selection.get("selected_on"), str)
        or not selection["selected_on"].strip()
        or not isinstance(selection.get("purpose"), str)
        or not selection["purpose"].strip()
        or not isinstance(selection.get("corpus"), str)
        or not selection["corpus"].strip()
        or type(selection.get("candidate_count")) is not int
        or selection["candidate_count"] < 1
        or not isinstance(selection.get("selection_method"), str)
        or not selection["selection_method"].strip()
        or type(selection.get("seed")) is not int
        or not _is_sha256(selection.get("candidate_paths_sha256"))
    ):
        raise ValueError("PDF selection registry metadata is invalid.")
    files = selection.get("files")
    if not isinstance(files, list) or not files or len(files) > selection["candidate_count"]:
        raise ValueError("PDF selection registry has an invalid file list.")
    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise ValueError("PDF selection registry file entry is malformed.")
        path = entry["path"]
        pure = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("")
        if (
            not isinstance(path, str)
            or not path.strip()
            or pure.is_absolute()
            or not pure.parts
            or ".." in pure.parts
            or path in seen_paths
            or not _is_sha256(entry.get("sha256"))
            or type(entry.get("bytes")) is not int
            or entry["bytes"] < 1
        ):
            raise ValueError("PDF selection registry contains duplicate or invalid file metadata.")
        seen_paths.add(path)
    return files


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Cannot read JSON manifest {path}: {type(exc).__name__}.") from exc


def _checked_source(repo_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("Selected PDF path must be a repository-relative path without traversal.")
    root = repo_root.resolve()
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink paths are not allowed for evaluation sources.")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("Selected PDF path must resolve to a regular file inside the repository.")
    return path


def _validate_cases(cases: list[object], physical_pages: int) -> None:
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each manifest case must be an object.")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise ValueError("Manifest case IDs must be nonempty and unique.")
        case_ids.add(case_id)
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError(f"Case {case_id} has no question.")
        if not isinstance(case.get("category"), str) or not case["category"].strip():
            raise ValueError(f"Case {case_id} has no category.")
        if (
            not isinstance(case.get("expected_facts"), list)
            or not case["expected_facts"]
            or not all(isinstance(fact, str) and fact.strip() for fact in case["expected_facts"])
        ):
            raise ValueError(f"Case {case_id} expected_facts must be a nonempty list of nonempty strings.")
        kind = case.get("kind")
        groups = case.get("evidence_groups")
        if kind not in {"answerable", "unsupported"} or not isinstance(groups, list):
            raise ValueError(f"Case {case_id} has an invalid kind or evidence_groups.")
        if kind == "unsupported":
            if groups:
                raise ValueError(f"Unsupported case {case_id} cannot have positive evidence groups.")
            continue
        if not groups:
            raise ValueError(f"Answerable case {case_id} requires evidence groups.")
        group_ids: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(f"Case {case_id} evidence groups must be objects.")
            group_id = group.get("id")
            pages = group.get("pages")
            alternatives = group.get("anchor_alternatives")
            if not isinstance(group_id, str) or not group_id.strip() or group_id in group_ids:
                raise ValueError(f"Case {case_id} evidence group IDs must be nonempty and unique.")
            group_ids.add(group_id)
            if (
                not isinstance(pages, list)
                or not pages
                or any(type(page) is not int or not 1 <= page <= physical_pages for page in pages)
            ):
                raise ValueError(f"Evidence group {group_id} contains an invalid physical page.")
            if (
                not isinstance(alternatives, list)
                or not alternatives
                or any(
                    not isinstance(combo, list)
                    or not combo
                    or any(
                        not isinstance(anchor, str) or not anchor.strip() or not normalize_anchor(anchor)
                        for anchor in combo
                    )
                    for combo in alternatives
                )
            ):
                raise ValueError(f"Evidence group {group_id} needs nonempty AND anchor combinations.")


def normalize_anchor(value: str) -> str:
    """Reject anchors that become empty under the scorer's conservative normalization."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("−", "-").replace("|", " ")
    normalized = re.sub(r"(?<=\w)[\-\u2010\u2011]\s*\n\s*(?=\w)", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()
