"""Pure-input contract for high/medium prerequisite planning."""

from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from lab.errors import DoesNotFit, InvalidInput
from lab.prerequisites import build_prerequisite_plan, validate_prerequisite_response

CV_TEXT = "Experience: Python basics.\nRepeat marker.\nRepeat marker.\n"


def _map_record():
    return {
        "revision": "map-revision-1",
        "file_id": "synthetic-paper",
        "source_revision": {"pdf_sha256": "a" * 64, "docling_sha256": "b" * 64},
        "sections": [
            {
                "id": "section-root",
                "title": "Methods",
                "source_unit_ids": ["header", "body", "table", "formula", "child"],
                "children": [
                    {
                        "id": "section-child",
                        "title": "Estimation",
                        "source_unit_ids": ["child"],
                        "children": [],
                    }
                ],
                "summary": "must not be used as source",
            }
        ],
        "units": [
            {
                "id": "header",
                "source_refs": ["#/texts/0"],
                "pages": [1],
                "kind": "text",
                "text": "Methods",
                "included": True,
            },
            {
                "id": "body",
                "source_refs": ["#/texts/1"],
                "pages": [1],
                "kind": "text",
                "text": "The method estimates a relationship.",
                "included": True,
            },
            {
                "id": "table",
                "source_refs": ["#/tables/0"],
                "pages": [2],
                "kind": "table",
                "text": "| Estimate | Error |\n| --- | --- |\n| 2 | 0.1 |",
                "included": True,
            },
            {
                "id": "formula",
                "source_refs": ["#/texts/2"],
                "pages": [2],
                "kind": "formula",
                "text": "y = βx + ε",
                "included": True,
            },
            {
                "id": "child",
                "source_refs": ["#/texts/3"],
                "pages": [3],
                "kind": "text",
                "text": "The estimator uses a matrix inverse.",
                "included": True,
            },
        ],
        "latest_attempt": {"content": "untrusted generated summary"},
        "chat_history": [{"content": "must not enter the new request"}],
    }


