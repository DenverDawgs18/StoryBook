"""Paint the website's watercolour landscapes procedurally.

Each plate is built back to front like a real one: a wet-in-wet sky, then ridges of hills
that get darker and greener as they come nearer, tree lines dropped along those ridges,
and the odd building, river or moon. Lights are lifted out to the white of the paper.
Every layer goes through the same glaze as tools/paint.py, so edges dry dark and the
pigment granulates in the paper's tooth.

    python tools/landscape.py            # writes site/assets/land/*.webp
    python tools/landscape.py hero wood  # just those
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paint import GREENS, bloom, fbm, glaze  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "site" / "assets" / "land"

PIG = dict(GREENS)
PIG.update({
    "indigo": (44, 74, 80),
    "slate": (96, 112, 118),
    "mist": (178, 196, 184),
    "straw": (206, 180, 112),
    "rose": (182, 118, 102),
    "umber": (110, 84, 60),
    "night": (26, 60, 52),
    "ember": (214, 120, 52),
})


# ---------------------------------------------------------------- primitives
def noise1d(w, rng, octaves=5, base=3.0, persistence=0.5):
    out = np.zeros(w)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = int(base * 2 ** o) + 2
        pts = rng.random(cells + 2)
        out += np.interp(np.linspace(0, cells, w), np.arange(cells + 2), pts) * amp
        total += amp
        amp *= persistence
    out /= total
    return out - out.mean()


class Plate:
    def __init__(self, w, h, seed):
        self.w, self.h = w, h
        self.rng = np.random.default_rng(seed)
        self.yy, self.xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.u, self.v = self.xx / w, self.yy / h
        self.layers = []  # [density, colour, strength]

    # each add_* returns the mask it painted, so later features can sit on it
    def add(self, mask, color, k=0.8, blur=2.0, blooms=0, wet=1.0, occlude=0.0):
        """Lay a glaze. occlude>0 first blots out what is behind, so solid things read as solid."""
        if occlude:
            self.lift(mask, occlude)
        d = glaze(np.clip(mask, 0, 1), self.rng, blur)
        if blooms:
            d = bloom(self.h, self.w, self.rng, d, blooms)
        self.layers.append([d * wet, PIG[color] if isinstance(color, str) else color, k])
        return mask

    def lift(self, mask, amount=1.0):
        """Blot paint off everything laid so far (lights, moon, snow, window glow)."""
        m = ndimage.gaussian_filter(np.clip(mask, 0, 1), 1.5) * amount
        for L in self.layers:
            L[0] = L[0] * (1 - m)

    def sky(self, top, bottom, k=0.55, dark_at_top=True, blooms=0):
        n = fbm(self.h, self.w, self.rng, 5, 2.5)
        g = (1 - self.v) if dark_at_top else self.v
        self.add(np.clip(g * 1.1 + (n - 0.5) * 0.5, 0, 1) * 0.9, top, k, blur=6, blooms=0)
        if blooms:  # a single soft back-run, not a cauliflower
            self.layers[-1][0] = bloom(self.h, self.w, self.rng, self.layers[-1][0], 1) * 0.5 + self.layers[-1][0] * 0.5
        self.add(np.clip((self.v - 0.25) * 1.4 + (n - 0.5) * 0.4, 0, 1) * 0.6, bottom, k * 0.6, blur=8)

    def ridge(self, y0, amp, color, k=0.8, rough=1.0, base=2.5, octaves=5, blooms=0):
        line = y0 + amp * noise1d(self.w, self.rng, octaves, base) * 2 * rough
        mask = np.clip((self.v - line[None, :]) * self.h / 3.0, 0, 1)
        self.add(mask, color, k, blooms=blooms, occlude=0.92)
        return line

    def conifers(self, line, color, n, height=(0.06, 0.12), width=0.35, k=0.85, x_range=(0, 1), dense=False):
        """A tree line: tall spiky firs standing on a ridge line (list of y per x)."""
        mask = np.zeros((self.h, self.w), np.float32)
        xs = np.sort(self.rng.uniform(*x_range, n)) if not dense else np.linspace(*x_range, n) + self.rng.normal(0, 0.004, n)
        for xc in xs:
            xi = int(np.clip(xc * self.w, 0, self.w - 1))
            base = line[xi] + 0.01
            hgt = self.rng.uniform(*height)
            top = base - hgt
            half = hgt * width * self.h / self.w
            x0, x1 = int((xc - half * 1.2) * self.w), int((xc + half * 1.2) * self.w) + 1
            y0, y1 = int(top * self.h) - 2, int(base * self.h) + 2
            x0, x1, y0, y1 = max(x0, 0), min(x1, self.w), max(y0, 0), min(y1, self.h)
            if x1 <= x0 or y1 <= y0:
                continue
            u = self.u[y0:y1, x0:x1]
            v = self.v[y0:y1, x0:x1]
            t = np.clip((v - top) / hgt, 0, 1)  # 0 at tip, 1 at base
            # ragged boughs: the edge saw-tooths as it widens
            saw = 0.75 + 0.25 * np.abs(np.sin(t * self.rng.uniform(16, 26) + xc * 50))
            edge = half * t * saw
            inside = np.clip((edge - np.abs(u - xc)) * self.w / 1.5, 0, 1) * (v >= top) * (v <= base)
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], inside)
        return self.add(mask, color, k, blur=1.2, occlude=0.9)

    def round_trees(self, line, color, n, size=(0.03, 0.07), k=0.8, x_range=(0, 1)):
        """Deciduous trees: clumps of overlapping blobs on short trunks."""
        mask = np.zeros((self.h, self.w), np.float32)
        noise = fbm(self.h, self.w, self.rng, 4, 12)
        for xc in self.rng.uniform(*x_range, n):
            xi = int(np.clip(xc * self.w, 0, self.w - 1))
            r = self.rng.uniform(*size)
            cy = line[xi] - r * 1.6
            for _ in range(5):
                bx = xc + self.rng.normal(0, r * 0.45) * self.h / self.w
                by = cy + self.rng.normal(0, r * 0.35)
                br = r * self.rng.uniform(0.55, 0.85)
                d = np.sqrt(((self.u - bx) * self.w / self.h) ** 2 + (self.v - by) ** 2) / br
                mask = np.maximum(mask, np.clip((1 - d + (noise - 0.5) * 0.5) * 6, 0, 1))
            trunk = (np.abs(self.u - xc) * self.w < r * self.h * 0.08) & (self.v > cy) & (self.v < line[xi] + 0.01)
            mask = np.maximum(mask, trunk.astype(np.float32))
        return self.add(mask, color, k, blur=1.5, occlude=0.88)

    def poly(self, pts, color, k=0.9, blur=1.0):
        """Filled polygon in unit coordinates (buildings, roofs)."""
        from matplotlib.path import Path as MPath
        p = MPath(np.array(pts) * [self.w, self.h])
        inside = p.contains_points(np.c_[self.xx.ravel(), self.yy.ravel()]).reshape(self.h, self.w)
        return self.add(inside.astype(np.float32), color, k, blur=blur, occlude=0.92)

    def rect(self, x0, y0, x1, y1):
        return ((self.u >= x0) & (self.u <= x1) & (self.v >= y0) & (self.v <= y1)).astype(np.float32)

    def disc(self, cx, cy, r, soft=1.0):
        d = np.sqrt(((self.u - cx) * self.w / self.h) ** 2 + (self.v - cy) ** 2)
        return np.clip((r - d) * self.h / soft, 0, 1)

    def glow(self, cx, cy, r, color, k=0.5):
        d = np.sqrt(((self.u - cx) * self.w / self.h) ** 2 + (self.v - cy) ** 2)
        return self.add(np.exp(-(d / r) ** 2) * 0.9, color, k, blur=4)

    def stars(self, n, below=0.45):
        m = np.zeros((self.h, self.w), np.float32)
        for _ in range(n):
            x, y = self.rng.integers(0, self.w), int(self.rng.uniform(0.02, below) * self.h)
            m[y, x] = 1
        self.lift(np.clip(ndimage.gaussian_filter(m, 1.1) * 14, 0, 1), 0.9)

    def water(self, y0, y1, color, k=0.6):
        band = np.clip((self.v - y0) * self.h / 3, 0, 1) * np.clip((y1 - self.v) * self.h / 3, 0, 1)
        self.add(band, color, k, blur=3)
        streak = fbm(self.h, self.w * 6, self.rng, 3, 40)[:, ::6]
        self.lift(band * np.clip((streak - 0.55) * 4, 0, 1), 0.8)

    def path(self, pts, width0, width1, amount=0.85):
        """A winding road lifted out of the fields (pts are centre points, near to far)."""
        pts = np.array(pts)
        ys = np.linspace(pts[0, 1], pts[-1, 1], 200)
        xs = np.interp(ys, pts[::-1, 1], pts[::-1, 0]) if pts[0, 1] > pts[-1, 1] else np.interp(ys, pts[:, 1], pts[:, 0])
        m = np.zeros((self.h, self.w), np.float32)
        for i, (x, y) in enumerate(zip(xs, ys)):
            t = i / (len(ys) - 1)
            r = (width0 * (1 - t) + width1 * t)
            m = np.maximum(m, self.disc(x, y, r, 2.0))
        self.lift(m, amount)
        self.add(m * 0.5, "straw", 0.35, blur=2)

    def save(self, name, quality=84, deckle=True):
        """Subtractive mix of every glaze onto white paper; the page shows through via multiply."""
        absorb = np.zeros((self.h, self.w, 3))
        for d, col, k in self.layers:
            absorb += np.clip(d, 0, 1)[..., None] * k * (1 - np.array(col) / 255.0)
        rgb = np.exp(-absorb * 2.2)
        if deckle:  # the wash stops short of the sheet in a soft, ragged edge
            e = np.minimum.reduce([self.u, 1 - self.u, self.v * self.h / self.w, (1 - self.v) * self.h / self.w])
            ragged = fbm(self.h, self.w, np.random.default_rng(5), 5, 6)
            a = np.clip((e - 0.012 + (ragged - 0.5) * 0.03) / 0.03, 0, 1)
            rgb = 1 - (1 - rgb) * a[..., None]
        img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        OUT.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img, "RGB").save(OUT / f"{name}.webp", "WEBP", quality=quality, method=6)
        print("painted", name, img.shape[1], "x", img.shape[0])


# ---------------------------------------------------------------- buildings
def cottage(p, x, y, s, color="umber", roof="forest", lit=True, snow=False):
    w = s * p.h / p.w * 0.62
    p.poly([(x - w, y), (x - w, y - s * 0.75), (x + w, y - s * 0.75), (x + w, y)], color, 0.85)
    p.poly([(x + w * 0.45, y - s * 1.0), (x + w * 0.45, y - s * 1.45), (x + w * 0.7, y - s * 1.45), (x + w * 0.7, y - s * 1.0)], roof, 0.9)
    rm = p.poly([(x - w * 1.3, y - s * 0.7), (x, y - s * 1.35), (x + w * 1.3, y - s * 0.7)], roof, 0.95)
    if snow:
        p.lift(rm * (p.v < y - s * 0.95), 0.85)
    if lit:
        win = p.rect(x - w * 0.55, y - s * 0.5, x - w * 0.15, y - s * 0.22)
        p.lift(win, 1.0)
        p.add(win, "ochre", 0.55, blur=1.2)
        p.glow(x - w * 0.35, y - s * 0.36, s * 0.5, "ochre", 0.18)


def castle(p, x, y, s, color="slate", roof="viridian"):
    w = s * p.h / p.w
    p.poly([(x - w * 1.6, y), (x - w * 1.6, y - s * 0.9), (x + w * 1.6, y - s * 0.9), (x + w * 1.6, y)], color, 0.8)
    for dx, th in [(-1.6, 1.7), (1.6, 1.5), (0, 2.3), (-0.7, 1.3), (0.8, 1.2)]:
        cx = x + dx * w
        tw = w * 0.32
        p.poly([(cx - tw, y - s * 0.5), (cx - tw, y - s * th), (cx + tw, y - s * th), (cx + tw, y - s * 0.5)], color, 0.85)
        p.poly([(cx - tw * 1.25, y - s * th), (cx, y - s * (th + 0.55)), (cx + tw * 1.25, y - s * th)], roof, 0.95)
        p.lift(p.rect(cx - tw * 0.18, y - s * (th - 0.25), cx + tw * 0.18, y - s * (th - 0.45)), 0.9)


def town(p, y, x0, x1, color="umber", roof="madder", rng=None, spire_at=None, lit=0.0):
    rng = rng or p.rng
    x = x0
    while x < x1:
        bw = rng.uniform(0.025, 0.05)
        bh = rng.uniform(0.06, 0.13)
        yb = y + rng.uniform(-0.005, 0.01)
        p.poly([(x, yb), (x, yb - bh), (x + bw, yb - bh), (x + bw, yb)], color, rng.uniform(0.6, 0.85))
        p.poly([(x - 0.004, yb - bh), (x + bw / 2, yb - bh - bw * 0.9 * p.w / p.h * 0.5), (x + bw + 0.004, yb - bh)], roof, 0.85)
        if lit and rng.random() < lit:
            wx, wy = x + bw * rng.uniform(0.25, 0.6), yb - bh * rng.uniform(0.3, 0.7)
            win = p.rect(wx, wy, wx + bw * 0.2, wy + bh * 0.12)
            p.lift(win, 1.0)
            p.add(win, "ochre", 0.6, blur=1)
        x += bw + rng.uniform(0.0, 0.01)
    if spire_at:
        sx = spire_at
        p.poly([(sx - 0.018, y), (sx - 0.018, y - 0.2), (sx + 0.018, y - 0.2), (sx + 0.018, y)], color, 0.85)
        p.poly([(sx - 0.024, y - 0.2), (sx, y - 0.36), (sx + 0.024, y - 0.2)], roof, 0.95)


def well(p, x, y, s):
    w = s * p.h / p.w
    p.poly([(x - w, y), (x - w, y - s * 0.45), (x + w, y - s * 0.45), (x + w, y)], "slate", 0.85)
    for dx in (-0.85, 0.85):
        p.poly([(x + dx * w - w * 0.08, y - s * 0.4), (x + dx * w - w * 0.08, y - s * 1.2), (x + dx * w + w * 0.08, y - s * 1.2), (x + dx * w + w * 0.08, y - s * 0.4)], "umber", 0.9)
    p.poly([(x - w * 1.25, y - s * 1.1), (x, y - s * 1.55), (x + w * 1.25, y - s * 1.1)], "forest", 0.9)


# ---------------------------------------------------------------- the plates
def hero():
    """The frontispiece: a long view over a river valley to blue hills, a road, a cottage."""
    p = Plate(2400, 1000, 11)
    p.sky("celadon", "straw", 0.45)
    p.lift(p.disc(0.78, 0.2, 0.09, 30) * 0.6)
    r1 = p.ridge(0.42, 0.06, "mist", 0.55, base=2, blooms=2)
    p.conifers(r1 + 0.01, "sage", 70, (0.02, 0.05), 0.4, 0.4)
    r2 = p.ridge(0.53, 0.05, "sage", 0.65, base=2.5)
    p.round_trees(r2, "moss", 26, (0.015, 0.03), 0.6, (0.0, 0.45))
    p.water(0.6, 0.66, "viridian", 0.45)
    r3 = p.ridge(0.66, 0.035, "moss", 0.75, base=3)
    p.conifers(r3, "viridian", 34, (0.08, 0.16), 0.33, 0.85, (0.62, 1.0))
    cottage(p, 0.36, float(r3[int(0.36 * p.w)]) + 0.02, 0.07, lit=False)
    p.path([(0.5, 1.02), (0.44, 0.86), (0.4, 0.75), (0.37, 0.69)], 0.06, 0.008)
    r4 = p.ridge(0.84, 0.05, "sap", 0.85, base=2)
    p.round_trees(r4, "forest", 7, (0.06, 0.11), 0.85, (0.0, 0.16))
    p.conifers(r4 + 0.02, "forest", 9, (0.18, 0.3), 0.3, 0.9, (0.88, 1.0))
    p.save("hero")


def cottage_night():
    """The Elves and the Shoemaker: a lit window, snow on the roof, a moon over the green."""
    p = Plate(1500, 1000, 21)
    p.sky("viridian", "sage", 0.6)
    p.lift(p.disc(0.74, 0.2, 0.07, 3), 1.0)
    p.glow(0.74, 0.2, 0.18, "mist", 0.12)
    p.stars(70)
    r1 = p.ridge(0.55, 0.05, "viridian", 0.7, base=2)
    p.conifers(r1, "night", 40, (0.04, 0.09), 0.38, 0.8)
    r2 = p.ridge(0.74, 0.04, "sap", 0.75, base=2)
    cottage(p, 0.4, float(r2[int(0.4 * p.w)]) + 0.03, 0.2, color="umber", roof="night", lit=True, snow=True)
    p.round_trees(r2, "forest", 4, (0.05, 0.09), 0.85, (0.72, 0.95))
    r3 = p.ridge(0.9, 0.02, "forest", 0.7)
    p.lift(np.clip((p.v - 0.88) * 8, 0, 1) * fbm(p.h, p.w, p.rng, 4, 8) * 0.6, 0.5)
    p.save("land_cottage")


def wood():
    """Little Red-Cap: a sunny ride through a beech wood, flowers, the path to grandmother's."""
    p = Plate(1500, 1000, 31)
    p.sky("straw", "celadon", 0.35, dark_at_top=False)
    r1 = p.ridge(0.45, 0.04, "sage", 0.6)
    p.round_trees(r1, "sage", 18, (0.04, 0.08), 0.55)
    r2 = p.ridge(0.6, 0.03, "moss", 0.65)
    p.round_trees(r2, "moss", 10, (0.07, 0.12), 0.7, (0, 0.35))
    p.round_trees(r2, "moss", 8, (0.07, 0.12), 0.7, (0.65, 1))
    p.path([(0.55, 1.02), (0.47, 0.84), (0.52, 0.7), (0.5, 0.62)], 0.09, 0.01)
    r3 = p.ridge(0.92, 0.03, "sap", 0.6)
    flowers = np.zeros((p.h, p.w), np.float32)
    for _ in range(140):
        x, y = p.rng.uniform(0, 1), p.rng.uniform(0.66, 0.98)
        if abs(x - 0.5) < 0.08:
            continue
        flowers = np.maximum(flowers, p.disc(x, y, p.rng.uniform(0.002, 0.005), 1.5))
    p.add(flowers * 0.7, "rose", 0.6, blur=0.8)
    p.round_trees(r3, "forest", 3, (0.12, 0.18), 0.85, (0.0, 0.12))
    p.round_trees(r3, "forest", 2, (0.12, 0.18), 0.85, (0.9, 1.0))
    p.save("land_wood")


