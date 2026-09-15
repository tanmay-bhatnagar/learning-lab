#!/usr/bin/env python3
"""One-off helper to fetch and validate Qwen benchmark PDFs."""
from __future__ import annotations

import csv
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PDF_DIR = Path(__file__).resolve().parents[1] / "benchmark_PDFs"
MANIFEST = Path(__file__).resolve().parent / "qwen.csv"

PAPERS = [
    {
        "filename": "qwen_technical_report_2309.16609.pdf",
        "title": "Qwen Technical Report",
        "year": "2023",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2309.16609",
    },
    {
        "filename": "qwen_vl_2308.12966.pdf",
        "title": "Qwen-VL: A Versatile Vision-Language Model for Understanding, Localization, Text Reading, and Beyond",
        "year": "2023",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2308.12966",
    },
    {
        "filename": "qwen_audio_2311.07919.pdf",
        "title": "Qwen-Audio: Advancing Universal Audio Understanding via Unified Large-Scale Audio-Language Models",
        "year": "2023",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2311.07919",
    },
    {
        "filename": "qwen2_2407.10671.pdf",
        "title": "Qwen2 Technical Report",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2407.10671",
    },
    {
        "filename": "qwen2_audio_2407.10759.pdf",
        "title": "Qwen2-Audio Technical Report",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2407.10759",
    },
    {
        "filename": "qwen2_vl_2409.12191.pdf",
        "title": "Qwen2-VL: Enhancing Vision-Language Model's Perception of the World at Any Resolution",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2409.12191",
    },
    {
        "filename": "qwen2_5_coder_2409.12186.pdf",
        "title": "Qwen2.5-Coder Technical Report",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2409.12186",
    },
    {
        "filename": "qwen2_5_math_2409.12122.pdf",
        "title": "Qwen2.5-Math Technical Report: Toward Mathematical Expert Model via Self-Improvement",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2409.12122",
    },
    {
        "filename": "qwen_marco_o1_2411.14405.pdf",
        "title": "Marco-o1: Towards Open Reasoning Models for Open-Ended Solutions",
        "year": "2024",
        "lab": "MarcoPolo Team, Alibaba International Digital Commerce",
        "arxiv": "2411.14405",
    },
    {
        "filename": "qwen2_5_2412.15115.pdf",
        "title": "Qwen2.5 Technical Report",
        "year": "2024",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2412.15115",
    },
    {
        "filename": "qwen2_5_1m_2501.15383.pdf",
        "title": "Qwen2.5-1M Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2501.15383",
    },
    {
        "filename": "qwen2_5_vl_2502.13923.pdf",
        "title": "Qwen2.5-VL Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2502.13923",
    },
    {
        "filename": "qwen2_5_omni_2503.20215.pdf",
        "title": "Qwen2.5-Omni Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2503.20215",
    },
    {
        "filename": "qwen3_2505.09388.pdf",
        "title": "Qwen3 Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2505.09388",
    },
    {
        "filename": "qwen_image_2508.02324.pdf",
        "title": "Qwen-Image Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2508.02324",
    },
    {
        "filename": "qwen3_omni_2509.17765.pdf",
        "title": "Qwen3-Omni Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2509.17765",
    },
    {
        "filename": "qwen3_vl_2511.21631.pdf",
        "title": "Qwen3-VL Technical Report",
        "year": "2025",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2511.21631",
    },
    {
        "filename": "qwen3_coder_next_2603.00729.pdf",
        "title": "Qwen3-Coder-Next Technical Report",
        "year": "2026",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2603.00729",
    },
    {
        "filename": "qwen3_5_omni_2604.15804.pdf",
        "title": "Qwen3.5-Omni Technical Report",
        "year": "2026",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2604.15804",
    },
    {
        "filename": "qwen_music_2607.11699.pdf",
        "title": "Qwen-Music Technical Report",
        "year": "2026",
        "lab": "Qwen Team, Alibaba Group",
        "arxiv": "2607.11699",
    },
]


def download_pdf(url: str, dest: Path, retries: int = 3) -> None:
    headers = {"User-Agent": "learning-lab-benchmark/1.0 (research PDF collection)"}
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF-"):
                raise ValueError(f"not a PDF (magic={data[:16]!r})")
            if len(data) < 1024:
                raise ValueError(f"too small ({len(data)} bytes)")
            dest.write_bytes(data)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to download {url}: {last_err}")


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for paper in PAPERS:
        dest = PDF_DIR / paper["filename"]
        url = f"https://arxiv.org/pdf/{paper['arxiv']}.pdf"
        print(f"Downloading {paper['filename']} ...", flush=True)
        download_pdf(url, dest)
        size = dest.stat().st_size
        print(f"  OK {size:,} bytes", flush=True)
        rows.append(
            {
                "filename": paper["filename"],
                "title": paper["title"],
                "year": paper["year"],
                "lab": paper["lab"],
                "source_url": f"https://arxiv.org/abs/{paper['arxiv']}",
            }
        )

    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["filename", "title", "year", "lab", "source_url"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote manifest: {MANIFEST} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
