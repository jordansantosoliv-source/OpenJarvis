#!/usr/bin/env bash
# Uso: pipeline/build.sh <ep> [etapa]
#   etapas: vo | audio | frames | preview | mux | all (padrão: all = vo audio frames mux)
#   cenas avulsas: SCENES=s3,s7 pipeline/build.sh ep01 frames   (só se as durações não mudaram)
# Saída final: entrega/ARQUIVO013_<ep>_<data-hora>.mp4 (nunca sobrescreve).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
EP=${1:?informe o episódio, ex.: ep01}; STEP=${2:-all}
B=$EP/build; W=${WORKERS:-4}; VOICE=voices/pt_BR-faber-medium.onnx
mkdir -p "$B" entrega
run() { [ "$STEP" = all ] || [ "$STEP" = "$1" ]; }

if run vo; then python3 pipeline/retime.py "$EP" "$VOICE" 1.0 2>&1 | grep -vi "warn"; fi
[ -f "$B/timeline.json" ] || { echo "falta $B/timeline.json: rode a etapa vo"; exit 1; }
read -r TOT NF <<<"$(python3 -c "import json;t=sum(s['dur'] for s in json.load(open('$B/timeline.json'))['scenes']);print(round(t,3),round(t*30))")"

if run audio; then python3 pipeline/audio.py "$B/timeline.json" "$B/audio.wav"; fi

if run frames; then
  if [ -n "${SCENES:-}" ]; then
    node pipeline/render.js "$EP" "$B/timeline.json" "$B/frames" scenes "$SCENES"
  else
    rm -rf "$B/frames"; Q=$(( (NF + W - 1) / W ))
    for i in $(seq 0 $((W - 1))); do
      s=$((i * Q)); e=$(((i + 1) * Q)); [ $e -gt "$NF" ] && e=$NF
      node pipeline/render.js "$EP" "$B/timeline.json" "$B/frames" range $s $e > "$B/render_$i.log" 2>&1 &
    done
    wait; cat "$B"/render_*.log
  fi
  echo "quadros: $(ls "$B/frames" | wc -l)/$NF"
fi

if [ "$STEP" = preview ]; then  # 1 quadro por cena + folha pequena (barata para revisar)
  FR=$(python3 -c "
import json;t=0;o=[]
for s in json.load(open('$B/timeline.json'))['scenes']:o.append(str(round((t+s['dur']*.7)*30)));t+=s['dur']
print(','.join(o))")
  rm -rf "$B/preview"; node pipeline/render.js "$EP" "$B/timeline.json" "$B/preview" preview "$FR"
  python3 -c "
from PIL import Image;import glob
f=sorted(glob.glob('$B/preview/p_*.png'));c=6;r=(len(f)+c-1)//c;S=Image.new('RGB',(c*270,r*480))
for i,p in enumerate(f):S.paste(Image.open(p).resize((270,480)),((i%c)*270,(i//c)*480))
S.save('$B/preview_sheet.jpg',quality=80);print('$B/preview_sheet.jpg')"
fi

if run mux; then
  ffmpeg -hide_banner -loglevel error -y -i "$B/audio.wav" -i "$B/vo.wav" -filter_complex \
"[1:a]aresample=48000,highpass=f=70,equalizer=f=180:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.2:g=3,acompressor=threshold=-22dB:ratio=3:attack=5:release=90:makeup=3,aecho=0.85:0.5:38:0.10,pan=stereo|c0=c0|c1=c0,asplit=2[vo][sc];[0:a]volume=0.8[m];[m][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[md];[md][vo]amix=inputs=2:duration=first:normalize=0[out]" \
    -map "[out]" -t "$TOT" -ar 48000 "$B/mix.wav"
  LN=$(ffmpeg -hide_banner -i "$B/mix.wav" -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p' | python3 -c "
import json,sys;d=json.load(sys.stdin)
print(f\"measured_I={d['input_i']}:measured_TP={d['input_tp']}:measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}\")")
  OUT=entrega/ARQUIVO013_${EP}_$(date +%Y%m%d-%H%M).mp4
  ffmpeg -hide_banner -loglevel error -n -framerate 30 -i "$B/frames/f_%05d.jpg" -i "$B/mix.wav" -c:v libx264 -preset slow -crf 22 \
    -maxrate 9M -bufsize 18M -pix_fmt yuv420p -profile:v high -level 4.1 -r 30 -af "loudnorm=I=-14:TP=-1.5:LRA=11:$LN:linear=true" \
    -ar 48000 -c:a aac -b:a 192k -movflags +faststart -shortest "$OUT"
  ffprobe -v error -show_entries format=duration,size -of compact "$OUT"; echo "$OUT"
fi