def forest():
    """Hansel and Gretel: the deep fir forest, and far off a small bright cottage."""
    p = Plate(1500, 1000, 41)
    p.sky("sage", "celadon", 0.5)
    r0 = p.ridge(0.4, 0.03, "mist", 0.5)
    p.conifers(r0, "sage", 90, (0.06, 0.12), 0.35, 0.55, dense=True)
    r1 = p.ridge(0.6, 0.03, "sage", 0.6)
    p.conifers(r1, "viridian", 40, (0.15, 0.28), 0.3, 0.75)
    cottage(p, 0.56, float(r1[int(0.56 * p.w)]) + 0.02, 0.07, color="ochre", roof="rose", lit=True)
    p.path([(0.52, 1.02), (0.58, 0.82), (0.55, 0.66)], 0.05, 0.006, 0.7)
    r2 = p.ridge(0.88, 0.02, "sap", 0.7)
    p.conifers(r2, "forest", 8, (0.45, 0.7), 0.28, 0.9, (0.0, 0.25))
    p.conifers(r2, "forest", 7, (0.45, 0.7), 0.28, 0.9, (0.8, 1.0))
    crumbs = np.zeros((p.h, p.w), np.float32)
    for i in range(14):
        t = i / 13
        crumbs = np.maximum(crumbs, p.disc(0.52 + 0.06 * np.sin(t * 3), 0.98 - t * 0.28, 0.004, 1))
    p.lift(crumbs, 1.0)
    p.save("land_forest")


