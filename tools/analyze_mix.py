"""Draw a loudness timeline + spectrogram of a rendered episode, with speech spans on top.

    python tools/analyze_mix.py site/audio/tell_tale_heart.mp3 out.png
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import signal


def main(mp3, out):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp3, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    sr, hop = 16000, 8000
    r = np.sqrt(np.mean(x[: len(x) // hop * hop].reshape(-1, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(r)
    t = json.loads(Path(mp3).with_suffix(".json").read_text())
    W, H = 1600, 700
    im = Image.new("RGB", (W, H), (250, 248, 240))
    d = ImageDraw.Draw(im)
    N = len(db)
    f, _, S = signal.spectrogram(x, sr, nperseg=1024, noverlap=512)
    S = np.clip((10 * np.log10(S + 1e-12) + 100) / 70, 0, 1)[f < 6000]
    im.paste(Image.fromarray((255 * (1 - S[::-1])).astype(np.uint8)).resize((W, 300)).convert("RGB"), (0, 380))
    for i in range(N - 1):
        d.line([(i * W / N, 350 - (db[i] + 60) * 5), ((i + 1) * W / N, 350 - (db[i + 1] + 60) * 5)], fill=(40, 90, 70))
    palette = [(200, 120, 60), (60, 60, 180), (180, 40, 40), (40, 140, 40), (140, 40, 140)]
    names = list(t["cast"])
    for p in t["paragraphs"]:
        for s in p["segments"]:
            c = palette[names.index(s["speaker"]) % len(palette)] if s["speaker"] in names else (0, 0, 0)
            d.rectangle([s["start"] / (N / 2) * W, 5, s["end"] / (N / 2) * W, 15], fill=c)
    for k in range(0, int(N / 2), 60):
        d.text((k / (N / 2) * W + 2, 20), f"{k // 60}m", fill=(0, 0, 0))
    for y in (-20, -30, -40, -50):
        d.line([(0, 350 - (y + 60) * 5), (W, 350 - (y + 60) * 5)], fill=(200, 200, 200))
        d.text((2, 350 - (y + 60) * 5), str(y), fill=(120, 120, 120))
    im.save(out)


if __name__ == "__main__":
    main(*sys.argv[1:])
