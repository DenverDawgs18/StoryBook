"""Procedural sound design: ambience beds and one-shot effects.

Nothing here is sampled: every wind gust, ember crackle, bell and chain is
synthesised from noise and oscillators, so the whole project is reproducible
and free of licensing concerns.

Beds:   fn(duration, rng, **params) -> (n, 2) float32, designed to sit at ~-20 dB RMS
SFX:    fn(rng, **params)           -> (n, 2) float32, peak-normalised-ish
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import dsp
from .dsp import SR, samples

BEDS: dict = {}
SFX: dict = {}


def bed(name):
    def deco(fn):
        BEDS[name] = fn
        return fn
    return deco


def sfx(name):
    def deco(fn):
        SFX[name] = fn
        return fn
    return deco


def chunked(gen, duration: float, rng, chunk: float = 30.0, xfade: float = 3.0, **kw) -> np.ndarray:
    """Build a long texture from independently generated, crossfaded chunks."""
    total = samples(duration)
    out = np.zeros((total, 2), dtype=np.float32)
    pos = 0
    xf = samples(xfade)
    first = True
    while pos < total:
        clen = min(samples(chunk) + xf, total - pos + xf)
        c = gen(clen / SR, np.random.default_rng(rng.integers(2**32)), t0=pos / SR, **kw)
        c = c[:clen]
        if not first:
            c[:xf] *= np.sin(np.linspace(0, np.pi / 2, xf))[:, None]
            out[max(pos - xf, 0):pos] *= np.cos(np.linspace(0, np.pi / 2, xf))[-min(xf, pos):, None]
            start = pos - xf
        else:
            start = pos
        end = min(start + len(c), total)
        out[start:end] += c[:end - start]
        pos = end
        first = False
    return out


def _grains(n: int, rng, rate: float, kernels: list, amp_alpha: float = 2.5, clumpy: float = 0.0) -> np.ndarray:
    """Poisson-distributed impulses, each rendered with a random kernel from a bank."""
    out = np.zeros(n + max(len(k) for k in kernels), dtype=np.float32)
    count = rng.poisson(rate * n / SR)
    if count == 0:
        return out[:n]
    pos = rng.integers(0, n, count)
    if clumpy > 0:  # add satellite impulses to create bursts
        extra = pos[rng.random(count) < clumpy]
        pos = np.concatenate([pos, extra + rng.integers(50, 2500, len(extra))])
    amps = (rng.pareto(amp_alpha, len(pos)) + 1) ** -1 * rng.choice([-1, 1], len(pos))
    which = rng.integers(0, len(kernels), len(pos))
    for k_i, k in enumerate(kernels):
        imp = np.zeros(n, dtype=np.float32)
        sel = which == k_i
        np.add.at(imp, np.clip(pos[sel], 0, n - 1), amps[sel])
        conv = signal.oaconvolve(imp, k)
        out[:len(conv)] += conv[:len(out)]
    return out[:n]


# =========================================================================
# BEDS
# =========================================================================
def _wind_chunk(duration, rng, t0=0.0, intensity=0.5, howl=0.3, brightness=1.0):
    def env_for(seed):
        r = np.random.default_rng(seed)

        def envelope(freqs, times):
            T = len(times)
            pts = r.uniform(0.15, 1.0, max(int(times[-1] * 0.18) + 3, 3))
            gust = np.interp(times, np.linspace(0, times[-1], len(pts)), pts)
            w = min(41, T)
            gust = np.convolve(np.pad(gust, (w, w), mode="edge"), np.hanning(w) / np.hanning(w).sum(), "same")[w:-w]
            gust = np.clip(gust, 0.05, 1.2) ** 1.6 * (0.4 + intensity)
            cutoff = (250 + 1400 * gust * brightness)[None, :]
            f = freqs[:, None] + 1.0
            base = (f / 120.0) ** -0.6 / (1 + (f / cutoff) ** 4)
            base *= 1 / (1 + (40 / f) ** 4)  # remove sub-rumble
            # howl: narrow resonances that glide with the gust strength
            hw = np.zeros_like(base)
            for k in range(3):
                pts2 = r.uniform(280, 850, max(int(times[-1] * 0.08) + 3, 3)) * (1 + 0.5 * k)
                fc = np.interp(times, np.linspace(0, times[-1], len(pts2)), pts2) * (0.8 + 0.4 * gust)
                bw = fc * 0.025
                hw += np.exp(-0.5 * ((f - fc[None, :]) / bw[None, :]) ** 2) * (0.6 / (k + 1))
            return (base * gust[None, :] + hw * howl * gust[None, :] ** 2 * 1.4)
        return envelope

    # share gusts between channels but decorrelate fine structure
    seed = rng.integers(2**32)
    L = dsp.shaped_noise(duration, np.random.default_rng(rng.integers(2**32)), env_for(seed))
    R = dsp.shaped_noise(duration, np.random.default_rng(rng.integers(2**32)), env_for(seed))
    st = np.stack([L, R * 0.95], axis=1)
    return dsp.set_rms(st, -20)


@bed("wind")
def wind(duration, rng, intensity=0.5, howl=0.3, brightness=1.0):
    return chunked(_wind_chunk, duration, rng, chunk=40, xfade=5, intensity=float(intensity),
                   howl=float(howl), brightness=float(brightness))


def _drop_kernels(rng, lo=1500, hi=7000, k=10):
    ks = []
    for _ in range(k):
        f = rng.uniform(lo, hi)
        d = rng.uniform(0.002, 0.012)
        n = samples(d * 6)
        t = np.arange(n) / SR
        # droplets have a slight upward chirp
        ph = 2 * np.pi * np.cumsum(f * (1 + 0.6 * t / (d * 6))) / SR
        ks.append((np.sin(ph) * np.exp(-t / d)).astype(np.float32))
    return ks


def _rain_chunk(duration, rng, t0=0.0, intensity=0.6, roof=0.3):
    n = samples(duration)

    def envelope(freqs, times):
        f = freqs[:, None] + 1
        hump = np.exp(-0.5 * (np.log(f / 4000) / 0.9) ** 2) + 0.25 * np.exp(-0.5 * (np.log(f / 900) / 0.7) ** 2)
        flutter = 1 + 0.08 * np.random.default_rng(int(t0)).standard_normal(len(times))[None, :]
        return hump * flutter
    out = []
    kern = _drop_kernels(rng)
    heavy = []
    for _ in range(5):
        nn = samples(0.03)
        t = np.arange(nn) / SR
        heavy.append((dsp.lowpass(rng.standard_normal(nn).astype(np.float32), 1800) * np.exp(-t / 0.006)).astype(np.float32))
    for c in range(2):
        hiss = dsp.shaped_noise(duration, rng, envelope) * 0.5
        drops = _grains(n, rng, 400 * intensity + 50, kern, 2.0)
        drops = drops / (np.std(drops) + 1e-9) * 0.35
        pat = _grains(n, rng, 40 * roof, heavy, 3.0)
        pat = pat / (np.std(pat) + 1e-9) * 0.25 * roof
        out.append(hiss + drops + pat)
    return dsp.set_rms(np.stack(out, axis=1), -20)


@bed("rain")
def rain(duration, rng, intensity=0.6, roof=0.3):
    return chunked(_rain_chunk, duration, rng, chunk=30, intensity=float(intensity), roof=float(roof))


def _fire_chunk(duration, rng, t0=0.0, size=0.5):
    n = samples(duration)
    rumble = dsp.lowpass(dsp.colored(n, rng, 2.0), 180 + 300 * size, 2)
    rumble = dsp.highpass(rumble, 35)
    flick = dsp.smooth_random(n, rng, 3.0, 0.4, 1.0)
    rumble *= flick
    hiss = dsp.bandpass(dsp.white(n, rng), 2500, 9000) * dsp.smooth_random(n, rng, 9.0, 0.0, 1.0) ** 2 * 0.15
    kernels = []
    for _ in range(14):
        d = rng.uniform(0.0004, 0.004)
        nn = samples(d * 7)
        t = np.arange(nn) / SR
        k = rng.standard_normal(nn) * np.exp(-t / d)
        k = dsp.highpass(k.astype(np.float32), rng.uniform(800, 2500))
        kernels.append(k)
    for _ in range(4):  # resinous pops
        f = rng.uniform(350, 1100)
        kernels.append(dsp.damped_sines([(f, 1, 0.006), (f * 2.3, 0.4, 0.003)], 0.05, rng))
    pan = rng.uniform(-0.25, 0.25)
    crack_c = []
    for c in range(2):
        cr = _grains(n, rng, 10 + 25 * size, kernels, 1.6, clumpy=0.5)
        crack_c.append(cr / (np.max(np.abs(cr)) + 1e-9))
    cr = np.stack(crack_c, axis=1) * 0.5 + dsp.pan(crack_c[0], pan) * 0.5
    bodyL = rumble * 0.7 + hiss
    bodyR = np.roll(rumble, 37) * 0.7 + np.roll(hiss, 211)
    st = np.stack([bodyL, bodyR], axis=1)
    st = dsp.set_rms(st, -24) + cr * dsp.db(-9)
    return st.astype(np.float32)


@bed("fire")
def fire(duration, rng, size=0.5):
    x = chunked(_fire_chunk, duration, rng, chunk=30, size=float(size))
    return dsp.set_rms(dsp.reverb(x, "room", 0.15, tail=False), -21)


def _tick_kernel(rng, base):
    k = dsp.damped_sines([(base, 1, 0.004), (base * 1.83, 0.6, 0.003), (base * 2.71, 0.4, 0.002),
                          (base * 0.5, 0.3, 0.008)], 0.06, rng)
    click = rng.standard_normal(samples(0.002)) * 0.4
    k[:len(click)] += click
    return dsp.highpass(k, 300)


@bed("clock")
def clock(duration, rng, rate=1.0, pitch=2200.0, room="room", wet=0.35):
    """A mantel/long-case clock: alternating tick and tock."""
    n = samples(duration)
    x = np.zeros(n + SR, dtype=np.float32)
    tick = _tick_kernel(rng, float(pitch))
    tock = _tick_kernel(rng, float(pitch) * 0.84)
    period = 1.0 / float(rate)
    t = 0.2
    i = 0
    while t < duration:
        k = tick if i % 2 == 0 else tock
        jitter = rng.normal(0, 0.002)
        dsp.place(x, k * rng.uniform(0.85, 1.0), samples(t + jitter))
        t += period
        i += 1
    x = x[:n]
    st = dsp.reverb(x, room, float(wet), tail=False)
    return dsp.normalize_peak(st, -14)


@bed("watch")
def watch(duration, rng):
    """Tell-Tale Heart: 'a low, dull, quick sound, such as a watch makes when enveloped in cotton'."""
    n = samples(duration)
    x = np.zeros(n + SR, dtype=np.float32)
    k = dsp.lowpass(_tick_kernel(rng, 1500), 1200, 2)
    t = 0.1
    while t < duration:
        dsp.place(x, k, samples(t))
        t += 0.2
    return dsp.normalize_peak(dsp.to_stereo(x[:n]), -22)


def _beat(rng, pitch=55.0, dur=0.22):
    n = samples(dur)
    t = np.arange(n) / SR
    f = pitch * (1 + 0.8 * np.exp(-t / 0.02))
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * (1 - np.exp(-t / 0.004)) * np.exp(-t / 0.06)
    thud = dsp.lowpass(rng.standard_normal(n).astype(np.float32), 220) * np.exp(-t / 0.02) * 0.6
    return (body + thud).astype(np.float32)


def heartbeat_track(duration, rng, bpm_from, bpm_to, gain_from=0.5, gain_to=1.0, curve=2.0):
    n = samples(duration)
    x = np.zeros(n + SR, dtype=np.float32)
    lub = _beat(rng, 52, 0.24)
    dub = _beat(rng, 64, 0.18) * 0.65
    t = 0.3
    while t < duration:
        p = (t / duration) ** curve
        bpm = bpm_from + (bpm_to - bpm_from) * p
        g = gain_from + (gain_to - gain_from) * p
        period = 60.0 / bpm
        dsp.place(x, lub * g, samples(t))
        dsp.place(x, dub * g, samples(t + min(0.28, period * 0.36)))
        t += period * rng.uniform(0.985, 1.015)
    x = dsp.lowpass(x[:n], 260, 2)
    return x


@bed("heartbeat")
def heartbeat(duration, rng, bpm="60", gain="1", curve=2.0):
    """bpm='60:150' and gain='0.3:1' ramp over the bed's length."""
    b = [float(v) for v in str(bpm).split(":")]
    g = [float(v) for v in str(gain).split(":")]
    b = b if len(b) == 2 else b * 2
    g = g if len(g) == 2 else g * 2
    x = heartbeat_track(duration, rng, b[0], b[1], g[0], g[1], float(curve))
    st = dsp.reverb(x, "booth", 0.25, tail=False)
    return (st / (np.max(np.abs(st)) + 1e-9) * dsp.db(-6) * max(g)).astype(np.float32)


