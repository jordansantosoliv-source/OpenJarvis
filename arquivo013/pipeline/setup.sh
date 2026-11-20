#!/usr/bin/env bash
# Prepara o ambiente (idempotente). Rede: npm, PyPI e huggingface.co + us.aws.cdn.hf.co (voz).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
[ -d node_modules/@fontsource/special-elite ] || npm ci --silent
python3 -c "import piper" 2>/dev/null || pip install -q piper-tts
# faster-whisper só é usado quando há fala nova (seleção da melhor tomada)
python3 -c "import faster_whisper" 2>/dev/null || pip install -q faster-whisper
[ -f voices/pt_BR-faber-medium.onnx ] || { mkdir -p voices; (cd voices && python3 -m piper.download_voices pt_BR-faber-medium); }
for ep in ep*/; do [ -f "${ep}paper.png" ] || python3 pipeline/gen_textures.py "${ep%/}"; done
node -e "require('playwright')" && command -v ffmpeg >/dev/null && echo "setup ok"
