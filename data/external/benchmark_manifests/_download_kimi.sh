#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PDF_DIR="$ROOT/data/external/benchmark_PDFs"
MANIFEST="$ROOT/data/external/benchmark_manifests/kimi.csv"

mkdir -p "$PDF_DIR"

download_arxiv() {
  local id="$1"
  local out="$2"
  if [[ -f "$out" ]] && head -c 5 "$out" | grep -q '%PDF-'; then
    echo "SKIP (exists): $out"
    return 0
  fi
  curl -fsSL --retry 3 --retry-delay 2 -o "$out" "https://arxiv.org/pdf/${id}.pdf"
}

download_url() {
  local url="$1"
  local out="$2"
  if [[ -f "$out" ]] && head -c 5 "$out" | grep -q '%PDF-'; then
    echo "SKIP (exists): $out"
    return 0
  fi
  curl -fsSL --retry 3 --retry-delay 2 -L -o "$out" "$url"
}

validate_pdf() {
  local f="$1"
  if [[ ! -s "$f" ]]; then
    echo "FAIL empty: $f" >&2
    return 1
  fi
  if ! head -c 5 "$f" | grep -q '%PDF-'; then
    echo "FAIL not PDF: $f" >&2
    return 1
  fi
  echo "OK: $f ($(wc -c < "$f" | tr -d ' ') bytes)"
}

# Kimi / Moonshot (14)
download_arxiv "2407.00079" "$PDF_DIR/kimi_mooncake_2407.00079.pdf"
download_arxiv "2501.12599" "$PDF_DIR/kimi_k1_5_2501.12599.pdf"
download_arxiv "2502.13189" "$PDF_DIR/kimi_moba_2502.13189.pdf"
download_arxiv "2502.16982" "$PDF_DIR/kimi_moonlight_muon_2502.16982.pdf"
download_arxiv "2504.07491" "$PDF_DIR/kimi_vl_2504.07491.pdf"
download_arxiv "2504.18425" "$PDF_DIR/kimi_audio_2504.18425.pdf"
download_arxiv "2507.20534" "$PDF_DIR/kimi_k2_2507.20534.pdf"
download_arxiv "2508.09123" "$PDF_DIR/kimi_opencua_2508.09123.pdf"
download_arxiv "2509.23045" "$PDF_DIR/kimi_dev_2509.23045.pdf"
download_arxiv "2510.26692" "$PDF_DIR/kimi_linear_2510.26692.pdf"
download_arxiv "2602.02276" "$PDF_DIR/kimi_k2_5_2602.02276.pdf"
download_arxiv "2603.15031" "$PDF_DIR/kimi_attention_residuals_2603.15031.pdf"
download_arxiv "2607.24653" "$PDF_DIR/kimi_k3_2607.24653.pdf"
download_arxiv "2607.24957" "$PDF_DIR/kimi_perceptionbench_2607.24957.pdf"

# Fill from other top labs (6)
download_arxiv "2403.05530" "$PDF_DIR/other_google_deepmind_gemini_1_5_2403.05530.pdf"
download_arxiv "2407.21783" "$PDF_DIR/other_meta_ai_llama_3_2407.21783.pdf"
download_arxiv "2401.04088" "$PDF_DIR/other_mistral_mixtral_2401.04088.pdf"
download_arxiv "2406.11704" "$PDF_DIR/other_nvidia_nemotron_4_2406.11704.pdf"
download_url "https://data.x.ai/2025-08-20-grok-4-model-card.pdf" "$PDF_DIR/other_xai_grok_4_model_card_2025.pdf"
download_arxiv "2403.08295" "$PDF_DIR/other_google_deepmind_gemma_2_2403.08295.pdf"

echo "--- validation ---"
for f in "$PDF_DIR"/kimi_*.pdf "$PDF_DIR"/other_*.pdf; do
  [[ -f "$f" ]] || continue
  validate_pdf "$f"
done

cat > "$MANIFEST" <<'EOF'
filename,title,year,lab,source_url
kimi_mooncake_2407.00079.pdf,"Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving",2024,Moonshot AI,https://arxiv.org/abs/2407.00079
kimi_k1_5_2501.12599.pdf,"Kimi k1.5: Scaling Reinforcement Learning with LLMs",2025,Moonshot AI,https://arxiv.org/abs/2501.12599
kimi_moba_2502.13189.pdf,"MoBA: Mixture of Block Attention for Long-Context LLMs",2025,Moonshot AI,https://arxiv.org/abs/2502.13189
kimi_moonlight_muon_2502.16982.pdf,"Muon is Scalable for LLM Training",2025,Moonshot AI,https://arxiv.org/abs/2502.16982
kimi_vl_2504.07491.pdf,"Kimi-VL Technical Report",2025,Moonshot AI,https://arxiv.org/abs/2504.07491
kimi_audio_2504.18425.pdf,"Kimi-Audio Technical Report",2025,Moonshot AI,https://arxiv.org/abs/2504.18425
kimi_k2_2507.20534.pdf,"Kimi K2: Open Agentic Intelligence",2025,Moonshot AI,https://arxiv.org/abs/2507.20534
kimi_opencua_2508.09123.pdf,"OpenCUA: Open Foundations for Computer-Use Agents",2025,Moonshot AI,https://arxiv.org/abs/2508.09123
kimi_dev_2509.23045.pdf,"Kimi-Dev: Agentless Training as Skill Prior for SWE-Agents",2025,Moonshot AI,https://arxiv.org/abs/2509.23045
kimi_linear_2510.26692.pdf,"Kimi Linear: An Expressive, Efficient Attention Architecture",2025,Moonshot AI,https://arxiv.org/abs/2510.26692
kimi_k2_5_2602.02276.pdf,"Kimi K2.5: Visual Agentic Intelligence",2026,Moonshot AI,https://arxiv.org/abs/2602.02276
kimi_attention_residuals_2603.15031.pdf,"Attention Residuals",2026,Moonshot AI,https://arxiv.org/abs/2603.15031
kimi_k3_2607.24653.pdf,"Kimi K3: Open Frontier Intelligence",2026,Moonshot AI,https://arxiv.org/abs/2607.24653
kimi_perceptionbench_2607.24957.pdf,"PerceptionBench: Evaluating Atomic Visual Perception in Multimodal Large Language Models",2026,Moonshot AI,https://arxiv.org/abs/2607.24957
other_google_deepmind_gemini_1_5_2403.05530.pdf,"Gemini 1.5: Unlocking multimodal understanding across millions of tokens of context",2024,Google DeepMind,https://arxiv.org/abs/2403.05530
other_meta_ai_llama_3_2407.21783.pdf,"The Llama 3 Herd of Models",2024,Meta AI,https://arxiv.org/abs/2407.21783
other_mistral_mixtral_2401.04088.pdf,"Mixtral of Experts",2024,Mistral AI,https://arxiv.org/abs/2401.04088
other_nvidia_nemotron_4_2406.11704.pdf,"Nemotron-4 340B Technical Report",2024,NVIDIA,https://arxiv.org/abs/2406.11704
other_xai_grok_4_model_card_2025.pdf,"Grok 4 Model Card",2025,xAI,https://data.x.ai/2025-08-20-grok-4-model-card.pdf
other_google_deepmind_gemma_2_2403.08295.pdf,"Gemma 2: Improving Open Language Models at a Practical Size",2024,Google DeepMind,https://arxiv.org/abs/2403.08295
EOF

echo "--- manifest rows: $(tail -n +2 "$MANIFEST" | wc -l | tr -d ' ') ---"
