"""HTTP request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TopicInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Topic name must contain printable text.")
        return value


class LearningGoalInput(BaseModel):
    learning_goal: str = Field(max_length=2000)

    @field_validator("learning_goal")
    @classmethod
    def clean_learning_goal(cls, value: str) -> str:
        value = value.strip()
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Learning goal must contain printable text.")
        return value


class Settings(BaseModel):
    model: str = Field(default="", max_length=200)
    context_limit: int = Field(default=32768, ge=1024, le=32768)
    parser: Literal["docling", "markitdown", "anydoc"] = "docling"
    embedding_model: str = Field(default="nomic-embed-text", max_length=200)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=200000)
    file_ids: list[str] = Field(default_factory=list, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    think: bool | str | None = None
    context_limit: int = Field(default=32768, ge=1024, le=32768)


class RetrievalInput(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=6, ge=1, le=20)
