"""Manual proficiency persists independently of CV and topic state."""

from __future__ import annotations

import json

import pytest
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


def test_proficiency_batch_saves_multiple_manual_rows_with_one_revision(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
        )
    )
    response = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 0,
            "additions": [
                {"concept": "Python basics", "comfort": "refresher", "notes": "Brief refresh."},
                {"concept": "Regression", "comfort": "new", "notes": ""},
            ],
            "updates": [],
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["revision"] == 1
    assert [entry["concept"] for entry in saved["entries"]] == ["Python basics", "Regression"]
    assert all(entry["source_kind"] == "user_manual" for entry in saved["entries"])
    reopened = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
        )
    )
    assert reopened.get("/api/profile/proficiency").json() == saved


def test_invalid_later_batch_row_leaves_saved_state_byte_identical(tmp_path):
    profile_root = tmp_path / "Profile"
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
        )
    )
    existing = client.post(
        "/api/profile/proficiency/entries",
        json={"expected_revision": 0, "concept": "Python", "comfort": "new", "notes": "Original."},
    ).json()["entries"][0]
    state_file = profile_root / "proficiency.json"
    original_bytes = state_file.read_bytes()

    response = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 1,
            "updates": [{"id": existing["id"], "comfort": "comfortable", "notes": "Changed."}],
            "additions": [
                {"concept": "Statistics", "comfort": "new", "notes": ""},
                {"concept": " statistics ", "comfort": "refresher", "notes": "Duplicate."},
            ],
        },
    )

    assert response.status_code == 409
    assert state_file.read_bytes() == original_bytes


def test_stale_or_forged_batch_updates_leave_profile_file_unchanged(tmp_path):
    profile_root = tmp_path / "Profile"
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
        )
    )
    client.post(
        "/api/profile/proficiency/entries",
        json={"expected_revision": 0, "concept": "Python", "comfort": "new", "notes": ""},
    )
    state_file = profile_root / "proficiency.json"
    original_bytes = state_file.read_bytes()

    stale = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 0,
            "updates": [],
            "additions": [{"concept": "Statistics", "comfort": "new", "notes": ""}],
        },
    )
    forged = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 1,
            "updates": [],
            "additions": [
                {
                    "concept": "Statistics",
                    "comfort": "new",
                    "notes": "",
                    "source_kind": "model_requirement",
                    "topic_id": "topic-forged",
                }
            ],
        },
    )

    assert stale.status_code == 409
    assert forged.status_code == 422
    assert state_file.read_bytes() == original_bytes


def test_model_requirement_batch_answer_projects_only_active_assessment_and_includes_notes(tmp_path):
    profile_root = tmp_path / "Profile"
    profile_root.mkdir()
    state_file = profile_root / "proficiency.json"
    entries = [
        {
            "id": f"{index:032x}",
            "concept": concept,
            "comfort": None,
            "notes": "",
            "source_kind": "model_requirement",
            "topic_id": topic,
            "assessment_id": assessment,
            "requirement_id": f"requirement-{index}",
        }
        for index, (concept, topic, assessment) in enumerate(
            [
                ("Regression methods", "topic-a", "assessment-a"),
                ("Bayesian methods", "topic-a", "assessment-b"),
                ("Data visualization", "topic-b", "assessment-a"),
            ],
            start=1,
        )
    ]
    state_file.write_text(
        json.dumps({"schema_version": 1, "revision": 3, "entries": entries}),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
        )
    )

    saved = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 3,
            "updates": [{"id": entries[0]["id"], "comfort": "unsure", "notes": "Explain notation."}],
            "additions": [],
        },
    )

    assert saved.status_code == 200
    from lab.learner_profile import proficiency_context

    context = proficiency_context(saved.json(), topic_id="topic-a", active_assessment_id="assessment-a")
    assert "Regression methods: unsure — Explain notation." in context
    assert "Bayesian methods" not in context
    assert "Data visualization" not in context


@pytest.mark.parametrize("starting_comfort", ["comfortable", None])
def test_batch_can_explicitly_clear_model_requirement_comfort_to_pending(tmp_path, starting_comfort):
    profile_root = tmp_path / "Profile"
    profile_root.mkdir()
    requirement_id = "a" * 32
    state_file = profile_root / "proficiency.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": 1,
                "entries": [
                    {
                        "id": requirement_id,
                        "concept": "Regression",
                        "comfort": starting_comfort,
                        "notes": "",
                        "source_kind": "model_requirement",
                        "topic_id": "topic-a",
                        "assessment_id": "assessment-a",
                        "requirement_id": "requirement-a",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
        )
    )

    response = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 1,
            "updates": [{"id": requirement_id, "comfort": None, "notes": "Revisit later."}],
            "additions": [],
        },
    )

    assert response.status_code == 200
    updated = response.json()["entries"][0]
    assert updated["comfort"] is None
    assert updated["notes"] == "Revisit later."


def test_empty_proficiency_batch_is_a_noop(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=tmp_path / "Profile",
        )
    )

    response = client.put(
        "/api/profile/proficiency",
        json={"expected_revision": 0, "updates": [], "additions": []},
    )

    assert response.status_code == 200
    assert response.json() == {"schema_version": 1, "revision": 0, "entries": []}


def test_proficiency_capacity_is_five_hundred_and_refuses_overflow_without_write(tmp_path):
    profile_root = tmp_path / "Profile"
    profile_root.mkdir()
    entries = [
        {
            "id": f"{index:032x}",
            "concept": f"Topic {index}",
            "comfort": "unsure",
            "notes": "",
            "source_kind": "user_manual",
        }
        for index in range(1, 501)
    ]
    state_file = profile_root / "proficiency.json"
    state_file.write_text(
        json.dumps({"schema_version": 1, "revision": 12, "entries": entries}),
        encoding="utf-8",
    )
    original_bytes = state_file.read_bytes()
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            profile_root=profile_root,
        )
    )

    response = client.put(
        "/api/profile/proficiency",
        json={
            "expected_revision": 12,
            "updates": [],
            "additions": [{"concept": "Overflow", "comfort": "new", "notes": ""}],
        },
    )

    assert response.status_code == 400
    assert state_file.read_bytes() == original_bytes


def test_empty_proficiency_batch_transform_is_repeatable_with_explicit_metadata():
    from lab.learner_profile import apply_proficiency_batch, empty_proficiency

    state = empty_proficiency()
    before = json.loads(json.dumps(state))
    kwargs = {
        "additions": [
            {"concept": "Python", "comfort": "new", "notes": ""},
            {"concept": "Statistics", "comfort": "refresher", "notes": "Review."},
        ],
        "updates": [],
        "expected_revision": 0,
        "entry_ids": ["a" * 32, "b" * 32],
        "updated_at": "2026-10-12T00:00:00+00:00",
    }

    first = apply_proficiency_batch(state, **kwargs)
    second = apply_proficiency_batch(state, **kwargs)

    assert first == second
    assert first["revision"] == 1
    assert state == before
