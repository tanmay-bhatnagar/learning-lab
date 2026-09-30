"""Compatibility re-exports for tests and scripts."""

from lab.chat_prompt import SYSTEM_RULES
from lab.http.app import create_app

__all__ = ["SYSTEM_RULES", "create_app"]
