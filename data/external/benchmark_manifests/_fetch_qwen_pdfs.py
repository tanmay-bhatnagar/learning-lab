#!/usr/bin/env python3
"""One-shot fetcher for Qwen benchmark PDFs. Run once, then remove if desired."""
from __future__ import annotations

import csv
import os
import sys
import time
import urllib.request
from pathlib import Path

PDF_DIR = Path(__file__).resolve().parents[1] / "benchmark_PDFs"
MANIFEST = Path(__file__).resolve().parent / "qwen.csv"

PAPERS = [
    (
        "qwen_2023_technical_report.pdf",
        "Qwen Technical Report",
        "2023",
        "2309.16609",
    ),
    (
        "qwen_vl_2023_versatile_vision_language.pdf",
        "Qwen-VL: A Versatile Vision-Language Model for Understanding, Localization, Text Reading, and Beyond",
        "2023",
        "2308.12966",
    ),
    (
        "qwen_audio_2023_universal_audio_understanding.pdf",
        "Qwen-Audio: Advancing Universal Audio Understanding via Unified Large-Scale Audio-Language Models",
        "2023",
        "2311.07919",
    ),
    (
        "qwen2_2024_technical_report.pdf",
        "Qwen2 Technical Report",
        "2024",
        "2407.10671",
    ),
    (
        "qwen2_audio_2024_technical_report.pdf",
        "Qwen2-Audio Technical Report",
        "2024",
        "2407.10759",
    ),
    (
        "qwen2_vl_2024_any_resolution.pdf",
        "Qwen2-VL: Enhancing Vision-Language Model's Perception of the World at Any Resolution",
        "2024",
        "2409.12191",
    ),
    (
        "qwen2_5_math_2024_self_improvement.pdf",
        "Qwen2.5-Math Technical Report: Toward Mathematical Expert Model via Self-Improvement",
        "2024",
        "2409.12122",
    ),
    (
        "qwen2_5_coder_2024_technical_report.pdf",
        "Qwen2.5-Coder Technical Report",
        "2024",
        "2409.12186",
    ),
    (
        "qwen2_5_2024_technical_report.pdf",
        "Qwen2.5 Technical Report",
        "2024",
        "2412.15115",
    ),
    (
        "qwen2_5_1m_2025_long_context.pdf",
        "Qwen2.5-1M Technical Report",
        "2025",
        "2501.15383",
    ),
    (
        "qwen2_5_vl_2025_technical_report.pdf",
        "Qwen2.5-VL Technical Report",
        "2025",
        "2502.13923",
    ),
    (
        "qwen2_5_omni_2025_technical_report.pdf",
        "Qwen2.5-Omni Technical Report",
        "2025",
        "2503.20215",
    ),
    (
        "qwen3_2025_technical_report.pdf",
        "Qwen3 Technical Report",
        "2025",
        "2505.09388",
    ),
    (
        "qwenlong_cprs_2025_dynamic_context.pdf",
        "QwenLong-CPRS: Towards ∞-LLMs with Dynamic Context Optimization",
        "2025",
        "2505.18092",
    ),
    (
        "qwen_image_2025_technical_report.pdf",
        "Qwen-Image Technical Report",
        "2025",
        "2508.02324",
    ),
    (
        "qwen3_omni_2025_technical_report.pdf",
        "Qwen3-Omni Technical Report",
        "2025",
        "2509.17765",
    ),
    (
        "qwen3_vl_2025_technical_report.pdf",
        "Qwen3-VL Technical Report",
        "2025",
        "2511.21631",
    ),
    (
        "qwen3_coder_next_2026_technical_report.pdf",
        "Qwen3-Coder-Next Technical Report",
        "2026",
        "2603.00729",
    ),
    (
        "qwen3_5_omni_2026_technical_report.pdf",
        "Qwen3.5-Omni Technical Report",
        "2026",
        "2604.15804",
    ),
    (
        "qwen_image_2_0_2026_technical_report.pdf",
        "Qwen-Image-2.0 Technical Report",
        "2026",
        "2605.10730",
    ),
]

LAB = "Qwen Team / Alibaba Group"


def clear_proxy_env() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def download_pdf(arxiv_id: str, dest: Path, retries: int = 3) -> None:
    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "learning-lab-benchmark-fetch/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF-"):
                raise ValueError(f"Not a PDF (missing %PDF- header): {url}")
            if len(data) < 1024:
                raise ValueError(f"PDF too small ({len(data)} bytes): {url}")
            dest.write_bytes(data)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    assert last_err is not None
    raise last_err


def main() -> int:
    clear_proxy_env()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for filename, title, year, arxiv_id in PAPERS:
        dest = PDF_DIR / filename
        print(f"Downloading {arxiv_id} -> {filename}")
        download_pdf(arxiv_id, dest)
        rows.append(
            {
                "filename": filename,
                "title": title,
                "year": year,
                "lab": LAB,
                "source_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )

    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["filename", "title", "year", "lab", "source_url"],
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)

    total_bytes = sum((PDF_DIR / r["filename"]).stat().st_size for r in rows)
    print(f"OK: {len(rows)} PDFs, {total_bytes} bytes total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
