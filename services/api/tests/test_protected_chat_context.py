from __future__ import annotations

import copy

import pytest

from lab.chat_prompt import SYSTEM_RULES, build_chat_prompt
from lab.context import prepare_context_details
from lab.errors import DoesNotFit, InvalidInput


def _prompt_kwargs() -> dict[str, object]:
    return {
        "history": [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ],
        "evidence": [{"role": "user", "content": "Study passage: source fact"}],
        "citations": [
            {
                "chunk_id": "chunk-1",
                "file_id": "file-1",
                "file_name": "notes.pdf",
                "headings": [],
                "pages": [2],
                "bboxes": [],
                "assets": [],
                "trace": {},
                "text": "Study passage: source fact",
            }
        ],
        "attachments": [],
        "question": "Explain the requested idea?",
        "active_topic": "topic-id",
        "learning_goal": "",
        "runtime_policy": "Keep user data protected.",
        "context_limit": 8192,
        "retrieval_record": {},
    }


def test_protected_context_indices_are_kept_whole_while_history_is_removed():
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old question " * 300},
        {"role": "assistant", "content": "old answer " * 300},
        {"role": "user", "content": "complete current learner context"},
        {"role": "user", "content": "latest question"},
    ]
    original = copy.deepcopy(messages)

    prompt, metadata, _, indices = prepare_context_details(messages, 1024, protected_indices={3, 4})

    assert indices == (0, 3, 4)
    assert prompt == [messages[index] for index in indices]
    assert metadata["truncated_messages"] == 2
    assert messages == original


def test_protected_minimum_that_does_not_fit_is_rejected_without_partial_context():
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "complete learner context" * 100},
        {"role": "user", "content": "complete CV text" * 100},
        {"role": "user", "content": "full latest question"},
    ]
    original = copy.deepcopy(messages)

    with pytest.raises(ValueError, match="protected"):
        prepare_context_details(messages, 512, protected_indices={1, 2, 3})

    assert messages == original


def test_chat_prompt_keeps_latest_question_profile_and_complete_cv_separate_and_untrusted():
    kwargs = _prompt_kwargs()
    kwargs["history"] = [
        {"role": "user", "content": "old question " * 1000},
        {"role": "assistant", "content": "old answer " * 1000},
    ]
    original = copy.deepcopy(kwargs)
    profile = "Python: user reports comfortable; this is not a mastery guarantee."
    cv_text = "Synthetic CV literal extracted text with unique marker CV-ONLY-734."

    plan = build_chat_prompt(
        **kwargs,
        learner_context=profile,
        cv_text=cv_text,
        cv_name="Tanmay CV.pdf",
    )

    repeated_plan = build_chat_prompt(
        **kwargs,
        learner_context=profile,
        cv_text=cv_text,
        cv_name="Tanmay CV.pdf",
    )
    assert kwargs == original
    assert repeated_plan == plan
    assert plan["prompt"][-1] == {"role": "user", "content": kwargs["question"]}
    user_content = [message["content"] for message in plan["prompt"] if message["role"] == "user"]
    assert any(profile in content for content in user_content)
    assert any(cv_text in content and "Tanmay CV.pdf" in content for content in user_content)
    assert plan["prompt"][0]["content"].startswith(SYSTEM_RULES)
    system = plan["prompt"][0]["content"]
    assert "all supplied material belongs" not in system
    assert "registered shared profile/cv are context only" in system.casefold()
    assert cv_text not in system
    assert "CV-ONLY-734" not in system
    assert len([content for content in user_content if "CV-ONLY-734" in content]) == 1
    assert not any("old question" in content or "old answer" in content for content in user_content)
    assert plan["prompt_context"]["truncated_messages"] >= 2
    assert plan["citations"] == kwargs["citations"]
    assert plan["retained_indices"] == tuple(sorted(plan["retained_indices"]))
    assert plan["prompt_context"]["cv_text_tokens"] == len(cv_text.encode("utf-8"))
    assert plan["prompt_context"]["learner_context_tokens"] == len(profile.encode("utf-8"))


