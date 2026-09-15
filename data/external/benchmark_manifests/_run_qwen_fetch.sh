#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PDF_DIR="$ROOT/data/external/benchmark_PDFs"
MANIFEST="$ROOT/data/external/benchmark_manifests/qwen.csv"

mkdir -p "$PDF_DIR"

download_arxiv() {
  local id="$1"
  local out="$2"
  curl -fsSL --retry 3 --retry-delay 2 -A "Mozilla/5.0 learning-lab/1.0" \
    -o "$out" "https://arxiv.org/pdf/${id}.pdf"
}

validate_pdf() {
  local f="$1"
  [[ -s "$f" ]] || { echo "FAIL empty: $f" >&2; return 1; }
  head -c 5 "$f" | grep -q '%PDF-' || { echo "FAIL not PDF: $f" >&2; return 1; }
  echo "OK: $f ($(wc -c < "$f" | tr -d ' ') bytes)"
}

declare -a ROWS=(
  'qwen_2023_technical_report.pdf|Qwen Technical Report|2023|Qwen Team, Alibaba Group|2309.16609'
  'qwen_vl_2023_versatile_vision_language.pdf|Qwen-VL: A Versatile Vision-Language Model for Understanding, Localization, Text Reading, and Beyond|2023|Qwen Team, Alibaba Group|2308.12966'
  'qwen_audio_2023_universal_audio_understanding.pdf|Qwen-Audio: Advancing Universal Audio Understanding via Unified Large-Scale Audio-Language Models|2023|Qwen Team, Alibaba Group|2311.07919'
  'qwen2_2024_technical_report.pdf|Qwen2 Technical Report|2024|Qwen Team, Alibaba Group|2407.10671'
  'qwen2_audio_2024_technical_report.pdf|Qwen2-Audio Technical Report|2024|Qwen Team, Alibaba Group|2407.10759'
  'qwen2_vl_2024_any_resolution.pdf|Qwen2-VL: Enhancing Vision-Language Model'\''s Perception of the World at Any Resolution|2024|Qwen Team, Alibaba Group|2409.12191'
  'qwen2_5_math_2024_self_improvement.pdf|Qwen2.5-Math Technical Report: Toward Mathematical Expert Model via Self-Improvement|2024|Qwen Team, Alibaba Group|2409.12122'
  'qwen2_5_coder_2024_technical_report.pdf|Qwen2.5-Coder Technical Report|2024|Qwen Team, Alibaba Group|2409.12186'
  'qwen2_5_2024_technical_report.pdf|Qwen2.5 Technical Report|2024|Qwen Team, Alibaba Group|2412.15115'
  'qwen2_5_1m_2025_long_context.pdf|Qwen2.5-1M Technical Report|2025|Qwen Team, Alibaba Group|2501.15383'
  'qwen2_5_vl_2025_technical_report.pdf|Qwen2.5-VL Technical Report|2025|Qwen Team, Alibaba Group|2502.13923'
  'qwen2_5_omni_2025_technical_report.pdf|Qwen2.5-Omni Technical Report|2025|Qwen Team, Alibaba Group|2503.20215'
  'qwen3_2025_technical_report.pdf|Qwen3 Technical Report|2025|Qwen Team, Alibaba Group|2505.09388'
  'qwenlong_cprs_2025_dynamic_context.pdf|QwenLong-CPRS: Towards ∞-LLMs with Dynamic Context Optimization|2025|Qwen Team, Alibaba Group|2505.18092'
  'qwen_image_2025_technical_report.pdf|Qwen-Image Technical Report|2025|Qwen Team, Alibaba Group|2508.02324'
  'qwen3_omni_2025_technical_report.pdf|Qwen3-Omni Technical Report|2025|Qwen Team, Alibaba Group|2509.17765'
  'qwen3_vl_2025_technical_report.pdf|Qwen3-VL Technical Report|2025|Qwen Team, Alibaba Group|2511.21631'
  'qwen3_coder_next_2026_technical_report.pdf|Qwen3-Coder-Next Technical Report|2026|Qwen Team, Alibaba Group|2603.00729'
  'qwen3_5_omni_2026_technical_report.pdf|Qwen3.5-Omni Technical Report|2026|Qwen Team, Alibaba Group|2604.15804'
  'qwen_image_2_0_2026_technical_report.pdf|Qwen-Image-2.0 Technical Report|2026|Qwen Team, Alibaba Group|2605.10730'
)

echo "filename,title,year,lab,source_url" > "$MANIFEST"
for row in "${ROWS[@]}"; do
  IFS='|' read -r filename title year lab arxiv_id <<< "$row"
  out="$PDF_DIR/$filename"
  echo "Downloading $arxiv_id -> $filename"
  download_arxiv "$arxiv_id" "$out"
  validate_pdf "$out"
  printf '%s,"%s",%s,"%s",https://arxiv.org/abs/%s\n' \
    "$filename" "$title" "$year" "$lab" "$arxiv_id" >> "$MANIFEST"
done

echo "--- done: $(tail -n +2 "$MANIFEST" | wc -l | tr -d ' ') rows ---"
