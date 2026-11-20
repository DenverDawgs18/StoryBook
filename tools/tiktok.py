"""A vertical (9:16) promo video for TikTok / Reels / Shorts, 1080x1920 at 30 fps.

The wolf at the straw house from The Three Little Pigs, with a read-along caption inked in
word by word from the episode's timings; then a montage of the painted plates; then a title-page
end card. Needs the rendered episode, the plates (tools/landscape.py, incl. `pigs_fallen`) and ffmpeg.

    python tools/tiktok.py                 # -> dist/storybook_tiktok.mp4
    python tools/tiktok.py 2 15.2 37       # stills at those seconds, for checking
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "dist"
F = REPO / ".cache" / "fonts"
OUT = HERE / "storybook_tiktok.mp4"
FONT_CSS = ("https://fonts.googleapis.com/css2?family=IM+Fell+English:ital@0;1&family=IM+Fell+English+SC"
            "&family=Spectral:ital,wght@0,300;0,400;1,300&family=Caveat:wght@600")


def fetch_fonts():
    """The site's fonts (SIL OFL) as TTFs: Google Fonts serves TTF links to a plain user agent."""
    import re
    import urllib.request
    F.mkdir(parents=True, exist_ok=True)
    if len(list(F.glob("*.ttf"))) >= 7:
        return
    req = urllib.request.Request(FONT_CSS, headers={"User-Agent": "Mozilla/4.0"})
    css = urllib.request.urlopen(req).read().decode()
    for block in css.split("@font-face")[1:]:
        fam = re.search(r"font-family: '([^']+)'", block).group(1).replace(" ", "")
        sty = re.search(r"font-style: (\w+)", block).group(1)
        wt = re.search(r"font-weight: (\d+)", block).group(1)
        url = re.search(r"url\(([^)]+)\)", block).group(1)
        urllib.request.urlretrieve(url, F / f"{fam}-{sty}-{wt}.ttf")


HERE.mkdir(exist_ok=True)
fetch_fonts()
W, H, FPS = 1080, 1920, 30

INK = (34, 49, 42)
INK_SOFT = (75, 92, 81)
FAINT = (160, 168, 156)
MOSS = (94, 123, 78)
VIRIDIAN = (46, 106, 88)
PAPER = (245, 240, 226)


def font(name, size):
    return ImageFont.truetype(str(F / name), size)


FELL = lambda s: font("IMFellEnglish-normal-400.ttf", s)
FELL_I = lambda s: font("IMFellEnglish-italic-400.ttf", s)
FELL_SC = lambda s: font("IMFellEnglishSC-normal-400.ttf", s)
SPEC = lambda s: font("Spectral-normal-400.ttf", s)
HAND = lambda s: font("Caveat-normal-600.ttf", s)

# ------------------------------------------------------------------ audio edit
EP = json.loads((REPO / "site/audio/the_three_little_pigs.json").read_text())
MP3 = REPO / "site/audio/the_three_little_pigs.mp3"
CUTS = [(65.40, 70.85), (70.85, 73.40), (75.95, 78.70), (81.75, 96.40)]  # source spans, in order
OUTRO = (398.0, 411.8)
XF = 0.12


def src_to_out(t):
    o = 0.0
    for a, b in CUTS:
        if a <= t <= b:
            return o + (t - a)
        o += b - a
    return None


STORY_END = sum(b - a for a, b in CUTS)  # ~25.4s
MONTAGE_START = STORY_END - 0.4
END_CARD = MONTAGE_START + 9.2
TOTAL = MONTAGE_START + (OUTRO[1] - OUTRO[0]) - 0.3

# speech captions from the read-along timings
LABELS = {"wolf": "the wolf", "pig1": "the first little pig", "narrator": ""}
CAPS = []
for p in EP["paragraphs"]:
    for s in p["segments"]:
        for txt, a, b in s["phrases"]:
            oa, ob = src_to_out(a + 0.01), src_to_out(b - 0.01)
            if oa is not None and ob is not None:
                CAPS.append((oa, ob, s["speaker"], txt))
# trim the first narrator phrase down to what we actually hear
BLOW1, BLOW2, COLLAPSE = src_to_out(86.0), src_to_out(88.15), src_to_out(89.1)


