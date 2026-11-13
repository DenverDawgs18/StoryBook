"""A second vertical promo video, for the personalised stories: "the bedtime story knows your kid's name".

A name is typed into the form, then we hear that child's real preview: the dedication, "The third
little pig was called Mia", the wolf calling her name at the brick house, the huffing that can't blow
it down, and the teaser. Her name lights up in green every time it is spoken. Ends on the offer.

    python tools/tiktok_personal.py              # -> dist/storybook_tiktok_personal.mp4
    python tools/tiktok_personal.py 1 12 30      # stills, for checking
Needs the sample preview: python -m storybook personal --tale the_three_little_pigs --name Mia
    --pronouns she --from Grandma --preview -o site/audio/personal
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
import tiktok as T  # noqa: E402  (fonts, paper, plates, the drawing helpers)

W, H, FPS = T.W, T.H, T.FPS
NAME = "Mia"
BASE = T.REPO / "site/audio/personal/the_three_little_pigs_for_mia_preview"
EP = json.loads(BASE.with_suffix(".json").read_text())
OUT = T.HERE / "storybook_tiktok_personal.mp4"

# source spans of the preview to keep, in order
CUTS = [(3.6, 9.7),     # music in; "This story is for Mia. With love, from Grandma."
        (20.2, 24.8),   # "The third little pig was called Mia, and Mia was the cleverest of the three."
        (31.9, 36.5),   # "...and Mia built her house with them, brick by brick."
        (40.3, 58.3),   # the knock; "Mia, Mia, let me come in"; chinny chin chin; huff, huff, huff
        (64.2, 66.5),   # "but he could not get the house down."
        (73.1, 81.0)]   # "And what happens next? That's in Mia's story." + sparkle
XF = 0.15


def src_to_out(t):
    o = 0.0
    for a, b in CUTS:
        if a <= t <= b:
            return o + (t - a)
        o += b - a
    return None


TOTAL = sum(b - a for a, b in CUTS) - XF * (len(CUTS) - 1)
LABELS = {"wolf": "the wolf", "pig3": f"{NAME}, the third little pig", "narrator": "", "host": ""}
CAPS = []
for p in EP["paragraphs"]:
    for s in p["segments"]:
        for txt, a, b in s["phrases"]:
            oa, ob = src_to_out(a + 0.01), src_to_out(b - 0.01)
            if oa is not None and ob is not None:
                CAPS.append((oa, ob, s["speaker"], txt))
# crossfades pull later spans earlier by XF each; shift caption times to match
def _xf_shift(t):
    o, k = 0.0, 0
    for a, b in CUTS:
        if t <= o + (b - a):
            return t - XF * k
        o += b - a
        k += 1
    return t - XF * (len(CUTS) - 1)


CAPS = [(_xf_shift(a), _xf_shift(b), spk, txt) for a, b, spk, txt in CAPS]
BLOWS = [_xf_shift(src_to_out(t)) for t in (52.4, 54.8, 57.2)]
KNOCK = _xf_shift(src_to_out(41.4))
DEDICATION_END = _xf_shift(src_to_out(9.4))
TEASER = _xf_shift(src_to_out(73.1))
END_CARD = _xf_shift(src_to_out(77.6))


def build_audio(path):
    inputs, filters = [], []
    for a, b in CUTS:
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(BASE.with_suffix(".mp3"))]
    chain = "[0:a]"
    for i in range(1, len(CUTS)):
        filters.append(f"{chain}[{i}:a]acrossfade=d={XF}:c1=tri:c2=tri[x{i}]")
        chain = f"[x{i}]"
    # crossfades can sum above full scale; a limiter keeps the peaks safely under it
    filters.append(f"{chain}afade=t=in:d=0.1,afade=t=out:st={TOTAL - 1.4:.2f}:d=1.4,"
                   f"alimiter=limit=0.84:attack=2:release=60:level=disabled[out]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-ar", "48000", "-ac", "2", str(path)], check=True)


ease = T.ease
mix = lambda c, a: tuple(int(x * a + p * (1 - a)) for x, p in zip(c, T.PAPER))


def caption(draw, t, top=1290):
    """Read-along with the child's name inked in green whenever it is said."""
    cur = [c for c in CAPS if c[0] - 0.15 <= t <= c[1] + 0.45]
    if not cur:
        return
    a, b, spk, txt = cur[-1]
    f = T.FELL(62) if spk in ("wolf", "pig3") else T.SPEC(52)
    if spk in ("wolf", "pig3"):
        txt = f"“{txt}”"
    words = txt.split()
    weights = np.cumsum([len(w) + 1 for w in words])
    spoken = int(np.searchsorted(weights / weights[-1], np.clip((t - a) / max(b - a, 0.1), 0, 1) + 1e-6))
    y = top
    if LABELS.get(spk):
        T.centred(draw, y, LABELS[spk], T.HAND(50), T.MOSS)
        y += 70
    lh = 82 if spk in ("wolf", "pig3") else 72
    k = 0
    for line in T.wrap(txt, f, 880):
        x = W / 2 - f.getlength(line) / 2
        for w in line.split():
            is_name = re.sub(r"\W", "", w).startswith(NAME) and len(re.sub(r"\W", "", w)) <= len(NAME) + 1
            if k < spoken:
                col = T.VIRIDIAN if is_name else T.INK
            else:
                col = (150, 182, 160) if is_name else T.FAINT
            draw.text((x, y), w, font=f, fill=col)
            if is_name and k < spoken:  # a hand-drawn underline under the name
                wl = f.getlength(w.rstrip(",.!?:;”"))
                draw.line([(x + 4, y + lh - 14), (x + wl - 2, y + lh - 18)], fill=(138, 160, 126), width=5)
            x += f.getlength(w + " ")
            k += 1
        y += lh


