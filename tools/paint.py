"""Paint the website's watercolour textures procedurally.

Each wash is built like a real one: several translucent glazes of a noise-distorted
shape, pigment pooling at the drying edge, granulation in the paper's tooth, and the
odd back-run bloom. Output is RGBA PNG meant to be laid on paper with multiply blending.

    python tools/paint.py            # writes site/assets/paint/*.png
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

OUT = Path(__file__).resolve().parent.parent / "site" / "assets" / "paint"

GREENS = {
    "sap": (74, 110, 62),
    "moss": (104, 128, 74),
    "sage": (138, 160, 126),
    "viridian": (46, 106, 88),
    "olive": (150, 146, 82),
    "forest": (38, 66, 50),
    "celadon": (160, 190, 160),
    "ochre": (190, 140, 70),
    "madder": (150, 62, 58),
}


def fbm(h, w, rng, octaves=6, base=4.0, persistence=0.55):
    """Fractal value noise in [0,1]."""
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = int(base * 2 ** o)
        g = rng.random((cells + 2, int(cells * w / h) + 2))
        layer = ndimage.zoom(g, (h / cells, h / cells), order=3)[:h, :w]
        if layer.shape != (h, w):
            layer = np.pad(layer, ((0, h - layer.shape[0]), (0, w - layer.shape[1])), mode="edge")
        out += layer * amp
        total += amp
        amp *= persistence
    out /= total
    return (out - out.min()) / (np.ptp(out) + 1e-9)


def blob_mask(h, w, rng, cx=0.5, cy=0.5, rx=0.38, ry=0.32, rough=0.35, elong=0.0):
    yy, xx = np.mgrid[0:h, 0:w]
    x = (xx / w - cx) / rx
    y = (yy / h - cy) / ry
    d = np.sqrt(x ** 2 + y ** 2)
    n = fbm(h, w, rng, 6, 3)
    d = d + (n - 0.5) * rough * 2
    return np.clip((1.0 - d) * 6, 0, 1)


def glaze(mask, rng, blur=2.0):
    """A single layer of paint: soft body, dark drying edge, granulation."""
    h, w = mask.shape
    m = ndimage.gaussian_filter(mask, blur)
    inner = ndimage.gaussian_filter(m, 18)
    edge = np.clip(m - inner, 0, 1) * 2.2  # pigment pools at the boundary
    body = m * (0.35 + 0.25 * fbm(h, w, rng, 5, 6))
    gran = fbm(h, w, rng, 3, 90, 0.7)
    density = (body + edge * m) * (0.75 + 0.5 * gran)
    return np.clip(density, 0, 1)


def bloom(h, w, rng, density, n=3):
    """Back-runs: cauliflower blooms where wet paint crept into a drying wash."""
    for _ in range(n):
        cx, cy = rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.75)
        r = rng.uniform(0.05, 0.14)
        bm = blob_mask(h, w, rng, cx, cy, r, r * w / h, 0.55)
        ring = np.clip(ndimage.gaussian_filter(bm, 3) - ndimage.gaussian_filter(bm, 10), 0, 1)
        density = density * (1 - 0.55 * ndimage.gaussian_filter(bm, 4)) + ring * 0.9 * (density > 0.05)
    return density


def to_rgba(density, color, strength=0.85):
    h, w = density.shape
    a = np.clip(density * strength, 0, 1)
    rgb = np.zeros((h, w, 3))
    rgb[:] = color
    return np.dstack([rgb, a * 255]).astype(np.uint8)


def composite(layers):
    """Multiply-style accumulation of several RGBA pigment layers into one RGBA."""
    h, w = layers[0][0].shape
    absorb = np.zeros((h, w, 3))
    for dens, col, k in layers:
        c = np.array(col) / 255.0
        absorb += dens[..., None] * k * (1 - c)  # subtractive pigment
    trans = np.exp(-absorb * 2.2)
    alpha = 1 - trans.mean(axis=2)
    alpha = np.clip(alpha * 1.25, 0, 1)
    # let the paint feather out before the canvas edge, never a hard crop
    yy, xx = np.mgrid[0:h, 0:w]
    e = np.minimum.reduce([xx / w, (w - 1 - xx) / w, yy / h, (h - 1 - yy) / h])
    feather = fbm(h, w, np.random.default_rng(h * w % 997), 4, 5)
    alpha *= np.clip((e - 0.01 + (feather - 0.5) * 0.06) / 0.07, 0, 1)
    rgb = np.where(alpha[..., None] > 1e-4, (trans - (1 - alpha[..., None])) / (alpha[..., None] + 1e-6), 1)
    rgb = np.clip(rgb, 0, 1)
    return np.dstack([rgb * 255, alpha * 255]).astype(np.uint8)


def wash(name, w, h, colors, seed, shapes=None, blooms=2, strength=1.0):
    rng = np.random.default_rng(seed)
    layers = []
    shapes = shapes or [(0.5, 0.5, 0.42, 0.38)] * len(colors)
    for col, (cx, cy, rx, ry) in zip(colors, shapes):
        m = blob_mask(h, w, rng, cx + rng.normal(0, 0.03), cy + rng.normal(0, 0.03), rx, ry, rng.uniform(0.25, 0.45))
        d = glaze(m, rng)
        d = bloom(h, w, rng, d, blooms)
        layers.append((d, GREENS[col], rng.uniform(0.6, 0.9) * strength))
    img = composite(layers)
    Image.fromarray(img, "RGBA").save(OUT / f"{name}.png", optimize=True)
    print("painted", name)


def stroke(name, w, h, color, seed):
    """A loaded flat brush dragged left to right: dry-brush breaks at the tail."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    t = xx / w
    centre = 0.5 + 0.08 * np.sin(t * 3 + rng.uniform(0, 3))
    thick = 0.34 * (1 - 0.35 * t) * (0.9 + 0.2 * fbm(h, w, rng, 3, 2))
    d = np.abs(yy / h - centre) / thick
    n = fbm(h, w, rng, 6, 4)
    m = np.clip((1 - d - (n - 0.5) * 0.5) * 5, 0, 1)
    m *= np.clip((t - 0.01) * 30, 0, 1) * np.clip((0.99 - t) * 12, 0, 1)
    streak = fbm(h, w * 4, rng, 4, 60)[:, ::4]
    dry = np.clip((streak - t * 0.55) * 3, 0, 1)
    m = m * (0.4 + 0.6 * dry)
    dens = glaze(m, rng, 1.2)
    img = composite([(dens, GREENS[color], 0.9)])
    Image.fromarray(img, "RGBA").save(OUT / f"{name}.png", optimize=True)
    print("painted", name)


