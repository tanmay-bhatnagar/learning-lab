"""Manual proficiency persists independently of CV and topic state."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lab.web.app import create_app


def test_manual_proficiency_is_available_without_cv_or_topics_and_survives_reload(tmp_path):
    app = create_app(
        tmp_path / "Learning",
        tmp_path / "state/settings.json",
        profile_root=tmp_path / "Profile",
    )
    client = TestClient(app)
    initial = client.get("/api/profile/proficiency")
    assert initial.status_code == 200
    assert initial.json() == {"schema_version": 1, "revision": 0, "entries": []}

    created = client.post(
        "/api/profile/proficiency/entries",
        json={
            "expected_revision": 0,
            "concept": "Python programming",
            "comfort": "refresher",
            "notes": "Used it before; would like a quick review.",
        },
    )
    assert created.status_code == 201
    entry = created.json()["entries"][0]
    assert entry["source_kind"] == "user_manual"
    assert entry["comfort"] == "refresher"
    assert "topic_id" not in entry
    assert "assessment_id" not in entry

    edited = client.patch(
        f"/api/profile/proficiency/entries/{entry['id']}",
        json={"expected_revision": 1, "comfort": "comfortable", "notes": "Current self-report."},
    )
    assert edited.status_code == 200
    assert edited.json()["entries"][0]["comfort"] == "comfortable"
    assert edited.json()["entries"][0]["notes"] == "Current self-report."

    reopened = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
        )
    )
    assert reopened.get("/api/profile/proficiency").json() == edited.json()


def test_manual_proficiency_rejects_stale_revision_duplicate_and_client_provenance(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
        )
    )
    payload = {"expected_revision": 0, "concept": "Python", "comfort": "new", "notes": ""}
    created = client.post("/api/profile/proficiency/entries", json=payload)
    assert created.status_code == 201
    stale = client.patch(
        f"/api/profile/proficiency/entries/{created.json()['entries'][0]['id']}",
        json={"expected_revision": 0, "comfort": "unsure"},
    )
    assert stale.status_code == 409
    duplicate = client.post(
        "/api/profile/proficiency/entries",
        json={"expected_revision": 1, "concept": " python ", "comfort": "comfortable", "notes": ""},
    )
    assert duplicate.status_code == 409
    forged = client.post(
        "/api/profile/proficiency/entries",
        json={**payload, "expected_revision": 1, "source_kind": "model_requirement", "topic_id": "topic-x"},
    )
    assert forged.status_code == 422
    unchanged = client.get("/api/profile/proficiency").json()
    assert unchanged["revision"] == 1
    assert len(unchanged["entries"]) == 1


def test_manual_proficiency_updates_never_invoke_learning_model(tmp_path):
    class ForbiddenModel:
        async def stream_chat(self, *_args, **_kwargs):
            raise AssertionError("manual proficiency changes must not invoke a model")

        async def embed_texts(self, *_args, **_kwargs):
            raise AssertionError("manual proficiency changes must not invoke embeddings")

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
            model_backend=ForbiddenModel(),
        )
    )
    response = client.post(
        "/api/profile/proficiency/entries",
        json={"expected_revision": 0, "concept": "Probability", "comfort": "unsure", "notes": ""},
    )
    assert response.status_code == 201


def test_my_proficiency_remains_usable_when_cv_storage_is_corrupt(tmp_path):
    def parsed_cv(data: bytes, filename: str, parser: str):
        return {
            "canonical_text": "synthetic CV text",
            "native_document": None,
            "parser": parser,
            "parser_version": "test",
            "diagnostics": {"status": "ready", "findings": []},
        }

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
        files={"file": ("cv.pdf", b"%PDF-1.7\nsynthetic", "application/pdf")},
        data={"original_name": "CV.pdf", "parser": "docling"},
    )
    assert uploaded.status_code == 201
    (profile_root / "CVs" / "CV.pdf").write_bytes(b"changed")

    created = client.post(
        "/api/profile/proficiency/entries",
        json={"expected_revision": 0, "concept": "Statistics", "comfort": "new", "notes": ""},
    )
    assert created.status_code == 201
    assert client.get("/api/profile/proficiency").json()["entries"][0]["concept"] == "Statistics"
