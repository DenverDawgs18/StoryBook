"""Collect rendered episodes into site/audio/catalog.json for the website.

    python tools/build_catalog.py
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "site" / "audio"


def main():
    eps = []
    for story in sorted((ROOT / "scripts").glob("*.story")):
        slug = story.stem
        timings = AUDIO / f"{slug}.json"
        if not (AUDIO / f"{slug}.mp3").exists() or not timings.exists():
            continue
        meta = yaml.safe_load(story.read_text().split("---", 2)[1])
        t = json.loads(timings.read_text())
        labels = meta.get("labels", {})
        eps.append({
            "slug": slug,
            "title": meta.get("title"),
            "author": meta.get("author"),
            "year": meta.get("year"),
            "blurb": " ".join(str(meta.get("blurb", "")).split()),
            "mood": meta.get("mood", ""),
            "caption": meta.get("caption", ""),
            "art": meta.get("art", "blob2"),
            "featured": bool(meta.get("featured")),
            "order": meta.get("order", 50),
            "duration": t["duration"],
            "audio": f"audio/{slug}.mp3",
            "timings": f"audio/{slug}.json",
            "voices": len({v["voice"] for v in t["cast"].values()}),
            "castLabels": {k: {"label": v} for k, v in labels.items()},
        })
    eps.sort(key=lambda e: (not e["featured"], e["order"], e["title"]))
    (AUDIO / "catalog.json").write_text(json.dumps({"episodes": eps}, indent=1, ensure_ascii=False))
    print(f"catalog: {len(eps)} episode(s)")


if __name__ == "__main__":
    main()