@bed("roomtone")
def roomtone(duration, rng, creaks=0.3, level=-30.0):
    """Old house at night: near-silent air, the faintest hum, occasional timber creaks."""
    n = samples(duration)
    air = dsp.lowpass(dsp.colored(n, rng, 1.6), 900, 2)
    air = dsp.highpass(air, 40)
    st = np.stack([air, np.roll(air, 4801)], axis=1)
    st = dsp.set_rms(st, float(level))
    t = rng.uniform(3, 12)
    while t < duration - 3:
        c = creak(rng, length=rng.uniform(0.3, 1.1), pitch=rng.uniform(25, 60))
        c = dsp.reverb(c, "room", 0.4)
        dsp.place(st, c * dsp.db(-16) * float(creaks), samples(t))
        t += rng.exponential(18)
    return st


def _babble_voice(n, rng, pitch_base):
    """One indistinct distant talker: glottal buzz through moving formants."""
    out = np.zeros(n, dtype=np.float32)
    pos = 0
    vowels = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480),
              (570, 840, 2410), (440, 1020, 2240), (660, 1720, 2410)]
    while pos < n:
        if rng.random() < 0.25:  # pause between phrases
            pos += samples(rng.uniform(0.3, 1.5))
            continue
        phrase = samples(rng.uniform(0.8, 3.0))
        seg = min(phrase, n - pos)
        t = np.arange(seg) / SR
        f0 = pitch_base * (1 + 0.12 * np.sin(2 * np.pi * rng.uniform(0.3, 0.8) * t + rng.uniform(0, 6))) \
            * np.linspace(1.05, 0.9, seg)
        ph = np.cumsum(f0) / SR
        buzz = (2 * (ph % 1.0) - 1).astype(np.float32)
        buzz = dsp.lowpass(buzz, 3000)
        syl_rate = rng.uniform(3.5, 5.5)
        env = np.clip(np.sin(2 * np.pi * syl_rate * t / 2) ** 2, 0, 1) ** 0.7
        y = np.zeros(seg, dtype=np.float32)
        # change vowel each syllable
        syl_len = samples(1 / syl_rate)
        for s0 in range(0, seg, max(syl_len, 1)):
            s1 = min(s0 + syl_len, seg)
            F = vowels[rng.integers(len(vowels))]
            part = buzz[s0:s1]
            if len(part) < 64:
                continue
            v = sum(dsp.resonator(part, f, 8) * g for f, g in zip(F, (1, 0.6, 0.25)))
            y[s0:s1] = v
        out[pos:pos + seg] = y * env
        pos += seg
    return out