def _cv_record(text: str = CV_TEXT):
    return {
        "id": "cv-version-1",
        "original_name": "CV.pdf",
        "status": "ready",
        "revoked": False,
        "original_sha256": "c" * 64,
        "extracted_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _plan(*, context_limit: int = 8192, cv_text: str = CV_TEXT, runtime_policy: str = "Complete runtime policy."):
    return build_prerequisite_plan(
        _map_record(),
        "section-root",
        selected_cv=_cv_record(cv_text),
        cv_text=cv_text,
        runtime_policy=runtime_policy,
        goal="Understand the method",
        model="local-model",
        context_limit=context_limit,
        think=False,
        assessment_id="assessment-1",
        attempt_id="attempt-1",
        started_at="2026-10-12T00:00:00+00:00",
    )


def _model_response():
    return {
        "overview": "A high-level understanding of regression is useful here.",
        "requirements": [
            {
                "concept": "Basic Python",
                "reason": "It can help reproduce the described analysis.",
                "source_labels": ["S2", "S5"],
                "cv_background": "mentioned",
                "cv_source_labels": ["CV1"],
                "cv_quote": "Experience: Python basics.",
            }
        ],
    }


def test_plan_uses_full_section_sources_and_fresh_source_separated_context():
    source_map = _map_record()
    before = deepcopy(source_map)
    plan = build_prerequisite_plan(
        source_map,
        "section-root",
        selected_cv=_cv_record(),
        cv_text=CV_TEXT,
        runtime_policy="Fresh complete runtime policy text.",
        goal="Understand the method",
        model="local-model",
        context_limit=8192,
        think=False,
        assessment_id="assessment-1",
        attempt_id="attempt-1",
        started_at="2026-10-12T00:00:00+00:00",
    )
    message_text = "\n".join(message["content"] for message in plan["messages"])

    assert len(plan["messages"]) == 2
    assert "The method estimates a relationship." in message_text
    assert "| Estimate | Error |" in message_text
    assert "y = βx + ε" in message_text
    assert "The estimator uses a matrix inverse." in message_text
    assert "untrusted generated summary" not in message_text
    assert "must not enter the new request" not in message_text
    assert "Fresh complete runtime policy text." in message_text
    assert "Runtime policy is not evidence" in message_text
    assert "Never infer skill or unfamiliarity from a degree" in message_text
    assert "cv_source_labels MUST be []" in message_text
    assert "cv_quote MUST be an exact, non-whitespace substring" in message_text
    assert "Never quote unrelated CV experience or omission as evidence" in message_text
    assert "Do not omit a section requirement merely because the CV mentions it" in message_text
    assert "basic programming may be relevant at a conceptual level" in message_text
    assert "Do not list libraries" in message_text
    assert "CV_TEXT" not in message_text
    assert message_text.count(CV_TEXT) == 1
    assert CV_TEXT in plan["messages"][1]["content"]
    assert source_map == before
    assert plan["provenance"]["map_revision"] == "map-revision-1"
    assert plan["provenance"]["section_id"] == "section-root"
    assert plan["provenance"]["cv_id"] == "cv-version-1"
    assert plan["provenance"]["cv_text_sha256"] == _cv_record()["extracted_sha256"]


def test_plan_is_repeatable_and_does_not_mutate_caller_inputs():
    source_map = _map_record()
    cv = _cv_record()
    before_map = deepcopy(source_map)
    before_cv = deepcopy(cv)
    options = {
        "runtime_policy": "Policy.",
        "goal": None,
        "model": "local-model",
        "context_limit": 8192,
        "think": None,
        "assessment_id": "assessment-1",
        "attempt_id": "attempt-1",
        "started_at": "2026-10-12T00:00:00+00:00",
    }
    first = build_prerequisite_plan(source_map, "section-root", selected_cv=cv, cv_text=CV_TEXT, **options)
    second = build_prerequisite_plan(source_map, "section-root", selected_cv=cv, cv_text=CV_TEXT, **options)

    assert first == second
    assert source_map == before_map
    assert cv == before_cv


@pytest.mark.parametrize("selected_cv,cv_text", [(None, CV_TEXT), (_cv_record(), ""), (_cv_record(), "  ")])
def test_missing_or_empty_cv_blocks_prerequisite_planning(selected_cv, cv_text):
    with pytest.raises(InvalidInput, match="CV"):
        build_prerequisite_plan(
            _map_record(),
            "section-root",
            selected_cv=selected_cv,
            cv_text=cv_text,
            runtime_policy="Policy.",
            goal=None,
            model="local-model",
            context_limit=8192,
            think=None,
            assessment_id="assessment-1",
            attempt_id="attempt-1",
            started_at="2026-10-12T00:00:00+00:00",
        )


@pytest.mark.parametrize(
    "cv",
    [
        {**_cv_record(), "status": "error"},
        {**_cv_record(), "revoked": True},
    ],
)
def test_ineligible_or_revoked_cv_blocks_planning(cv):
    with pytest.raises(InvalidInput, match="CV"):
        build_prerequisite_plan(
            _map_record(),
            "section-root",
            selected_cv=cv,
            cv_text=CV_TEXT,
            runtime_policy="Policy.",
            goal=None,
            model="local-model",
            context_limit=8192,
            think=None,
            assessment_id="assessment-1",
            attempt_id="attempt-1",
            started_at="2026-10-12T00:00:00+00:00",
        )


def test_cv_extraction_must_match_selected_version_hash():
    with pytest.raises(InvalidInput, match="CV"):
        build_prerequisite_plan(
            _map_record(),
            "section-root",
            selected_cv=_cv_record("other extracted text"),
            cv_text=CV_TEXT,
            runtime_policy="Policy.",
            goal=None,
            model="local-model",
            context_limit=8192,
            think=None,
            assessment_id="assessment-1",
            attempt_id="attempt-1",
            started_at="2026-10-12T00:00:00+00:00",
        )


def test_complete_policy_section_cv_and_goal_refuse_when_response_reserve_does_not_fit():
    with pytest.raises(DoesNotFit):
        _plan(context_limit=1024, cv_text=CV_TEXT + "Background. " * 1000, runtime_policy="Full policy. " * 1000)


def test_response_schema_uses_exact_section_and_cv_reference_enums():
    schema = _plan()["response_schema"]
    requirement = schema["properties"]["requirements"]["items"]
    properties = requirement["properties"]

    assert properties["source_labels"]["items"]["enum"] == ["S1", "S2", "S3", "S4", "S5"]
    assert properties["cv_source_labels"]["items"]["enum"] == ["CV1"]
    assert properties["cv_background"]["enum"] == ["mentioned", "not_stated"]
    assert schema["additionalProperties"] is False
    assert requirement["additionalProperties"] is False


def test_valid_response_gets_one_deterministic_pending_question_per_requirement():
    plan = _plan()
    validated = validate_prerequisite_response(
        _model_response(),
        sources=plan["sources"],
        cv_text=CV_TEXT,
        assessment_id="assessment-1",
    )
    repeated = validate_prerequisite_response(
        _model_response(),
        sources=plan["sources"],
        cv_text=CV_TEXT,
        assessment_id="assessment-1",
    )
    requirement = validated["requirements"][0]

    assert repeated == validated
    assert requirement["comfort"] is None
    assert requirement["comfort_status"] == "pending"
    assert requirement["question"] == "Are you already comfortable with Basic Python?"
    assert requirement["requirement_id"] == repeated["requirements"][0]["requirement_id"]
    assert requirement["cv_quote"] == "Experience: Python basics."


def test_not_stated_cv_background_requires_no_label_and_an_empty_quote():
    response = _model_response()
    response["requirements"][0].update(
        {
            "cv_background": "not_stated",
            "cv_source_labels": [],
            "cv_quote": "",
        }
    )

    validated = validate_prerequisite_response(
        response,
        sources=_plan()["sources"],
        cv_text=CV_TEXT,
        assessment_id="assessment-1",
    )

    assert validated["requirements"][0]["cv_background"] == "not_stated"
    assert validated["requirements"][0]["cv_source_labels"] == []
    assert validated["requirements"][0]["cv_quote"] == ""


def test_zero_requirements_is_a_valid_model_answer():
    validated = validate_prerequisite_response(
        {"overview": "No preparatory prerequisites were found in this section.", "requirements": []},
        sources=_plan()["sources"],
        cv_text=CV_TEXT,
        assessment_id="assessment-1",
    )

    assert validated["requirements"] == []


def test_whitespace_only_cv_quote_is_not_evidence():
    response = _model_response()
    response["requirements"][0]["cv_quote"] = " "

    with pytest.raises(InvalidInput):
        validate_prerequisite_response(
            response,
            sources=_plan()["sources"],
            cv_text=CV_TEXT,
            assessment_id="assessment-1",
        )


@pytest.mark.parametrize(
    "response",
    [
        {"overview": "o" * 1201, "requirements": []},
        {"overview": "ok", "requirements": [_model_response()["requirements"][0]] * 9},
        " " * 24_001,
    ],
)
def test_response_size_and_item_limits_are_enforced(response):
    with pytest.raises(InvalidInput):
        validate_prerequisite_response(
            response,
            sources=_plan()["sources"],
            cv_text=CV_TEXT,
            assessment_id="assessment-1",
        )


@pytest.mark.parametrize(
    "response",
    [
        "not JSON",
        {"overview": "ok", "requirements": [], "action": "create a course"},
        {
            "overview": "ok",
            "requirements": [
                {
                    **_model_response()["requirements"][0],
                    "source_labels": ["S99"],
                }
            ],
        },
        {
            "overview": "ok",
            "requirements": [
                _model_response()["requirements"][0],
                {**_model_response()["requirements"][0], "concept": " basic   python "},
            ],
        },
        {
            "overview": "ok",
            "requirements": [{**_model_response()["requirements"][0], "cv_quote": "Python basics were not in the CV."}],
        },
        {
            "overview": "ok",
            "requirements": [
                {
                    **_model_response()["requirements"][0],
                    "cv_background": "not_stated",
                    "cv_source_labels": ["CV1"],
                    "cv_quote": "Experience: Python basics.",
                }
            ],
        },
        {
            "overview": "ok",
            "requirements": [
                {
                    **_model_response()["requirements"][0],
                    "cv_background": "mentioned",
                    "cv_source_labels": [],
                    "cv_quote": "Experience: Python basics.",
                }
            ],
        },
        {
            "overview": "ok",
            "requirements": [{**_model_response()["requirements"][0], "source_labels": []}],
        },
    ],
)
def test_invalid_or_unsupported_model_output_is_rejected(response):
    plan = _plan()
    with pytest.raises(InvalidInput):
        validate_prerequisite_response(
            response,
            sources=plan["sources"],
            cv_text=CV_TEXT,
            assessment_id="assessment-1",
        )


def test_existing_topic_goal_length_is_supported_without_truncation():
    goal = "Learn the method. " * 60
    plan = build_prerequisite_plan(
        _map_record(),
        "section-root",
        selected_cv=_cv_record(),
        cv_text=CV_TEXT,
        runtime_policy="Complete runtime policy.",
        goal=goal,
        model="local-model",
        context_limit=8192,
        think=False,
        assessment_id="assessment-1",
        attempt_id="attempt-1",
        started_at="2026-10-13T00:00:00+00:00",
    )
    assert plan["provenance"]["goal"] == goal.strip()
    assert goal.strip() in plan["messages"][1]["content"]
