"""First-party analytics: page views and a few named events, a login-protected dashboard, and a daily digest.

Nothing leaves the server. Each event is one JSON line in DATA/events/YYYY-MM-DD.jsonl:

    {"at": "...Z", "ev": "pageview", "path": "/listen.html", "story": "little_red_cap",
     "ref": "tiktok.com", "utm_source": "tiktok", "utm_content": "little_red_cap-1120", "v": "3f9a…", "dev": "mobile"}

`v` is a visitor id that changes every day (a hash of IP + browser + the date + a server secret), so a day's
unique visitors can be counted without following anyone from one day to the next. No IP addresses, names or
emails are stored here; sign-ups stay in signups.jsonl.

Routes:
    POST /api/track            the pages' beacon (see site/js/analytics.js)
    GET  /admin                the dashboard (log in with STORYBOOK_ADMIN_TOKEN)
    POST /admin/login, GET /admin/logout
    GET  /api/admin/digest     yesterday's numbers as JSON, for the daily digest (token or login cookie)
"""
from __future__ import annotations

import hashlib
import hmac
import html as H
import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

router = APIRouter()

EVENTS_DIR: Path = Path(".")
SIGNUPS: Callable[[], list[dict]] = lambda: []
INTEREST: Callable[[dict], str] = lambda r: ""
_LOCK = threading.Lock()

COOKIE = "sb_admin"
COOKIE_DAYS = 30
# Named events the pages already send (window.sbTrack) that are worth keeping, and the props kept for each.
EVENTS = {"pageview", "story_play", "story_complete", "library_open", "cta_click",
          "preview_requested", "preview_ready", "signup_submitted", "subscribe"}
PROPS = ("story", "kind", "cta", "tale", "source")
BOT_RX = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|headless|lighthouse|curl|wget|python|httpx|go-http", re.I)
MOBILE_RX = re.compile(r"Mobi|Android|iPhone|iPad", re.I)
SLUG_RX = re.compile(r"[^a-z0-9_.\-]")
PER_MINUTE = 60
_RECENT: dict[str, list[float]] = {}
PAGES = {"/": "Home", "/index.html": "Home", "/listen.html": "Listen", "/personal.html": "Personalised tale",
         "/studio.html": "Studio waitlist"}
# Referrer hosts folded into one name, so "m.facebook.com" and "l.facebook.com" count together.
REF_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "facebook": "Facebook", "google": "Google", "bing": "Bing",
             "duckduckgo": "DuckDuckGo", "youtube": "YouTube", "reddit": "Reddit", "pinterest": "Pinterest",
             "t.co": "X / Twitter", "twitter": "X / Twitter", "x.com": "X / Twitter", "linktr": "Linktree"}


def init(data: Path, signups: Callable[[], list[dict]], interest: Callable[[dict], str]) -> None:
    global EVENTS_DIR, SIGNUPS, INTEREST
    EVENTS_DIR = data / "events"
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    SIGNUPS, INTEREST = signups, interest


# ------------------------------------------------------------------ auth
def _token() -> str:
    return os.environ.get("STORYBOOK_ADMIN_TOKEN", "")


def _cookie_value(token: str) -> str:
    return hmac.new(token.encode(), b"storybook-admin-session", hashlib.sha256).hexdigest()


def authed(request: Request) -> bool:
    """True for the owner: a login cookie, `Authorization: Bearer <token>`, or ?token=."""
    token = _token()
    if not token:
        return False
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    if given and hmac.compare_digest(token, given):
        return True
    return hmac.compare_digest(_cookie_value(token), request.cookies.get(COOKIE, ""))


def _salt() -> str:
    return _token() or os.environ.get("FLY_APP_NAME", "storybook")


# ------------------------------------------------------------------ recording
def _clean(v, n=80) -> str:
    return SLUG_RX.sub("", str(v or "").lower())[:n]


