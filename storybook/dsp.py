"""Low-level DSP helpers shared by the voice, soundscape and mixing stages.

Everything works on float32 numpy arrays at a single project sample rate.
Stereo signals are shaped (n, 2).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

SR = 48_000


# --------------------------------------------------------------------------
# basic conversions
# --------------------------------------------------------------------------
def db(x: float) -> float:
    """Decibels -> linear gain."""
    return float(10.0 ** (x / 20.0))


def secs(n: int) -> float:
    return n / SR


def samples(t: float) -> int:
    return int(round(t * SR))


def to_stereo(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        return np.stack([x, x], axis=1)
    return x


def pan(x: np.ndarray, p: float) -> np.ndarray:
    """Equal-power pan of a mono signal. p in [-1, 1]."""
    if x.ndim == 2:
        x = x.mean(axis=1)
    a = (p + 1.0) * np.pi / 4.0
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1).astype(np.float32)


def fade(x: np.ndarray, fin: float = 0.0, fout: float = 0.0) -> np.ndarray:
    """Apply equal-power-ish (sine) fades in place-safe manner."""
    x = x.copy()
    n = len(x)
    fi = min(samples(fin), n)
    fo = min(samples(fout), n)
    if fi > 0:
        r = np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
        x[:fi] *= r[:, None] if x.ndim == 2 else r
    if fo > 0:
        r = np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
        x[n - fo:] *= r[:, None] if x.ndim == 2 else r
    return x


def normalize_peak(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    m = np.max(np.abs(x)) if len(x) else 0.0
    if m < 1e-9:
        return x
    return (x * (db(peak_db) / m)).astype(np.float32)


def rms_db(x: np.ndarray) -> float:
    r = np.sqrt(np.mean(np.square(x, dtype=np.float64)) + 1e-20)
    return 20 * np.log10(r)


def set_rms(x: np.ndarray, target_db: float) -> np.ndarray:
    return (x * db(target_db - rms_db(x))).astype(np.float32)


# --------------------------------------------------------------------------
# noise
# --------------------------------------------------------------------------
def white(n: int, rng: np.random.Generator, ch: int = 1) -> np.ndarray:
    shape = (n,) if ch == 1 else (n, ch)
    return rng.standard_normal(shape).astype(np.float32)


def colored(n: int, rng: np.random.Generator, exponent: float = 1.0, ch: int = 1) -> np.ndarray:
    """1/f^exponent noise via FFT shaping. exponent 1 = pink, 2 = brown."""
    out = []
    for _ in range(ch):
        w = rng.standard_normal(n)
        f = np.fft.rfft(w)
        freqs = np.fft.rfftfreq(n, 1 / SR)
        freqs[0] = freqs[1]
        f *= freqs ** (-exponent / 2.0)
        y = np.fft.irfft(f, n)
        y /= np.std(y) + 1e-12
        out.append(y.astype(np.float32))
    return out[0] if ch == 1 else np.stack(out, axis=1)


def smooth_random(n: int, rng: np.random.Generator, rate_hz: float, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """A slowly wandering control signal (smoothed random points, cosine interp)."""
    npts = max(int(secs(n) * rate_hz) + 3, 3)
    pts = rng.uniform(lo, hi, npts)
    xp = np.linspace(0, n, npts)
    t = np.arange(n)
    idx = np.clip(np.searchsorted(xp, t, side="right") - 1, 0, npts - 2)
    frac = (t - xp[idx]) / (xp[idx + 1] - xp[idx])
    w = (1 - np.cos(np.pi * frac)) / 2
    return (pts[idx] * (1 - w) + pts[idx + 1] * w).astype(np.float32)


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------
def _sos(kind: str, freq, order: int = 2):
    return signal.butter(order, freq, btype=kind, fs=SR, output="sos")


def lowpass(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("lowpass", min(f, SR / 2 - 100), order), x, axis=0).astype(np.float32)


def highpass(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("highpass", f, order), x, axis=0).astype(np.float32)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("bandpass", [lo, min(hi, SR / 2 - 100)], order), x, axis=0).astype(np.float32)


def _biquad(kind: str, f0: float, gain_db: float = 0.0, q: float = 0.707):
    """RBJ cookbook biquads -> sos."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / SR
    alpha = np.sin(w0) / (2 * q)
    cw = np.cos(w0)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    elif kind == "highshelf":
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
        a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    elif kind == "bpf":  # constant 0 dB peak gain
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    b = np.array(b) / a[0]
    a = np.array(a) / a[0]
    return np.concatenate([b, a])[None, :]


