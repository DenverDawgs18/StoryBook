"""Turn a parsed Script into a finished, mastered audiobook episode."""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from . import dsp, music  # noqa: F401  (music registers its beds)
from .dsp import SR, samples
from .script import Cue, Line, Script
from .sounds import BEDS, SFX
from .voices import Character, speak

PARA_GAP = 0.85
SEG_GAP = 0.22
HEADING_GAP = 1.6

# default levels (dB relative to a bed's native ~-20 dBFS RMS) and sidechain depth
LAYER_DEFAULTS = {
    "music": {"vol": -9.0, "duck": 9.0},
    "amb": {"vol": -8.0, "duck": 4.0},
    "amb2": {"vol": -10.0, "duck": 4.0},
    "fx": {"vol": -6.0, "duck": 0.0},
}


@dataclass
class BedSpan:
    layer: str
    name: str
    params: dict
    start: float
    end: float | None
    fade_in: float
    fade_out: float
    vol: float
    duck: float


def _num(params, key, default):
    v = params.pop(key, None)
    return float(v) if v is not None else default


def render(script: Script, out_base: Path, seed: int = 7, progress=None, mp3=True) -> dict:
    """Render `script`; writes out_base.mp3 (+ .wav if mp3=False) and out_base.json timings."""
    rng = np.random.default_rng(seed)
    cast = {name: Character.from_dict(name, d) for name, d in script.cast.items()}
    narrator = cast["narrator"]

    voice_clips = []  # (start_s, mono, character)
    sfx_clips = []  # (start_s, stereo, gain_db)
    spans: list[BedSpan] = []
    active: dict[str, BedSpan] = {}
    chapters = []
    paragraphs = []  # [{"start","end","segments":[{"speaker","text","start","end"}]}]
    cur_para = None

    cursor = 1.0
    last_was_speech = False
    lines_total = sum(isinstance(e, Line) for e in script.events) or 1
    lines_done = 0

    for ev in script.events:
        if isinstance(ev, Line):
            ch = cast.get(ev.speaker)
            if ch is None:
                ch = Character.from_dict(ev.speaker, {"voice": narrator.voice})
                cast[ev.speaker] = ch
            audio, marks = speak(ev.text, ch)
            lines_done += 1
            if progress:
                progress(lines_done / lines_total, ev.text[:80])
            if len(audio) == 0:
                continue
            if last_was_speech:
                cursor += SEG_GAP
            voice_clips.append((cursor, audio, ch))
            if cur_para is None:
                cur_para = {"start": round(cursor, 2), "segments": []}
            cur_para["segments"].append({
                "speaker": ev.speaker, "text": ev.text, "start": round(cursor, 2),
                "end": round(cursor + len(audio) / SR, 2),
                "phrases": [[p, round(cursor + a, 2), round(cursor + b, 2)] for p, a, b in marks],
            })
            cursor += len(audio) / SR
            last_was_speech = True
            continue

        cue: Cue = ev
        p = dict(cue.params)
        if cue.kind == "para_break":
            if cur_para:
                cur_para["end"] = round(cursor, 2)
                paragraphs.append(cur_para)
                cur_para = None
            cursor += PARA_GAP
            last_was_speech = False
        elif cue.kind == "pause":
            cursor += float(cue.args[0]) if cue.args else 1.0
            last_was_speech = False
        elif cue.kind == "heading":
            title = cue.args[0]
            chapters.append({"title": title, "start": round(cursor, 2)})
            audio, _ = speak(title, narrator)
            voice_clips.append((cursor, audio, narrator))
            paragraphs.append({"start": round(cursor, 2), "end": round(cursor + len(audio) / SR, 2), "heading": True,
                               "segments": [{"speaker": "narrator", "text": title, "start": round(cursor, 2),
                                             "end": round(cursor + len(audio) / SR, 2), "phrases": []}]})
            cursor += len(audio) / SR + HEADING_GAP
            last_was_speech = False
        elif cue.kind == "voice":
            ch = cast[cue.args[0]]
            for k, v in p.items():
                cur = getattr(ch, k)
                setattr(ch, k, type(cur)(v) if cur is not None else v)
        elif cue.kind == "bed":
            layer, name = cue.args[0], cue.args[1]
            d = LAYER_DEFAULTS.get(layer, {"vol": -8.0, "duck": 4.0})
            fade_in = _num(p, "fade", 3.0)
            xfade = _num(p, "xfade", fade_in)
            at = _num(p, "at", 0.0)
            vol = _num(p, "vol", d["vol"])
            duck = _num(p, "duck", d["duck"])
            if layer in active:
                old = active.pop(layer)
                old.end = cursor + at + xfade
                old.fade_out = xfade
            span = BedSpan(layer, name, p, cursor + at, None, fade_in, 3.0, vol, duck)
            spans.append(span)
            active[layer] = span
        elif cue.kind == "stop":
            layers = cue.args or list(active)
            fade_out = _num(p, "fade", 4.0)
            at = _num(p, "at", 0.0)
            for layer in layers:
                if layer in active:
                    s = active.pop(layer)
                    s.end = cursor + at + fade_out
                    s.fade_out = fade_out
        elif cue.kind == "sfx":
            name = cue.args[0]
            vol = _num(p, "vol", -6.0)
            at = _num(p, "at", 0.0)
            wait = _num(p, "wait", 0.0)
            pan = p.pop("pan", None)
            clip = SFX[name](np.random.default_rng(rng.integers(2**32)), **p)
            if pan is not None:
                clip = dsp.pan(clip.mean(axis=1), float(pan))
            sfx_clips.append((cursor + at, clip, vol))
            if wait:
                # wait=1 -> until the sound's audible end (ignoring reverb tail); else seconds
                cursor += (len(clip) / SR * 0.7 + at) if wait == 1 else wait
            last_was_speech = False
        else:
            raise ValueError(f"unknown cue {cue.kind}")

    if cur_para:
        cur_para["end"] = round(cursor, 2)
        paragraphs.append(cur_para)
    end_time = cursor + 4.0
    for s in active.values():
        s.end = end_time
        s.fade_out = 5.0
    end_time = max([end_time] + [s.end for s in spans] + [a + len(c) / SR for a, c, _ in sfx_clips])
    total = samples(end_time + 1.0)

    # ---------------- voice bus ----------------
    if progress:
        progress(1.0, "Mixing voices")
    voice = np.zeros((total, 2), dtype=np.float32)
    by_room: dict = {}
    for start, audio, ch in voice_clips:
        st = dsp.pan(audio, ch.pan)
        dsp.place(voice, st, samples(start))
        if ch.room and ch.wet > 0:
            buf = by_room.setdefault(ch.room, np.zeros((total, 2), dtype=np.float32))
            dsp.place(buf, st * ch.wet, samples(start))
    for room, buf in by_room.items():
        voice += dsp.reverb(buf, room, 1.0, 0.0, tail=False)
    voice = dsp.compress(voice, -22, 2.5, 0.004, 0.15, makeup_db=1.5)
    voice_env = dsp.envelope_follow(voice, 0.03, 0.7)
    activity = np.clip(voice_env / (dsp.db(-34)), 0, 1)

    # ---------------- beds ----------------
    beds = np.zeros((total, 2), dtype=np.float32)
    for i, s in enumerate(spans):
        if progress:
            progress(1.0, f"Painting soundscape: {s.name}")
        dur = max(s.end - s.start, 0.5)
        x = BEDS[s.name](dur, np.random.default_rng(seed + i * 101), **s.params)
        x = dsp.fade(x, s.fade_in, s.fade_out)
        a = samples(s.start)
        seg = x[: max(min(len(x), total - a), 0)]
        gain = dsp.db(s.vol)
        if s.duck > 0:
            act = activity[a:a + len(seg)]
            g = (10 ** (-(s.duck * act) / 20))[:, None]
            seg = seg * g
        dsp.place(beds, seg, a, gain)

    fx = np.zeros((total, 2), dtype=np.float32)
    for start, clip, vol in sfx_clips:
        dsp.place(fx, clip, samples(start), dsp.db(vol))

    mix = voice + beds + fx
    mix = dsp.highpass(mix, 28)
    mix = dsp.soft_limit(mix * dsp.db(-1), -0.5)

    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(1.0, "Mastering")
    _master(mix, out_base, script.meta, chapters, mp3)
    timings = {
        "meta": script.meta,
        "duration": round(total / SR, 2),
        "chapters": chapters,
        "paragraphs": paragraphs,
        "cast": {k: {"voice": v.voice} for k, v in cast.items()},
    }
    out_base.with_suffix(".json").write_text(json.dumps(timings, indent=1, ensure_ascii=False))
    return timings


