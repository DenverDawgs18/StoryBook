"""Paid recordings through Stripe Checkout.

Two things are for sale:

* **Studio**: a full-cast recording of the buyer's own manuscript, priced by its length in tiers.
* **A story for your child**: one of the personalised fairy tales, in full, at one fixed price.

Both keep their free previews. The buyer pays on Stripe's hosted Checkout page, comes back to
/order.html, and the recording is rendered once Stripe says the payment went through (from the
webhook, or by asking Stripe when the buyer lands back on the site, whichever happens first).

Configured with environment variables (Fly secrets):

    STRIPE_SECRET_KEY      sk_test_... or sk_live_...  (payments are off without it;
                           STRIPE_TEST_KEY or STRIPE_LIVE_KEY also work)
    STRIPE_WEBHOOK_SECRET  whsec_...  for /api/stripe/webhook (recommended, not required)
    PERSONAL_PRICE         dollars for a personalised story, default 6
    STUDIO_TIERS           "max_words:dollars,..." default "2000:9,7500:19,15000:29,25000:45";
                           the last tier also covers anything up to the Studio's length limit
    STRIPE_TAX_CODE        product tax code for Stripe Tax, default txcd_10401100 (downloaded audio)
    PUBLIC_URL             the site's address for Stripe's return links (else taken from the request)

The buy buttons always show. Without a key, checkout answers "opening shortly". With a test key
(sk_test_) checkout works only for the owner logged in at /admin (everyone else gets "opening
shortly"), so nobody gets a free recording with a test card. A live key opens it to everyone.
"""
from __future__ import annotations

import html as H
import json
import os
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import analytics

router = APIRouter()
ORDERS: Path = Path("orders")
LOCK = threading.Lock()
_render: Callable[[dict], str] | None = None   # order -> job id (set by the app)
_job_status: Callable[[str], dict | None] | None = None

DEFAULT_TIERS = "2000:9,7500:19,15000:29,25000:45"
TIER_NAMES = ["A short story", "A long story", "A novelette", "A novella"]
OID_RX = re.compile(r"^[0-9a-f]{24}$")
# Stripe Tax needs a product tax code on each line: "Digital Audio Works - Downloaded - Non Subscription -
# With Permanent Rights" (docs.stripe.com/tax/digital-products). Override with the STRIPE_TAX_CODE secret.
TAX_CODE = lambda: os.environ.get("STRIPE_TAX_CODE", "").strip() or "txcd_10401100"


# ------------------------------------------------------------------ prices
def personal_price_cents() -> int:
    return _cents(os.environ.get("PERSONAL_PRICE", "6"), 600)


def _cents(raw: str, default: int) -> int:
    try:
        v = round(float(str(raw).strip().lstrip("$")) * 100)
        return v if v >= 50 else default  # Stripe's minimum charge is 50 cents
    except ValueError:
        return default


def _parse_tiers(raw: str) -> list[dict]:
    tiers = []
    for part in raw.split(","):
        try:
            words, dollars = part.split(":")
            tiers.append({"max_words": int(words), "cents": _cents(dollars, 0)})
        except ValueError:
            continue
    return sorted((t for t in tiers if t["cents"]), key=lambda t: t["max_words"])


def studio_tiers() -> list[dict]:
    tiers = _parse_tiers(os.environ.get("STUDIO_TIERS", "")) or _parse_tiers(DEFAULT_TIERS)
    for i, t in enumerate(tiers):
        t["name"] = TIER_NAMES[i] if i < len(TIER_NAMES) else f"Up to {t['max_words']:,} words"
        t["min_words"] = tiers[i - 1]["max_words"] + 1 if i else 1
    return tiers


def studio_quote(words: int) -> dict:
    tiers = studio_tiers()
    tier = next((t for t in tiers if words <= t["max_words"]), tiers[-1])  # the cap on length is MAX_CHARS
    return {"words": words, "cents": tier["cents"], "tier": tier["name"], "price": _money(tier["cents"])}


def _money(cents: int) -> str:
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def pricing() -> dict:
    return {"personal": {"cents": personal_price_cents(), "price": _money(personal_price_cents())},
            "studio": [{**t, "price": _money(t["cents"])} for t in studio_tiers()]}


# ------------------------------------------------------------------ stripe
def _key() -> str:
    # STRIPE_SECRET_KEY wins; STRIPE_TEST_KEY / STRIPE_LIVE_KEY are accepted too. A publishable pk_ key never works here.
    for name in ("STRIPE_SECRET_KEY", "STRIPE_LIVE_KEY", "STRIPE_TEST_KEY"):
        k = os.environ.get(name, "").strip()
        if k.startswith(("sk_", "rk_")):
            return k
    return ""


def mode() -> str:
    k = _key()
    return "live" if k.startswith(("sk_live_", "rk_live_")) else "test" if k else "off"