@bed("crowd")
def crowd(duration, rng, voices=14, distance=0.6):
    """Murmur of a crowd behind walls or across a hall."""
    n = samples(duration)
    voices = int(voices)
    st = np.zeros((n, 2), dtype=np.float32)
    for i in range(voices):
        v = _babble_voice(n, rng, rng.choice([rng.uniform(95, 140), rng.uniform(180, 250)]))
        st += dsp.pan(v, rng.uniform(-0.8, 0.8)) * rng.uniform(0.5, 1.0)
    st = dsp.lowpass(st, 4000 - 2500 * float(distance))
    st = dsp.reverb(st, "hall", 0.3 + 0.5 * float(distance), tail=False)
    return dsp.set_rms(st, -20)


def _river_chunk(duration, rng, t0=0.0, flow=0.6):
    n = samples(duration)

    def envelope(freqs, times):
        f = freqs[:, None] + 1
        return np.exp(-0.5 * (np.log(f / 1100) / 1.1) ** 2) * (1 + 0.15 * np.random.default_rng(int(t0) + 7).standard_normal(len(times))[None, :])
    kern = []
    for _ in range(16):  # bubbles: rising damped sines
        f = rng.uniform(400, 2200)
        d = rng.uniform(0.006, 0.03)
        nn = samples(d * 5)
        t = np.arange(nn) / SR
        ph = 2 * np.pi * np.cumsum(f * (1 + 2.5 * t / (d * 5))) / SR
        kern.append((np.sin(ph) * np.exp(-t / d)).astype(np.float32))
    ch = []
    for c in range(2):
        wash = dsp.shaped_noise(duration, rng, envelope)
        bub = _grains(n, rng, 60 + 200 * flow, kern, 2.0)
        bub = bub / (np.std(bub) + 1e-9) * 0.45
        ch.append(wash * 0.6 + bub)
    return dsp.set_rms(np.stack(ch, axis=1), -20)


