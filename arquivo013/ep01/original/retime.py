"""Synthesize narration with Piper, retime scenes/captions/sfx to the voice, write timeline2.json + vo.wav."""
import json, wave, sys
import numpy as np
from piper import PiperVoice, SynthesisConfig

D = sys.argv[1]; VOICE = sys.argv[2]; LS = float(sys.argv[3]) if len(sys.argv) > 3 else 0.9
TL = json.load(open(f"{D}/timeline_v1.json"))
N = json.load(open(f"{D}/narration.json"))
v = PiperVoice.load(VOICE)
SR = v.config.sample_rate
LEAD, GAP, TAIL = .28, .24, .42

import os, re, difflib, unicodedata
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from faster_whisper import WhisperModel
ASR = WhisperModel("small", device="cpu", compute_type="int8")
NUM = {"66": "sessenta e seis", "013": "zero treze", "17": "dezessete", "16": "dezesseis", "18": "dezoito", "30": "trinta", "60": "sessenta", "6": "seis"}
def norm(s):
    s = " ".join(NUM.get(w, w) for w in re.findall(r"\w+", s.lower()))
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
def score(x, text):
    n = int(len(x) * 16000 / SR)
    a = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    segs, _ = ASR.transcribe(a, language="pt", beam_size=5)
    heard = " ".join(s.text for s in segs)
    return difflib.SequenceMatcher(None, norm(text), norm(heard)).ratio(), heard
def synth(text):
    best = None
    for ls in (LS, LS, LS * .95, LS * .95):
        x = synth1(text, ls); sc, heard = score(x, text)
        if best is None or sc > best[0] + 1e-9: best = (sc, x, heard, ls)
    print(f"  {best[0]:.2f} ls={best[3]:.2f} | {text} -> {best[2].strip()}")
    return best[1]
def synth1(text, ls):
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        v.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=ls, noise_scale=.5, noise_w_scale=.6))
    buf.seek(0)
    with wave.open(buf) as wf:
        x = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    a = np.abs(x); thr = .02
    idx = np.where(a > thr)[0]
    if len(idx): x = x[max(0, idx[0] - int(.03 * SR)): idx[-1] + int(.06 * SR)]
    return x

out = {"fps": TL["fps"], "scenes": []}
clips = []  # (abs_time, samples)
t_abs = 0.0
for sc in TL["scenes"]:
    lines = N[sc["id"]]
    assert len(lines) == len(sc["caps"]), sc["id"]
    t = LEAD if sc["id"] != "s1" else .15
    starts, durs = [], []
    for txt in lines:
        x = synth(txt); d = len(x) / SR
        starts.append(round(t, 3)); durs.append(d); clips.append((t_abs + t, x))
        t += d + GAP
    dur = round(t - GAP + TAIL + (1.6 if sc["id"] == "s11" else 0), 2)
    old = [c[0] for c in sc["caps"]]
    def remap(at):
        # shift an event to follow the caption it belonged to
        k = max([i for i, o in enumerate(old) if o <= at + 1e-6] or [0])
        return round(starts[k] + (at - old[k]), 3) if at > 0 else 0.0
    new = dict(sc)
    new["dur"] = dur
    new["caps"] = [[starts[i], c[1]] for i, c in enumerate(sc["caps"])]
    new["sfx"] = [[remap(a), n] for a, n in sc.get("sfx", [])]
    if sc["id"] == "s11":
        new["sfx"] = [[starts[0] + 1.6, "stamp"], [dur - 1.4, "sting"]]
    if "note" in sc:
        nt = dict(sc["note"]); chars = sum(len(l) for l in nt["lines"])
        nt["start"] = starts[2]
        nt["cps"] = round(chars / max(1.0, durs[2] - nt["gap"] * (len(nt["lines"]) - 1)), 2)
        new["note"] = nt
    new["vo"] = [[starts[i], round(durs[i], 3)] for i in range(len(lines))]
    out["scenes"].append(new)
    t_abs += dur

total = t_abs
vo = np.zeros(int(total * SR) + SR)
for at, x in clips:
    i = int(at * SR); vo[i:i + len(x)] += x
with wave.open(f"{D}/vo.wav", "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.clip(vo, -1, 1) * 32767).astype(np.int16).tobytes())
json.dump(out, open(f"{D}/timeline2.json", "w"), ensure_ascii=False, indent=1)
print("total", round(total, 2), [s["dur"] for s in out["scenes"]])
