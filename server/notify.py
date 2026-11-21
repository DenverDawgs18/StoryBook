"""Tell the owner about each new sign-up.

Configured with environment variables (Fly secrets):

    NOTIFY_EMAIL_TO      where to send the notice (required to send anything)
    NOTIFY_EMAIL_FROM    the From address (default "StoryBook <onboarding@resend.dev>")
    RESEND_API_KEY       send through Resend's HTTP API, or
    SMTP_URL             send through any SMTP server, e.g.
                         smtps://you%40gmail.com:app-password@smtp.gmail.com:465

If none of these are set, or sending fails, the sign-up is written to the log instead.
Sending happens on a background thread, so a slow mail server never slows the visitor down.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import threading
import urllib.request
from email.message import EmailMessage
from urllib.parse import unquote, urlparse

log = logging.getLogger("storybook.notify")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False

LABELS = [("at", "When (UTC)"), ("source", "From"), ("email", "Email"), ("use", "Would make"), ("note", "Note"),
          ("name", "Child's name"), ("tale", "Tale"), ("gift_from", "Gift from")]


def _body(row: dict, interest: str = "") -> tuple[str, str]:
    subject = f"New StoryBook sign-up: {row.get('email', '?')} ({row.get('source', '?')})"
    lines = []
    for key, label in LABELS:
        val = interest if key == "use" and interest else row.get(key, "")
        if val:
            lines.append(f"{label}: {val}")
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if base:
        lines.append(f"\nAll sign-ups: {base}/admin/signups?token=<your admin token>")
    return subject, "\n".join(lines) + "\n"


def _send_resend(key: str, sender: str, to: str, subject: str, text: str) -> None:
    req = urllib.request.Request(
        "https://api.resend.com/emails", method="POST",
        data=json.dumps({"from": sender, "to": [a.strip() for a in to.split(",") if a.strip()],
                         "subject": subject, "text": text}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "storybook-notify/1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 300:
            raise RuntimeError(f"Resend answered {r.status}")


def _send_smtp(url: str, sender: str, to: str, subject: str, text: str) -> None:
    u = urlparse(url)
    secure = u.scheme == "smtps"
    port = u.port or (465 if secure else 587)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(text)
    ctx = ssl.create_default_context()
    if secure:
        s = smtplib.SMTP_SSL(u.hostname, port, timeout=15, context=ctx)
    else:
        s = smtplib.SMTP(u.hostname, port, timeout=15)
        s.starttls(context=ctx)
    with s:
        if u.username:
            s.login(unquote(u.username), unquote(u.password or ""))
        s.send_message(msg)


def _deliver(row: dict, interest: str) -> None:
    subject, text = _body(row, interest)
    to = os.environ.get("NOTIFY_EMAIL_TO", "").strip()
    sender = os.environ.get("NOTIFY_EMAIL_FROM", "").strip() or "StoryBook <onboarding@resend.dev>"
    resend, smtp = os.environ.get("RESEND_API_KEY", "").strip(), os.environ.get("SMTP_URL", "").strip()
    if to and (resend or smtp):
        try:
            if resend:
                _send_resend(resend, sender, to, subject, text)
            else:
                _send_smtp(smtp, sender, to, subject, text)
            log.info("sign-up notice sent for %s (%s)", row.get("email"), row.get("source"))
            return
        except Exception as e:  # never lose the notice: fall through to the log
            log.warning("could not email the sign-up notice (%s); logging it instead", str(e)[:200])
    log.info("%s | %s", subject, text.strip().replace("\n", " | "))


def signup(row: dict, interest: str = "") -> threading.Thread:
    """Send (or log) a notice about one sign-up without blocking the request."""
    t = threading.Thread(target=_deliver, args=(dict(row), interest), daemon=True)
    t.start()
    return t
