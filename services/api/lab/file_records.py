"""Pure decisions about persisted topic file records."""
from __future__ import annotations

from collections.abc import Collection

INTERRUPTED_ERROR = (
    "Processing was interrupted before it finished, for example because the API stopped. "
    "The original PDF and any partial output are kept; upload the PDF again to retry."
)


def mark_interrupted(records: list[dict], active_ids: Collection[str]) -> list[dict]:
    """Return records with abandoned `processing` entries marked as interrupted errors."""
    return [
        {**record, "status": "error", "error": INTERRUPTED_ERROR, "interrupted": True}
        if record.get("status") == "processing" and record.get("id") not in active_ids
        else record
        for record in records
    ]