@bed("river")
def river(duration, rng, flow=0.6):
    return chunked(_river_chunk, duration, rng, chunk=30, flow=float(flow))


@bed("crickets")
def crickets(duration, rng, density=0.5):
    n = samples(duration)
    st = np.zeros((n, 2), dtype=np.float32)
    for _ in range(int(3 + 6 * float(density))):
        f = rng.uniform(4200, 5200)
        rate = rng.uniform(0.5, 1.2)  # chirps per second
        p = rng.uniform(-0.9, 0.9)
        t0 = rng.uniform(0, 1)
        voice = np.zeros(n, dtype=np.float32)
        chirp_n = samples(0.12)
        tt = np.arange(chirp_n) / SR
        pulses = (np.sin(2 * np.pi * 30 * tt) > 0.2).astype(np.float32)
        ch = np.sin(2 * np.pi * f * tt) * pulses * np.hanning(chirp_n)
        t = t0
        while t < duration:
            dsp.place(voice, ch.astype(np.float32), samples(t), rng.uniform(0.6, 1))
            t += 1 / rate * rng.uniform(0.9, 1.1)
        st += dsp.pan(voice, p) * rng.uniform(0.2, 1.0)
    st = dsp.reverb(st, "chamber", 0.2, tail=False)
    return dsp.set_rms(st, -26)


@bed("battle")
def battle(duration, rng, distance=0.7):
    """A city falling at night, heard from a distance: fire-roar, drums, shouts, horns."""
    n = samples(duration)
    roar = dsp.lowpass(dsp.colored(n, rng, 1.8, ch=2), 500)
    roar *= dsp.smooth_random(n, rng, 0.3, 0.5, 1.0)[:, None]
    st = dsp.set_rms(roar, -22)
    st += crowd(duration, rng, voices=20, distance=0.9) * dsp.db(-4)
    t = rng.uniform(1, 5)
    while t < duration - 6:
        kind = rng.choice(["drums", "horn", "clash"], p=[0.45, 0.2, 0.35])
        if kind == "drums":
            s = war_drums(rng, bars=int(rng.integers(2, 5)))
            g = -10
        elif kind == "horn":
            s = horn(rng, note=float(rng.choice([45, 47, 50])), length=rng.uniform(2.5, 4.5))
            g = -12
        else:
            s = clash(rng, hits=int(rng.integers(3, 9)))
            g = -14
        s = dsp.pan(s.mean(axis=1), rng.uniform(-0.8, 0.8))
        s = dsp.reverb(dsp.lowpass(s, 2500 - 1500 * float(distance)), "cathedral", 0.6)
        dsp.place(st, s * dsp.db(g), samples(t))
        t += rng.exponential(7)
    return dsp.set_rms(st, -20)


@bed("silence")
def silence(duration, rng):
    return np.zeros((samples(duration), 2), dtype=np.float32)


# =========================================================================
# SFX
# =========================================================================
@sfx("creak")
def creak(rng, length=0.8, pitch=40.0, room=None):
    """Stick-slip friction of old timber or a door hinge."""
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    rate = float(pitch) * (1 + 0.6 * np.sin(2 * np.pi * rng.uniform(0.5, 1.5) * t + rng.uniform(0, 6))) \
        * dsp.smooth_random(n, rng, 6, 0.6, 1.4)
    ph = np.cumsum(rate) / SR
    imp = np.diff(np.floor(ph), prepend=0).astype(np.float32)
    imp *= rng.uniform(0.6, 1.0, n).astype(np.float32)
    y = sum(dsp.resonator(imp, f, q) * g for f, q, g in [(380, 12, 1), (920, 10, 0.7), (1750, 9, 0.5), (3100, 8, 0.25)])
    y = y * np.hanning(n) ** 0.5
    y = dsp.normalize_peak(y, -3)
    out = dsp.to_stereo(y)
    if room:
        out = dsp.reverb(out, room, 0.35)
    return out


@sfx("door")
def door(rng, kind="open", room="hall"):
    parts = []
    if kind in ("open", "close"):
        parts.append(creak(rng, rng.uniform(1.0, 1.8), rng.uniform(22, 35))[:, 0] * 0.7)
    n = samples(0.6)
    t = np.arange(n) / SR
    thump = dsp.damped_sines([(85, 1, 0.08), (140, 0.7, 0.05), (260, 0.3, 0.03)], 0.6, rng)
    thump += dsp.lowpass(rng.standard_normal(n).astype(np.float32), 900) * np.exp(-t / 0.015) * 0.6
    if kind == "close":
        parts.append(np.zeros(samples(0.05), np.float32))
        parts.append(thump)
    elif kind == "slam":
        parts = [thump * 1.4]
    y = np.concatenate(parts)
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.4)


@sfx("knock")
def knock(rng, count=3, room="hall", heavy=1.0):
    """Knuckles - or a heavy iron knocker - on a wooden door."""
    count, heavy = int(count), float(heavy)
    gap = 0.32
    n = samples(gap * count + 0.5)
    y = np.zeros(n, dtype=np.float32)
    for i in range(count):
        f = rng.uniform(150, 190)
        k = dsp.damped_sines([(f, 1, 0.05), (f * 2.4, 0.5, 0.025), (f * 4.1, 0.3, 0.012), (1900, 0.2 * heavy, 0.004)], 0.3, rng)
        dsp.place(y, k * rng.uniform(0.8, 1), samples(i * gap + rng.normal(0, 0.01)))
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.45)