def _master(mix: np.ndarray, out_base: Path, meta: dict, chapters: list, mp3: bool) -> None:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "mix.wav"
        sf.write(wav, mix, SR, subtype="FLOAT")
        # measure, then apply two-pass EBU R128 loudness normalisation (-18 LUFS: spoken word, room for dynamics)
        target = "I=-18:TP=-1.5:LRA=11"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", f"loudnorm={target}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True)
        js = r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1]
        m = json.loads(js)
        af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        metaf = Path(td) / "meta.txt"
        lines = [";FFMETADATA1", f"title={meta.get('title', '')}", f"artist={meta.get('author', '')}",
                 "album=StoryBook", "genre=Audiobook"]
        dur_ms = int(len(mix) / SR * 1000)
        for i, c in enumerate(chapters):
            s = int(c["start"] * 1000)
            e = int(chapters[i + 1]["start"] * 1000) if i + 1 < len(chapters) else dur_ms
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={s}", f"END={e}", f"title={c['title']}"]
        metaf.write_text("\n".join(lines) + "\n")
        if mp3:
            out = out_base.with_suffix(".mp3")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-i", str(metaf),
                   "-map_metadata", "1", "-map_chapters", "1", "-af", af + ",aresample=44100",
                   "-c:a", "libmp3lame", "-b:a", "128k", "-id3v2_version", "3", str(out)]
        else:
            out = out_base.with_suffix(".wav")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-af", af, str(out)]
        subprocess.run(cmd, check=True)