def hills_night():
    """Rumpelstiltskin: high hills at night, a hut, and a fire with someone dancing round it."""
    p = Plate(1500, 1000, 51)
    p.sky("viridian", "celadon", 0.6)
    p.stars(110, 0.5)
    r1 = p.ridge(0.42, 0.09, "slate", 0.6, base=2.2)
    r2 = p.ridge(0.58, 0.07, "viridian", 0.75, base=2)
    p.conifers(r2, "night", 30, (0.05, 0.1), 0.35, 0.85, (0.0, 0.45))
    x = 0.64
    y = float(r2[int(x * p.w)]) + 0.03
    p.glow(x, y - 0.02, 0.16, "ember", 0.35)
    fy = y - 0.04
    taper = np.where(p.v < fy, 1 + (fy - p.v) * 40, 1.0)  # a point at the top, round at the base
    flame = np.clip(1 - np.sqrt(((p.u - x) * p.w / p.h / 0.018 * taper) ** 2 + ((p.v - fy) / 0.035) ** 2), 0, 1)
    flame = np.clip(flame * 4, 0, 1)
    p.lift(flame, 1.0)
    p.add(flame, "ember", 0.7, blur=1.5)
    cottage(p, 0.75, y + 0.01, 0.07, roof="night", lit=False)
    r3 = p.ridge(0.82, 0.04, "forest", 0.8, base=2)
    p.conifers(r3, "night", 6, (0.25, 0.4), 0.3, 0.9, (0.0, 0.2))
    p.save("land_hills")