def paper(name="paper", size=512, seed=3):
    """Cold-pressed paper tooth, tileable (wrap-around noise)."""
    rng = np.random.default_rng(seed)
    g = rng.random((size, size))
    tooth = ndimage.gaussian_filter(g, 1.2, mode="wrap")
    tooth2 = ndimage.gaussian_filter(rng.random((size, size)), 6, mode="wrap")
    v = (tooth - tooth.mean()) * 3.5 + (tooth2 - tooth2.mean()) * 6
    fibres = np.zeros((size, size))
    for _ in range(120):
        x, y = rng.integers(0, size, 2)
        L = rng.integers(10, 40)
        ang = rng.uniform(0, np.pi)
        for i in range(L):
            fibres[int(y + i * np.sin(ang)) % size, int(x + i * np.cos(ang)) % size] += 1
    fibres = ndimage.gaussian_filter(fibres, 0.6, mode="wrap")
    v = v - fibres * 0.25
    lum = np.clip(0.5 + v * 0.5, 0, 1)
    # neutral grey texture to multiply over the paper colour
    shade = (249 + (lum - 0.5) * 18).clip(0, 255)
    img = np.dstack([shade, shade, shade]).astype(np.uint8)
    Image.fromarray(img, "RGB").save(OUT / f"{name}.png", optimize=True)
    print("painted", name)


