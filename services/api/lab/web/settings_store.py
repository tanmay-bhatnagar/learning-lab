"""Load persisted workspace settings."""

from __future__ import annotations

from lab.contracts import StoreProtocol
from lab.storage import read_json
from lab.web.schemas import Settings


def load_settings(store: StoreProtocol) -> Settings:
    return Settings(**read_json(store.settings, {}))