def spring():
    """The Frog-Prince: a cool spring under a lime tree, the palace on its hill beyond."""
    p = Plate(1500, 1000, 61)
    p.sky("celadon", "straw", 0.4)
    r1 = p.ridge(0.4, 0.05, "mist", 0.55)
    castle(p, 0.72, float(r1[int(0.72 * p.w)]) + 0.01, 0.07, color="sage", roof="viridian")
    r2 = p.ridge(0.6, 0.03, "sage", 0.65)
    p.round_trees(r2, "moss", 12, (0.03, 0.05), 0.65)
    ell = np.sqrt(((p.u - 0.42) * p.w / p.h / 0.26) ** 2 + ((p.v - 0.81) / 0.055) ** 2)
    pool = np.clip((1 - ell) * 12 + (fbm(p.h, p.w, p.rng, 4, 8) - 0.5) * 1.5, 0, 1)
    r3 = p.ridge(0.74, 0.02, "moss", 0.7)
    p.add(pool, "viridian", 0.85, blur=3, occlude=0.9)
    p.lift(pool * np.clip((fbm(p.h, p.w * 5, p.rng, 3, 30)[:, ::5] - 0.6) * 4, 0, 1), 0.8)
    p.lift(p.disc(0.47, 0.79, 0.02, 1), 0.8)
    p.add(p.disc(0.47, 0.79, 0.016, 1), "ochre", 0.9)  # the golden ball
    p.round_trees(r3, "forest", 1, (0.2, 0.24), 0.85, (0.12, 0.14))
    p.ridge(0.92, 0.02, "sap", 0.7)
    p.save("land_spring")


