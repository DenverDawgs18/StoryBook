"""Neural narration (Kokoro-82M, run locally via ONNX) plus per-character voice treatment."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from . import dsp
from .dsp import SR

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = Path(os.environ.get("STORYBOOK_MODELS", ROOT / "models"))
CACHE_DIR = Path(os.environ.get("STORYBOOK_CACHE", ROOT / ".cache" / "tts"))

MODEL_URLS = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

# A curated palette, described for the Studio UI.
VOICE_CATALOG = {
    "bm_lewis": "Deep, grave British male - the documentary narrator",
    "bm_george": "Warm, measured British male",
    "bm_daniel": "Dry, clipped British male",
    "bm_fable": "Bright, lively British male",
    "bf_emma": "Clear, composed British female",
    "bf_isabella": "Soft, warm British female",
    "bf_alice": "Crisp, youthful British female",
    "bf_lily": "Gentle, light British female",
    "am_michael": "Steady American male",
    "am_onyx": "Low, gravelly American male",
    "am_fenrir": "Strong, rough American male",
    "am_puck": "Playful American male",
    "af_heart": "Expressive American female",
    "af_bella": "Rich, emotive American female",
    "af_nicole": "Hushed, breathy American female",
    "af_sky": "Light American female",
}

_KOKORO = None


def ensure_models() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_URLS.items():
        p = MODEL_DIR / name
        if not p.exists():
            print(f"downloading {name} ...")
            subprocess.run(["curl", "-sSL", "-o", str(p), url], check=True)


def kokoro():
    global _KOKORO
    if _KOKORO is None:
        ensure_models()
        from kokoro_onnx import Kokoro
        _KOKORO = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
    return _KOKORO


def resolve_voice(spec: str):
    """'bm_lewis', a blend like 'bm_lewis*0.7+am_onyx*0.3', or 'TIMBRE|PROSODY@amount'.

    A Kokoro style vector is two halves: the first 128 values colour the voice (timbre), the last 128
    drive the prosody predictor (pitch contour, energy, timing). 'TIMBRE|PROSODY@0.8' keeps the
    speaker's own timbre and moves 80% of the way to another voice's prosody, so the model itself
    performs a livelier, higher, wider-ranging line, with no pitch-shifting afterwards.
    """
    if "|" in spec:
        timbre, _, rest = spec.partition("|")
        pros, _, amt = rest.partition("@")
        a = float(amt or 1.0)
        base = _style(timbre)
        other = _style(pros)
        out = base.copy()
        out[..., 128:] = (1 - a) * base[..., 128:] + a * other[..., 128:]
        return out.astype(np.float32)
    if "+" not in spec and "*" not in spec:
        return spec
    return _style(spec)


def _style(spec: str):
    k = kokoro()
    style = None
    for term in spec.split("+"):
        name, _, w = term.strip().partition("*")
        v = k.get_voice_style(name.strip()) * float(w or 1.0)
        style = v if style is None else style + v
    return style


@dataclass
class Character:
    name: str
    voice: str = "bm_george"
    speed: float = 1.0
    lang: str = "en-gb"
    pitch: float = 0.0  # semitones (formant-preserving shift via rubberband)
    room: str | None = "booth"
    wet: float = 0.06
    gain: float = 0.0  # dB
    pan: float = 0.0
    tone: str = "warm"  # warm | plain | ghost | distant | thin
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name, d):
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "lang" not in known:
            known["lang"] = "en-us" if str(d.get("voice", "b")).startswith("a") else "en-gb"
        return cls(name=name, **known)


# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------
def clean_text(t: str) -> str:
    t = t.replace("_", "")
    t = re.sub(r"\[\d+\]", "", t)
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("&", " and ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


_BREAKS = [
    (re.compile(r"(?<=[.!?])['\"”]?\s+"), 0.42),
    (re.compile(r"\s*[—–]\s*|\s*--\s*"), 0.22),
    (re.compile(r"(?<=[;:])\s+"), 0.28),
]


def phrase_split(text: str, max_len: int = 280):
    """Split text into (phrase, pause_after) units for natural, controllable pacing."""
    text = clean_text(text)
    units = [(text, 0.0)]
    for rx, pause in _BREAKS:
        new = []
        for chunk, p in units:
            parts = [x for x in rx.split(chunk) if x and x.strip()]
            for i, part in enumerate(parts):
                new.append((part.strip(), pause if i < len(parts) - 1 else p))
        units = new
    # break very long phrases at commas
    out = []
    for chunk, p in units:
        if len(chunk) <= max_len:
            out.append((chunk, p))
            continue
        pieces = re.split(r"(?<=,)\s+", chunk)
        buf = ""
        for pc in pieces:
            if buf and len(buf) + len(pc) > max_len:
                out.append((buf, 0.12))
                buf = pc
            else:
                buf = f"{buf} {pc}".strip()
        if buf:
            out.append((buf, p))
    # merge tiny fragments into neighbours ("Yes." stays; but "and" alone doesn't)
    merged = []
    for chunk, p in out:
        if merged and len(re.sub(r"\W", "", chunk)) == 0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], p))
            continue
        merged.append((chunk, p))
    return _absorb_short(merged, max_len)


MIN_WORDS = 4  # Kokoro reads one- to three-word inputs with flat, stock "TTS" prosody


def _words(s: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", s))


def _join(a: str, b: str) -> str:
    # a split on a dash consumed the dash; keep a comma's worth of breath where it was
    return f"{a} {b}" if re.search(r"[.!?;:,'\"”)]$", a) else f"{a}, {b}"


def _absorb_short(units, max_len: int):
    """Join phrases too short for natural prosody onto a neighbour, so the model always reads
    them in context ("Goodnight, Mia. Sleep tight." as one breath, not two robotic stubs).
    A text that is short as a whole is left alone: there is nothing to give it context."""
    units = list(units)
    i = 0
    while len(units) > 1 and i < len(units):
        chunk, pause = units[i]
        if _words(chunk) >= MIN_WORDS:
            i += 1
            continue
        prev_ok = i > 0 and len(units[i - 1][0]) + len(chunk) < max_len
        next_ok = i + 1 < len(units) and len(units[i + 1][0]) + len(chunk) < max_len
        # prefer the shorter neighbour, so the joined phrase stays well-proportioned
        if prev_ok and (not next_ok or len(units[i - 1][0]) <= len(units[i + 1][0])):
            units[i - 1] = (_join(units[i - 1][0], chunk), pause)
            del units[i]
            i = max(i - 1, 0)
        elif next_ok:
            units[i + 1] = (_join(chunk, units[i + 1][0]), units[i + 1][1])
            del units[i]
        else:
            i += 1
    return units


# --------------------------------------------------------------------------
# synthesis
# --------------------------------------------------------------------------
def _trim(x: np.ndarray, thresh_db: float = -45, pad: float = 0.02) -> np.ndarray:
    if len(x) == 0:
        return x
    env = np.abs(x)
    thr = dsp.db(thresh_db) * max(env.max(), 1e-6)
    idx = np.where(env > thr)[0]
    if len(idx) == 0:
        return x[:0]
    a = max(idx[0] - dsp.samples(pad), 0)
    b = min(idx[-1] + dsp.samples(pad * 4), len(x))
    return x[a:b]


def _raw_tts(text: str, ch: Character) -> np.ndarray:
    key = hashlib.sha1(json.dumps([text, ch.voice, round(ch.speed, 3), ch.lang]).encode()).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.npy"
    if path.exists():
        return np.load(path)
    audio, sr = kokoro().create(text, voice=resolve_voice(ch.voice), speed=float(ch.speed), lang=ch.lang)
    audio = signal.resample_poly(audio.astype(np.float32), SR // 1000, sr // 1000).astype(np.float32)
    audio = _trim(audio)
    np.save(path, audio)
    return audio


def _pitch_shift(x: np.ndarray, semis: float) -> np.ndarray:
    if abs(semis) < 0.05 or len(x) == 0:
        return x
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.wav"), os.path.join(td, "b.wav")
        sf.write(a, x, SR)
        ratio = 2 ** (semis / 12)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", a, "-af",
                        f"rubberband=pitch={ratio:.5f}:formant=preserved:pitchq=quality", b], check=True)
        y, _ = sf.read(b, dtype="float32")
    return y[: len(x) + dsp.samples(0.05)]


def treat(x: np.ndarray, ch: Character) -> np.ndarray:
    """Per-character tone shaping; returns mono (room is applied on the bus)."""
    x = dsp.highpass(x, 70)
    if ch.tone == "warm":
        x = dsp.eq(x, "lowshelf", 180, 2.0)
        x = dsp.eq(x, "peak", 3200, 1.0, 0.8)
        x = dsp.eq(x, "highshelf", 9000, -1.5)
    elif ch.tone == "ghost":
        x = dsp.eq(x, "lowshelf", 220, 4.0)
        x = dsp.eq(x, "highshelf", 4000, -5)
    elif ch.tone == "distant":
        x = dsp.bandpass(x, 250, 3500)
    elif ch.tone == "thin":
        x = dsp.highpass(x, 220)
        x = dsp.eq(x, "peak", 2500, 3, 1.0)
    return x


# --------------------------------------------------------------------------
# delivery: per-line direction
# --------------------------------------------------------------------------
# Kokoro has no emotion control: capitals, "!!!", repeats and speed leave the pitch flat. Pitch-shifting
# and saturating the result afterwards (the first attempt) sounded synthetic. What does work is the
# prosody half of the style vector (see resolve_voice): borrowing it from a livelier voice makes the model
# itself speak higher, wider and more urgently while the character keeps their own timbre.
# Measured on Rumpelstiltskin's "Some witch told you that!": own prosody 119 Hz median / 96 Hz range;
# am_santa's prosody 192 Hz / 193 Hz range; am_fenrir's 138 Hz / 121 Hz.
# `amount` is how far to move toward that prosody; `climb` adds to it on each later phrase, so a repeated
# line escalates. `gain` is dB above the character's usual level: a shout is much louder, not just
# more forceful (Paul, Nov 22). The mix limits the peaks of these lines cleanly so they don't distort.
DELIVERIES = {
    "snap": {"male": "am_fenrir", "female": "af_sarah", "amount": 0.5, "climb": 0.0, "speed": 1.04, "gain": 3.0, "gap": 1.0},
    "shout": {"male": "am_fenrir", "female": "af_sarah", "amount": 0.9, "climb": 0.1, "speed": 1.08, "gain": 7.0, "gap": 0.7},
    "rage": {"male": "am_santa", "female": "af_bella", "amount": 0.5, "climb": 0.4, "speed": 1.12, "gain": 14.0, "gap": 0.45},
}
if os.environ.get("STORYBOOK_RAGE"):  # experiments: "voice:amount:climb"
    _v, _a, _c = os.environ["STORYBOOK_RAGE"].split(":")
    DELIVERIES["rage"].update(male=_v, amount=float(_a), climb=float(_c))


def _female(spec: str) -> bool:
    w = {}
    for term in spec.split("|")[0].split("+"):
        name, _, x = term.strip().partition("*")
        w[name.strip()[1:2] == "f"] = w.get(name.strip()[1:2] == "f", 0) + float(x or 1)
    return w.get(True, 0) > w.get(False, 0)


def speak(text: str, ch: Character, delivery: str | None = None):
    """Render a run of text in one character's voice, optionally with a delivery (see DELIVERIES).

    Returns (mono audio, [(phrase, start_s, end_s), ...]).
    """
    d = DELIVERIES.get(delivery or "")
    if delivery and d is None:
        raise ValueError(f"unknown delivery {delivery!r} (have {', '.join(DELIVERIES)})")
    pieces = []
    marks = []
    t = 0.0
    speed = ch.speed * (d["speed"] if d else 1.0)
    for i, (phrase, pause) in enumerate(phrase_split(text)):
        pch = ch
        if d:
            src = d["female" if _female(ch.voice) else "male"]
            amt = min(d["amount"] + d["climb"] * i, 1.0)
            pch = dataclasses.replace(ch, voice=f"{ch.voice}|{src}@{amt:.2f}", speed=round(speed, 3))
            pause *= d["gap"]
        a = _raw_tts(phrase, pch)
        if len(a) == 0:
            continue
        pieces.append(a)
        marks.append((phrase, t, t + len(a) / SR))
        t += len(a) / SR
        if pause:
            pieces.append(np.zeros(dsp.samples(pause / max(speed, 0.5)), dtype=np.float32))
            t += pause / max(speed, 0.5)
    if not pieces:
        return np.zeros(0, dtype=np.float32), []
    y = np.concatenate(pieces)
    y = _pitch_shift(y, ch.pitch)
    y = treat(y, ch)
    if d and d["gain"] >= 6 and np.any(y):
        # a shouted voice is dense: tame its peaks relative to its body, like a voice at full stretch
        y = dsp.compress(y, dsp.rms_db(y) + 2, 4.0, 0.002, 0.06)
    y = dsp.set_rms(y, -20 + ch.gain + (d["gain"] if d else 0.0)) if np.any(y) else y
    return y.astype(np.float32), marks
