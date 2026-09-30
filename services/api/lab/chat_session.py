"""Pure session transitions for chat."""

from __future__ import annotations

from lab.contracts import Message, Session


def append_user_message(session: Session, content: str, file_ids: list[str]) -> Session:
    messages = [*session.get("messages", []), {"role": "user", "content": content, "file_ids": file_ids}]
    return {**session, "messages": messages}


def append_assistant_message(session: Session, assistant: Message) -> Session:
    messages = [*session.get("messages", []), assistant]
    return {**session, "messages": messages}


def with_session_context(session: Session, context: dict[str, object]) -> Session:
    return {**session, "context": context}


def history_messages(session: Session) -> list[dict[str, object]]:
    return [
        {
            "role": message["role"],
            "content": message["content"],
            **({"thinking": message["thinking"]} if message.get("thinking") else {}),
        }
        for message in session.get("messages", [])
    ]