def town_day():
    """The Emperor's New Clothes: a walled capital in the sun, towers, flags, a long procession road."""
    p = Plate(1500, 1000, 71)
    p.sky("celadon", "straw", 0.4)
    r1 = p.ridge(0.45, 0.04, "mist", 0.5)
    town(p, 0.62, 0.08, 0.92, color="ochre", roof="madder", spire_at=0.5)
    castle(p, 0.25, 0.62, 0.08, color="straw", roof="viridian")
    r2 = p.ridge(0.66, 0.015, "moss", 0.7)
    p.path([(0.5, 1.02), (0.5, 0.8), (0.5, 0.66)], 0.12, 0.02)
    crowd = np.zeros((p.h, p.w), np.float32)
    for _ in range(160):
        side = p.rng.choice([-1, 1])
        t = p.rng.uniform(0, 1)
        y = 0.68 + t * 0.32
        x = 0.5 + side * (0.012 + 0.07 * t + p.rng.uniform(0.0, 0.03))
        crowd = np.maximum(crowd, p.disc(x, y, 0.004 + 0.012 * t, 1.2))
    p.add(crowd, "forest", 0.7, blur=1)
    p.save("land_town")


def castle_storm():
    """The Real Princess: a castle on a crag in driving rain, one window lit."""
    p = Plate(1500, 1000, 81)
    p.sky("sage", "slate", 0.6)
    rain = fbm(p.h, p.w * 8, p.rng, 2, 80)[:, ::8]
    rain = ndimage.shift(rain, (0, 0))
    streaks = np.clip((np.roll(rain, 0, 1) - 0.6) * 3, 0, 1)
    r1 = p.ridge(0.6, 0.12, "viridian", 0.75, base=1.5)
    x = 0.55
    castle(p, x, float(r1[int(x * p.w)]) + 0.03, 0.13, color="night", roof="indigo")
    win = p.rect(x - 0.006, float(r1[int(x * p.w)]) - 0.15, x + 0.006, float(r1[int(x * p.w)]) - 0.12)
    p.lift(win, 1.0)
    p.add(win, "ochre", 0.7)
    r2 = p.ridge(0.86, 0.03, "forest", 0.8)
    p.lift(ndimage.rotate(streaks, -12, reshape=False, order=1) * 0.35, 0.6)
    p.save("land_castle")


