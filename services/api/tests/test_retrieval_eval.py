"""Regression checks for anchored retrieval-evaluation contracts."""

from __future__ import annotations

import hashlib
import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.retrieval import runner as eval_runner
from evals.retrieval.manifest import LoadedManifest, load_manifest
from evals.retrieval.runner import (
    SIMULATED_ANSWER,
    SIMULATED_THINKING,
    SimulatedGateway,
    _check_trace,
    _prepared_record,
    _stage_prepared_workspace,
    _validate_hybrid_index,
)
from evals.retrieval.scorer import group_matches, score_case
from lab.index import TopicIndex
from lab.retrieval import search
from lab.storage import write_json
from lab.web.app import create_app


def _manifest_files(tmp_path: Path, *, schema_version: int = 1) -> tuple[Path, Path, Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / "paper.pdf"
    pdf_bytes = b"%PDF-1.7\nsynthetic test source"
    pdf.write_bytes(pdf_bytes)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    manifest = {
        "schema_version": schema_version,
        "source": {"path": "paper.pdf", "sha256": digest, "physical_pages": 2},
        "cases": [
            {
                "id": "case-one",
                "category": "exact",
                "question": "What is the value?",
                "kind": "answerable",
                "evidence_groups": [
                    {"id": "value", "pages": [1], "anchor_alternatives": [["value 42"]]},
                    {"id": "model", "pages": [2], "anchor_alternatives": [["model tiny"]]},
                ],
                "expected_facts": ["Value is 42."],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "selected_on": "2026-10-03",
                "purpose": "synthetic registry test",
                "corpus": "synthetic",
                "candidate_count": 2,
                "selection_method": "fixed test data",
                "seed": 1,
                "candidate_paths_sha256": "a" * 64,
                "files": [{"path": "paper.pdf", "sha256": digest, "bytes": len(pdf_bytes)}],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, selection_path, pdf, manifest


def _runtime_policy(tmp_path: Path) -> Path:
    path = tmp_path / "runtime-policy.md"
    path.write_text("Synthetic isolated runtime policy for retrieval evaluation tests.\n", encoding="utf-8")
    return path


def test_manifest_accepts_exact_selected_pdf_and_rejects_boolean_schema(tmp_path: Path):
    manifest_path, selection, _pdf, _ = _manifest_files(tmp_path)
    loaded = load_manifest(manifest_path, tmp_path, selection_path=selection)
    assert loaded.source_bytes.startswith(b"%PDF-")
    assert loaded.manifest_bytes == manifest_path.read_bytes()

    bad_manifest, selection, _pdf, _ = _manifest_files(tmp_path / "bad", schema_version=True)
    with pytest.raises(ValueError, match="schema"):
        load_manifest(bad_manifest, bad_manifest.parent, selection_path=selection)


def test_manifest_accepts_registered_second_pdf_and_rejects_unregistered_or_duplicate_entries(tmp_path: Path):
    manifest_path, selection_path, _first_pdf, data = _manifest_files(tmp_path)
    second_bytes = b"%PDF-1.7\nsecond selected PDF"
    second_pdf = tmp_path / "second.pdf"
    second_pdf.write_bytes(second_bytes)
    second_digest = hashlib.sha256(second_bytes).hexdigest()
    data["source"] = {"path": "second.pdf", "sha256": second_digest, "physical_pages": 2}
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    registry = json.loads(selection_path.read_text(encoding="utf-8"))
    registry["files"].append({"path": "second.pdf", "sha256": second_digest, "bytes": len(second_bytes)})
    selection_path.write_text(json.dumps(registry), encoding="utf-8")
    loaded = load_manifest(manifest_path, tmp_path, selection_path=selection_path)
    assert loaded.source_path == second_pdf
    assert loaded.source_bytes == second_bytes

    registry["files"] = [registry["files"][0]]
    selection_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one path and SHA-256"):
        load_manifest(manifest_path, tmp_path, selection_path=selection_path)

    registry["files"].append(registry["files"][0].copy())
    selection_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate or invalid"):
        load_manifest(manifest_path, tmp_path, selection_path=selection_path)

    registry["files"] = [
        {
            "path": "paper.pdf",
            "sha256": hashlib.sha256((tmp_path / "paper.pdf").read_bytes()).hexdigest(),
            "bytes": (tmp_path / "paper.pdf").stat().st_size,
        },
        {"path": "second.pdf", "sha256": second_digest, "bytes": len(second_bytes)},
    ]
    registry["schema_version"] = True
    selection_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="registry metadata is invalid"):
        load_manifest(manifest_path, tmp_path, selection_path=selection_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["cases"][0].pop("category"),
        lambda data: data["cases"][0].update(expected_facts=[]),
        lambda data: data["cases"][0]["evidence_groups"][0].update(anchor_alternatives=[["|"]]),
    ],
)
def test_manifest_rejects_empty_required_fields_and_normalized_empty_anchor(tmp_path: Path, mutate):
    manifest_path, selection, _pdf, data = _manifest_files(tmp_path)
    mutate(data)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(manifest_path, tmp_path, selection_path=selection)


def _hit(chunk_id: str, rank: int, page: int, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "file_id": "file-1",
        "pages": [page],
        "text": text,
        "trace": {"fusion": {"rank": rank, "score": 1 / rank}},
    }


def test_score_requires_page_and_same_chunk_and_keeps_gold_denominator(tmp_path: Path):
    case = _manifest_files(tmp_path)[3]["cases"][0]
    indexed = [
        {"pages": [2], "text": "value 42"},
        {"pages": [1], "text": "model tiny"},
    ]
    hits = [_hit("wrong-page", 1, 2, "value 42"), _hit("split-a", 2, 1, "value"), _hit("split-b", 3, 1, "42")]
    result = score_case(case, indexed, hits, [], top_k=3)
    assert result["status"] == "extraction_limited"
    assert result["extraction"]["total_groups"] == 2
    assert result["retrieval"]["recall_at_k"] is None


def test_score_rejects_hits_above_the_requested_top_k(tmp_path: Path):
    case = _manifest_files(tmp_path)[3]["cases"][0]
    index = [
        {"pages": [1], "text": "value 42"},
        {"pages": [2], "text": "model tiny"},
    ]
    hits = [_hit(f"irrelevant-{rank}", rank, 1, "unrelated") for rank in range(1, 7)]
    hits.append(_hit("relevant", 7, 1, "value 42"))
    with pytest.raises(ValueError, match="top_k bound"):
        score_case(case, index, hits, [], top_k=6)


def test_score_rejects_missing_or_noncontiguous_fusion_ranks(tmp_path: Path):
    case = _manifest_files(tmp_path)[3]["cases"][0]
    with pytest.raises(ValueError, match="positive integer"):
        score_case(case, [], [{"trace": {"fusion": {"rank": None}}}], [], top_k=6)
    with pytest.raises(ValueError, match="contiguous"):
        score_case(case, [], [_hit("gap", 2, 1, "x")], [], top_k=6)


def test_score_positive_partial_recall_first_rank_and_retained_subset(tmp_path: Path):
    case = _manifest_files(tmp_path)[3]["cases"][0]
    indexed = [
        {"pages": [1], "text": "Value | 42"},
        {"pages": [2], "text": "Model\nTiny"},
    ]
    hits = [_hit("value-hit", 1, 1, "Value | 42"), _hit("noise", 2, 1, "unrelated")]
    scored = score_case(case, indexed, hits, ["noise"], top_k=2)
    assert scored["extraction"]["coverage"] == 1
    assert scored["retrieval"]["recall_at_k"] == pytest.approx(0.5)
    assert scored["retrieval"]["first_relevant_rank"] == 1
    assert scored["retrieval"]["reciprocal_rank"] == 1
    assert scored["retrieval"]["all_required_at_k"] is False
    assert scored["retained"]["recall_at_k"] == 0


def test_numeric_anchor_requires_a_token_boundary():
    group = {"pages": [1], "anchor_alternatives": [["55.2"]]}
    assert group_matches(group, [{"pages": [1], "text": "Relative error reduction 55.2%"}])
    assert not group_matches(group, [{"pages": [1], "text": "Relative error reduction 55.21%"}])
    negative_threshold = {"pages": [1], "anchor_alternatives": [["lower than −1"]]}
    assert group_matches(negative_threshold, [{"pages": [1], "text": "lower than -1."}])
    assert not group_matches(negative_threshold, [{"pages": [1], "text": "lower than -1.5"}])


@pytest.mark.parametrize(
    "body",
    [
        (
            "Table 17. Whisper training hyperparameters. Updates 655360. Batch Size 1024. "
            "Table 18. Hyperparameters changed for Whisper Large V2. Updates 1048576. Batch Size 256."
        ),
        (
            "Table 17. Whisper training hyperparameters. Updates, Value = 655360. "
            "Batch Size, Value = 1024. Table 18. Hyperparameters changed for Whisper Large V2. "
            "Updates, Value = 1048576. Batch Size, Value = 256."
        ),
    ],
    ids=["raw-swapped-table-bodies", "serialized-swapped-table-bodies"],
)
def test_whisper_table_gold_preserves_original_and_v2_table_association(body: str):
    repo_root = Path(__file__).resolve().parents[3]
    data = json.loads((repo_root / "evals/retrieval/whisper.v1.json").read_text(encoding="utf-8"))
    case = next(item for item in data["cases"] if item["id"] == "whisper-08-large-v2-training")
    groups = {item["id"]: item for item in case["evidence_groups"]}
    swapped_chunk = {"pages": [28], "text": body}
    assert not group_matches(groups["original_updates_row"], [swapped_chunk])
    assert not group_matches(groups["original_batch_row"], [swapped_chunk])
    assert not group_matches(groups["v2_updates_row"], [swapped_chunk])
    assert not group_matches(groups["v2_batch_row"], [swapped_chunk])


def test_prepared_run_rejects_unsafe_path_and_source_mismatch(tmp_path: Path):
    run = tmp_path / ".local/evals/run-1"
    run.mkdir(parents=True)
    (run / "result.v1.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="below this repository"):
        _prepared_record(run, repo, "a" * 64, "paper.pdf")

    symlink_repo = tmp_path / "symlink-repo"
    linked_run = symlink_repo / ".local/evals/run-linked"
    linked_run.mkdir(parents=True)
    outside_result = tmp_path / "outside-result.json"
    outside_result.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    (linked_run / "result.v1.json").symlink_to(outside_result)
    with pytest.raises(ValueError, match="symlink"):
        _prepared_record(linked_run, symlink_repo, "a" * 64, "paper.pdf")

    good_run = repo / ".local/evals/run-1"
    good_run.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "run_id": "run-1",
        "source": {"path": "paper.pdf", "sha256": "a" * 64},
        "provenance": {
            "parser": "docling",
            "parser_version": "1",
            "index_mode": "hybrid",
            "retrieval_top_k": 6,
            "context_limit": 8192,
        },
        "mode": "hybrid",
        "exit_status": "completed_descriptive_baseline",
        "topic_id": "topic-id",
        "file_id": "file-id",
    }
    (good_run / "result.v1.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="source or parser provenance"):
        _prepared_record(good_run, repo, "b" * 64, "paper.pdf")
    with pytest.raises(ValueError, match="source or parser provenance"):
        _prepared_record(good_run, repo, "a" * 64, "second.pdf")


def test_prepared_workspace_rejects_settings_symlink(tmp_path: Path):
    source = tmp_path / "source-run"
    topic = source / "Learning/topic-1"
    topic.mkdir(parents=True)
    (topic / "topic.json").write_text(json.dumps({"id": "topic-1"}), encoding="utf-8")
    outside_settings = tmp_path / "settings.json"
    outside_settings.write_text("{}", encoding="utf-8")
    (source / "settings.json").symlink_to(outside_settings)
    with pytest.raises(ValueError, match="settings file.*unsafe"):
        _stage_prepared_workspace(source, tmp_path / "new-run", "topic-1")


def test_hybrid_index_requires_exact_model_and_complete_vector_metadata(tmp_path: Path):
    sqlite3 = __import__("sqlite3")
    db = tmp_path / "retrieval.sqlite"
    connection = sqlite3.connect(db)
    connection.executescript(
        "CREATE TABLE chunks (chunk_id TEXT, file_id TEXT, chunk_index INTEGER, has_embedding INTEGER);"
        "CREATE TABLE chunk_embeddings (chunk_id TEXT, model TEXT, dimension INTEGER, vector BLOB);"
        "INSERT INTO chunks VALUES ('c1', 'f1', 1, 1);"
        "INSERT INTO chunk_embeddings VALUES ('c1', 'nomic:latest#v1', 2, X'0000000000000000');"
    )
    connection.commit()
    connection.close()
    assert _validate_hybrid_index(db, "f1", "nomic:latest#v1") == {
        "chunk_count": 1,
        "embedding_model": "nomic:latest#v1",
        "dimension": 2,
    }
    with pytest.raises(ValueError, match="mismatched embedding metadata"):
        _validate_hybrid_index(db, "f1", "nomic:latest#other-format")


def test_run_failure_artifact_keeps_source_manifest_settings_and_fingerprint(tmp_path: Path, monkeypatch):
    manifest_path, _selection, pdf_path, _data = _manifest_files(tmp_path)
    loaded = LoadedManifest(
        data=json.loads(manifest_path.read_text(encoding="utf-8")),
        source_path=pdf_path,
        source_bytes=pdf_path.read_bytes(),
        manifest_bytes=manifest_path.read_bytes(),
    )

    async def fail_run(*_args, **_kwargs):
        raise RuntimeError("private detail must not be persisted")

    monkeypatch.setattr(eval_runner, "_execute_evaluation", fail_run)
    with pytest.raises(RuntimeError):
        asyncio.run(
            eval_runner.run_evaluation(
                tmp_path,
                loaded,
                mode="hybrid",
                top_k=6,
                context_limit=8192,
                runtime_policy_path=_runtime_policy(tmp_path),
            )
        )
    result_path = next((tmp_path / ".local/evals").glob("*/result.v1.json"))
    failure = json.loads(result_path.read_text(encoding="utf-8"))
    assert failure["exit_status"] == "infrastructure_failed"
    assert failure["source"]["sha256"] == hashlib.sha256(loaded.source_bytes).hexdigest()
    assert failure["provenance"]["manifest_sha256"] == hashlib.sha256(loaded.manifest_bytes).hexdigest()
    policy_bytes = (tmp_path / "runtime-policy.md").read_bytes()
    assert failure["provenance"]["runtime_policy"] == {
        "sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "snapshot": "runtime-policy.md",
    }
    assert (result_path.parent / "runtime-policy.md").read_bytes() == policy_bytes
    assert failure["provenance"]["relevant_source_sha256"] == {}
    assert failure["requested_settings"] == {
        "mode": "hybrid",
        "top_k": 6,
        "context_limit": 8192,
        "prepared_from_run": None,
    }
    assert failure["failure"] == {"exception_type": "RuntimeError", "stage": "run"}
    assert "private detail" not in result_path.read_text(encoding="utf-8")


def test_run_fails_if_policy_snapshot_changes_during_evaluation(tmp_path: Path, monkeypatch):
    manifest_path, _selection, pdf_path, _data = _manifest_files(tmp_path)
    loaded = LoadedManifest(
        data=json.loads(manifest_path.read_text(encoding="utf-8")),
        source_path=pdf_path,
        source_bytes=pdf_path.read_bytes(),
        manifest_bytes=manifest_path.read_bytes(),
    )
    policy_path = _runtime_policy(tmp_path)
    initial_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()

    async def mutate_policy(*_args, **kwargs):
        kwargs["runtime_policy_path"].write_text("Mutated policy during evaluation.\n", encoding="utf-8")
        return {
            "exit_status": "completed_descriptive_baseline",
            "provenance": {},
            "cases": [],
            "hard_failures": [],
            "readiness": "infrastructure_validated",
        }

    monkeypatch.setattr(eval_runner, "_execute_evaluation", mutate_policy)
    with pytest.raises(RuntimeError, match="Runtime policy snapshot changed"):
        asyncio.run(
            eval_runner.run_evaluation(
                tmp_path,
                loaded,
                mode="keyword",
                top_k=6,
                context_limit=16384,
                runtime_policy_path=policy_path,
            )
        )

    result_path = next((tmp_path / ".local/evals").glob("*/result.v1.json"))
    failure = json.loads(result_path.read_text(encoding="utf-8"))
    state = json.loads((result_path.parent / "run_state.json").read_text(encoding="utf-8"))
    assert failure["exit_status"] == "infrastructure_failed"
    assert failure["provenance"]["runtime_policy"]["sha256"] == initial_sha256
    assert state["status"] == "infrastructure_failed"


def test_unsupported_case_is_diagnostic_with_null_quality_metrics():
    case = {
        "id": "unsupported",
        "category": "absent_answer",
        "kind": "unsupported",
        "evidence_groups": [],
    }
    scored = score_case(case, [], [], [], top_k=6)
    assert scored["abstention"] == "not_assessed"
    assert scored["retrieval"]["recall_at_k"] is None
    assert scored["retained"]["all_required_at_k"] is None


def test_trace_invariants_detect_projection_privacy_and_lifecycle_mutations():
    hit = _hit("chunk-1", 1, 3, "some evidence")
    expected = [{"chunk_id": "chunk-1", "file_id": "file-1", "page": 3, "rank": 1, "score": 1.0}]
    trace = {
        "id": "trace-1",
        "topic_id": "topic-1",
        "conversation_id": "conversation-1",
        "schema_version": 1,
        "started_at": "2026-10-03T00:00:00+00:00",
        "finished_at": "2026-10-03T00:00:00+00:00",
        "status": "completed",
        "query_chars": 8,
        "requested_think": None,
        "selected_file_ids": ["file-1"],
        "retrieval_top_k": 6,
        "requested_model": "eval-simulated",
        "actual_model": "eval-simulated",
        "context_limit": 8192,
        "topic_id": "topic-1",
        "embedding_model": "",
        "retrieval_mode": "keyword",
        "retrieval_warning": None,
        "prompt_budget": 8192,
        "context_used": 10,
        "final_context": {"used": 10, "limit": 8192, "estimated": True, "truncated_messages": 0},
        "cleanup_error": None,
        "retrieved_chunks": expected,
        "retained_chunks": expected,
        "user_saved": True,
        "assistant_saved": True,
        "user_message_index": 0,
        "assistant_message_index": 1,
        "conversation_id": "conversation-1",
        "preflight_ms": 0,
        "retrieval_ms": 0,
        "generation_ms": 1,
        "first_output_ms": 1,
        "total_ms": 1,
        "output_chars": len(SIMULATED_ANSWER),
        "thinking_chars": len(SIMULATED_THINKING),
        "stage": "complete",
        "error": None,
    }
    args = (
        trace,
        [hit],
        "file-1",
        "conversation-1",
        0,
        1,
        6,
        8192,
        "topic-1",
        ["chunk-1"],
        "",
        "keyword",
        8,
        {"used": 10, "limit": 8192, "estimated": True, "truncated_messages": 0},
        ["some\n evidence"],
    )
    assert _check_trace(*args) == []
    broken = deepcopy(trace)
    broken["retained_chunks"] = [{**expected[0], "score": 99}]
    assert "retained_trace_projection_mismatch" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["retrieved_chunks"][0]["text"] = "private passage"
    assert "trace_contains_duplicated_content" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["total_ms"] = float("nan")
    assert "negative_or_invalid_total_ms" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["debug_payload"] = {"blob": {"passage": "private fake-generation content"}}
    assert "trace_schema_fields_mismatch" in _check_trace(broken, *args[1:])
    assert "trace_contains_duplicated_content" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["retrieval_ms"] = None
    assert "missing_retrieval_ms" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["id"] = "prefix\nsome\n evidence\nsuffix"
    assert "trace_contains_private_text_value" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["schema_version"] = 999
    assert "trace_schema_version_mismatch" in _check_trace(broken, *args[1:])
    broken = deepcopy(trace)
    broken["retrieved_chunks"][0]["rank"] = True
    assert "trace_chunk_values_invalid" in _check_trace(broken, *args[1:])


def test_production_chat_captures_same_retrieval_and_trace_scope(tmp_path: Path):
    gateway = SimulatedGateway()
    captured = {}

    async def capture(store, topic, query, **kwargs):
        result = await search(store, topic, query, **kwargs)
        captured[query] = result
        return result

    app = create_app(
        tmp_path / "Learning",
        tmp_path / "state" / "settings.json",
        runtime_policy_path=_runtime_policy(tmp_path),
        model_backend=gateway,
        retriever=capture,
    )
    with TestClient(app) as client:
        topic_id = client.post("/api/topics", json={"name": "Eval route"}).json()["id"]
        settings_response = client.put(
            "/api/settings",
            json={
                "model": "eval-simulated",
                "context_limit": 8192,
                "parser": "docling",
                "embedding_model": "",
                "retrieval_top_k": 6,
            },
        )
        assert settings_response.status_code == 200
        file_id = "file-one"
        write_json(
            app.state.deps.store.topic(topic_id) / "files.json",
            [
                {
                    "id": file_id,
                    "name": "paper.pdf",
                    "original_name": "paper.pdf",
                    "status": "ready",
                    "parser": "docling",
                    "index_status": "ready",
                    "index_mode": "keyword",
                }
            ],
        )
        with TopicIndex(app.state.deps.store.file_path(topic_id, "retrieval.sqlite")) as index:
            index.replace_file(
                file_id,
                [
                    {
                        "chunk_id": f"{file_id}:text:000001",
                        "file_id": file_id,
                        "file_name": "paper.pdf",
                        "chunk_index": 1,
                        "text": "On page one the reported value is 42.",
                        "headings": [],
                        "pages": [1],
                        "bboxes": [],
                        "asset_ids": [],
                        "content_hash": "value-hash",
                    }
                ],
            )
        conversation_id = client.post(
            f"/api/topics/{topic_id}/conversations", json={"title": "evaluation case"}
        ).json()["id"]
        question = "What value was reported?"
        response = client.post(
            f"/api/topics/{topic_id}/conversations/{conversation_id}/chat",
            json={
                "message": question,
                "file_ids": [file_id],
                "model": "eval-simulated",
                "context_limit": 8192,
            },
        )
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        done = next(event for event in events if event["type"] == "done")
        captured_result = captured[question]
        traces = client.get(f"/api/topics/{topic_id}/query-traces", params={"conversation_id": conversation_id}).json()[
            "traces"
        ]
        assert len(traces) == 1
        citation_ids = [item["chunk_id"] for item in done["retrieval"]["citations"]]
        retained_in_search_order = [
            hit["chunk_id"] for hit in captured_result["hits"] if hit["chunk_id"] in set(citation_ids)
        ]
        saved_session = client.get(f"/api/topics/{topic_id}/conversations/{conversation_id}/messages").json()
        assert done["context"] == saved_session["context"]
        assert (
            _check_trace(
                traces[0],
                captured_result["hits"],
                file_id,
                conversation_id,
                0,
                1,
                6,
                8192,
                topic_id,
                retained_in_search_order,
                "",
                captured_result["mode"],
                len(question),
                saved_session["context"],
                [question, SIMULATED_ANSWER, SIMULATED_THINKING, "On page one the reported value is 42."],
            )
            == []
        )
        saved = saved_session["messages"]
        assert [message["role"] for message in saved] == ["user", "assistant"]
        assert saved[1]["retrieval"]["citations"] == done["retrieval"]["citations"]
        unrelated = client.post(f"/api/topics/{topic_id}/conversations", json={"title": "unrelated"}).json()["id"]
        assert (
            client.get(f"/api/topics/{topic_id}/query-traces", params={"conversation_id": unrelated}).json()["traces"]
            == []
        )
        fit_conv = client.post(
            f"/api/topics/{topic_id}/conversations", json={"title": "tight context fit check"}
        ).json()["id"]
        too_large_question = "What value was reported? " + "padding " * 2000
        fit_response = client.post(
            f"/api/topics/{topic_id}/conversations/{fit_conv}/chat",
            json={
                "message": too_large_question,
                "file_ids": [file_id],
                "model": "eval-simulated",
                "context_limit": 1024,
            },
        )
        assert fit_response.status_code == 422
        assert client.get(f"/api/topics/{topic_id}/conversations/{fit_conv}/messages").json()["messages"] == []
        fit_traces = client.get(f"/api/topics/{topic_id}/query-traces", params={"conversation_id": fit_conv}).json()[
            "traces"
        ]
        assert len(fit_traces) == 1
        assert fit_traces[0]["status"] == "rejected"
