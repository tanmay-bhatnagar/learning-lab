"""CV profile routes use an isolated parser and never create topic attachments."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from lab.web.app import create_app

PDF = b"%PDF-1.7\nsynthetic profile CV\n%%EOF"
COMPLETE_TEXT = "line 1\nrepeat marker\nrepeat marker\nline 4\n"


def parsed_cv(data: bytes, filename: str, parser: str):
    assert data == PDF
    assert filename == "Chosen CV.pdf"
    assert parser == "docling"
    return {
        "canonical_text": COMPLETE_TEXT,
        "native_document": {"text": COMPLETE_TEXT, "source": "synthetic docling"},
        "parser": "docling",
        "parser_version": "synthetic-1",
        "diagnostics": {"status": "ready", "findings": []},
    }


def test_profile_cv_upload_preserves_name_original_and_complete_canonical_text(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parsed_cv,
        )
    )

    initial = client.get("/api/profile")
    assert initial.status_code == 200
    assert initial.json()["active_cv_id"] is None
    assert "canonical_text" not in str(initial.json())
    assert str(tmp_path) not in str(initial.json())

    uploaded = client.post(
        "/api/profile/cvs",
        files={"file": ("upload-name.pdf", PDF, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "docling"},
    )
    assert uploaded.status_code == 201
    cv = uploaded.json()
    assert cv["original_name"] == "Chosen CV.pdf"
    assert cv["status"] == "ready"
    assert cv["parser"] == "docling"

    preview = client.get(f"/api/profile/cvs/{cv['id']}/text")
    assert preview.status_code == 200
    assert preview.json()["text"] == COMPLETE_TEXT
    assert preview.json()["text"].count("repeat marker") == 2
    original = client.get(f"/api/profile/cvs/{cv['id']}/original")
    assert original.status_code == 200
    assert original.content == PDF
    assert not list((tmp_path / "Learning").glob("**/*Chosen CV*"))


def test_profile_cv_duplicate_name_and_revision_checked_select_revoke(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parsed_cv,
        )
    )
    cv = client.post(
        "/api/profile/cvs",
        files={"file": ("ignored.pdf", PDF, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "docling"},
    ).json()
    conflict = client.post(
        "/api/profile/cvs",
        files={"file": ("different.pdf", PDF, "application/pdf")},
        data={"original_name": "chosen cv.PDF", "parser": "docling"},
    )
    assert conflict.status_code == 409

    selected = client.post(f"/api/profile/cvs/{cv['id']}/select", json={"expected_revision": 1})
    assert selected.status_code == 200
    assert selected.json()["active_cv_id"] == cv["id"]
    stale = client.post(f"/api/profile/cvs/{cv['id']}/revoke", json={"expected_revision": 1})
    assert stale.status_code == 409
    assert client.get("/api/profile").json()["active_cv_id"] == cv["id"]

    revoked = client.post(f"/api/profile/cvs/{cv['id']}/revoke", json={"expected_revision": 2})
    assert revoked.status_code == 200
    assert revoked.json()["active_cv_id"] is None
    assert revoked.json()["cvs"][0]["revoked"] is True
    assert client.get(f"/api/profile/cvs/{cv['id']}/text").status_code == 409


def test_duplicate_upload_is_rejected_before_parser_runs(tmp_path):
    calls = []

    def parser(data: bytes, filename: str, selected_parser: str):
        calls.append((filename, selected_parser))
        return parsed_cv(data, "Chosen CV.pdf", selected_parser)

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parser,
        )
    )
    upload = {
        "files": {"file": ("upload.pdf", PDF, "application/pdf")},
        "data": {"original_name": "Chosen CV.pdf", "parser": "docling"},
    }
    assert client.post("/api/profile/cvs", **upload).status_code == 201
    assert client.post("/api/profile/cvs", **upload).status_code == 409
    assert calls == [("Chosen CV.pdf", "docling")]


def test_selection_rejects_tampered_extraction(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parsed_cv,
        )
    )
    cv = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "docling"},
    ).json()
    (tmp_path / "Profile" / "CVs" / ".records" / cv["id"] / "extracted.txt").write_text("tampered")
    selected = client.post(f"/api/profile/cvs/{cv['id']}/select", json={"expected_revision": 1})
    assert selected.status_code == 500
    assert client.get("/api/profile").status_code == 500


def test_profile_parser_failure_preserves_original_but_never_selects(tmp_path):
    def fail_parser(_data: bytes, _filename: str, _parser: str):
        raise ValueError("synthetic parser failure")

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=fail_parser,
        )
    )
    response = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "Failed CV.pdf", "parser": "docling"},
    )
    assert response.status_code == 201
    cv = response.json()
    assert cv["status"] == "error"
    assert client.get(f"/api/profile/cvs/{cv['id']}/original").content == PDF
    assert client.post(f"/api/profile/cvs/{cv['id']}/select", json={"expected_revision": 1}).status_code == 409
    assert client.get("/api/profile").json()["active_cv_id"] is None


def test_unexpected_parser_programming_error_is_not_saved_as_failed_cv(tmp_path):
    def broken_parser(_data: bytes, _filename: str, _parser: str):
        raise TypeError("synthetic parser programming error")

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=broken_parser,
        ),
        raise_server_exceptions=False,
    )
    response = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "Broken CV.pdf", "parser": "docling"},
    )

    assert response.status_code == 500
    assert client.get("/api/profile").json()["cvs"] == []


def test_legacy_v1_cv_without_parser_metadata_remains_previewable(tmp_path):
    profile_root = tmp_path / "Profile"
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
            profile_parser=parsed_cv,
        )
    )
    uploaded = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "docling"},
    ).json()
    metadata_path = profile_root / "profile.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["cvs"][0].pop("parser")
    metadata["cvs"][0].pop("parser_version")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    preview = client.get(f"/api/profile/cvs/{uploaded['id']}/text")

    assert preview.status_code == 200
    assert preview.json()["parser"] == "unknown"
    assert preview.json()["parser_version"] == "unknown"
    assert preview.json()["text"] == COMPLETE_TEXT


def test_profile_upload_rejects_path_name_non_pdf_and_oversized_bytes(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parsed_cv,
            max_upload_bytes=64,
        )
    )
    unsafe = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "../Chosen CV.pdf", "parser": "docling"},
    )
    assert unsafe.status_code == 400
    wrong_type = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.txt", PDF, "text/plain")},
        data={"original_name": "Chosen CV.txt", "parser": "docling"},
    )
    assert wrong_type.status_code == 400
    oversized = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", b"%PDF-" + b"x" * 100, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "docling"},
    )
    assert oversized.status_code == 413


def test_unsupported_parser_is_rejected_without_invoking_parser(tmp_path):
    calls = []

    def parser(*args):
        calls.append(args)
        raise AssertionError("unsupported parser must be rejected before invocation")

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parser,
        )
    )
    response = client.post(
        "/api/profile/cvs",
        files={"file": ("upload.pdf", PDF, "application/pdf")},
        data={"original_name": "Chosen CV.pdf", "parser": "other"},
    )
    assert response.status_code == 422
    assert calls == []


def test_profile_parser_failure_and_wrong_identifier_do_not_expose_paths(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            profile_parser=parsed_cv,
        )
    )
    response = client.get("/api/profile/cvs/../../etc/passwd/original")
    assert response.status_code in {400, 404}
    assert "etc/passwd" not in response.text