def build_audio(path):
    parts, filters = [], []
    inputs = []
    for i, (a, b) in enumerate(CUTS + [OUTRO]):
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(MP3)]
    n = len(CUTS) + 1
    chain = "[0:a]"
    for i in range(1, n):
        d = 0.6 if i == n - 1 else XF
        filters.append(f"{chain}[{i}:a]acrossfade=d={d}:c1=tri:c2=tri[x{i}]")
        chain = f"[x{i}]"
    filters.append(f"{chain}afade=t=in:d=0.15,afade=t=out:st={TOTAL - 1.6:.2f}:d=1.6,atrim=0:{TOTAL:.2f}[out]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-ar", "48000", "-ac", "2", str(path)], check=True)


# ------------------------------------------------------------------ painting helpers
def load_plate(name):
    return Image.open(REPO / f"site/assets/land/{name}.webp").convert("RGB")


PAPER_TEX = Image.open(REPO / "site/assets/paint/paper.png").convert("RGB")


def paper_bg():
    bg = Image.new("RGB", (W, H), PAPER)
    tex = Image.new("RGB", (W, H))
    for y in range(0, H, PAPER_TEX.height):
        for x in range(0, W, PAPER_TEX.width):
            tex.paste(PAPER_TEX, (x, y))
    bg = ImageChops.multiply(bg, tex)
    # warm vignette toward the page edges, like an old leaf
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    v = np.clip((d - 0.55) * 0.5, 0, 0.18)[..., None]
    a = np.array(bg, float) * (1 - v) + np.array([150, 128, 80]) * v
    return Image.fromarray(a.astype(np.uint8))


BG = paper_bg()


