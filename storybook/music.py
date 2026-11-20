"""Procedural score: pads, drones, music box and a spectral waltz.

Music beds follow the same signature as ambience beds:
    fn(duration, rng, **params) -> (n, 2) float32
"""
from __future__ import annotations

import numpy as np

from . import dsp
from .dsp import SR, samples, midi_hz, note
from .sounds import bed

# formant tables (centre Hz, bandwidth Hz, gain)
FORMANTS = {
    "aah": [(800, 80, 1.0), (1150, 90, 0.5), (2900, 120, 0.25), (3900, 130, 0.12)],
    "ooh": [(350, 60, 1.0), (600, 80, 0.35), (2400, 100, 0.08)],
    "cello": [(280, 200, 1.0), (1000, 400, 0.5), (2600, 600, 0.15)],
    "strings": [(450, 300, 1.0), (1400, 600, 0.6), (3200, 900, 0.2)],
    "organ": [(500, 2000, 1.0)],
}


def _harm_weights(f0: float, timbre: str, kmax_hz: float = 4500.0):
    fm = FORMANTS[timbre]
    ks = np.arange(1, int(kmax_hz / f0) + 1)
    fk = ks * f0
    w = np.zeros(len(ks))
    for fc, bw, g in fm:
        w += g * np.exp(-0.5 * ((fk - fc) / bw) ** 2)
    w = w * 0.85 + 0.15 / ks  # keep a little raw saw for body
    if timbre == "organ":
        w = np.where(np.isin(ks, [1, 2, 3, 4, 6, 8]), 1.0 / np.sqrt(ks), 0.02)
    return ks, w


TABLE = 8192


def _wavetable(ks, w, rng):
    """One period of the note's timbre; the oscillator just reads through it."""
    x = np.arange(TABLE) / TABLE
    tab = np.zeros(TABLE, dtype=np.float32)
    for k, a in zip(ks, w):
        if a >= 0.03:
            tab += (a * np.sin(2 * np.pi * k * x + rng.uniform(0, 6.28))).astype(np.float32)
    return np.append(tab, tab[0])


def sustained(midi: float, dur: float, rng, timbre="aah", attack=2.0, release=2.5, vibrato=0.004,
              detune_cents=7.0, voices=3) -> np.ndarray:
    """A sustained ensemble note (several detuned players) - stereo."""
    n = samples(dur)
    t = np.arange(n, dtype=np.float32) / SR
    f0 = midi_hz(midi)
    ks, w = _harm_weights(f0, timbre)
    out = np.zeros((n, 2), dtype=np.float32)
    env = dsp.adsr(n, attack, 0.5, 0.85, release)
    for v in range(voices):
        cents = (v - (voices - 1) / 2) * detune_cents + rng.normal(0, 1.5)
        f = f0 * 2 ** (cents / 1200)
        vib = 1 + vibrato * np.sin(2 * np.pi * rng.uniform(4.6, 5.6) * t + rng.uniform(0, 6)) \
            * np.clip(t / 1.5, 0, 1)
        drift = 1 + 0.0015 * dsp.smooth_random(n, rng, 0.3, -1, 1)
        cyc = np.cumsum(f * vib * drift) / SR  # phase in cycles
        y = _wavetable(ks, w, rng)[((cyc % 1.0) * TABLE).astype(np.int32)]
        # bow / breath noise, very low
        y += dsp.bandpass(rng.standard_normal(n).astype(np.float32), 400, 3000) * 0.01
        out += dsp.pan(y, (v - (voices - 1) / 2) * 0.5)
    return out * env[:, None] / voices


def pluck(midi: float, dur: float, rng, bright=0.5, kind="harp") -> np.ndarray:
    f = midi_hz(midi)
    parts = []
    for k in range(1, 18):
        fk = f * k * (1 + 0.0004 * k * k)  # slight inharmonicity
        if fk > 12000:
            break
        a = (1 / k ** (1.6 - bright)) * (0.7 if kind == "harp" else 1)
        d = (2.5 if kind == "harp" else 1.2) / (1 + 0.35 * k)
        parts.append((fk, a, d))
    y = dsp.damped_sines(parts, dur, rng)
    y[: samples(0.002)] *= np.linspace(0, 1, samples(0.002))
    return y


def music_box_note(midi: float, dur: float, rng) -> np.ndarray:
    f = midi_hz(midi)
    parts = [(f, 1.0, 1.6), (f * 2.0, 0.15, 0.9), (f * 3.0, 0.07, 0.5), (f * 5.93, 0.25, 0.35), (f * 9.5, 0.08, 0.12)]
    y = dsp.damped_sines(parts, dur, rng)
    tick = dsp.highpass(rng.standard_normal(samples(0.003)).astype(np.float32), 3000) * 0.2
    y[: len(tick)] += tick
    return y


