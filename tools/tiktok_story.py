"""Cut a vertical (9:16) promo video for any StoryBook episode from a short clip sheet.

    python tools/tiktok_story.py tools/clips/elves_and_the_shoemaker.json        # -> dist/tiktok_<name>.mp4
    python tools/tiktok_story.py tools/clips/elves_and_the_shoemaker.json 2 20   # stills at those seconds

A clip sheet is JSON. All times are in seconds of the SOURCE episode audio, so you can read them straight
off the episode's timings file (site/audio/<story>.json: paragraphs -> segments -> phrases [text, start, end]):

{
  "story": "elves_and_the_shoemaker",          // site/audio/<story>.mp3 + .json (or "audio": "path/without/ext")
  "name": "elves",                             // output: dist/tiktok_<name>.mp4
  "plate": "land_cottage",                     // a painting in site/assets/land/ (webp)
  "plate_after": {"plate": "land_x", "at": 89.3},   // optional: swap paintings at a moment (e.g. a house falls)
  "running_head": "the elves and the shoemaker",
  "hook": ["A shoemaker went to bed broke.", "He woke up to finished shoes."],   // shown for hook_seconds
  "hook_seconds": 3.4,
  "title": "The Elves and the Shoemaker", "byline": "The Brothers Grimm · 1812",  // replaces the hook after it
  "cuts": [[61.8, 66.7], [71.6, 76.6]],        // spans to keep, in order; joined with short crossfades
  "labels": {"shoemaker": "the shoemaker"},    // caption labels for speakers (narrator/host get none)
  "highlight": ["elves", "dwarfs"],            // words inked in green when spoken
  "camera": [[61.8, 0.5, 0.5, 1.0], [177, 0.4, 0.6, 1.6]],  // keyframes [time, focus x, focus y, zoom]
  "moments": [[172.4, "dong…"], [207.6, "tap tap tap"]],      // a handwritten word pops up over the plate
  "shake": [207.6],                            // the plate shakes (knocks, blows, crashes)
  "end": {"line1": "Old tales,", "line2": "a full cast & weather", "sub": "twelve free stories", "foot": "link in bio"}
}

Keep the result 30-45 s: a hook in the first 2 s, the story's most vivid stretch (dialogue plus a sound
moment), and an end card. Check stills before rendering, and check the moments against the audio.
"""
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tiktok as T  # noqa: E402  (fonts, paper, plates and the drawing helpers)

W, H, FPS = T.W, T.H, T.FPS
XF = 0.15
ease = T.ease
mix = lambda c, a: tuple(int(x * a + p * (1 - a)) for x, p in zip(c, T.PAPER))