def eye(name="eye", w=1400, h=900, seed=7):
    """The old man's eye: an almond of shadow, a pale filmed iris, a dark pupil."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    x = (xx - w / 2) / (w * 0.40)
    y = (yy - h / 2) / (h * 0.30)
    n = fbm(h, w, rng, 6, 3)
    # almond: intersection of two offset circles
    lid = np.clip((1 - (np.abs(y) + x ** 2 * 0.95) - (n - 0.5) * 0.25) * 5, 0, 1)
    socket = blob_mask(h, w, rng, 0.5, 0.5, 0.47, 0.44, 0.4)
    r = np.sqrt(((xx - w / 2) / (h * 0.25)) ** 2 + ((yy - h / 2) / (h * 0.25)) ** 2)
    theta = np.arctan2(yy - h / 2, xx - w / 2)
    iris = np.clip((1 - r - (n - 0.5) * 0.45) * 5, 0, 1) * lid
    streak = 0.7 + 0.3 * np.sin(theta * 31 + fbm(h, w, rng, 4, 6) * 26) * fbm(h, w, rng, 3, 10)
    pupil = np.clip((0.3 - r + (n - 0.5) * 0.18) * 9, 0, 1)
    film = np.clip(np.exp(-((xx - w * 0.48) ** 2 + (yy - h * 0.46) ** 2) / (2 * (h * 0.16) ** 2)) * (0.6 + 0.6 * fbm(h, w, rng, 4, 5)), 0, 1)
    layers = [
        (glaze(socket, rng) * (1 - 0.85 * lid), GREENS["sage"], 0.7),
        (glaze(np.clip(socket - lid * 0.85, 0, 1), rng) * 1.1, GREENS["forest"], 0.8),
        (glaze(iris, rng, 1.5) * (0.55 + 0.45 * streak) * (1 - 0.55 * film), (120, 150, 160), 0.85),
        (glaze(np.clip(iris - pupil, 0, 1), rng) * np.clip((r - 0.55) * 2, 0, 1) * 0.7, GREENS["viridian"], 0.6),
        (glaze(pupil, rng, 1.0) * (1 - 0.35 * film), (30, 36, 40), 1.0),
    ]
    img = composite(layers)
    Image.fromarray(img, "RGBA").save(OUT / f"{name}.png", optimize=True)
    print("painted", name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paper()
    eye()
    wash("hero", 1600, 900, ["celadon", "sage", "moss", "viridian", "olive"], 11,
         [(0.30, 0.45, 0.42, 0.55), (0.68, 0.40, 0.40, 0.48), (0.50, 0.62, 0.38, 0.34),
          (0.80, 0.70, 0.22, 0.30), (0.18, 0.72, 0.20, 0.25)], blooms=3, strength=0.9)
    wash("featured", 1100, 1100, ["forest", "viridian", "madder"], 21,
         [(0.5, 0.5, 0.44, 0.44), (0.42, 0.55, 0.30, 0.32), (0.58, 0.46, 0.09, 0.09)], blooms=2)
    for i, (cols, seed) in enumerate([(["sage", "olive"], 31), (["viridian", "celadon"], 41),
                                       (["moss", "ochre"], 51), (["forest", "sage"], 61),
                                       (["celadon", "moss"], 71), (["olive", "viridian"], 81)]):
        wash(f"blob{i + 1}", 640, 640, cols, seed, [(0.5, 0.5, 0.4, 0.38), (0.55, 0.45, 0.3, 0.3)], blooms=2)
    stroke("stroke_green", 1200, 180, "moss", 91)
    stroke("stroke_dark", 1200, 180, "forest", 92)
    stroke("stroke_sage", 1200, 180, "sage", 93)
    wash("corner", 900, 700, ["sage", "celadon", "olive"], 101,
         [(0.2, 0.2, 0.5, 0.45), (0.35, 0.15, 0.35, 0.3), (0.1, 0.4, 0.25, 0.3)], blooms=1, strength=0.7)


if __name__ == "__main__":
    main()