def enabled_for(request: Request) -> bool:
    """Whether checkout takes an order from this visitor: everyone with a live key, only the
    owner (logged in at /admin) with a test key, so nobody gets a free recording with a test card.
    The Buy buttons show either way."""
    m = mode()
    return m == "live" or (m == "test" and analytics.authed(request))


def _stripe():
    import stripe
    stripe.api_key = _key()
    stripe.max_network_retries = 2
    return stripe


def _base(request: Request) -> str:
    url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if url:
        return url
    base = str(request.base_url).rstrip("/")
    return base.replace("http://", "https://", 1) if "fly.dev" in base else base


# ------------------------------------------------------------------ orders
def init(data: Path, render: Callable[[dict], str], job_status: Callable[[str], dict | None]) -> None:
    global ORDERS, _render, _job_status
    ORDERS = data / "orders"
    ORDERS.mkdir(parents=True, exist_ok=True)
    _render, _job_status = render, job_status
    # a restart (deploy, or the machine sleeping) loses the render queue: pick paid work back up
    for o in all_orders():
        if o["status"] == "paid" or (o["status"] == "rendering" and _needs_restart(o)):
            o["status"] = "paid"
            _start(o)


def _path(oid: str) -> Path:
    return ORDERS / f"{oid}.json"


def load(oid: str) -> dict | None:
    if not OID_RX.match(oid or ""):
        return None
    p = _path(oid)
    return json.loads(p.read_text()) if p.exists() else None


def save(o: dict) -> None:
    tmp = _path(o["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False))
    tmp.replace(_path(o["id"]))


def all_orders() -> list[dict]:
    out = []
    for p in ORDERS.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda o: o["created"], reverse=True)


def _needs_restart(o: dict) -> bool:
    st = _job_status(o.get("job_id", "")) if o.get("job_id") else None
    return st is None or st.get("status") not in ("queued", "running", "done")


def create_checkout(request: Request, kind: str, payload: dict, cents: int, title: str, summary: str,
                    cancel_path: str, words: int = 0) -> dict:
    if not enabled_for(request):
        raise HTTPException(503, "Checkout is opening shortly. Please try again in a little while.")
    oid = uuid.uuid4().hex[:24]
    base = _base(request)
    link = f"{base}/order.html?o={oid}"
    o = {"id": oid, "kind": kind, "status": "pending", "created": time.time(), "cents": cents, "currency": "usd",
         "title": title[:200], "summary": summary[:300], "words": words, "payload": payload, "mode": mode(),
         "session_id": "", "email": "", "job_id": "", "paid_at": None, "error": ""}
    stripe = _stripe()
    try:
        s = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"quantity": 1, "price_data": {
                "currency": "usd", "unit_amount": cents,
                "product_data": {"name": title[:250], "description": summary[:500] or title[:250],
                                 "tax_code": TAX_CODE()}}}],
            client_reference_id=oid, metadata={"order": oid, "kind": kind},
            payment_intent_data={"description": f"StoryBook: {title[:200]}. Listen and download at {link}",
                                 "metadata": {"order": oid}},
            allow_promotion_codes=True,
            success_url=f"{link}&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}{cancel_path}",
        )
    except Exception as e:  # a Stripe error, or no network
        raise HTTPException(502, f"Couldn't reach the payment page: {getattr(e, 'user_message', None) or e}"[:200])
    o["session_id"] = s.id
    with LOCK:
        save(o)
    return {"order": oid, "url": s.url}


def _mark_paid(oid: str, session: dict) -> dict | None:
    with LOCK:
        o = load(oid)
        if o is None:
            return None
        if o["status"] != "pending":
            return o
        if session.get("payment_status") not in ("paid", "no_payment_required"):
            return o
        o.update(status="paid", paid_at=time.time(), session_id=session.get("id") or o["session_id"],
                 email=((session.get("customer_details") or {}).get("email") or ""),
                 amount_paid=session.get("amount_total", o["cents"]))
        save(o)
    _start(o)
    return o


def _start(o: dict) -> None:
    try:
        jid = _render(o)
        o.update(status="rendering", job_id=jid, error="")
    except Exception as e:
        o.update(status="failed", error=str(e)[:300])
    with LOCK:
        save(o)


def _refresh(o: dict) -> dict:
    """Ask Stripe about an unpaid order, and fold the render's progress into a rendering one."""
    if o["status"] == "pending" and o.get("session_id") and mode() != "off":
        try:
            s = _stripe().checkout.Session.retrieve(o["session_id"])
            o = _mark_paid(o["id"], s.to_dict() if hasattr(s, "to_dict") else dict(s)) or o
        except Exception:
            pass
    if o["status"] == "rendering":
        st = _job_status(o["job_id"]) or {}
        if st.get("status") in ("done", "error"):
            with LOCK:
                o = load(o["id"]) or o
                o["status"] = "done" if st["status"] == "done" else "failed"
                o["error"] = "" if st["status"] == "done" else st.get("message", "")[:300]
                save(o)
    return o