class Clip:
    def __init__(self, spec: dict):
        self.s = spec
        base = Path(spec["audio"]) if "audio" in spec else T.REPO / "site/audio" / spec["story"]
        self.base = base if base.is_absolute() else T.REPO / base
        self.ep = json.loads(self.base.with_suffix(".json").read_text())
        self.cuts = [tuple(c) for c in spec["cuts"]]
        self.total = sum(b - a for a, b in self.cuts) - XF * (len(self.cuts) - 1)
        self.plate = T.load_plate(spec["plate"])
        after = spec.get("plate_after")
        self.after = (T.load_plate(after["plate"]), self.out(after["at"])) if after else None
        self.labels = {"narrator": "", "host": "", **spec.get("labels", {})}
        self.hl = [w.lower() for w in spec.get("highlight", [])]
        self.caps = []
        for p in self.ep["paragraphs"]:
            for sg in p["segments"]:
                for txt, a, b in sg["phrases"]:
                    oa, ob = self.out(a + 0.01, strict=True), self.out(b - 0.01, strict=True)
                    if oa is not None and ob is not None:
                        self.caps.append((oa, ob, sg["speaker"], txt))
        self.moments = [(self.out(t), w) for t, w in spec.get("moments", []) if self.out(t, strict=True) is not None]
        self.shakes = [self.out(t) for t in spec.get("shake", []) if self.out(t, strict=True) is not None]
        cam = sorted(spec.get("camera", [[self.cuts[0][0], 0.5, 0.5, 1.0]]))
        self.cam = [(self.out(t), x, y, z) for t, x, y, z in cam]
        self.end_at = self.total - spec.get("end_seconds", 3.6)

    def out(self, t, strict=False):
        """Source time -> time in the finished video (None if the moment was cut, when strict)."""
        o = 0.0
        for k, (a, b) in enumerate(self.cuts):
            if a <= t <= b:
                return o + (t - a) - XF * k
            o += b - a
        if strict:
            return None
        # a moment that falls in a gap: snap to the start of the next kept span
        o = 0.0
        for k, (a, b) in enumerate(self.cuts):
            if t < a:
                return o - XF * k
            o += b - a
        return self.total

    def camera(self, t):
        ks = self.cam
        if t <= ks[0][0]:
            return ks[0][1:]
        for (t0, *a), (t1, *b) in zip(ks, ks[1:]):
            if t0 <= t <= t1:
                k = ease((t - t0) / max(t1 - t0, 1e-3))
                return tuple(x + (y - x) * k for x, y in zip(a, b))
        return ks[-1][1:]

    # ------------------------------------------------------------- audio
    def build_audio(self, path):
        inputs, filters = [], []
        for a, b in self.cuts:
            inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(self.base.with_suffix(".mp3"))]
        chain = "[0:a]"
        for i in range(1, len(self.cuts)):
            filters.append(f"{chain}[{i}:a]acrossfade=d={XF}:c1=tri:c2=tri[x{i}]")
            chain = f"[x{i}]"
        filters.append(f"{chain}afade=t=in:d=0.1,afade=t=out:st={self.total - 1.4:.2f}:d=1.4,"
                       f"alimiter=limit=0.84:attack=2:release=60:level=disabled[out]")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters),
                        "-map", "[out]", "-ar", "48000", "-ac", "2", str(path)], check=True)

    # ------------------------------------------------------------- drawing
    def caption(self, d, t, top=1290):
        cur = [c for c in self.caps if c[0] - 0.15 <= t <= c[1] + 0.45]
        if not cur:
            return
        a, b, spk, txt = cur[-1]
        quoted = spk not in ("narrator", "host")
        f = T.FELL(62) if quoted else T.SPEC(50)
        if quoted:
            txt = f"“{txt}”"
        words = txt.split()
        weights = np.cumsum([len(w) + 1 for w in words])
        spoken = int(np.searchsorted(weights / weights[-1], np.clip((t - a) / max(b - a, 0.1), 0, 1) + 1e-6))
        y = top
        label = self.labels.get(spk, spk.replace("_", " "))
        if label:
            T.centred(d, y, label, T.HAND(50), T.MOSS)
            y += 70
        lh = 82 if quoted else 70
        k = 0
        for line in T.wrap(txt, f, 880):
            x = W / 2 - f.getlength(line) / 2
            for w in line.split():
                core = re.sub(r"[^\w']", "", w).lower()
                hot = any(core == h or core.startswith(h) for h in self.hl)
                col = (T.VIRIDIAN if hot else T.INK) if k < spoken else ((150, 182, 160) if hot else T.FAINT)
                d.text((x, y), w, font=f, fill=col)
                x += f.getlength(w + " ")
                k += 1
            y += lh

    def frame(self, t):
        fr = T.BG.copy().convert("RGBA")
        d = ImageDraw.Draw(fr)
        T.running_head(d, self.s.get("running_head", ""))
        if t < self.end_at:
            hs = self.s.get("hook_seconds", 3.4)
            hook = self.s.get("hook", [])
            if t < hs and hook:
                a = ease(t / 0.3) * (1 - ease((t - hs + 0.5) / 0.5))
                T.centred(d, 255, hook[0], T.FELL(74 if len(hook[0]) < 26 else 62), mix(T.INK, a))
                if len(hook) > 1:
                    T.centred(d, 345, hook[1], T.FELL_I(74 if len(hook[1]) < 26 else 62), mix(T.VIRIDIAN, a))
            else:
                a = ease((t - hs) / 0.6)
                T.centred(d, 270, self.s.get("title", ""), T.FELL(76 if len(self.s.get("title", "")) < 24 else 64), mix(T.INK, a))
                T.centred(d, 380, self.s.get("byline", ""), T.FELL_I(38), mix(T.INK_SOFT, a))
            fx, fy, zoom = self.camera(t)
            shake = (0, 0)
            for ev in self.shakes:
                dt = t - ev
                if 0 <= dt < 1.1:
                    amp = 13 * math.exp(-dt * 3.5)
                    shake = (amp * math.sin(dt * 55), amp * math.cos(dt * 41))
            plate = self.plate
            if self.after and t >= self.after[1]:
                plate = self.after[0]
            T.tipped_plate(fr, plate, T.PLATE_BOX, zoom, (fx, fy), shake)
            if self.after and self.after[1] - 0.1 <= t < self.after[1] + 0.35:
                T.tipped_plate(fr, self.plate, T.PLATE_BOX, zoom, (fx, fy), shake,
                               alpha=1 - ease((t - self.after[1] + 0.1) / 0.45))
            for i, (mt, word) in enumerate(self.moments):
                dt = t - mt
                if -0.15 <= dt < 1.6:
                    al = ease((dt + 0.15) / 0.25) * (1 - ease((dt - 1.1) / 0.5))
                    # pencilled in the gap between the title and the plate, clear of the captions
                    x = W // 2 + (-170, 170, 0)[i % 3]
                    d.text((x, 452), word, font=T.HAND(int(86 + 20 * ease(dt / 0.6))), fill=mix(T.VIRIDIAN, al), anchor="ma")
            self.caption(d, t)
        else:
            e = self.s.get("end", {})
            lt = t - self.end_at
            a = ease(lt / 0.6)
            T.tipped_plate(fr, self.after[0] if self.after else self.plate, (170, 300, 910, 793), 1.0, (0.5, 0.5),
                           (0, 0), tilt=0.5, alpha=a)
            T.centred(d, 880, e.get("line1", "Old tales,"), T.FELL(92), mix(T.INK, a))
            T.centred(d, 985, e.get("line2", "read aloud by a full cast"), T.FELL_I(70), mix(T.VIRIDIAN, a))
            T.ornament(d, 1125)
            T.centred(d, 1175, e.get("sub", "twelve free stories"), T.SPEC(44), mix(T.INK_SOFT, a))
            T.centred(d, 1260, "storybook-audio.fly.dev", T.FELL(64), mix(T.INK, a))
            b = ease((lt - 0.9) / 0.7)
            T.centred(d, 1370, e.get("foot", "link in bio"), T.HAND(58), mix(T.MOSS, b))
        return fr


def main():
    spec_path = Path(sys.argv[1])
    clip = Clip(json.loads(spec_path.read_text()))
    name = clip.s.get("name", spec_path.stem)
    wav = T.HERE / f"audio_{name}.wav"
    clip.build_audio(wav)
    if len(sys.argv) > 2:
        for s in sys.argv[2:]:
            clip.frame(float(s)).convert("RGB").save(T.HERE / f"still_{name}_{s}.png")
        print(f"{clip.total:.1f}s; captions:", [(round(a, 1), c[3][:40]) for a, *c in [(x[0], *x) for x in clip.caps]][:3], "…")
        return
    out = T.HERE / f"tiktok_{name}.mp4"
    n = int(clip.total * FPS)
    enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                            str(out)], stdin=subprocess.PIPE)
    for i in range(n):
        enc.stdin.write(clip.frame(i / FPS).convert("RGB").tobytes())
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close()
    enc.wait()
    print("wrote", out, f"{clip.total:.1f}s")


if __name__ == "__main__":
    main()