def centred(draw, y, text, f, fill, x=W // 2, anchor="ma"):
    draw.text((x, y), text, font=f, fill=fill, anchor=anchor)


def ornament(draw, y, w=300):
    draw.line([(W // 2 - w, y), (W // 2 - 30, y)], fill=(138, 160, 126), width=2)
    draw.line([(W // 2 + 30, y), (W // 2 + w, y)], fill=(138, 160, 126), width=2)
    c = (138, 160, 126)
    draw.polygon([(W // 2, y - 12), (W // 2 + 12, y), (W // 2, y + 12), (W // 2 - 12, y)], fill=c)


def running_head(draw, right):
    draw.text((70, 175), "StoryBook", font=FELL_I(46), fill=INK, anchor="ls")
    draw.text((W - 70, 175), right, font=FELL_SC(30), fill=INK_SOFT, anchor="rs")
    draw.line([(60, 196), (W - 60, 196)], fill=(190, 198, 186), width=2)
    draw.line([(60, 202), (W - 60, 202)], fill=(190, 198, 186), width=2)


def tipped_plate(frame, plate, box, zoom=1.0, focus=(0.5, 0.5), shake=(0, 0), tilt=-0.5, alpha=1.0):
    """A plate on a whiter sheet with a plate mark and a soft shadow, painted by multiply."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    pad = 18
    sheet = Image.new("RGBA", (bw + 2 * pad, bh + 2 * pad), (251, 248, 239, 255))
    sd = ImageDraw.Draw(sheet)
    sd.rectangle([7, 7, bw + 2 * pad - 8, bh + 2 * pad - 8], outline=(214, 208, 190), width=2)
    # the painting itself, panned and zoomed inside its frame
    pw, ph = plate.size
    cw, ch = pw / zoom, ph / zoom
    cx = np.clip(focus[0] * pw, cw / 2, pw - cw / 2)
    cy = np.clip(focus[1] * ph, ch / 2, ph - ch / 2)
    crop = plate.resize((bw, bh), Image.BICUBIC, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))
    inner = Image.new("RGB", (bw, bh), (251, 248, 239))
    inner = ImageChops.multiply(inner, crop)
    sheet.paste(inner, (pad, pad))
    sheet = sheet.rotate(tilt, resample=Image.BICUBIC, expand=True)
    shadow = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    shadow.paste((60, 50, 20, 70), (0, 0, *sheet.size), sheet.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    sx, sy = x0 - pad + int(shake[0]), y0 - pad + int(shake[1])
    if alpha < 1:
        sheet.putalpha(sheet.split()[3].point(lambda v: int(v * alpha)))
        shadow.putalpha(shadow.split()[3].point(lambda v: int(v * alpha)))
    frame.alpha_composite(shadow, (sx + 4, sy + 14))
    frame.alpha_composite(sheet, (sx, sy))


def wrap(text, f, width):
    """Greedy wrap, then narrow the measure as far as it goes without adding a line (no widows)."""
    lines = _wrap(text, f, width)
    while width > 300 and len(_wrap(text, f, width - 20)) == len(lines):
        width -= 20
        lines = _wrap(text, f, width)
    return lines


def _wrap(text, f, width):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = f"{cur} {w_}".strip()
        if f.getlength(t) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def caption(draw, t, top=1300):
    """Read-along: the phrase being spoken, words inked in as they are said."""
    cur = [c for c in CAPS if c[0] - 0.15 <= t <= c[1] + 0.5]
    if not cur:
        return
    a, b, spk, txt = cur[-1]
    label = LABELS.get(spk, spk)
    f = FELL(62) if spk != "narrator" else SPEC(50)
    if spk != "narrator":
        txt = f"“{txt}”"
    lines = wrap(txt, f, 860)
    words = txt.split()
    # estimate each word's moment by its share of the letters
    weights = np.cumsum([len(w_) + 1 for w_ in words])
    spoken = int(np.searchsorted(weights / weights[-1], np.clip((t - a) / max(b - a, 0.1), 0, 1) + 1e-6))
    y = top
    if label:
        centred(draw, y, label, HAND(50), MOSS)
        y += 70
    k = 0
    lh = 82 if spk != "narrator" else 70
    for line in lines:
        lw = f.getlength(line)
        x = W / 2 - lw / 2
        for w_ in line.split():
            col = INK if k < spoken else FAINT
            draw.text((x, y), w_, font=f, fill=col)
            x += f.getlength(w_ + " ")
            k += 1
        y += lh


def ease(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ scenes
PIGS, PIGS_FALLEN = load_plate("land_pigs"), load_plate("land_pigs_fallen")
MONTAGE = [("land_cottage", "The Elves and the Shoemaker", "Plate II"), ("land_wood", "Little Red-Cap", "Plate III"),
           ("land_forest", "Hansel and Gretel", "Plate IV"), ("land_hills", "Rumpelstiltskin", "Plate V"),
           ("land_spring", "The Frog-Prince", "Plate VI"), ("land_snow", "The Little Match Girl", "Plate VII")]
MONTAGE = [(load_plate(a), b, c) for a, b, c in MONTAGE]
HERO = load_plate("hero")
PLATE_BOX = (70, 560, 1010, 1187)  # 940 x 627, 3:2


def story_frame(t):
    fr = BG.copy().convert("RGBA")
    d = ImageDraw.Draw(fr)
    running_head(d, "the three little pigs")
    # hook, then the chapter heading
    if t < 3.4:
        a = 1 - ease((t - 2.8) / 0.6)
        col = tuple(int(c * a + p * (1 - a)) for c, p in zip(INK, PAPER))
        centred(d, 262, "Bedtime stories,", FELL(92), col)
        centred(d, 362, "performed.", FELL_I(92), tuple(int(c * a + p * (1 - a)) for c, p in zip(VIRIDIAN, PAPER)))
        centred(d, 478, "a full cast · weather · a painted plate", SPEC(34), tuple(int(c * a + p * (1 - a)) for c, p in zip(INK_SOFT, PAPER)))
    else:
        a = ease((t - 3.4) / 0.6)
        centred(d, 290, "CHAPTER THE FIRST", FELL_SC(30), tuple(int(c * a + p * (1 - a)) for c, p in zip(MOSS, PAPER)))
        centred(d, 335, "The Three Little Pigs", FELL(86), tuple(int(c * a + p * (1 - a)) for c, p in zip(INK, PAPER)))
        centred(d, 450, "Joseph Jacobs · 1890", FELL_I(38), tuple(int(c * a + p * (1 - a)) for c, p in zip(INK_SOFT, PAPER)))
    # camera: creep in on the straw house, shake on each blow, ease back out after it falls
    straw = (0.2, 0.6)
    if t < COLLAPSE:
        k = ease(t / COLLAPSE)
        zoom = 1.0 + 0.9 * k
        focus = (0.5 + (straw[0] - 0.5) * k, 0.5 + (straw[1] - 0.5) * k)
    else:
        k = ease((t - COLLAPSE - 1.2) / 5.0)
        zoom = 1.9 - 0.85 * k
        focus = (straw[0] + (0.45 - straw[0]) * k, straw[1] + (0.55 - straw[1]) * k)
    shake = (0, 0)
    for blow in (BLOW1, BLOW2, COLLAPSE):
        dt = t - blow
        if 0 <= dt < 1.2:
            amp = 14 * math.exp(-dt * 3.5)
            shake = (amp * math.sin(dt * 55), amp * math.cos(dt * 41))
    plate = PIGS if t < COLLAPSE else PIGS_FALLEN
    tipped_plate(fr, plate, PLATE_BOX, zoom, focus, shake)
    if COLLAPSE - 0.1 <= t < COLLAPSE + 0.35:  # the old picture blown away in a puff
        a = 1 - ease((t - COLLAPSE + 0.1) / 0.45)
        tipped_plate(fr, PIGS, PLATE_BOX, zoom, focus, shake, alpha=a)
    for blow, word in ((BLOW1, "huff…"), (BLOW2, "puff…")):
        dt = t - blow
        if -0.2 <= dt < 1.6:
            a = ease((dt + 0.2) / 0.25) * (1 - ease((dt - 1.1) / 0.5))
            col = tuple(int(c * a + p * (1 - a)) for c, p in zip(VIRIDIAN, PAPER))
            size = int(110 + 30 * ease(dt / 0.6))
            d.text((W // 2 + (-170 if word == "huff…" else 170), 1215), word, font=HAND(size), fill=col, anchor="ma")
    caption(d, t)
    return fr


def montage_frame(t):
    fr = BG.copy().convert("RGBA")
    d = ImageDraw.Draw(fr)
    running_head(d, "the fairy tales")
    lt = t - MONTAGE_START
    a = ease(lt / 0.5)
    centred(d, 270, "Twelve tales,", FELL(84), tuple(int(c * a + p * (1 - a)) for c, p in zip(INK, PAPER)))
    centred(d, 362, "each with its own cast & weather", FELL_I(52), tuple(int(c * a + p * (1 - a)) for c, p in zip(VIRIDIAN, PAPER)))
    span = (END_CARD - MONTAGE_START) / len(MONTAGE)
    i = min(int(lt / span), len(MONTAGE) - 1)
    li = lt - i * span
    plate, title, no = MONTAGE[i]
    # each plate is laid down on the page like a card dealt onto a table
    drop = 1 - ease(li / 0.35)
    tipped_plate(fr, plate, PLATE_BOX, 1.08 - 0.06 * ease(li / span), (0.5, 0.5), (0, -60 * drop), tilt=(-0.6 if i % 2 else 0.6))
    if i > 0 and li < 0.35:
        prev = MONTAGE[i - 1][0]
        tipped_plate(fr, prev, PLATE_BOX, 1.02, (0.5, 0.5), (0, 0), tilt=(-0.6 if (i - 1) % 2 else 0.6), alpha=1 - ease(li / 0.35))
    centred(d, 1250, no.upper(), FELL_SC(32), MOSS)
    centred(d, 1300, title, FELL(76), INK)
    return fr


def end_frame(t):
    fr = BG.copy().convert("RGBA")
    d = ImageDraw.Draw(fr)
    lt = t - END_CARD
    a = ease(lt / 0.7)
    hero = HERO.crop((300, 0, 2100, 1000))
    tipped_plate(fr, hero, (90, 250, 990, 750), 1.0 + 0.04 * lt / 5, (0.5, 0.5), (0, 0), tilt=0, alpha=a)
    fade = lambda c: tuple(int(x * a + p * (1 - a)) for x, p in zip(c, PAPER))
    centred(d, 820, "StoryBook", FELL(150), fade(INK))
    centred(d, 990, "or, Old Tales Read Aloud", FELL_I(58), fade(VIRIDIAN))
    ornament(d, 1110)
    centred(d, 1160, "twelve tales, free to listen", SPEC(44), fade(INK_SOFT))
    centred(d, 1240, "storybook-audio.fly.dev", FELL(64), fade(INK))
    b = ease((lt - 1.0) / 0.8)
    centred(d, 1350, "and a Studio to perform your own pages", HAND(54),
            tuple(int(x * b + p * (1 - b)) for x, p in zip(MOSS, PAPER)))
    return fr


def frame(t):
    if t < MONTAGE_START:
        return story_frame(t)
    if t < END_CARD:
        return montage_frame(t)
    return end_frame(t)


def main():
    wav = HERE / "audio.wav"
    build_audio(wav)
    n = int(TOTAL * FPS)
    if len(sys.argv) > 1:  # stills for checking: python make_tiktok.py 2 10 18.5 ...
        for s in sys.argv[1:]:
            frame(float(s)).convert("RGB").save(HERE / f"still_{s}.png")
        return
    enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium",
                            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
                            "-movflags", "+faststart", str(OUT)], stdin=subprocess.PIPE)
    for i in range(n):
        enc.stdin.write(frame(i / FPS).convert("RGB").tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close()
    enc.wait()
    print("wrote", OUT, f"{TOTAL:.1f}s")


if __name__ == "__main__":
    main()
