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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from storybook import director
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


app.mount("/media/jobs", StaticFiles(directory=JOBS_DIR), name="jobs")
app.mount("/", StaticFiles(directory=SITE, html=True), name="site")