def form_card(fr, d, t):
    """The 'who is the story for?' form, with the name being typed and the button pressed."""
    a = 1 - ease((t - 3.2) / 0.6)
    if a <= 0:
        return
    x0, y0, x1, y1 = 120, 600, 960, 1180
    d.rounded_rectangle([x0, y0, x1, y1], 18, fill=mix((251, 248, 239), a), outline=mix((205, 200, 182), a), width=3)
    T.centred(d, y0 + 50, "Who is the story for?", T.FELL(64), mix(T.INK, a))
    d.text((x0 + 70, y0 + 170), "THEIR FIRST NAME", font=T.FELL_SC(30), fill=mix(T.INK_SOFT, a))
    typed = NAME[: max(0, min(len(NAME), int((t - 0.2) / 0.25) + 1))] if t > 0.2 else ""
    d.line([(x0 + 70, y0 + 300), (x1 - 70, y0 + 300)], fill=mix((138, 160, 126), a), width=3)
    d.text((x0 + 76, y0 + 215), typed, font=T.FELL(76), fill=mix(T.INK, a))
    if (t * 2) % 2 < 1.2 and t < 1.6:  # caret
        cx = x0 + 80 + T.FELL(76).getlength(typed)
        d.line([(cx, y0 + 225), (cx, y0 + 290)], fill=mix(T.INK, a), width=3)
    for i, p in enumerate(("she", "he", "they")):  # pronoun pills, "she" chosen
        px = x0 + 70 + i * 150
        sel = i == 0
        d.rounded_rectangle([px, y0 + 335, px + 130, y0 + 395], 30, fill=mix(T.VIRIDIAN, a) if sel else None,
                            outline=mix(T.VIRIDIAN if sel else (205, 200, 182), a), width=2)
        T.centred(d, y0 + 345, p, T.FELL_I(36), mix(T.PAPER if sel else T.INK_SOFT, a) if sel else mix(T.INK_SOFT, a), x=px + 65)
    press = 1 - 0.06 * math.exp(-max(t - 1.15, 0) * 8) * (t > 1.15)
    bw, bh = 520 * press, 96 * press
    bx, by = W / 2 - bw / 2, y0 + 440
    d.rounded_rectangle([bx, by, bx + bw, by + bh], 12, fill=mix((38, 66, 50), a))
    T.centred(d, by + 24 * press, "HEAR THEIR PREVIEW", T.FELL_SC(40), mix(T.PAPER, a))