@sfx("footsteps")
def footsteps(rng, count=8, pace=0.55, surface="stone", room="hall"):
    count = int(count)
    n = samples(float(pace) * count + 0.6)
    y = np.zeros(n, dtype=np.float32)
    for i in range(count):
        nn = samples(0.15)
        t = np.arange(nn) / SR
        heel = dsp.lowpass(rng.standard_normal(nn).astype(np.float32), 700 if surface == "wood" else 1400) * np.exp(-t / 0.012)
        body = dsp.damped_sines([(rng.uniform(90, 130), 0.8, 0.03)], 0.15, rng)
        scuff = dsp.bandpass(rng.standard_normal(nn).astype(np.float32), 2000, 6000) * np.exp(-t / 0.03) * 0.15
        step = heel + body + scuff
        dsp.place(y, step * rng.uniform(0.7, 1.0) * (1 if i % 2 else 0.85), samples(i * float(pace) + rng.normal(0, 0.015)))
    return dsp.reverb(dsp.normalize_peak(y, -4), room, 0.35)


def bell_partials(fund: float, rng, decay: float = 6.0, bright: float = 1.0):
    # classic church bell partial structure (hum, prime, tierce, quint, nominal...)
    ratios = [(0.5, 0.6, 1.0), (1.0, 0.8, 0.75), (1.183, 0.6, 0.55), (1.506, 0.35, 0.4), (2.0, 0.7, 0.35),
              (2.5, 0.25 * bright, 0.25), (2.66, 0.25 * bright, 0.22), (3.01, 0.2 * bright, 0.18),
              (4.16, 0.12 * bright, 0.12), (5.43, 0.07 * bright, 0.08)]
    parts = []
    for r, a, d in ratios:
        for det in (-0.0015, 0.0015):  # doublet beating
            parts.append((fund * r * (1 + det), a / 2, decay * d))
    return parts


@sfx("bell")
def bell(rng, count=1, pitch=196.0, interval=3.2, room="cathedral", distance=0.4, decay=6.0):
    """Church bell tolling. pitch = strike note in Hz."""
    count = int(count)
    dur = float(interval) * count + float(decay) * 1.2
    n = samples(dur)
    y = np.zeros(n, dtype=np.float32)
    for i in range(count):
        strike = dsp.damped_sines(bell_partials(float(pitch), rng, float(decay)), float(decay) * 1.2, rng)
        clang = dsp.highpass(rng.standard_normal(samples(0.02)).astype(np.float32), 1500) * 0.3
        strike[:len(clang)] += clang
        dsp.place(y, strike, samples(i * float(interval)))
    y = dsp.lowpass(y, 9000 - 6000 * float(distance))
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.3 + 0.5 * float(distance))


@sfx("chime")
def chime(rng, count=1, pitch=110.0, interval=4.5, room="hall"):
    """A deep, peculiar clock chime - the ebony clock of the Red Death."""
    count = int(count)
    dec = 7.0
    n = samples(float(interval) * count + dec * 1.3)
    y = np.zeros(n, dtype=np.float32)
    f = float(pitch)
    for i in range(count):
        parts = [(f, 1.0, dec), (f * 2.0, 0.5, dec * 0.6), (f * 2.76, 0.45, dec * 0.45), (f * 3.0, 0.2, dec * 0.3),
                 (f * 5.40, 0.25, dec * 0.25), (f * 8.93, 0.1, dec * 0.12), (f * 0.5, 0.35, dec * 1.2)]
        parts = [(pf * (1 + d), a / 2, dd) for pf, a, dd in parts for d in (-0.001, 0.0012)]
        s = dsp.damped_sines(parts, dec * 1.3, rng)
        hammer = dsp.lowpass(rng.standard_normal(samples(0.03)).astype(np.float32), 3000) * 0.4
        s[:len(hammer)] += hammer
        dsp.place(y, s, samples(i * float(interval)))
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.55)


@sfx("house_bells")
def house_bells(rng, length=9.0, room="hall"):
    """Every bell in the house jangling at once, swelling and dying away."""
    length = float(length)
    n = samples(length + 3)
    y = np.zeros((n, 2), dtype=np.float32)
    swell = lambda t: np.sin(np.pi * min(t / length, 1)) ** 0.6
    for b in range(9):
        f = rng.uniform(900, 2600)
        p = rng.uniform(-0.9, 0.9)
        t = rng.uniform(0, 0.8)
        while t < length:
            s = dsp.damped_sines([(f, 1, 0.5), (f * 2.76, 0.4, 0.25), (f * 5.4, 0.2, 0.12), (f * 1.003, 0.6, 0.6)], 1.2, rng)
            dsp.place(y, dsp.pan(s, p) * swell(t) * rng.uniform(0.4, 1), samples(t))
            t += rng.uniform(0.09, 0.22)
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.35)


@sfx("chains")
def chains(rng, length=4.0, drag=0.5, room="cellar"):
    """Heavy chains: metallic clinks and a grinding drag along stone."""
    length = float(length)
    n = samples(length + 0.5)
    y = np.zeros(n, dtype=np.float32)
    links = []
    for _ in range(12):
        f = rng.uniform(1800, 5200)
        links.append(dsp.damped_sines([(f, 1, 0.02), (f * 1.47, 0.6, 0.015), (f * 2.13, 0.4, 0.01), (f * 0.61, 0.5, 0.03)], 0.15, rng))
    t = 0.05
    while t < length:
        burst = rng.integers(2, 7)
        for _ in range(burst):
            dsp.place(y, links[rng.integers(len(links))] * rng.uniform(0.3, 1), samples(t))
            t += rng.uniform(0.015, 0.07)
        t += rng.exponential(0.18)
    grind = dsp.bandpass(dsp.white(n, rng), 300, 3000) * dsp.smooth_random(n, rng, 4, 0, 1) ** 2
    y = y + grind * 0.25 * float(drag)
    thud_n = samples(0.4)
    for k in range(int(length / 1.3)):
        th = dsp.damped_sines([(rng.uniform(70, 110), 1, 0.06)], 0.4, rng)
        dsp.place(y, th * 0.4 * float(drag), samples(rng.uniform(0, length)))
    y = y * np.hanning(n) ** 0.25
    room = "chamber" if room == "cellar" else room
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.45)