def snow_street():
    """The Little Match Girl: a snowy street on New Year's Eve, lit windows, a falling star."""
    p = Plate(1500, 1000, 91)
    p.sky("viridian", "sage", 0.55)
    p.stars(60, 0.35)
    star = np.zeros((p.h, p.w), np.float32)
    for i in range(60):
        t = i / 59
        star = np.maximum(star, p.disc(0.25 + t * 0.15, 0.1 + t * 0.12, 0.002 + 0.004 * t, 1) * (0.2 + 0.8 * t))
    p.lift(star, 1.0)
    town(p, 0.72, 0.0, 1.0, color="slate", roof="night", lit=0.55)
    snow = np.clip((p.v - 0.72) * 30, 0, 1)
    p.lift(snow, 0.9)
    p.add(snow * (0.2 + 0.4 * fbm(p.h, p.w, p.rng, 4, 4)), "mist", 0.35, blur=4)
    fl = np.zeros((p.h, p.w), np.float32)
    for _ in range(260):
        fl = np.maximum(fl, p.disc(p.rng.uniform(0, 1), p.rng.uniform(0, 0.95), p.rng.uniform(0.0015, 0.004), 1))
    p.lift(fl, 0.9)
    p.glow(0.18, 0.86, 0.05, "ember", 0.4)
    p.save("land_snow")