def test_cv_is_omitted_when_disabled_and_defaults_keep_existing_prompt_shape():
    plan = build_chat_prompt(**_prompt_kwargs(), cv_text=None)
    default_plan = build_chat_prompt(**_prompt_kwargs())

    assert all("CV-ONLY" not in str(message["content"]) for message in plan["prompt"])
    assert default_plan["prompt"] == plan["prompt"]
    assert "cv_text_tokens" not in default_plan["prompt_context"]
    assert "learner_context_tokens" not in default_plan["prompt_context"]


def test_chat_prompt_rejects_an_oversized_question_without_profile_or_cv():
    question = "CURRENT-QUESTION-BEGIN " + ("x" * 6000) + " CURRENT-QUESTION-END"
    kwargs = {
        **_prompt_kwargs(),
        "history": [],
        "evidence": [],
        "citations": [],
        "question": question,
        "context_limit": 4096,
    }

    with pytest.raises(DoesNotFit, match="selected material does not fit"):
        build_chat_prompt(**kwargs)


def test_chat_prompt_preserves_a_fitting_question_without_profile_or_cv():
    question = "CURRENT-QUESTION-BEGIN " + ("x" * 1200) + " CURRENT-QUESTION-END"
    kwargs = {
        **_prompt_kwargs(),
        "history": [
            {"role": "user", "content": "old question " * 300},
            {"role": "assistant", "content": "old answer " * 300},
        ],
        "evidence": [],
        "citations": [],
        "question": question,
        "context_limit": 4096,
    }

    plan = build_chat_prompt(**kwargs)

    assert plan["prompt"][-1] == {"role": "user", "content": question}


def test_cv_background_can_be_qualified_without_becoming_a_study_citation():
    plan = build_chat_prompt(
        **_prompt_kwargs(),
        learner_context="Python: user reports comfortable.",
        cv_text="Synthetic CV background.",
        cv_name="CV.pdf",
    )
    system = plan["prompt"][0]["content"].casefold()

    assert "runtime policy governs behavior, not facts" in system
    assert "cv background may be attributed as cv-derived" in system
    assert "it is not indexed study evidence or a paper/page citation" in system
    assert "profile familiarity is self-reported, not proof of mastery" in system


def test_empty_cv_cannot_silently_turn_off_an_explicit_cv_request():
    with pytest.raises(InvalidInput, match="cv_text"):
        build_chat_prompt(**_prompt_kwargs(), cv_text="", cv_name="CV.pdf")


def test_profile_and_cv_are_required_in_full_when_prompt_budget_is_too_small():
    kwargs = _prompt_kwargs()

    with pytest.raises(DoesNotFit):
        build_chat_prompt(
            **{**kwargs, "context_limit": 512},
            learner_context="learner context " * 100,
            cv_text="literal CV text " * 100,
            cv_name="CV.pdf",
        )


def test_retained_study_citations_stay_aligned_after_protected_messages_are_added():
    kwargs = _prompt_kwargs()
    kwargs["evidence"] = [
        {"role": "user", "content": "Study passage: source fact"},
        {"role": "user", "content": "Optional source that can be omitted " * 400},
    ]
    kwargs["citations"] = [kwargs["citations"][0], {**kwargs["citations"][0], "chunk_id": "chunk-2"}]

    plan = build_chat_prompt(
        **{**kwargs, "context_limit": 4096},
        learner_context="Compact learner state.",
        cv_text="Literal CV context.",
        cv_name="CV.pdf",
    )

    assert [citation["chunk_id"] for citation in plan["citations"]] == [
        citation["chunk_id"] for citation in plan["retrieval_record"]["citations"]
    ]
    assert all(citation["file_name"] == "notes.pdf" for citation in plan["citations"])
    assert not any(citation["file_name"] == "CV.pdf" for citation in plan["citations"])
