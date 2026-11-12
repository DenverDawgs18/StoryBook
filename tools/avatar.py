"""A square profile picture: a watercolour landscape rising out of an open storybook,
in a cream roundel on green book-cloth. Everything that matters sits inside the circle
that TikTok, Instagram and YouTube crop avatars to.

    python tools/avatar.py        # -> dist/storybook_avatar.png (1080x1080) and a preview sheet
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from landscape import Plate, cottage  # noqa: E402
from paint import fbm  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "dist"
S = 2160  # paint at 2x, then downsample for a crisp 1080
CLOTH, CLOTH_DEEP = np.array([63, 90, 72]), np.array([44, 67, 52])
CREAM = np.array([247, 242, 228])


def landscape():
    """The scene inside the roundel, painted with the site's glazes."""
    p = Plate(1200, 1200, 7)
    p.sky("celadon", "straw", 0.5)
    p.lift(p.disc(0.68, 0.27, 0.075, 3), 0.95)  # a pale moon
    r1 = p.ridge(0.47, 0.05, "mist", 0.55, base=2)
    p.conifers(r1, "sage", 26, (0.04, 0.08), 0.38, 0.6)
    r2 = p.ridge(0.6, 0.035, "moss", 0.7, base=2)
    p.round_trees(r2, "sap", 3, (0.05, 0.08), 0.8, (0.62, 0.8))
    p.conifers(r2, "viridian", 5, (0.16, 0.24), 0.32, 0.85, (0.14, 0.3))
    cottage(p, 0.47, float(r2[int(0.47 * p.w)]) + 0.02, 0.11, color="umber", roof="forest", lit=True)
    p.ridge(0.7, 0.02, "sap", 0.75, base=2)
    absorb = np.zeros((p.h, p.w, 3))
    for d, col, k in p.layers:
        absorb += np.clip(d, 0, 1)[..., None] * k * (1 - np.array(col) / 255.0)
    rgb = np.exp(-absorb * 2.2)
    return np.array(Image.fromarray((rgb * 255).astype(np.uint8)).resize((S, S), Image.LANCZOS)) / 255.0


def cloth():
    """Green book-cloth: a fine weave under a soft light from above."""
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:S, 0:S]
    weave = 0.04 * ((yy % 6) < 2) - 0.03 * ((xx % 6) < 2) + rng.normal(0, 0.02, (S, S))
    light = np.clip(1 - np.sqrt(((xx - S * 0.5) / S) ** 2 + ((yy - S * 0.35) / S) ** 2) * 1.3, 0, 1)[..., None]
    base = CLOTH_DEEP + (CLOTH - CLOTH_DEEP) * light
    return np.clip(base * (1 + weave[..., None]), 0, 255) / 255.0


def ragged_disc(r, rough, seed, soft=2.5):
    yy, xx = np.mgrid[0:S, 0:S]
    d = np.sqrt((xx - S / 2) ** 2 + (yy - S / 2) ** 2) / S
    n = fbm(S // 4, S // 4, np.random.default_rng(seed), 5, 6)
    n = np.array(Image.fromarray((n * 255).astype(np.uint8)).resize((S, S), Image.BICUBIC)) / 255.0
    return np.clip((r + (n - 0.5) * rough - d) * S / soft, 0, 1)


def book(img):
    """An open book along the bottom of the roundel, pages curling up from the gutter."""
    d = ImageDraw.Draw(img)
    cx, top, bottom, half = S * 0.5, S * 0.69, S * 0.84, S * 0.31
    sag = S * 0.035  # the pages dip into the gutter

    def page(side, grow=0.0):
        """One page as a closed outline: top edge dipping into the gutter, bottom edge sagging to the spine."""
        top_pts, bot_pts = [], []
        for t in np.linspace(0, 1, 60):  # gutter -> outer edge
            x = cx + side * (half + S * grow) * t
            top_pts.append((x, top + sag * (1 - t) ** 2 - S * 0.012 * np.sin(np.pi * t) - S * grow * 0.4))
            bot_pts.append((x, bottom + S * 0.025 * (1 - t) ** 1.5 - S * 0.01 * t + S * grow))
        return top_pts + bot_pts[::-1]

    # cloth boards peeping out under the page block, then the stacked page edges, then the top leaf
    for side in (-1, 1):
        d.polygon(page(side, 0.014), fill=tuple(CLOTH_DEEP))
        d.polygon([(x, y + S * 0.012) for x, y in page(side, 0.004)], fill=(206, 196, 172))
        d.polygon([(x, y + S * 0.006) for x, y in page(side, 0.002)], fill=(226, 218, 197))
        d.polygon(page(side), fill=tuple(CREAM))
        # a few lines of type, following the page's curl
        for i in range(5):
            ys = top + S * (0.05 + 0.021 * i)
            x0 = cx + side * S * 0.05
            x1 = cx + side * (half * (0.55 if i == 4 else 0.86))
            pts = [(x, ys + sag * 0.5 * (1 - abs(x - cx) / half) ** 2 - S * 0.01 * np.sin(np.pi * abs(x - cx) / half))
                   for x in np.linspace(x0, x1, 30)]
            d.line(pts, fill=(176, 172, 156), width=int(S * 0.004))
    # the gutter shadow
    sh = Image.new("L", img.size, 0)
    ImageDraw.Draw(sh).line([(cx, top + sag * 0.9), (cx, bottom + S * 0.022)], fill=110, width=int(S * 0.02))
    sh = sh.filter(ImageFilter.GaussianBlur(S * 0.008))
    dark = Image.new("RGB", img.size, (90, 80, 55))
    img.paste(dark, (0, 0), sh.point(lambda v: int(v * 0.7)))


def main():
    OUT.mkdir(exist_ok=True)
    land = landscape()
    canvas = cloth()
    # the roundel: cream paper, a fine plate-mark ring, the landscape in a ragged watercolour disc
    paper = ragged_disc(0.455, 0.0, 1, soft=1.5)
    canvas = canvas * (1 - paper[..., None]) + (CREAM / 255.0) * paper[..., None]
    wash = ragged_disc(0.415, 0.025, 9)
    wash[int(S * 0.8):] = 0  # the scene rises out of the book; below it is plain page
    canvas = canvas * (1 - wash[..., None]) + canvas * land * wash[..., None]
    img = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    r = S * 0.437
    d.ellipse([S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r], outline=(150, 168, 140), width=int(S * 0.0025))
    book(img)
    final = img.resize((1080, 1080), Image.LANCZOS)
    final.save(OUT / "storybook_avatar.png", optimize=True)
    # preview: as the apps show it, in a circle, at several sizes
    sheet = Image.new("RGB", (1080 + 360 + 60, 1080), (255, 255, 255))
    sheet.paste(final, (0, 0))
    y = 40
    for size in (200, 110, 56):
        a = final.resize((size, size), Image.LANCZOS)
        m = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(m).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
        sheet.paste(a, (1120, y), m.resize((size, size), Image.LANCZOS))
        y += size + 40
    sheet.save(OUT / "avatar_preview.png")
    print("wrote", OUT / "storybook_avatar.png")


if __name__ == "__main__":
    main()