def eq(x: np.ndarray, kind: str, f0: float, gain_db: float = 0.0, q: float = 0.707) -> np.ndarray:
    return signal.sosfilt(_biquad(kind, f0, gain_db, q), x, axis=0).astype(np.float32)


def resonator(x: np.ndarray, f0: float, q: float) -> np.ndarray:
    return eq(x, "bpf", f0, 0, q)


# --------------------------------------------------------------------------
# time-varying spectral shaping (the workhorse for weather-like textures)
# --------------------------------------------------------------------------
def shaped_noise(duration: float, rng: np.random.Generator, envelope, nfft: int = 2048) -> np.ndarray:
    """Synthesize noise whose magnitude spectrum follows envelope(freqs, times).

    envelope receives freqs (F,) and times (T,) and returns (F, T) magnitudes.
    Generated in the STFT domain with random phases, then overlap-added.
    """
    n = samples(duration)
    hop = nfft // 4
    frames = n // hop + 4
    freqs = np.fft.rfftfreq(nfft, 1 / SR)
    times = np.arange(frames) * hop / SR
    mag = envelope(freqs, times).astype(np.float32)
    phase = rng.uniform(0, 2 * np.pi, mag.shape).astype(np.float32)
    spec = mag * np.exp(1j * phase)
    win = np.hanning(nfft).astype(np.float32)
    frames_td = np.fft.irfft(spec.T, nfft).astype(np.float32) * win
    out = np.zeros(frames * hop + nfft, dtype=np.float32)
    for i in range(frames):
        out[i * hop:i * hop + nfft] += frames_td[i]
    out = out[nfft // 2: nfft // 2 + n]
    return out / (np.std(out) + 1e-9)


# --------------------------------------------------------------------------
# reverb
# --------------------------------------------------------------------------
def make_ir(rt60: float, rng: np.random.Generator, predelay: float = 0.01, damping: float = 0.5,
            early: int = 12, width: float = 1.0) -> np.ndarray:
    """Stereo synthetic impulse response.

    Exponentially decaying decorrelated noise whose high frequencies decay faster
    (damping 0..1), plus a sprinkle of early reflections.
    """
    length = samples(rt60 * 1.2) + samples(predelay)
    t = np.arange(length) / SR
    chans = []
    for c in range(2):
        nz = rng.standard_normal(length)
        # split into bands with different decay to emulate air absorption
        lo = signal.sosfilt(_sos("lowpass", 1500), nz)
        mid = signal.sosfilt(_sos("bandpass", [1500, 5000]), nz)
        hi = signal.sosfilt(_sos("highpass", 5000), nz)
        k = 6.91 / rt60
        y = (lo * np.exp(-k * t) + mid * np.exp(-k * (1 + damping * 1.5) * t)
             + hi * np.exp(-k * (1 + damping * 4) * t) * 0.7)
        # early reflections
        for _ in range(early):
            d = samples(predelay + rng.uniform(0.003, min(0.08, rt60 * 0.3)))
            if d < length:
                y[d] += rng.uniform(-1, 1) * 3.0
        pd = samples(predelay)
        y[:pd] = 0
        # soft onset to avoid a click at predelay
        ramp = min(samples(0.004), length - pd)
        y[pd:pd + ramp] *= np.linspace(0, 1, ramp)
        chans.append(y)
    L, R = chans
    mid = (L + R) / 2
    side = (L - R) / 2 * width
    ir = np.stack([mid + side, mid - side], axis=1)
    ir /= np.sqrt(np.sum(ir ** 2) / 2) + 1e-9
    return ir.astype(np.float32)


_IR_CACHE: dict = {}

ROOMS = {
    # name: (rt60, predelay, damping, width)
    "booth": (0.25, 0.002, 0.7, 0.4),
    "room": (0.6, 0.006, 0.6, 0.7),
    "chamber": (1.2, 0.012, 0.55, 0.9),
    "hall": (2.4, 0.02, 0.5, 1.0),
    "cathedral": (5.5, 0.035, 0.45, 1.0),
    "void": (9.0, 0.06, 0.35, 1.0),
}


def get_ir(room: str) -> np.ndarray:
    if room not in _IR_CACHE:
        rt, pd, dmp, w = ROOMS[room]
        _IR_CACHE[room] = make_ir(rt, np.random.default_rng(hash(room) % 2**32), pd, dmp, width=w)
    return _IR_CACHE[room]


def reverb(x: np.ndarray, room: str = "hall", wet: float = 0.3, dry: float = 1.0, tail: bool = True) -> np.ndarray:
    """Convolution reverb. Returns stereo; length grows by the IR tail if tail=True."""
    ir = get_ir(room)
    xs = to_stereo(x)
    wet_sig = np.stack([signal.oaconvolve(xs[:, c], ir[:, c]) for c in range(2)], axis=1)
    if not tail:
        wet_sig = wet_sig[: len(xs)]
    out = wet_sig * wet
    out[: len(xs)] += xs * dry
    return out.astype(np.float32)


# --------------------------------------------------------------------------
# dynamics
# --------------------------------------------------------------------------
def envelope_follow(x: np.ndarray, attack: float = 0.01, release: float = 0.25, hop: int = 240) -> np.ndarray:
    """Cheap RMS envelope at hop resolution, upsampled back to signal length."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    n = len(mono)
    nb = n // hop + 1
    padded = np.zeros(nb * hop, dtype=np.float32)
    padded[:n] = mono
    rms = np.sqrt(np.mean(padded.reshape(nb, hop) ** 2, axis=1) + 1e-12)
    a = np.exp(-hop / (attack * SR))
    r = np.exp(-hop / (release * SR))
    env = np.empty_like(rms)
    s = 0.0
    for i, v in enumerate(rms):
        c = a if v > s else r
        s = c * s + (1 - c) * v
        env[i] = s
    return np.interp(np.arange(n), np.arange(nb) * hop, env).astype(np.float32)


def compress(x: np.ndarray, threshold_db: float = -18, ratio: float = 3.0, attack: float = 0.005,
             release: float = 0.12, makeup_db: float = 0.0) -> np.ndarray:
    env = envelope_follow(x, attack, release, hop=96)
    lvl = 20 * np.log10(env + 1e-9)
    over = np.maximum(lvl - threshold_db, 0)
    gain = db(makeup_db) * 10 ** (-(over * (1 - 1 / ratio)) / 20)
    return (x * (gain[:, None] if x.ndim == 2 else gain)).astype(np.float32)


def soft_limit(x: np.ndarray, ceiling_db: float = -1.0) -> np.ndarray:
    c = db(ceiling_db)
    return (np.tanh(x / c) * c).astype(np.float32)


# --------------------------------------------------------------------------
# synthesis primitives
# --------------------------------------------------------------------------
def damped_sines(partials, dur: float, rng=None) -> np.ndarray:
    """partials: iterable of (freq, amp, decay_seconds[, phase])."""
    n = samples(dur)
    t = np.arange(n, dtype=np.float32) / SR
    y = np.zeros(n, dtype=np.float32)
    for p in partials:
        f, a, d = p[0], p[1], p[2]
        ph = p[3] if len(p) > 3 else (rng.uniform(0, 2 * np.pi) if rng is not None else 0.0)
        if f >= SR / 2:
            continue
        y += a * np.exp(-t / d) * np.sin(2 * np.pi * f * t + ph)
    return y


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """Attack/decay/sustain-level/release envelope that fits exactly n samples."""
    na, nd, nr = samples(a), samples(d), samples(r)
    ns = max(n - na - nd - nr, 0)
    env = np.concatenate([
        np.linspace(0, 1, na, endpoint=False) ** 1.5 if na else np.zeros(0),
        np.linspace(1, s, nd, endpoint=False) if nd else np.zeros(0),
        np.full(ns, s),
        np.linspace(s, 0, nr) ** 1.5 * (1 if s > 0 else 0) if nr else np.zeros(0),
    ])
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env[:n].astype(np.float32)


def place(buf: np.ndarray, x: np.ndarray, at: int, gain: float = 1.0) -> None:
    """Add x into buf starting at sample index `at`, clipping to bounds."""
    if at >= len(buf) or at + len(x) <= 0:
        return
    s0 = max(at, 0)
    s1 = min(at + len(x), len(buf))
    buf[s0:s1] += x[s0 - at:s1 - at] * gain


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note(name: str) -> float:
    """'F#4' -> MIDI number."""
    base = NOTE_NAMES[name[0].upper()]
    rest = name[1:]
    acc = 0
    while rest and rest[0] in "#b":
        acc += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    octave = int(rest)
    return 12 * (octave + 1) + base + acc
