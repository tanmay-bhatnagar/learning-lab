#!/usr/bin/env python3
"""Exercise real PDF converters and optionally local inference in an isolated topic root."""

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--model", help="Also run a real Ollama response using this installed model")
    args = parser.parse_args()
    from reportlab.pdfgen import canvas
    from fastapi.testclient import TestClient

    with TemporaryDirectory(prefix="learning-lab-smoke-") as scratch:
        os.environ["LEARNING_LAB_ROOT"] = str(Path(scratch).resolve() / "Learning")
        os.environ["LEARNING_LAB_STATE_ROOT"] = str(Path(scratch).resolve() / "state")
        from lab.main import app

        pdf = BytesIO()
        page = canvas.Canvas(pdf)
        page.drawString(72, 740, "Learning Lab parser check")
        page.drawString(72, 710, "The calibration value is 42. Retrieval finds relevant evidence.")
        page.showPage()
        page.save()
        original = pdf.getvalue()
        with TestClient(app) as client:
            topic = client.post("/api/topics", json={"name": "Isolated smoke test"})
            topic.raise_for_status()
            topic_id = topic.json()["id"]
            files = []
            for converter in ("markitdown", "anydoc"):
                response = client.post(
                    f"/api/topics/{topic_id}/files",
                    files={"file": ("fixture.pdf", original, "application/pdf")},
                    data={"parser": converter},
                )
                response.raise_for_status()
                record = response.json()
                assert record["status"] == "ready", record
                file_id = record["id"]
                markdown = client.get(f"/api/topics/{topic_id}/files/{file_id}/markdown").json()["markdown"]
                assert "42" in markdown and "Retrieval" in markdown, markdown
                assert client.get(f"/api/topics/{topic_id}/files/{file_id}/original").content == original
                files.append(file_id)
                print(f"PASS {converter}: extracted evidence and preserved original bytes")
            if args.model:
                with client.stream(
                    "POST",
                    f"/api/topics/{topic_id}/chat",
                    json={
                        "message": "What is the calibration value in the attached document? Answer in one short sentence.",
                        "file_ids": files[:1],
                        "model": args.model,
                        "think": False,
                        "context_limit": args.context,
                    },
                ) as response:
                    response.raise_for_status()
                    events = [json.loads(line) for line in response.iter_lines() if line]
                errors = [e for e in events if e["type"] == "error"]
                assert not errors, errors
                answer = "".join(e.get("text", "") for e in events if e["type"] == "token")
                assert "42" in answer, answer
                assert any(e["type"] == "done" for e in events), events
                history = client.get(f"/api/topics/{topic_id}/messages").json()["messages"]
                assert len(history) >= 2, history
                print("PASS real model, streamed answer, context event, saved history:", answer)
        print("Smoke complete. All test material was confined to a temporary root.")


if __name__ == "__main__":
    main()