def _chord_bed(duration, rng, chords, chord_len, timbre, room, wet, octave_bass=True, level=-20, bass_timbre="cello"):
    n = samples(duration)
    out = np.zeros((n + samples(chord_len * 2), 2), dtype=np.float32)
    t = 0.0
    i = 0
    while t < duration:
        ch = chords[i % len(chords)]
        L = chord_len * 1.6  # overlap chords for smooth legato
        for m in ch:
            s = sustained(m, L, rng, timbre, attack=chord_len * 0.45, release=chord_len * 0.6)
            dsp.place(out, s, samples(t))
        if octave_bass:
            s = sustained(min(ch) - 12, L, rng, bass_timbre, attack=chord_len * 0.4, release=chord_len * 0.6, voices=2)
            dsp.place(out, s * 0.9, samples(t))
        t += chord_len
        i += 1
    out = out[:n]
    out = dsp.reverb(out, room, wet, tail=False)
    out = dsp.fade(out, 2.0, 3.0)
    return dsp.set_rms(out, level)


def _parse_chords(spec: str):
    """'D3 F3 A3 | Bb2 D3 F3' -> [[50,53,57],[46,50,53]]"""
    return [[note(x) for x in grp.split()] for grp in spec.split("|")]


@bed("elegy")
def elegy(duration, rng, chords="D3 A3 F4 | Bb2 F3 D4 | F2 C4 A4 | C3 G3 E4", chord_len=9.0, timbre="aah"):
    """Mournful choir progression in the style of a historical documentary."""
    return _chord_bed(duration, rng, _parse_chords(chords), float(chord_len), timbre, "cathedral", 0.7)


@bed("dread")
def dread(duration, rng, root="D2"):
    """Low unresolved drone: cello pedal, a beating minor-second, subharmonic swell."""
    n = samples(duration)
    r = note(root)
    out = np.zeros((n, 2), dtype=np.float32)
    seg = 24.0
    t = 0.0
    while t < duration:
        L = min(seg * 1.5, duration - t + 4)
        out_seg = sustained(r, L, rng, "cello", attack=6, release=8, voices=3, detune_cents=4)
        out_seg += sustained(r + 7, L, rng, "cello", attack=9, release=8, voices=2) * 0.35
        top = r + 24 + rng.choice([1, 3, 6])
        out_seg += sustained(top, L, rng, "ooh", attack=10, release=8, voices=2, detune_cents=12) * 0.18
        dsp.place(out, out_seg, samples(t))
        t += seg
    tt = np.arange(n) / SR
    sub = np.sin(2 * np.pi * midi_hz(r - 12) * tt) * (0.5 + 0.5 * np.sin(2 * np.pi * tt / 37)) * 0.25
    out += dsp.to_stereo(sub.astype(np.float32))
    out = dsp.reverb(out, "hall", 0.55, tail=False)
    return dsp.set_rms(dsp.fade(out, 3, 4), -21)


@bed("hearth")
def hearth(duration, rng):
    """Warm, slightly melancholy strings (Christmas eve, a cold counting-house)."""
    return _chord_bed(duration, rng, _parse_chords("E3 B3 G4 | C3 G3 E4 | A2 E3 C4 | B2 F#3 D#4"), 8.0,
                      "strings", "hall", 0.5)


# God Rest Ye Merry, Gentlemen (traditional, 18th c.) - opening phrases, E minor
CAROL = [("E4", 1), ("E4", 1), ("B4", 1), ("B4", 1), ("A4", 1), ("G4", 1), ("F#4", 1), ("E4", 1), ("D4", 1),
         ("E4", 1), ("F#4", 1), ("G4", 1), ("A4", 1), ("B4", 3), ("-", 1)]


# Brahms, Wiegenlied Op. 49 No. 4 (1868) - first two phrases, in F
LULLABY = [("A4", .5), ("A4", .5), ("C5", 2), ("A4", .5), ("A4", .5), ("C5", 2), ("A4", .5), ("C5", .5),
           ("F5", 1), ("E5", 1.5), ("D5", .5), ("D5", 1), ("C5", 2), ("G4", .5), ("A4", .5), ("Bb4", 1),
           ("G4", 1), ("G4", .5), ("A4", .5), ("Bb4", 2), ("G4", .5), ("Bb4", .5), ("E5", .5), ("D5", .5),
           ("C5", 1), ("E5", 1), ("F5", 3), ("-", 1)]
TUNES = {"carol": CAROL, "lullaby": LULLABY}


@bed("music_box")
def music_box(duration, rng, tempo=84.0, tune="carol", room="hall"):
    beat = 60 / float(tempo)
    seq = TUNES.get(tune, CAROL)
    n = samples(duration)
    out = np.zeros(n + SR * 4, dtype=np.float32)
    t = 0.5
    while t < duration:
        for nm, b in seq:
            if nm != "-":
                dsp.place(out, music_box_note(note(nm) + 12, 2.5, rng), samples(t + rng.normal(0, 0.006)))
            t += b * beat
        t += 2 * beat
    out = dsp.lowpass(out[:n], 7000)
    st = dsp.reverb(out, room, 0.45, tail=False)
    return dsp.set_rms(dsp.fade(st, 0.2, 3), -22)


