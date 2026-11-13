"""StoryBook web app: the listening room (static site) + the Studio API.

    python -m storybook serve            # http://127.0.0.1:8000
"""
from __future__ import annotations

import io
import os
import json
import queue
import re
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

import csv
import hashlib
import hmac

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from storybook import director, personalize
from storybook.render import render
from storybook.script import parse
from storybook.voices import VOICE_CATALOG, Character, speak

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = Path(os.environ.get("STORYBOOK_DATA", ROOT / "data"))
JOBS_DIR = DATA / "jobs"
SAMPLES = DATA / "voice_samples"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES.mkdir(parents=True, exist_ok=True)

MAX_CHARS = 150_000  # ~ 25k words, ~ 3 hours of audio

app = FastAPI(title="StoryBook")

JOBS: dict[str, dict] = {}
WORK: "queue.Queue[str]" = queue.Queue()
LOCK = threading.Lock()


# ------------------------------------------------------------------ helpers
def extract_text(name: str, raw: bytes) -> str:
    n = name.lower()
    if n.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(raw))
        return "\n\n".join(p.text for p in d.paragraphs)
    if n.endswith(".epub"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        parts = []
        for f in sorted(z.namelist()):
            if f.endswith((".xhtml", ".html", ".htm")):
                h = z.read(f).decode("utf-8", "ignore")
                h = re.sub(r"(?is)<(script|style|head).*?</\1>", "", h)
                h = re.sub(r"(?i)</(p|div|h\d)>|<br\s*/?>", "\n\n", h)
                h = re.sub(r"<[^>]+>", "", h)
                parts.append(h)
        import html
        return html.unescape("\n\n".join(parts))
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Could not read that file as text.")


def _public(info: dict) -> dict:
    return {k: v for k, v in info.items() if not k.startswith("_")}


# ------------------------------------------------------------------ worker
def _worker():
    while True:
        jid = WORK.get()
        job = JOBS[jid]
        job["status"] = "running"
        job["started"] = time.time()

        def prog(frac, msg):
            job["progress"] = round(min(frac, 1.0) * 0.92, 3)
            job["message"] = msg

        try:
            sc = parse(job.pop("_source"))
            out = JOBS_DIR / jid
            info = render(sc, out, progress=prog)
            job.update(status="done", progress=1.0, message="Ready",
                       audio=f"/media/jobs/{jid}.mp3", duration=info["duration"],
                       timings=f"/media/jobs/{jid}.json")
        except Exception as e:  # surface the failure to the browser
            traceback.print_exc()
            job.update(status="error", message=str(e)[:300])
        finally:
            job["finished"] = time.time()
            (JOBS_DIR / f"{jid}.state.json").write_text(json.dumps({k: v for k, v in job.items() if not k.startswith("_")}))


threading.Thread(target=_worker, daemon=True).start()


# ------------------------------------------------------------------ API
@app.get("/api/config")
def public_config():
    """Settings the pages need. The PostHog project key is a public client key by design."""
    return {"posthog_key": os.environ.get("POSTHOG_KEY", ""),
            "posthog_host": os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")}


@app.get("/api/voices")
def voices():
    return [{"id": k, "description": v} for k, v in VOICE_CATALOG.items()]


@app.get("/api/voices/{vid}/sample")
def voice_sample(vid: str):
    if vid not in VOICE_CATALOG:
        raise HTTPException(404)
    p = SAMPLES / f"{vid}.wav"
    if not p.exists():
        import soundfile as sf
        line = "It was a dark and quiet evening, and the fire had burned down to embers, when the knock came at the door."
        a, _ = speak(line, Character.from_dict("s", {"voice": vid, "speed": 0.95}))
        sf.write(p, a, 48000, subtype="PCM_16")
    return FileResponse(p, media_type="audio/wav")


@app.post("/api/analyze")
async def analyze(text: str = Form(""), file: UploadFile | None = File(None)):
    if file is not None and file.filename:
        text = extract_text(file.filename, await file.read())
    text = text.strip()
    if len(text) < 40:
        raise HTTPException(400, "Please paste or upload at least a few sentences.")
    if len(text) > MAX_CHARS:
        raise HTTPException(413, f"That manuscript is {len(text):,} characters; the Studio takes up to {MAX_CHARS:,} at a time.")
    info = director.analyze(text)
    out = _public(info)
    out["text"] = text  # echo back the extracted text so the browser can submit it
    first = next((p for p in info["_paras"] if len(p) > 40), "")
    out["preview"] = first[:400]
    return out


class JobRequest(BaseModel):
    text: str
    title: str = "Untitled"
    author: str = "Anonymous"
    narrator: str = "bm_lewis"
    cast: dict[str, str] = {}
    mood: str | None = None
    effects: bool = True
    speed: float = 0.95


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if not req.text.strip():
        raise HTTPException(400, "No manuscript text.")
    if len(req.text) > MAX_CHARS:
        raise HTTPException(413, "Manuscript too long.")
    if req.narrator not in VOICE_CATALOG:
        raise HTTPException(400, "Unknown narrator voice.")
    if req.text.lstrip().startswith("---") and "\ncast:" in req.text[:4000]:
        source = req.text  # already a .story production script
    else:
        source = director.build_script(req.text, req.title[:120] or "Untitled", req.author[:120] or "Anonymous",
                                       req.narrator, {k: v for k, v in req.cast.items() if v in VOICE_CATALOG},
                                       req.mood, req.effects, max(0.7, min(req.speed, 1.3)))
    jid = uuid.uuid4().hex[:12]
    (JOBS_DIR / f"{jid}.story").write_text(source)
    with LOCK:
        ahead = sum(1 for j in JOBS.values() if j["status"] in ("queued", "running"))
        JOBS[jid] = {"id": jid, "status": "queued", "progress": 0.0, "message": f"Queued ({ahead} ahead)",
                     "title": req.title, "author": req.author, "created": time.time(), "_source": source}
    WORK.put(jid)
    return {"id": jid}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    job = JOBS.get(jid)
    if job is None:
        p = JOBS_DIR / f"{jid}.state.json"
        if p.exists():
            return json.loads(p.read_text())
        raise HTTPException(404)
    return {k: v for k, v in job.items() if not k.startswith("_")}


@app.get("/api/jobs/{jid}/script")
def job_script(jid: str):
    if not re.fullmatch(r"[0-9a-f]{12}", jid):
        raise HTTPException(404)
    p = JOBS_DIR / f"{jid}.story"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/plain", filename=f"{jid}.story")


# ------------------------------------------------------------------ personalised tales
SIGNUPS = DATA / "signups.jsonl"
PREVIEW_CACHE: dict[str, str] = {}  # request fingerprint -> job id
RECENT: dict[str, list[float]] = {}  # visitor -> preview request times
PREVIEWS_PER_HOUR = 6
MAX_QUEUED_PREVIEWS = 8
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def _visitor(request: Request) -> str:
    ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "?")
    return hashlib.sha256(ip.encode()).hexdigest()[:16]  # never stored raw


def _enqueue(source: str, title: str, kind: str) -> str:
    jid = uuid.uuid4().hex[:12]
    (JOBS_DIR / f"{jid}.story").write_text(source)
    with LOCK:
        ahead = sum(1 for j in JOBS.values() if j["status"] in ("queued", "running"))
        JOBS[jid] = {"id": jid, "status": "queued", "progress": 0.0, "message": f"Queued ({ahead} ahead)",
                     "title": title, "author": "", "kind": kind, "created": time.time(), "_source": source}
    WORK.put(jid)
    return jid


class PersonalRequest(BaseModel):
    tale: str
    name: str
    pronouns: str = "she"
    voice: str | None = None
    gift_from: str = ""
    say_as: str = ""


@app.get("/api/personal/tales")
def personal_tales():
    return personalize.tales_for_web()


@app.post("/api/personal/preview")
def personal_preview(req: PersonalRequest, request: Request):
    try:
        src = personalize.personalize(req.tale, req.name, req.pronouns, req.voice, req.gift_from, req.say_as, preview=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    key = hashlib.sha256(src.encode()).hexdigest()
    cached = PREVIEW_CACHE.get(key)
    if cached and JOBS.get(cached, {}).get("status") in ("queued", "running", "done"):
        return {"id": cached}
    who, now = _visitor(request), time.time()
    times = [t for t in RECENT.get(who, []) if now - t < 3600]
    if len(times) >= PREVIEWS_PER_HOUR:
        raise HTTPException(429, "That's a lot of previews! Please try again in a little while.")
    with LOCK:
        waiting = sum(1 for j in JOBS.values() if j.get("kind") == "preview" and j["status"] in ("queued", "running"))
    if waiting >= MAX_QUEUED_PREVIEWS:
        raise HTTPException(503, "The storytellers are busy right now. Please try again in a few minutes.")
    RECENT[who] = times + [now]
    jid = _enqueue(src, f"{personalize.TALES[req.tale]['title']}, for {personalize.clean_name(req.name)}", "preview")
    PREVIEW_CACHE[key] = jid
    return {"id": jid}


class SignupRequest(PersonalRequest):
    email: str
    preview_id: str = ""
    website: str = ""  # honeypot: people never see this field, bots fill it in


@app.post("/api/personal/signup")
def personal_signup(req: SignupRequest, request: Request):
    if req.website:
        return {"ok": True}  # quietly drop bots
    email = req.email.strip()
    if not EMAIL_RX.match(email) or len(email) > 254:
        raise HTTPException(400, "Please check the email address.")
    try:
        name = personalize.clean_name(req.name)
        say_as = personalize.clean_name(req.say_as) if req.say_as else ""
        gift_from = personalize.clean_from(req.gift_from)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if req.tale not in personalize.TALES or req.pronouns not in personalize.PRONOUNS:
        raise HTTPException(400, "Please choose a tale and pronouns.")
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "email": email, "name": name, "say_as": say_as,
           "pronouns": req.pronouns, "voice": req.voice or "", "tale": req.tale, "gift_from": gift_from,
           "preview_id": req.preview_id if re.fullmatch(r"[0-9a-f]{12}", req.preview_id or "") else "",
           "visitor": _visitor(request)}
    with LOCK, SIGNUPS.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True}


@app.get("/api/admin/signups")
def admin_signups(request: Request, format: str = "csv"):
    """Download sign-ups. Needs STORYBOOK_ADMIN_TOKEN, sent as `Authorization: Bearer <token>` or ?token=."""
    token = os.environ.get("STORYBOOK_ADMIN_TOKEN", "")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    if not token or not hmac.compare_digest(token, given):
        raise HTTPException(404)
    rows = [json.loads(l) for l in SIGNUPS.read_text().splitlines() if l.strip()] if SIGNUPS.exists() else []
    if format == "json":
        return rows
    buf = io.StringIO()
    cols = ["at", "email", "name", "say_as", "pronouns", "voice", "tale", "gift_from", "preview_id", "visitor"]
    w = csv.DictWriter(buf, cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=storybook-signups.csv"})


app.mount("/media/jobs", StaticFiles(directory=JOBS_DIR), name="jobs")
app.mount("/", StaticFiles(directory=SITE, html=True), name="site")