@router.get("/api/orders/{oid}")
def order_status(oid: str):
    o = load(oid)
    if o is None:
        raise HTTPException(404)
    o = _refresh(o)
    out = {k: o[k] for k in ("id", "kind", "status", "title", "summary", "job_id")}
    out["price"] = _money(o.get("amount_paid", o["cents"]))
    if o.get("job_id"):
        st = _job_status(o["job_id"]) or {}
        out["job"] = {k: st.get(k) for k in ("status", "progress", "message", "audio", "timings", "duration")}
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


@router.post("/api/stripe/webhook")
async def webhook(request: Request):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(404)
    payload = await request.body()
    try:
        event = _stripe().Webhook.construct_event(payload, request.headers.get("stripe-signature", ""), secret)
    except Exception:
        raise HTTPException(400, "Bad signature.")
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        s = event["data"]["object"]
        s = s.to_dict() if hasattr(s, "to_dict") else dict(s)
        oid = s.get("client_reference_id") or (s.get("metadata") or {}).get("order", "")
        _mark_paid(oid, s)
    return {"ok": True}


# ------------------------------------------------------------------ keep the machine awake while paid work renders
def keep_awake(busy: Callable[[], bool]) -> None:
    """Fly stops an idle machine when no requests come through its proxy, which would cut a long
    render short. While anything is rendering, ping our own public address once a minute."""
    app_name = os.environ.get("FLY_APP_NAME")
    if not app_name:
        return
    url = (os.environ.get("PUBLIC_URL") or f"https://{app_name}.fly.dev").rstrip("/") + "/api/voices"

    def loop():
        while True:
            time.sleep(60)
            if busy():
                try:
                    urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "storybook-keepalive"}), timeout=20).read(1)
                except Exception:
                    pass
    threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------------ owner's page
@router.get("/admin/orders")
def admin_orders(request: Request):
    if not analytics.authed(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin", status_code=303)
    orders = [_refresh(o) if o["status"] in ("pending", "rendering") and time.time() - o["created"] < 86400 * 2 else o
              for o in all_orders()]
    paid = [o for o in orders if o["status"] not in ("pending",)]
    live = [o for o in paid if o.get("mode") == "live"]
    revenue = sum(o.get("amount_paid", o["cents"]) for o in live)
    rows = "".join(
        f'<tr><td>{time.strftime("%Y-%m-%d %H:%M", time.gmtime(o["created"]))}</td>'
        f'<td>{H.escape(o["kind"])}{"" if o.get("mode") == "live" else " <small>(test)</small>"}</td>'
        f'<td><a href="/order.html?o={o["id"]}">{H.escape(o["title"])}</a><br><small>{H.escape(o.get("summary", ""))}</small></td>'
        f'<td>{_money(o.get("amount_paid", o["cents"]))}</td>'
        f'<td>{H.escape(o["status"])}{"<br><small>" + H.escape(o["error"]) + "</small>" if o.get("error") else ""}</td>'
        f'<td>{"<a href=" + chr(34) + "mailto:" + H.escape(o["email"]) + chr(34) + ">" + H.escape(o["email"]) + "</a>" if o.get("email") else ""}</td></tr>'
        for o in orders) or '<tr><td colspan="6" class="empty">No orders yet.</td></tr>'
    p = pricing()
    tiers = " · ".join(f'{t["name"]} (up to {t["max_words"]:,} words) {t["price"]}' for t in p["studio"])
    body = f"""<h2>Orders</h2>
<p class="range note">Payments: <b>{mode()}</b>{" (checkout works only for you while logged in; set a sk_live_ key to take real payments)" if mode() == "test" else " (no Stripe key: buy buttons say checkout is opening shortly)" if mode() == "off" else ""} ·
{len(live)} paid live order{"" if len(live) == 1 else "s"} · {_money(revenue)} taken
<span style="float:right"><a href="/admin">analytics</a> · <a href="/admin/signups">sign-ups</a></span></p>
<p class="note">Personalised story {p["personal"]["price"]} · Studio: {H.escape(tiers)}</p>
<div class="wrap"><table><thead><tr><th>When (UTC)</th><th>What</th><th>Title</th><th>Paid</th><th>Status</th><th>Buyer</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="note" style="font-size:.85rem;margin-top:1.4rem">"pending" means the buyer opened checkout but hasn't paid. Refunds are done in the Stripe dashboard.
Each title links to the buyer's own page, which you can send them if they lose it.</p>"""
    return HTMLResponse(analytics._HEAD.format(title="Orders", note="orders") + body + analytics._FOOT, headers=analytics._NOSTORE)