@bed("carol_voice")
def carol_voice(duration, rng, tempo=76.0):
    """A lone small voice singing the carol outside a keyhole (wordless, through a door)."""
    beat = 60 / float(tempo)
    n = samples(duration)
    out = np.zeros((n + SR * 6, 2), dtype=np.float32)
    t = 0.3
    for nm, b in CAROL:
        if nm == "-":
            t += b * beat
            continue
        s = sustained(note(nm), b * beat * 1.1 + 0.2, rng, "ooh", attack=0.06, release=0.18, vibrato=0.01, voices=1)
        dsp.place(out, s, samples(t))
        t += b * beat
    out = dsp.lowpass(out[:n], 2200)  # heard through the door
    return dsp.set_rms(dsp.reverb(out, "room", 0.3, tail=False), -22)


# A small original waltz for the masquerade (A minor, 3/4).
WALTZ_MELODY = ["E5", "-", "C5", "A4", "-", "B4", "C5", "-", "E5", "D5", "-", "-",
                "D5", "-", "B4", "G#4", "-", "A4", "B4", "-", "D5", "C5", "-", "-",
                "C5", "-", "A4", "F4", "-", "G4", "A4", "-", "C5", "B4", "-", "E4",
                "F4", "-", "G#4", "B4", "-", "D5", "C5", "B4", "G#4", "A4", "-", "-"]
WALTZ_BASS = ["A2", "E2", "D3", "E2", "F2", "D3", "E2", "A2"]
WALTZ_CHORD = [["C4", "E4"], ["B3", "D4"], ["A3", "D4"], ["B3", "E4"], ["A3", "C4"], ["A3", "D4"], ["B3", "D4"], ["C4", "E4"]]


@bed("waltz")
def waltz(duration, rng, tempo=150.0, room="hall", eerie=0.4):
    """Distant revel music, slightly out of tune (eerie>0 detunes and slows)."""
    beat = 60 / float(tempo)
    n = samples(duration)
    out = np.zeros((n + SR * 6, 2), dtype=np.float32)
    t = 0.0
    while t < duration:
        for bar in range(8):
            for b in range(3):
                pos = t + (bar * 3 + b) * beat
                if b == 0:
                    s = pluck(note(WALTZ_BASS[bar]), 1.5, rng, 0.3)
                    dsp.place(out, dsp.pan(s, -0.3) * 0.9, samples(pos))
                else:
                    for c in WALTZ_CHORD[bar]:
                        s = pluck(note(c), 0.8, rng, 0.5, "pizz")
                        dsp.place(out, dsp.pan(s, 0.25) * 0.35, samples(pos))
                m = WALTZ_MELODY[bar * 6 + b * 2] if bar * 6 + b * 2 < len(WALTZ_MELODY) else "-"
                if m != "-":
                    off = rng.normal(0, 18 * float(eerie)) / 100
                    s = sustained(note(m) + off, beat * 2.2, rng, "strings", attack=0.08, release=0.4,
                                  vibrato=0.006, voices=2)
                    dsp.place(out, s * 0.55, samples(pos))
        t += 24 * beat
    out = dsp.lowpass(out[:n], 5000)
    out = dsp.reverb(out, room, 0.55, tail=False)
    return dsp.set_rms(dsp.fade(out, 1.5, 2.5), -21)


@bed("title_theme")
def title_theme(duration, rng, chords="D3 A3 F4 | Bb2 F3 D4"):
    """A short swelling opening for episode titles."""
    return _chord_bed(duration, rng, _parse_chords(chords), max(duration / 2.2, 3.0), "aah", "cathedral", 0.75, level=-18)


@bed("fairytale")
def fairytale(duration, rng, key="F", tempo=66.0, room="hall"):
    """Once upon a time: harp arpeggios rolling over a soft string pad, in a major key."""
    prog = {
        "F": "F3 A3 C4 | D3 F3 A3 | Bb2 D3 F3 | C3 E3 G3",
        "G": "G3 B3 D4 | E3 G3 B3 | C3 E3 G3 | D3 F#3 A3",
        "D": "D3 F#3 A3 | B2 D3 F#3 | G2 B2 D3 | A2 C#3 E3",
        "Am": "A2 C3 E3 | F2 A2 C3 | D3 F3 A3 | E3 G#3 B3",
    }.get(key, key)
    chords = _parse_chords(prog)
    beat = 60 / float(tempo)
    bar = beat * 4
    n = samples(duration)
    pad = _chord_bed(duration, rng, chords, bar, "strings", room, 0.5, level=-27)
    out = np.zeros((n + SR * 4, 2), dtype=np.float32)
    t, i = 0.0, 0
    while t < duration:
        ch = chords[i % len(chords)]
        tones = [m + 12 for m in ch] + [ch[0] + 24, ch[1] + 24]
        pattern = tones + tones[-2:0:-1]
        step = bar / len(pattern)
        for k, m in enumerate(pattern):
            s = pluck(m, 2.4, rng, 0.45)
            dsp.place(out, dsp.pan(s, -0.5 + k / len(pattern)), samples(t + k * step + rng.normal(0, 0.008)), 0.35)
        t += bar
        i += 1
    out = dsp.lowpass(out[:n], 7500)
    out = dsp.set_rms(dsp.fade(dsp.reverb(out, room, 0.45, tail=False), 2.0, 3.0), -23)
    return out + pad
