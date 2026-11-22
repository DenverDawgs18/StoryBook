"""Build one static, shareable page per episode: site/tales/<slug>.html.

    python tools/build_tale_pages.py          # after tools/build_catalog.py

Each page has its own title, description, link-preview card (site/assets/og/tales/<slug>.jpg),
structured data and the full text of the story, so search engines can index it and a link
shared on X, iMessage or Facebook shows that story's plate. The player is the same as
listen.html. It also rewrites site/sitemap.xml.

Cards use the site's fonts from .cache/fonts (fetched by tools/tiktok.py on first run).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BASE = "https://storybook-audio.fly.dev"
FONTS = ROOT / ".cache" / "fonts"
OG = SITE / "assets" / "og" / "tales"
OUT = SITE / "tales"
STATIC_PAGES = ["/", "/personal.html", "/studio.html"]


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def plate(art: str) -> Image.Image:
    if art.startswith("land_"):
        return Image.open(SITE / f"assets/land/{art}.webp").convert("RGB")
    paper = Image.open(SITE / "assets/paint/paper.png").convert("RGB")
    im = Image.open(SITE / f"assets/paint/{art}.png").convert("RGBA")
    W, H = 1200, 630
    bg = paper.resize((W, int(paper.height * W / paper.width))).crop((0, 0, W, H)) if paper.width < W * 3 else paper.crop((0, 0, W, H))
    if bg.size != (W, H):
        bg = bg.resize((W, H))
    r = 470 / im.height
    im = im.resize((int(im.width * r), 470), Image.LANCZOS)
    bg.paste(im, ((W - im.width) // 2, 10), im)
    return bg


def card(ep: dict, out: Path):
    W, H = 1200, 630
    im = plate(ep["art"])
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H)).convert("RGBA")
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    for i in range(250):
        d.line([(0, H - 250 + i), (W, H - 250 + i)], fill=(245, 240, 226, int(238 * min(1, i / 90))))
    im = Image.alpha_composite(im, band).convert("RGB")
    d = ImageDraw.Draw(im)
    title = ep["title"]
    size = 72
    while font("IMFellEnglish-normal-400.ttf", size).getlength(title) > W - 120 and size > 40:
        size -= 2
    d.text((60, H - 185), title, font=font("IMFellEnglish-normal-400.ttf", size), fill="#22312a")
    mins = round(ep["duration"] / 60)
    sub = f"{ep['author']} · {ep['voices']} voices · {mins} minutes · free to listen"
    d.text((62, H - 95), sub, font=font("IMFellEnglish-italic-400.ttf", 32), fill="#4b5c51")
    d.text((W - 60, 40), "StoryBook", font=font("IMFellEnglish-normal-400.ttf", 30), fill="#f5f0e2",
           anchor="ra", stroke_width=2, stroke_fill="#2c4334")
    im.save(out, quality=86, optimize=True)


def transcript(slug: str) -> str:
    t = json.loads((SITE / f"audio/{slug}.json").read_text())
    paras = []
    for p in t["paragraphs"]:
        text = " ".join(s["text"].strip() for s in p["segments"])
        if text:
            paras.append(f"<p>{html.escape(text)}</p>")
    return "\n".join(paras)


def page(ep: dict) -> str:
    e = {k: html.escape(str(v or ""), quote=True) for k, v in ep.items() if isinstance(v, (str, int, float)) or v is None}
    slug = ep["slug"]
    kind = "audio story for kids" if ep["shelf"] == "fairy" else "audio drama"
    mins = round(ep["duration"] / 60)
    title = f"{ep['title']}: a full-cast {kind} · StoryBook"
    desc = (f"{ep['blurb']} Listen free: {mins} minutes, {ep['voices']} voices, "
            f"with sound effects and music made for this story.")
    url = f"{BASE}/tales/{slug}.html"
    img = f"{BASE}/assets/og/tales/{slug}.jpg"
    ld = {
        "@context": "https://schema.org", "@type": "AudioObject", "name": ep["title"],
        "description": ep["blurb"], "contentUrl": f"{BASE}/{ep['audio']}", "encodingFormat": "audio/mpeg",
        "duration": f"PT{int(ep['duration'] // 60)}M{int(ep['duration'] % 60)}S", "thumbnailUrl": img,
        "isAccessibleForFree": True, "inLanguage": "en", "url": url,
        "author": {"@type": "Person", "name": ep["author"]},
        "publisher": {"@type": "Organization", "name": "StoryBook", "url": BASE},
    }
    if ep.get("year"):
        ld["dateCreated"] = str(ep["year"])
    eye = "" if ep["art"].startswith("land_") else " eye"
    art = f"assets/land/{ep['art']}.webp" if ep["art"].startswith("land_") else f"assets/paint/{ep['art']}.png"
    T, D = html.escape(title, quote=True), html.escape(desc, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="/">
<title>{T}</title>
<meta name="description" content="{D}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="music.song">
<meta property="og:site_name" content="StoryBook">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(ep['title'], quote=True)} · StoryBook">
<meta property="og:description" content="{D}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:audio" content="{BASE}/{ep['audio']}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(ep['title'], quote=True)} · StoryBook">
<meta name="twitter:description" content="{D}">
<meta name="twitter:image" content="{img}">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="css/style.css">
<script src="js/analytics.js" defer></script>
<style>.text {{ max-width: 40rem; margin: 0 auto; }} .text summary {{ cursor: pointer; font-family: var(--caps); letter-spacing: .06em; color: var(--moss); }} .text p {{ margin: .9em 0; }}</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <filter id="rough"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="4"/><feDisplacementMap in="SourceGraphic" scale="5"/></filter>
</svg>
<div class="book">
<header class="running-head">
  <a class="wordmark" href="./">StoryBook</a>
  <nav class="nav" aria-label="Main">
    <a href="./">Listen</a><a href="./#tales" aria-current="page">Library</a><a href="personal.html">For your child</a><a href="studio.html">Studio</a><a href="./#craft">How it's made</a>
  </nav>
</header>
<aside class="offerbar" aria-label="Made for you">
  <a href="personal.html?utm_source=tale&amp;utm_content={slug}" data-track="cta_click" data-track-cta="tale_personal" data-track-story="{slug}"><b>A fairy tale starring your child</b> <span class="ob-p">· <span data-price="personal">$6</span></span> <span class="ob-go">Free preview →</span></a>
  <a href="studio.html?utm_source=tale&amp;utm_content={slug}" data-track="cta_click" data-track-cta="tale_studio" data-track-story="{slug}"><b>Your own pages as an audiobook</b> <span class="ob-p">· from <span data-price="studio-from">$9</span></span> <span class="ob-go">Upload →</span></a>
</aside>
<section class="spread featured" id="root">
  <div class="page verso">
    <figure class="plate">
      <div class="sheet{eye}" id="sheet"><img id="art" src="{art}" alt="A watercolour plate for {e['title']}"></div>
      <figcaption><b>Plate</b><span id="cap">{e['caption'] or e['title']}</span></figcaption>
    </figure>
  </div>
  <div class="page recto">
    <p class="running" id="mood">{e['mood']}</p>
    <h2 id="title">{e['title']}</h2>
    <p class="byline" id="byline">{e['author']}{(' · ' + e['year']) if e['year'] else ''}</p>
    <p class="blurb dropcap" id="blurb">{e['blurb']}</p>
    <div id="player"></div>
    <p class="folio"><a href="./#tales">← back to the contents</a></p>
  </div>
</section>
<section class="section text">
  <details>
    <summary>Read the whole story</summary>
{transcript(slug)}
  </details>
</section>
<footer class="colophon">
  <p class="finis">Finis.</p>
  <p>Text from <a href="https://www.gutenberg.org">Project Gutenberg</a>. Every voice is a custom blend, and every sound is synthesised.</p>
</footer>
</div>
<script type="module">
import {{ mountPlayer, loadCatalog }} from "./js/player.js";
const cat = await loadCatalog();
const ep = cat.episodes.find((e) => e.slug === {json.dumps(slug)});
const root = document.getElementById("root");
if (ep) mountPlayer(document.getElementById("player"), ep, {{ onplay: () => root.classList.add("playing"), onpause: () => root.classList.remove("playing") }});
</script>
<script>
fetch("/api/config").then((r) => r.json()).then((c) => {{
  const set = (k, v) => v && document.querySelectorAll(`[data-price="${{k}}"]`).forEach((el) => (el.textContent = v));
  set("personal", c.pricing?.personal?.price); set("studio-from", c.pricing?.studio?.[0]?.price);
}}).catch(() => {{}});
</script>
</body>
</html>
"""


def main():
    eps = json.loads((SITE / "audio/catalog.json").read_text())["episodes"]
    OUT.mkdir(exist_ok=True)
    OG.mkdir(parents=True, exist_ok=True)
    for ep in eps:
        (OUT / f"{ep['slug']}.html").write_text(page(ep))
        card(ep, OG / f"{ep['slug']}.jpg")
    urls = STATIC_PAGES + [f"/tales/{ep['slug']}.html" for ep in eps]
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{BASE}{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    print(f"{len(eps)} tale pages, cards and sitemap written")


if __name__ == "__main__":
    main()