def abbey():
    """The Masque of the Red Death: a walled abbey on a dark hill, seven lit windows."""
    p = Plate(1500, 1000, 101)
    p.sky("forest", "madder", 0.5)
    r1 = p.ridge(0.6, 0.1, "forest", 0.8, base=1.6)
    castle(p, 0.5, float(r1[int(0.5 * p.w)]) + 0.04, 0.12, color="night", roof="night")
    for i in range(7):
        xw = 0.43 + i * 0.023
        yw = float(r1[int(0.5 * p.w)]) - 0.03
        win = p.rect(xw, yw, xw + 0.008, yw + 0.025)
        p.lift(win, 1)
        p.add(win, ["indigo", "madder", "viridian", "ochre", "mist", "rose", "night"][i], 0.9, blur=0.8)
    p.ridge(0.88, 0.03, "night", 0.85)
    p.save("land_abbey")


def rome():
    """The Sack of Rome: seven hills at night, temple columns, the city burning."""
    p = Plate(1500, 1000, 111)
    p.sky("forest", "ember", 0.5)
    p.glow(0.6, 0.62, 0.25, "ember", 0.35)
    r1 = p.ridge(0.58, 0.05, "umber", 0.7, base=2.5)
    for i in range(8):
        cx = 0.38 + i * 0.03
        p.poly([(cx, 0.6), (cx, 0.47), (cx + 0.012, 0.47), (cx + 0.012, 0.6)], "straw", 0.75, blur=0.8)
    p.poly([(0.37, 0.47), (0.5, 0.42), (0.63, 0.47)], "straw", 0.8)
    town(p, 0.66, 0.0, 1.0, color="umber", roof="madder")
    p.ridge(0.84, 0.04, "night", 0.85)
    p.save("land_rome")