@sfx("wail")
def wail(rng, voices=6, length=8.0, room="cathedral"):
    """Disembodied voices moaning on the wind ('oo' formants, gliding pitch)."""
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    st = np.zeros((n, 2), dtype=np.float32)
    for v in range(int(voices)):
        f0 = rng.uniform(180, 420)
        glide = f0 * (1 + 0.35 * np.sin(2 * np.pi * rng.uniform(0.05, 0.15) * t + rng.uniform(0, 6))
                      - 0.25 * t / length)
        vib = 1 + 0.012 * np.sin(2 * np.pi * rng.uniform(4.5, 6) * t)
        ph = 2 * np.pi * np.cumsum(glide * vib) / SR
        s = np.sin(ph) + 0.25 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
        breath = dsp.bandpass(rng.standard_normal(n).astype(np.float32), 300, 1200) * 0.15
        env = np.clip(np.sin(np.pi * np.clip((t - rng.uniform(0, length * 0.3)) / (length * 0.7), 0, 1)), 0, 1) ** 1.5
        st += dsp.pan((s + breath) * env, rng.uniform(-1, 1))
    st = dsp.lowpass(st, 2500)
    return dsp.reverb(dsp.normalize_peak(st, -3), room, 0.8)


@sfx("boom")
def boom(rng, pitch=38.0, length=5.0, room="void"):
    """Cinematic low impact."""
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    f = float(pitch) * (1 + 1.5 * np.exp(-t / 0.05))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (length * 0.25))
    noise = dsp.lowpass(rng.standard_normal(n).astype(np.float32), 400) * np.exp(-t / 0.15) * 0.7
    y = dsp.soft_limit((body + noise) * 1.5, -1)
    return dsp.reverb(y, room, 0.35)


@sfx("swell")
def swell(rng, length=4.0, low=200.0, high=6000.0):
    """Rising noise/tone swell that cuts off - the breath before a revelation."""
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    env = (t / length) ** 3
    x = np.zeros((n, 2), dtype=np.float32)
    nfft = 2048

    def envelope(freqs, times):
        fc = float(low) * (float(high) / float(low)) ** (np.clip(times / length, 0, 1))
        f = freqs[:, None] + 1
        return np.exp(-0.5 * (np.log(f / fc[None, :]) / 0.6) ** 2)
    for c in range(2):
        x[:, c] = dsp.shaped_noise(length, rng, envelope, nfft)[:n] * env
    tone = sum(np.sin(2 * np.pi * float(low) / 4 * m * t * (1 + 0.02 * t)) / m for m in (1, 1.5, 2, 3)) * env
    x += dsp.to_stereo(tone.astype(np.float32)) * 0.5
    x[-samples(0.01):] *= np.linspace(1, 0, samples(0.01))[:, None]
    return dsp.normalize_peak(x, -3)


@sfx("sting")
def sting(rng, pitch=36.0):
    """Dark sting: reverse swell into a low boom with a dissonant cluster."""
    sw = swell(rng, 2.5, 80, 3000)
    bm = boom(rng, float(pitch), 6.0)
    n = samples(6.0)
    t = np.arange(n) / SR
    cluster = sum(np.sin(2 * np.pi * dsp.midi_hz(m) * t) for m in (62, 63, 68, 69)) * np.exp(-t / 1.8) * 0.12
    cl = dsp.reverb(dsp.to_stereo(cluster.astype(np.float32)), "cathedral", 0.6)
    out = np.zeros((len(sw) + max(len(bm), len(cl)), 2), dtype=np.float32)
    out[:len(sw)] += sw * 0.6
    dsp.place(out, bm, len(sw))
    dsp.place(out, cl, len(sw))
    return dsp.normalize_peak(out, -2)


@sfx("thunder")
def thunder(rng, distance=0.5, length=7.0):
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    crack = dsp.highpass(rng.standard_normal(n).astype(np.float32), 800) * np.exp(-t / 0.08) * (1 - float(distance))
    rumble = dsp.lowpass(dsp.colored(n, rng, 2.0), 300) * dsp.smooth_random(n, rng, 3, 0.3, 1.0) * np.exp(-t / (length * 0.35))
    onset = np.clip(t / 0.15, 0, 1)
    y = (crack + rumble * 1.2) * onset
    return dsp.reverb(dsp.normalize_peak(y, -2), "void", 0.5)


@sfx("horn")
def horn(rng, note=45.0, length=3.5, room="cathedral"):
    """A war horn / Gothic trumpet: brassy, swelling, slightly flat at the end."""
    length = float(length)
    n = samples(length)
    t = np.arange(n) / SR
    f0 = dsp.midi_hz(float(note)) * (1 - 0.015 * (t / length) ** 2) * (1 + 0.003 * np.sin(2 * np.pi * 5 * t))
    ph = 2 * np.pi * np.cumsum(f0) / SR
    env = np.clip(t / 0.35, 0, 1) ** 2 * np.clip((length - t) / 0.6, 0, 1)
    bright = 0.3 + 0.7 * np.clip(t / 0.8, 0, 1) * env
    y = np.zeros(n, dtype=np.float32)
    for k in range(1, 30):
        if dsp.midi_hz(float(note)) * k > 9000:
            break
        # brass: harmonic amplitude grows with brightness
        a = (1 / k) * bright ** (k * 0.18)
        y += (a * np.sin(k * ph)).astype(np.float32)
    y = dsp.eq(y * env, "peak", 1200, 4, 1.0)
    y += dsp.bandpass(rng.standard_normal(n).astype(np.float32), 800, 3000) * env * 0.02
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.55)


