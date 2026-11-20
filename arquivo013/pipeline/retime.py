"""Narração com cache + retiming.
Uso: python3 pipeline/retime.py <ep_dir> <voz.onnx> [length_scale=1.0]
Entrada: <ep>/timeline_v1.json (base), <ep>/narration.json (texto falado).
Saída:   <ep>/build/timeline.json, <ep>/build/vo.wav.
Falas já aprovadas vêm de <ep>/vo_cache (sem Piper/Whisper). Só falas novas/alteradas
são sintetizadas: 4 tomadas, escolhe a que o Whisper transcreve mais fiel ao texto."""
import json, wave, sys, os, re, io, hashlib, difflib, unicodedata
import numpy as np

EP, VOICE = sys.argv[1], sys.argv[2]
LS = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
VNAME = os.path.basename(VOICE).replace(".onnx", "")
TL = json.load(open(f"{EP}/timeline_v1.json"))
N = json.load(open(f"{EP}/narration.json"))
CACHE = f"{EP}/vo_cache"; os.makedirs(CACHE, exist_ok=True); os.makedirs(f"{EP}/build", exist_ok=True)
MANP = f"{CACHE}/manifest.json"
MAN = json.load(open(MANP)) if os.path.exists(MANP) else {}
SR = json.load(open(VOICE + ".json"))["audio"]["sample_rate"]
LEAD, GAP, TAIL, HOLD_END = .28, .24, .42, 1.6
NUM = {"66": "sessenta e seis", "013": "zero treze", "17": "dezessete", "16": "dezesseis",
       "18": "dezoito", "30": "trinta", "60": "sessenta", "6": "seis"}
_voice = _asr = None

def voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice
        _voice = PiperVoice.load(VOICE)
    return _voice

def asr():
    global _asr
    if _asr is None:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from faster_whisper import WhisperModel
        _asr = WhisperModel("small", device="cpu", compute_type="int8")
    return _asr

def norm(s):
    s = " ".join(NUM.get(w, w) for w in re.findall(r"\w+", s.lower()))
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def synth1(text, ls):
    from piper import SynthesisConfig
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice().synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=ls, noise_scale=.5, noise_w_scale=.6))
    buf.seek(0)
    with wave.open(buf) as wf:
        x = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    idx = np.where(np.abs(x) > .02)[0]
    return x[max(0, idx[0] - int(.03 * SR)): idx[-1] + int(.06 * SR)] if len(idx) else x

def score(x, text):
    n = int(len(x) * 16000 / SR)
    a = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    segs, _ = asr().transcribe(a, language="pt", beam_size=5)
    heard = " ".join(s.text for s in segs).strip()
    return difflib.SequenceMatcher(None, norm(text), norm(heard)).ratio(), heard

def get(text, sid):
    key = hashlib.sha1(f"{VNAME}|{LS}|{text}".encode()).hexdigest()[:16]
    p = f"{CACHE}/{key}.wav"
    if key in MAN and os.path.exists(p):
        with wave.open(p) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768, False
    best = None
    for ls in (LS, LS, LS * .95, LS * .95):
        x = synth1(text, ls); sc, heard = score(x, text)
        if best is None or sc > best[0] + 1e-9:
            best = (sc, x, heard)
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(best[1], -1, 1) * 32767).astype(np.int16).tobytes())
    MAN[key] = {"text": text, "scene": sid, "dur": round(len(best[1]) / SR, 3), "score": round(best[0], 3), "heard": best[2]}
    flag = "" if best[0] >= .99 else "  <-- OUVIR"
    print(f"  nova fala {best[0]:.2f} | {text} -> {best[2]}{flag}")
    return best[1], True

out = {"fps": TL["fps"], "scenes": []}
clips, t_abs, new = [], 0.0, 0
last_id = TL["scenes"][-1]["id"]
for sc in TL["scenes"]:
    lines = N[sc["id"]]
    assert len(lines) == len(sc["caps"]), f"{sc['id']}: falas != legendas"
    t = .15 if sc is TL["scenes"][0] else LEAD
    starts, durs = [], []
    for txt in lines:
        x, isnew = get(txt, sc["id"]); new += isnew
        d = len(x) / SR
        starts.append(round(t, 3)); durs.append(d); clips.append((t_abs + t, x))
        t += d + GAP
    dur = round(t - GAP + TAIL + (HOLD_END if sc["id"] == last_id else 0), 2)
    old = [c[0] for c in sc["caps"]]
    def remap(at):
        k = max([i for i, o in enumerate(old) if o <= at + 1e-6] or [0])
        return round(starts[k] + (at - old[k]), 3) if at > 0 else 0.0
    s2 = dict(sc, dur=dur)
    s2["caps"] = [[starts[i], c[1]] for i, c in enumerate(sc["caps"])]
    s2["sfx"] = [[remap(a), n] for a, n in sc.get("sfx", [])]
    if sc["id"] == last_id:
        s2["sfx"] = [[starts[0] + 1.6, "stamp"], [dur - 1.4, "sting"]]
    if "note" in sc:
        nt = dict(sc["note"]); chars = sum(len(l) for l in nt["lines"])
        nt["start"] = starts[2]
        nt["cps"] = round(chars / max(1.0, durs[2] - nt["gap"] * (len(nt["lines"]) - 1)), 2)
        s2["note"] = nt
    s2["vo"] = [[starts[i], round(durs[i], 3)] for i in range(len(lines))]
    out["scenes"].append(s2)
    t_abs += dur

vo = np.zeros(int(t_abs * SR) + SR)
for at, x in clips:
    i = int(at * SR); vo[i:i + len(x)] += x
with wave.open(f"{EP}/build/vo.wav", "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.clip(vo, -1, 1) * 32767).astype(np.int16).tobytes())
json.dump(out, open(f"{EP}/build/timeline.json", "w"), ensure_ascii=False, indent=1)
if new:
    json.dump(MAN, open(MANP, "w"), ensure_ascii=False, indent=1)
print(f"retime ok: {round(t_abs, 2)} s, {len(clips)} falas, {new} novas")