def frame(t):
    fr = T.BG.copy().convert("RGBA")
    d = ImageDraw.Draw(fr)
    T.running_head(d, "a story for your child")
    if t < END_CARD:
        # the hook stays up top the whole way through
        a = ease(t / 0.4)
        T.centred(d, 255, "POV: the bedtime story", T.FELL(80), mix(T.INK, a))
        T.centred(d, 345, "knows your kid's name", T.FELL_I(80), mix(T.VIRIDIAN, a))
        if t < 3.8:
            form_card(fr, d, t)
        if t > 2.8:
            b = ease((t - 2.8) / 0.8)
            # creep in toward the brick house; a shake on the knock and on every blow
            k = ease((t - 3) / (BLOWS[-1] - 3))
            back = ease((t - BLOWS[-1] - 1.5) / 3.0)
            zoom = 1.0 + 0.75 * k - 0.6 * back
            focus = (0.5 + 0.22 * k - 0.15 * back, 0.5 + 0.1 * k - 0.05 * back)
            shake = (0, 0)
            for ev, amp0 in [(KNOCK, 6), *[(bl, 14) for bl in BLOWS]]:
                dt = t - ev
                if 0 <= dt < 1.1:
                    amp = amp0 * math.exp(-dt * 3.5)
                    shake = (amp * math.sin(dt * 55), amp * math.cos(dt * 41))
            T.tipped_plate(fr, T.PIGS, T.PLATE_BOX, zoom, focus, shake, alpha=b)
            for i, bl in enumerate(BLOWS):
                dt = t - bl
                if -0.15 <= dt < 1.6:
                    al = ease((dt + 0.15) / 0.25) * (1 - ease((dt - 1.1) / 0.5))
                    word = ["huff…", "puff…", "HUFF!"][i]
                    x = W // 2 + [-200, 200, 0][i]
                    d.text((x, 1205), word, font=T.HAND(int(110 + 30 * ease(dt / 0.6))), fill=mix(T.VIRIDIAN, al), anchor="ma")
        caption(d, t)
    else:
        lt = t - END_CARD
        a = ease(lt / 0.6)
        T.tipped_plate(fr, T.PIGS, (170, 300, 910, 793), 1.0, (0.5, 0.5), (0, 0), tilt=0.5, alpha=a)
        T.centred(d, 880, "Put your child", T.FELL(96), mix(T.INK, a))
        T.centred(d, 990, "in the story.", T.FELL_I(96), mix(T.VIRIDIAN, a))
        T.ornament(d, 1140)
        T.centred(d, 1190, "hear a free preview with their name", T.SPEC(44), mix(T.INK_SOFT, a))
        T.centred(d, 1275, "storybook-audio.fly.dev", T.FELL(64), mix(T.INK, a))
        b = ease((lt - 0.9) / 0.7)
        T.centred(d, 1385, "free · link in bio", T.HAND(58), mix(T.MOSS, b))
    return fr


def main():
    wav = T.HERE / "audio_personal.wav"
    build_audio(wav)
    if len(sys.argv) > 1:
        for s in sys.argv[1:]:
            frame(float(s)).convert("RGB").save(T.HERE / f"pstill_{s}.png")
        return
    n = int(TOTAL * FPS)
    enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                            str(OUT)], stdin=subprocess.PIPE)
    for i in range(n):
        enc.stdin.write(frame(i / FPS).convert("RGB").tobytes())
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close()
    enc.wait()
    print("wrote", OUT, f"{TOTAL:.1f}s")


if __name__ == "__main__":
    main()
