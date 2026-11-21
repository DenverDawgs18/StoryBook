// After checkout: wait for the payment to be confirmed and the recording to render, then play it.
import { mountPlayer, fmt } from "./player.js";

const $ = (id) => document.getElementById(id);
const oid = new URLSearchParams(location.search).get("o") || "";
const fresh = new URLSearchParams(location.search).has("session_id");
if (fresh) history.replaceState(null, "", `order.html?o=${oid}`); // a clean link to bookmark
const LINES = ["Casting the voices…", "Lighting the fire…", "Tuning the harp…", "Painting the soundscape…", "Mixing it all together…"];

async function get() {
  const r = await fetch(`/api/orders/${encodeURIComponent(oid)}`, { cache: "no-store" });
  if (r.status === 404) throw new Error("We couldn't find that order. Please check the link in your receipt.");
  if (!r.ok) throw new Error(`Something went wrong (${r.status}). Please reload in a moment.`);
  return r.json();
}

let tracked = false, t0 = 0, p0 = 0, k = 0, pending = 0;
async function loop() {
  for (;;) {
    let o;
    try { o = await get(); } catch (e) {
      $("oerror").textContent = e.message; $("oerror").classList.remove("hidden"); $("olede").textContent = ""; return;
    }
    $("otitle").textContent = o.title;
    if (o.status !== "pending" && fresh && !tracked) { tracked = true; window.sbTrack?.("purchase_completed", { kind: o.kind }); }
    if (o.status === "pending") {
      $("olede").textContent = "Waiting for the payment to come through…";
      if (++pending > 40) { $("olede").textContent = "We haven't seen the payment yet. If you paid, reload this page in a minute."; return; }
    } else if (o.status === "failed" || o.job?.status === "error") {
      $("olede").textContent = "Your payment went through, but the recording hit a snag.";
      $("oerror").textContent = "We've been told and will fix it, or refund you in full. Reply to your receipt email any time.";
      $("oerror").classList.remove("hidden");
      $("oprog").classList.add("hidden");
      return;
    } else if (o.job?.status === "done") {
      $("kicker").textContent = "your recording is ready";
      $("olede").textContent = `${o.summary}. Paid ${o.price}. Thank you.`;
      $("oprog").classList.add("hidden");
      $("ostatus").textContent = "Ready. Put the lights out ~";
      $("oeta").textContent = "";
      $("oresult").classList.remove("hidden");
      $("odl").href = o.job.audio;
      $("odl").setAttribute("download", `${o.title.replace(/[^\w ,'-]+/g, "").trim() || "storybook"}.mp3`);
      const t = await (await fetch(o.job.timings)).json().catch(() => ({}));
      const labels = Object.fromEntries(Object.entries(t.meta?.labels || {}).map(([a, b]) => [a, { label: b }]));
      mountPlayer($("oplayer"), { title: o.title, audio: o.job.audio, timings: o.job.timings, duration: o.job.duration, castLabels: labels },
        { track: { kind: o.kind, story: o.kind } });
      return;
    } else {
      $("olede").textContent = "Paid, thank you. Your recording is being made now. You can leave this page open, or come back to it later.";
      $("oprog").classList.remove("hidden");
      const j = o.job || { progress: 0, status: "queued", message: "" };
      $("ofill").style.setProperty("--p", `${Math.max(2, (j.progress || 0) * 100).toFixed(1)}%`);
      if (j.status === "queued") $("ostatus").textContent = `Waiting for a storyteller (${(j.message || "queued").toLowerCase()})…`;
      else {
        if (!t0 && j.progress > 0.02) { t0 = Date.now(); p0 = j.progress; }
        if (k++ % 4 === 0) $("ostatus").textContent = LINES[Math.floor(k / 4) % LINES.length];
        if (t0 && j.progress - p0 > 0.03) {
          const el = (Date.now() - t0) / 1000;
          $("oeta").textContent = `about ${fmt(Math.max(5, (el / (j.progress - p0)) * (1 - j.progress)))} to go`;
        }
      }
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}
if (oid) loop(); else $("olede").textContent = "There's no order in this link.";