def _drum(rng, pitch=70.0, decay=0.35):
    n = samples(decay * 4)
    t = np.arange(n) / SR
    f = pitch * (1 + 0.5 * np.exp(-t / 0.03))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / decay)
    skin = dsp.bandpass(rng.standard_normal(n).astype(np.float32), 200, 2500) * np.exp(-t / 0.03) * 0.5
    return (body + skin).astype(np.float32)


@sfx("war_drums")
def war_drums(rng, bars=4, tempo=80.0, room="cathedral"):
    """Slow, heavy martial drums."""
    bars = int(bars)
    beat = 60 / float(tempo)
    pattern = [0, 1.5, 2, 3]  # beats per bar
    n = samples(bars * 4 * beat + 4)
    y = np.zeros((n, 2), dtype=np.float32)
    big = _drum(rng, 55, 0.5)
    small = _drum(rng, 95, 0.25)
    for b in range(bars):
        for i, p in enumerate(pattern):
            d = big if i in (0, 2) else small
            g = 1.0 if i == 0 else 0.7
            dsp.place(y, dsp.pan(d, -0.2 if i % 2 else 0.25) * g * rng.uniform(0.85, 1), samples((b * 4 + p) * beat))
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.5)


@sfx("clash")
def clash(rng, hits=6, room="hall"):
    """Distant iron on iron."""
    hits = int(hits)
    n = samples(hits * 0.5 + 2)
    y = np.zeros(n, dtype=np.float32)
    t = 0
    for _ in range(hits):
        f = rng.uniform(1200, 3500)
        s = dsp.damped_sines([(f, 1, 0.15), (f * 1.41, 0.7, 0.12), (f * 2.23, 0.5, 0.08), (f * 3.1, 0.3, 0.05)], 0.6, rng)
        s[:samples(0.003)] += rng.standard_normal(samples(0.003)) * 0.8
        dsp.place(y, s * rng.uniform(0.4, 1), samples(t))
        t += rng.uniform(0.15, 0.6)
    return dsp.reverb(dsp.normalize_peak(y, -3), room, 0.5)


@sfx("bolt")
def bolt(rng, room="room"):
    """A key turning, a bolt sliding home."""
    n = samples(0.7)
    y = np.zeros(n, dtype=np.float32)
    for i, (when, f) in enumerate([(0.0, 2600), (0.12, 3400), (0.35, 1800), (0.42, 900)]):
        k = dsp.damped_sines([(f, 1, 0.01), (f * 1.6, 0.5, 0.006), (f * 0.5, 0.4, 0.02)], 0.1, rng)
        dsp.place(y, k * (1 if i != 3 else 1.5), samples(when))
    scrape = dsp.bandpass(dsp.white(samples(0.2), rng), 1500, 5000) * np.hanning(samples(0.2)) * 0.2
    dsp.place(y, scrape, samples(0.15))
    return dsp.reverb(dsp.normalize_peak(y, -6), room, 0.35)


@sfx("quill")
def quill(rng, length=3.0):
    """A quill scratching across paper."""
    length = float(length)
    n = samples(length)
    strokes = dsp.smooth_random(n, rng, 7, 0, 1) ** 3
    gaps = (dsp.smooth_random(n, rng, 1.2, 0, 1) > 0.25).astype(np.float32)
    y = dsp.bandpass(dsp.white(n, rng), 2500, 9000) * strokes * gaps
    return dsp.to_stereo(dsp.normalize_peak(dsp.reverb(y, "booth", 0.2, tail=False).mean(axis=1), -12))


@sfx("lantern")
def lantern(rng):
    """The tin lantern's hinge squeak (Tell-Tale Heart)."""
    c = creak(rng, 0.25, 80)
    return dsp.reverb(c * 0.5, "room", 0.3)


@sfx("silence")
def silence_sfx(rng, length=1.0):
    return np.zeros((samples(float(length)), 2), dtype=np.float32)


@bed("tinnitus")
def tinnitus(duration, rng, freq=3800.0):
    """A thin ringing in the ears that slowly becomes distinct."""
    n = samples(duration)
    t = np.arange(n) / SR
    f = float(freq) * (1 + 0.002 * np.sin(2 * np.pi * 0.3 * t))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR)
    y *= (t / max(duration, 1e-3)) ** 1.5
    return dsp.set_rms(dsp.to_stereo(y.astype(np.float32)), -30)


@sfx("heartbeat_once")
def heartbeat_once(rng, beats=2, bpm=60.0):
    x = heartbeat_track(60.0 / float(bpm) * int(beats) + 0.6, rng, float(bpm), float(bpm), 1, 1)
    return dsp.normalize_peak(dsp.reverb(x, "chamber", 0.3), -3)


# =========================================================================
# Fairy-tale additions: woods, wells, workshops and a little magic
# =========================================================================
def _bird_call(rng, kind: int) -> np.ndarray:
    """One songbird phrase: a few frequency-swept whistles (FM), trilled or plain."""
    notes = int(rng.integers(2, 7))
    base = rng.uniform(2600, 4600)
    parts = []
    for i in range(notes):
        d = rng.uniform(0.05, 0.16) if kind else rng.uniform(0.12, 0.3)
        n = samples(d)
        t = np.arange(n) / SR
        f0 = base * rng.uniform(0.8, 1.25)
        sweep = f0 * (1 + rng.uniform(-0.35, 0.35) * t / d)
        if kind == 2:  # warble
            sweep = sweep * (1 + 0.06 * np.sin(2 * np.pi * rng.uniform(30, 60) * t))
        y = np.sin(2 * np.pi * np.cumsum(sweep) / SR) * np.hanning(n) ** 0.7
        y += 0.12 * np.sin(2 * np.pi * np.cumsum(sweep * 2) / SR) * np.hanning(n)
        parts.append(y.astype(np.float32))
        parts.append(np.zeros(samples(rng.uniform(0.02, 0.09)), np.float32))
    return np.concatenate(parts)