def _ref_name(ref: str) -> str:
    host = (urlparse(ref).hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    for k, name in REF_NAMES.items():
        if k in host:
            return name
    return host[:60]


@router.post("/api/track")
async def track(request: Request):
    ua = request.headers.get("user-agent", "")
    if not ua or BOT_RX.search(ua):
        return Response(status_code=204)
    try:
        raw = await request.body()
        if len(raw) > 4000:
            return Response(status_code=204)
        d = json.loads(raw or b"{}")
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        return Response(status_code=204)
    ev = d.get("ev")
    if ev not in EVENTS:
        return Response(status_code=204)
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "?")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    v = hashlib.sha256(f"{_salt()}|{day}|{ip}|{ua}".encode()).hexdigest()[:16]
    now = time.time()
    with _LOCK:
        times = [t for t in _RECENT.get(v, []) if now - t < 60]
        if len(times) >= PER_MINUTE:
            return Response(status_code=204)
        _RECENT[v] = times + [now]
        if len(_RECENT) > 5000:  # forget yesterday's visitors
            for k in [k for k, ts in _RECENT.items() if not ts or now - ts[-1] > 120]:
                _RECENT.pop(k, None)
    path = str(d.get("path") or "/")[:120]
    path = path if path in PAGES else ("/other" if path.startswith("/") else "/")
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ev": ev, "path": path, "v": v,
           "dev": "mobile" if MOBILE_RX.search(ua) else "desktop"}
    props = d.get("props") if isinstance(d.get("props"), dict) else {}
    for k in PROPS:
        if props.get(k):
            row[k] = _clean(props[k], 60)
    if ev == "pageview":
        ref = str(d.get("ref") or "")[:300]
        own = request.headers.get("host", "").split(":")[0]
        if ref and (urlparse(ref).hostname or "") != own:
            row["ref"] = _ref_name(ref)
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
            if d.get(k):
                row[k] = _clean(d[k])
        if path == "/listen.html" and d.get("story"):
            row["story"] = _clean(d["story"], 60)
    with _LOCK, (EVENTS_DIR / f"{day}.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    return Response(status_code=204)


# ------------------------------------------------------------------ reading
def _events(start: datetime, end: datetime) -> list[dict]:
    """Events with start <= at < end (UTC)."""
    out, d = [], start.date()
    lo, hi = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    while d <= end.date():
        p = EVENTS_DIR / f"{d.isoformat()}.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if lo <= r.get("at", "") < hi:
                    out.append(r)
        d += timedelta(days=1)
    return out


def _source(r: dict) -> str:
    """Where a visit came from: its utm_source if tagged, otherwise the referring site, otherwise direct."""
    if r.get("utm_source"):
        s = r["utm_source"]
        return REF_NAMES.get(s, s.capitalize() if s.isalpha() else s)
    return r.get("ref") or "Direct / unknown"


def summarize(start: datetime, end: datetime) -> dict:
    evs = _events(start, end)
    pv = [r for r in evs if r["ev"] == "pageview"]
    visitors = {(r["at"][:10], r["v"]) for r in pv}
    # The first page view of each visitor-day carries where they came from.
    first: dict[tuple, dict] = {}
    for r in sorted(pv, key=lambda r: r["at"]):
        first.setdefault((r["at"][:10], r["v"]), r)
    lo, hi = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    signups = [s for s in SIGNUPS() if lo <= s.get("at", "") < hi]
    days = defaultdict(lambda: {"visitors": set(), "pageviews": 0, "signups": 0, "plays": 0})
    d = start.date()
    while d < end.date() or (d == end.date() and end.time() != datetime.min.time()):
        days[d.isoformat()]
        d += timedelta(days=1)
    for r in pv:
        days[r["at"][:10]]["visitors"].add(r["v"])
        days[r["at"][:10]]["pageviews"] += 1
    for r in evs:
        if r["ev"] == "story_play":
            days[r["at"][:10]]["plays"] += 1
    for s in signups:
        days[s["at"][:10]]["signups"] += 1
    plays = Counter(r.get("story", "?") for r in evs if r["ev"] == "story_play")
    completes = Counter(r.get("story", "?") for r in evs if r["ev"] == "story_complete")
    utm = Counter(" · ".join(x for x in (r.get("utm_campaign"), r.get("utm_content")) if x)
                  for r in first.values() if r.get("utm_source") == "tiktok" and (r.get("utm_content") or r.get("utm_campaign")))
    return {
        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "visitors": len(visitors), "pageviews": len(pv), "signups": len(signups),
        "signups_by_source": dict(Counter(s.get("source", "?") for s in signups)),
        "story_plays": sum(plays.values()), "story_completes": sum(completes.values()),
        "previews_requested": sum(1 for r in evs if r["ev"] == "preview_requested"),
        "mobile_share": round(sum(1 for r in first.values() if r.get("dev") == "mobile") / len(first), 2) if first else 0,
        "pages": Counter(PAGES.get(r["path"], r["path"]) for r in pv).most_common(10),
        "sources": Counter(_source(r) for r in first.values()).most_common(10),
        "tiktok_posts": utm.most_common(10),
        "stories_played": plays.most_common(10),
        "stories_completed": completes.most_common(10),
        "stories_viewed": Counter(r["story"] for r in pv if r.get("story")).most_common(10),
        "ctas": Counter(r.get("cta", "?") for r in evs if r["ev"] == "cta_click").most_common(10),
        "daily": [{"day": k, "visitors": len(v["visitors"]), "pageviews": v["pageviews"], "signups": v["signups"],
                   "plays": v["plays"]} for k, v in sorted(days.items())],
        "recent_signups": [{"at": s["at"], "source": s.get("source", ""), "email": s.get("email", ""),
                            "interest": INTEREST(s), "note": s.get("note", "")}
                           for s in sorted(signups, key=lambda s: s["at"], reverse=True)[:25]],
    }


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/api/admin/digest")
def digest(request: Request):
    """Yesterday (UTC) next to the day before and the last 7 days, plus all-time sign-ups."""
    if not authed(request):
        raise HTTPException(404)
    today = _midnight(datetime.now(timezone.utc))
    y = today - timedelta(days=1)
    out = {"date": y.date().isoformat(),
           "yesterday": summarize(y, today),
           "day_before": {k: v for k, v in summarize(y - timedelta(days=1), y).items()
                          if k in ("visitors", "pageviews", "signups", "story_plays")},
           "last_7_days": summarize(today - timedelta(days=7), today),
           "today_so_far": {k: v for k, v in summarize(today, datetime.now(timezone.utc)).items()
                            if k in ("visitors", "pageviews", "signups", "story_plays")},
           "all_time_signups": len(SIGNUPS()),
           "all_time_unique_emails": len({s.get("email", "").lower() for s in SIGNUPS()})}
    out["last_7_days"].pop("recent_signups", None)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ pages
_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{title} · StoryBook</title><link rel="stylesheet" href="/css/style.css">
<style>
.kpis{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.8rem;margin:1.2rem 0 1.6rem;width:100%}}
@media (max-width:52rem){{.kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
.kpi{{border:1px solid var(--rule);padding:.7rem .8rem;background:rgba(255,255,255,.35)}}
.kpi b{{display:block;font-family:var(--display);font-size:2rem;font-weight:400;line-height:1.1}}
.kpi span{{font-family:var(--caps);letter-spacing:.05em;color:var(--ink-soft);font-size:.9rem}}
.kpi small{{display:block;color:var(--ink-faint);font-size:.8rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:1.6rem 2rem}}
h3{{font-family:var(--caps);font-weight:400;letter-spacing:.06em;color:var(--moss);margin:1.4rem 0 .5rem;font-size:1.05rem}}
.rank{{list-style:none;margin:0;padding:0;font-size:.95rem}}
.rank li{{display:grid;grid-template-columns:1fr auto;gap:.6rem;padding:.28rem 0;border-bottom:1px solid var(--rule);position:relative}}
.rank li i{{position:absolute;left:0;bottom:-1px;height:3px;background:var(--viridian);border-radius:0 2px 2px 0}}
.rank .n{{font-variant-numeric:tabular-nums;color:var(--ink-soft)}}
.empty{{color:var(--ink-faint);font-style:italic;font-size:.95rem}}
.range a{{margin-right:.8rem}} .range a.on{{font-weight:500;text-decoration:none;color:var(--ink)}}
.chart svg{{width:100%;height:auto;display:block}} .chart rect.vbar{{fill:var(--viridian)}} .chart rect.vbar:hover{{fill:var(--ochre)}}
.chart text{{font:11px var(--serif);fill:var(--ink-faint)}} .chart line{{stroke:var(--rule)}}
.chart rect.sig{{fill:var(--madder)}}
table{{width:100%;border-collapse:collapse;font-size:.92rem}} th,td{{text-align:left;padding:.4rem .45rem;border-bottom:1px solid var(--rule);vertical-align:top}}
th{{font-family:var(--caps);letter-spacing:.06em;color:var(--moss);font-weight:400}} .wrap{{overflow-x:auto}}
form.login{{max-width:20rem;margin:2rem auto}} form.login input{{width:100%;padding:.6rem;font:inherit;margin:.5rem 0 1rem;border:1px solid var(--rule);background:#fffdf6}}
.err{{color:var(--madder)}}
</style></head><body><div class="book"><header class="running-head"><a class="wordmark" href="/">StoryBook</a><span class="note">{note}</span></header>
<section class="section">"""
_FOOT = "</section></div></body></html>"
_NOSTORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}


def _login_page(error: str = "") -> HTMLResponse:
    err = f'<p class="err">{H.escape(error)}</p>' if error else ""
    body = f"""<form class="login" method="post" action="/admin/login"><h2>Owner log in</h2>{err}
<label for="pw">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" autofocus required>
<button class="btn" type="submit">Log in</button></form>"""
    return HTMLResponse(_HEAD.format(title="Log in", note="owner") + body + _FOOT, headers=_NOSTORE,
                        status_code=401 if error else 200)


@router.post("/admin/login")
def login(request: Request, password: str = Form("")):
    token = _token()
    if not token:
        return _login_page("The site has no admin password yet. Set the STORYBOOK_ADMIN_TOKEN secret on Fly.")
    if not hmac.compare_digest(token, password.strip()):
        time.sleep(1)  # slow down guessing
        return _login_page("That password isn't right.")
    r = RedirectResponse("/admin", status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    r.set_cookie(COOKIE, _cookie_value(token), max_age=COOKIE_DAYS * 86400, httponly=True, secure=secure, samesite="lax")
    return r


@router.get("/admin/logout")
def logout():
    r = RedirectResponse("/admin", status_code=303)
    r.delete_cookie(COOKIE)
    return r


def _rank(items: list, empty: str = "Nothing yet.") -> str:
    if not items:
        return f'<p class="empty">{H.escape(empty)}</p>'
    top = max(n for _, n in items) or 1
    return '<ol class="rank">' + "".join(
        f'<li><span>{H.escape(str(k).replace("_", " "))}</span><span class="n">{n:,}</span><i style="width:{n / top * 100:.0f}%"></i></li>'
        for k, n in items) + "</ol>"


def _chart(daily: list[dict]) -> str:
    """Daily visitors as bars, with a dot marking days that had sign-ups."""
    if not daily:
        return ""
    W, Ht, pad, top_pad = 720, 170, 28, 14
    top = max([d["visitors"] for d in daily] + [1])
    n = len(daily)
    slot = (W - pad) / n
    bw = max(2.0, slot - 2)
    parts = [f'<line x1="{pad}" x2="{W}" y1="{Ht - 20}" y2="{Ht - 20}"/>',
             f'<text x="0" y="{top_pad + 4}">{top:,}</text>', f'<text x="0" y="{Ht - 22}">0</text>']
    step = max(1, n // 7)
    for i, d in enumerate(daily):
        h = (Ht - 20 - top_pad) * d["visitors"] / top
        x = pad + i * slot
        tip = (f'{d["day"]}: {d["visitors"]} visitor{"s" * (d["visitors"] != 1)}, {d["pageviews"]} page views, '
               f'{d["plays"]} story plays, {d["signups"]} sign-up{"s" * (d["signups"] != 1)}')
        parts.append(f'<g><title>{H.escape(tip)}</title><rect x="{x:.1f}" y="{top_pad}" width="{slot:.1f}" height="{Ht - 20 - top_pad}" fill="transparent"/>'
                     f'<rect class="vbar" x="{x:.1f}" y="{Ht - 20 - h:.1f}" width="{bw:.1f}" height="{max(h, 0):.1f}" rx="2"/>'
                     + (f'<rect class="sig" x="{x + bw / 2 - 3:.1f}" y="{Ht - 20 - h - 9:.1f}" width="6" height="6" rx="3"/>' if d["signups"] else "")
                     + "</g>")
        if i % step == 0:
            parts.append(f'<text x="{x:.1f}" y="{Ht - 5}">{d["day"][5:]}</text>')
    return (f'<div class="chart" role="img" aria-label="Daily visitors"><svg viewBox="0 0 {W} {Ht}">{"".join(parts)}</svg></div>'
            '<p class="note" style="font-size:.85rem">Bars are unique visitors per day (UTC). A red dot marks a day with sign-ups. Hover a bar for that day\'s numbers.</p>')


@router.get("/admin")
def dashboard(request: Request, days: int = 7):
    if not _token():
        return _login_page("The site has no admin password yet. Set the STORYBOOK_ADMIN_TOKEN secret on Fly.")
    if not authed(request):
        return _login_page()
    days = days if days in (1, 7, 30, 90) else 7
    now = datetime.now(timezone.utc)
    start = _midnight(now) - timedelta(days=days - 1)
    s = summarize(start, now)
    prev = summarize(start - timedelta(days=days), start)
    all_signups = SIGNUPS()

    def delta(k):
        a, b = s[k], prev[k]
        if not b:
            return "new" if a else ""
        pct = round((a - b) / b * 100)
        return f'{"+" if pct >= 0 else ""}{pct}% vs previous {days}d'

    conv = f'{s["signups"] / s["visitors"] * 100:.1f}%' if s["visitors"] else "–"
    rng = " ".join(f'<a class="{"on" if d == days else ""}" href="/admin?days={d}">{"Today" if d == 1 else f"{d} days"}</a>'
                   for d in (1, 7, 30, 90))
    kpis = "".join(f'<div class="kpi"><span>{lab}</span><b>{val}</b><small>{sub}</small></div>' for lab, val, sub in [
        ("Visitors", f'{s["visitors"]:,}', delta("visitors")),
        ("Page views", f'{s["pageviews"]:,}', delta("pageviews")),
        ("Story plays", f'{s["story_plays"]:,}', f'{s["story_completes"]:,} listened to the end'),
        ("Sign-ups", f'{s["signups"]:,}', f'{len(all_signups):,} all time'),
        ("Visitor → sign-up", conv, f'{round(s["mobile_share"] * 100)}% of visits on mobile'),
    ])
    sig_rows = "".join(
        f'<tr><td>{H.escape(r["at"][:16].replace("T", " "))}</td><td>{H.escape(r["source"])}</td>'
        f'<td><a href="mailto:{H.escape(r["email"])}">{H.escape(r["email"])}</a></td><td>{H.escape(r["interest"])}</td></tr>'
        for r in s["recent_signups"]) or '<tr><td colspan="4" class="empty">No sign-ups in this period.</td></tr>'
    by_src = " · ".join(f"{k}: {v}" for k, v in sorted(s["signups_by_source"].items()))
    body = f"""<h2>How the site is doing</h2>
<p class="range note">{rng} <span style="float:right"><a href="/admin/signups">all sign-ups</a> · <a href="/admin/logout">log out</a></span></p>
<div class="kpis">{kpis}</div>
{_chart(s["daily"])}
<div class="stats">
<div><h3>Where visitors came from</h3>{_rank(s["sources"], "No visits yet.")}</div>
<div><h3>TikTok posts (utm_content)</h3>{_rank(s["tiktok_posts"], "No tagged TikTok visits yet.")}</div>
<div><h3>Pages</h3>{_rank(s["pages"], "No page views yet.")}</div>
<div><h3>Stories played</h3>{_rank(s["stories_played"], "No plays yet.")}</div>
<div><h3>Stories opened</h3>{_rank(s["stories_viewed"], "No story pages opened yet.")}</div>
<div><h3>Buttons clicked</h3>{_rank(s["ctas"], "No clicks yet.")}</div>
</div>
<h3>Sign-ups in this period{f" ({H.escape(by_src)})" if by_src else ""}</h3>
<div class="wrap"><table><thead><tr><th>When (UTC)</th><th>From</th><th>Email</th><th>Interest</th></tr></thead><tbody>{sig_rows}</tbody></table></div>
<p class="note" style="font-size:.85rem;margin-top:1.4rem">Counted on this server, with no cookies on visitors. A visitor is one browser on one day.
Visitors with Do Not Track on, and bots, aren't counted. {s["previews_requested"]:,} personalised previews were requested in this period.</p>"""
    return HTMLResponse(_HEAD.format(title="Analytics", note="analytics") + body + _FOOT, headers=_NOSTORE)