def pigs(fallen=False):
    """The Three Little Pigs: a sunny down, three houses of straw, furze and brick, an apple tree.

    fallen=True paints the same scene after the wolf has blown the straw house in: every
    random draw is the same, the straw house is painted with an empty brush, and a heap of
    straw lies where it stood.
    """
    p = Plate(1500, 1000, 131)
    p.sky("celadon", "straw", 0.4)
    r1 = p.ridge(0.42, 0.05, "mist", 0.5, base=2)
    p.round_trees(r1, "sage", 10, (0.02, 0.04), 0.5)
    r2 = p.ridge(0.66, 0.025, "moss", 0.65, base=2)
    y = lambda x: float(r2[int(x * p.w)]) + 0.02
    if fallen:
        real_add = p.add
        p.add = lambda mask, *a, **k: real_add(mask * 0, *a, **{**k, "occlude": 0})
    cottage(p, 0.2, y(0.2), 0.1, color="straw", roof="ochre", lit=False)
    if fallen:
        p.add = real_add
    sticks = cottage(p, 0.45, y(0.45), 0.11, color="umber", roof="olive", lit=False)
    cottage(p, 0.72, y(0.72), 0.14, color="madder", roof="slate", lit=True)
    # courses of brick: thin lifted lines across the brick house's walls
    w = 0.14 * p.h / p.w * 0.62
    walls = p.rect(0.72 - w, y(0.72) - 0.14 * 0.75, 0.72 + w, y(0.72))
    p.lift(walls * (np.sin(p.v * p.h / 3.2) > 0.82), 0.35)
    p.path([(0.6, 1.02), (0.68, 0.84), (0.72, y(0.72) + 0.005)], 0.05, 0.01)
    r3 = p.ridge(0.9, 0.02, "sap", 0.7)
    p.round_trees(r3, "forest", 1, (0.16, 0.2), 0.85, (0.92, 0.93))
    apples = np.zeros((p.h, p.w), np.float32)
    for _ in range(18):
        apples = np.maximum(apples, p.disc(p.rng.normal(0.925, 0.03), p.rng.normal(0.62, 0.05), 0.007, 1))
    p.lift(apples, 0.9)
    p.add(apples, "madder", 0.85, blur=0.8)
    if fallen:
        yb = y(0.2)
        heap = np.clip((1 - np.sqrt(((p.u - 0.2) * p.w / p.h / 0.11) ** 2 + ((p.v - yb) / 0.035) ** 2)) * 6, 0, 1) * (p.v < yb + 0.004)
        heap = np.clip(heap + (fbm(p.h, p.w, p.rng, 4, 30) - 0.5) * heap * 1.2, 0, 1)
        p.add(heap, "straw", 0.9, blur=1.2, occlude=0.9)
        p.add(heap * np.clip((fbm(p.h, p.w * 6, p.rng, 3, 60)[:, ::6] - 0.5) * 3, 0, 1), "ochre", 0.7, blur=0.6)
        straws = np.zeros((p.h, p.w), np.float32)
        for _ in range(40):  # loose straws blown across the grass
            x0, y0 = p.rng.uniform(0.08, 0.45), p.rng.uniform(yb - 0.02, yb + 0.08)
            ang, L = p.rng.uniform(-0.4, 0.4), p.rng.uniform(0.01, 0.025)
            for t in np.linspace(0, 1, 12):
                straws = np.maximum(straws, p.disc(x0 + t * L * np.cos(ang), y0 + t * L * np.sin(ang), 0.0015, 1))
        p.add(straws, "ochre", 0.8, blur=0.5)
        p.save("land_pigs_fallen")
        return
    p.save("land_pigs")


PLATES = {"pigs": pigs, "pigs_fallen": lambda: pigs(fallen=True), "hero": hero, "cottage": cottage_night, "wood": wood, "forest": forest, "hills": hills_night,
          "spring": spring, "town": town_day, "castle": castle_storm, "snow": snow_street,
          "abbey": abbey, "rome": rome}

if __name__ == "__main__":
    for key in (sys.argv[1:] or PLATES):
        PLATES[key]()