@bed("birds")
def birds(duration, rng, density=0.5, leaves=0.4):
    """A wood in daylight: scattered songbirds near and far, leaves moving in a breeze."""
    n = samples(duration)
    st = np.zeros((n, 2), dtype=np.float32)
    density = float(density)
    for _ in range(int(3 + 5 * density)):  # each bird has its own phrase and habits
        kind = int(rng.integers(0, 3))
        phrase_seed = int(rng.integers(2**31))
        p, dist = rng.uniform(-0.85, 0.85), rng.uniform(0.2, 1.0)
        voice = np.zeros(n, dtype=np.float32)
        t = rng.uniform(0, 6)
        while t < duration:
            call = _bird_call(np.random.default_rng(phrase_seed + int(rng.integers(0, 3))), kind)
            dsp.place(voice, call, samples(t), rng.uniform(0.6, 1.0))
            t += len(call) / SR + rng.exponential(5.0 / (0.4 + density))
        voice = dsp.lowpass(voice, 9000 - 5000 * dist)
        st += dsp.pan(voice, p) * (1.0 - 0.75 * dist)
    st = dsp.reverb(st, "hall", 0.25, tail=False)
    if float(leaves) > 0:
        rustle = dsp.bandpass(dsp.colored(n, rng, 1.0), 1200, 7000)
        rustle *= dsp.smooth_random(n, rng, 0.15, 0.1, 1.0) ** 2
        st += dsp.to_stereo(rustle.astype(np.float32)) * 0.08 * float(leaves)
    return dsp.set_rms(st, -27)


@bed("spinning")
def spinning(duration, rng, rate=1.6):
    """A spinning wheel: the treadle's knock, the wheel's whirr and the hiss of the thread."""
    n = samples(duration)
    t = np.arange(n) / SR
    rate = float(rate)
    whirr_f = 90 + 8 * np.sin(2 * np.pi * rate * t)
    whirr = dsp.bandpass(dsp.colored(n, rng, 0.5), 300, 2400) * (0.55 + 0.45 * np.sin(2 * np.pi * np.cumsum(whirr_f) / SR / 6) ** 2)
    hiss = dsp.highpass(dsp.white(n, rng), 4000) * 0.12 * (0.7 + 0.3 * np.sin(2 * np.pi * rate * t))
    y = (whirr * 0.5 + hiss).astype(np.float32)
    k = 0.0
    while k < duration:
        thud = dsp.damped_sines([(rng.uniform(110, 130), 1.0, 0.04), (420, 0.3, 0.015)], 0.2, rng) * 0.9
        dsp.place(y, thud, samples(k + rng.normal(0, 0.01)))
        k += 1 / rate
    st = dsp.reverb(dsp.to_stereo(y), "room", 0.3, tail=False)
    return dsp.set_rms(dsp.fade(st, 1.5, 1.5), -24)


@sfx("tapping")
def tapping(rng, count=10, pace=0.28, room="room"):
    """A cobbler's hammer on a last: quick small taps, the odd heavier blow."""
    count = int(count)
    n = samples(float(pace) * count + 0.5)
    y = np.zeros(n, dtype=np.float32)
    for i in range(count):
        heavy = 1.0 if rng.random() < 0.2 else 0.6
        f = rng.uniform(1800, 2300)
        k = dsp.damped_sines([(f, 1, 0.012), (f * 1.7, 0.5, 0.008), (rng.uniform(180, 240), 0.6 * heavy, 0.03)], 0.15, rng)
        dsp.place(y, k * heavy, samples(i * float(pace) + rng.normal(0, 0.02)))
    return dsp.reverb(dsp.normalize_peak(y, -4), room, 0.3)


@sfx("sparkle")
def sparkle(rng, length=3.0, rising=1, room="hall"):
    """Fairy dust: a glittering run of tiny bells, up (or down) a pentatonic scale."""
    length = float(length)
    n = samples(length + 2.5)
    st = np.zeros((n, 2), dtype=np.float32)
    scale = [0, 2, 4, 7, 9]
    count = int(14 * length)
    for i in range(count):
        step = i if int(rising) else count - 1 - i
        m = 79 + scale[step % 5] + 12 * ((step // 5) % 3)
        f = 440.0 * 2 ** ((m - 69) / 12) * rng.uniform(0.997, 1.003)
        tone = dsp.damped_sines([(f, 1, 0.5), (f * 2.76, 0.3, 0.2), (f * 5.4, 0.12, 0.08)], 1.2, rng)
        dsp.place(st, dsp.pan(tone, rng.uniform(-0.8, 0.8)), samples(i / count * length + rng.normal(0, 0.01)), rng.uniform(0.3, 0.8))
    st = dsp.highpass(st, 900)
    return dsp.normalize_peak(dsp.reverb(st, room, 0.5), -6)


@sfx("splash")
def splash(rng, size=0.5, room="chamber"):
    """Something dropped into deep water: a plop, a burst of spray, a hollow echo."""
    size = float(size)
    n = samples(1.6)
    t = np.arange(n) / SR
    plop_f = 900 * (1 - 0.6 * np.minimum(t / 0.08, 1)) / (0.6 + size)
    plop = np.sin(2 * np.pi * np.cumsum(plop_f) / SR) * np.exp(-t / 0.05)
    spray = dsp.bandpass(dsp.white(n, rng), 1500, 9000) * np.exp(-t / (0.08 + 0.25 * size)) * (0.4 + size)
    drops = np.zeros(n, np.float32)
    for _ in range(int(6 + 20 * size)):
        at = rng.uniform(0.05, 1.0)
        f = rng.uniform(1200, 3500)
        d = dsp.damped_sines([(f, 1, 0.012)], 0.05, rng)
        dsp.place(drops, d, samples(at), rng.uniform(0.05, 0.3))
    y = (plop + spray + drops).astype(np.float32)
    return dsp.reverb(dsp.normalize_peak(y, -4), room, 0.45)
