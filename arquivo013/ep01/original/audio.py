"""Original synthesized soundtrack for ARQUIVO 013 EP01 (no samples, no licenses)."""
import json, sys, wave
import numpy as np

D = sys.argv[1]
TL = json.load(open(f"{D}/timeline.json"))
SR = 48000
starts, t = [], 0.0
for s in TL["scenes"]:
    starts.append(t); t += s["dur"]
TOTAL = t
N = int(TOTAL * SR)
rng = np.random.default_rng(13)
L = np.zeros(N); R = np.zeros(N)

def band(x, lo, hi):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    m = ((f >= lo) & (f <= hi)).astype(float)
    # soft edges
    m = np.convolve(m, np.hanning(41) / np.hanning(41).sum(), mode="same")
    return np.fft.irfft(X * m, len(x))

def add(sig, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= N: return
    sig = sig[: N - i]
    L[i:i + len(sig)] += sig * gain * (1 - max(pan, 0))
    R[i:i + len(sig)] += sig * gain * (1 + min(pan, 0))

def env(n, a, r):
    e = np.ones(n); na, nr = int(a * SR), int(r * SR)
    if na: e[:na] = np.linspace(0, 1, na)
    if nr: e[-nr:] *= np.linspace(1, 0, nr)
    return e

tt = np.arange(N) / SR
# --- bed: low drone + minor pad + air ---
drone = (np.sin(2 * np.pi * 55 * tt) + .7 * np.sin(2 * np.pi * 55.35 * tt) + .55 * np.sin(2 * np.pi * 82.41 * tt + 1))
drone *= .5 + .5 * np.sin(2 * np.pi * tt / 9.0) ** 2
pad = sum(np.sin(2 * np.pi * f * tt + p) for f, p in ((110, 0), (130.81, .7), (164.81, 1.9)))
pad *= .35 + .25 * np.sin(2 * np.pi * tt / 13.0)
air = band(rng.standard_normal(N), 80, 600)
air /= np.abs(air).max()
bed = .055 * drone + .012 * pad + .03 * air
fade = np.minimum(1, tt / 1.0) * np.minimum(1, (TOTAL - tt) / 1.2)
L += bed * fade; R += bed * fade

# --- ambiences per scene ---
for s, st in zip(TL["scenes"], starts):
    n = int(s["dur"] * SR); e = env(n, .25, .25); a = s.get("amb")
    if a == "rain":
        x = band(rng.standard_normal(n), 1200, 9000); x /= np.abs(x).max()
        drops = np.zeros(n); idx = rng.integers(0, n, int(s["dur"] * 40)); drops[idx] = rng.uniform(.3, 1, len(idx))
        drops = np.convolve(drops, np.exp(-np.arange(200) / 25) * rng.standard_normal(200), "same")
        add((.06 * x + .03 * drops / (np.abs(drops).max() + 1e-9)) * e, st, 1, -.15)
        add((.06 * band(rng.standard_normal(n), 1200, 9000) / 3.5) * e, st, 1, .15)
    elif a == "wind":
        x = band(rng.standard_normal(n), 180, 900); x /= np.abs(x).max()
        lfo = .55 + .45 * np.sin(2 * np.pi * np.arange(n) / SR / 2.7 + 1)
        add(.09 * x * lfo * e, st, 1, -.2); add(.07 * np.roll(x, 3000) * lfo * e, st, 1, .2)
    elif a == "clock":
        for k in np.arange(.0, s["dur"], .5):
            m = int(.03 * SR); c = rng.standard_normal(m) * np.exp(-np.arange(m) / 90)
            c += .6 * np.sin(2 * np.pi * (2400 if int(k * 2) % 2 else 2000) * np.arange(m) / SR) * np.exp(-np.arange(m) / 120)
            add(.10 * c, st + k, 1, .25)
    elif a == "eerie":
        x = np.arange(n) / SR
        vib = np.sin(2 * np.pi * 660 * x + 3 * np.sin(2 * np.pi * 5 * x)) + .6 * np.sin(2 * np.pi * 990 * x + 2 * np.sin(2 * np.pi * 4.3 * x))
        swell = .5 + .5 * np.sin(2 * np.pi * x / 2.85 - 1.5)
        add(.022 * vib * swell * e, st, 1, .1)
    # room tone everywhere else
    rt = band(rng.standard_normal(n), 60, 400); rt /= np.abs(rt).max()
    add(.012 * rt * e, st)

# --- sfx ---
def boom(dur=1.6, f0=72, f1=38, g=1.0):
    n = int(dur * SR); x = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-x * 6); ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-x * 2.6)
    nz = band(rng.standard_normal(n), 30, 300) * np.exp(-x * 9); nz /= np.abs(nz).max()
    return g * (s + .5 * nz)
def whoosh(dur=.45):
    n = int(dur * SR); x = rng.standard_normal(n); out = np.zeros(n); seg = n // 8
    for k in range(8):
        lo = 300 * (1.45 ** k); out[k * seg:(k + 1) * seg] = band(x[k * seg:(k + 1) * seg], lo, lo * 3)
    return out / np.abs(out).max() * np.sin(np.pi * np.linspace(0, 1, n)) ** 2
def click(g=1.0):
    m = int(.022 * SR); x = np.arange(m)
    c = band(rng.standard_normal(m), 1800, 6000) * np.exp(-x / 60)
    c = c / (np.abs(c).max() + 1e-9) + .5 * np.sin(2 * np.pi * 620 * x / SR) * np.exp(-x / 180)
    return g * c
def stamp_s():
    n = int(.35 * SR); x = np.arange(n) / SR
    s = np.sin(2 * np.pi * 95 * x) * np.exp(-x * 22) + .7 * band(rng.standard_normal(n), 200, 3000) * np.exp(-x * 40) / 3
    return s
def paper():
    n = int(.3 * SR); x = band(rng.standard_normal(n), 2000, 7000)
    return x / np.abs(x).max() * np.exp(-np.linspace(0, 4, n)) * (rng.random(n) > .3)
def pin():
    n = int(.25 * SR); x = np.arange(n) / SR
    return np.sin(2 * np.pi * 1850 * x) * np.exp(-x * 18) * .6 + click(.6).tolist().__len__() * 0 + np.pad(click(.5), (0, n - int(.022 * SR)))
def sting():
    n = int(3.2 * SR); x = np.arange(n) / SR
    ch = sum(np.sin(2 * np.pi * f * x) for f in (55, 82.41, 110, 130.81))
    return ch * np.minimum(1, x / .25) * np.exp(-x * .9) * .5 + .6 * boom(3.2, 60, 35)

SFX = {"boom": (lambda: boom(), .42), "hit": (lambda: boom(.8, 90, 45), .3), "whoosh": (whoosh, .10),
       "stamp": (stamp_s, .5), "paper": (paper, .08), "pin": (pin, .16), "sting": (sting, .36)}
for s, st in zip(TL["scenes"], starts):
    for at, name in s.get("sfx", []):
        fn, g = SFX[name]; add(fn(), st + at, g)
    nt = s.get("note")
    if nt:
        tcur = nt["start"]
        for line in nt["lines"]:
            for k, ch in enumerate(line):
                if ch != " ":
                    add(click(rng.uniform(.8, 1.2)), st + tcur + k / nt["cps"], .17, rng.uniform(-.2, .2))
            tcur += len(line) / nt["cps"] + nt["gap"]

mix = np.stack([L, R], 1)
mix = np.tanh(mix * 1.4) / np.tanh(1.4)
mix /= np.abs(mix).max() / .9
with wave.open(f"{D}/audio.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print(f"audio ok {TOTAL}s")
