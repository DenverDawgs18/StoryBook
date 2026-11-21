// The Studio: a waitlist until checkout is open, then manuscript → cast → free opening → checkout.
import { mountPlayer, esc, fmt } from "./player.js";

const $ = (id) => document.getElementById(id);
const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5c0-.8.9-1.3 1.6-.9l11 7a1.1 1.1 0 0 1 0 1.8l-11 7c-.7.4-1.6-.1-1.6-.9z" fill="currentColor"/></svg>';
const MOOD_WASH = { night: "blob4", storm: "blob2", hearth: "blob3", epic: "blob6", water: "blob2", pastoral: "blob1", quiet: "blob5" };
const EMAIL_RX = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

let voices = [];
let analysis = null;
let fileText = null;
const sample = new Audio();

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `Something went wrong (${r.status}).`;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const showError = (el, msg) => { $(el).textContent = msg; $(el).classList.toggle("hidden", !msg); };

// ------------------------------------------------------------ the waitlist (while checkout isn't open)
$("wform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("email").value.trim();
  if (!EMAIL_RX.test(email)) { showError("werror", "Please check your email address."); $("email").focus(); return; }
  showError("werror", "");
  $("wgo").disabled = true;
  const use = (document.querySelector('input[name="use"]:checked') || {}).value || "";
  try {
    await api("/api/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, source: "studio", use, note: $("note").value.trim(), website: $("website").value }) });
    window.sbTrack?.("subscribe", { source: "studio", use: use || "none", has_note: !!$("note").value.trim() });
    $("wform").classList.add("hidden");
    $("wdone").classList.remove("hidden");
  } catch (err) {
    showError("werror", err instanceof TypeError ? "The waitlist needs the StoryBook server, which this copy of the site isn't connected to." : err.message);
  } finally {
    $("wgo").disabled = false;
  }
});

// ------------------------------------------------------------ boot
let config = {};
try { config = await api("/api/config"); } catch { /* static copy of the site: waitlist only */ }
if (config.payments) {
  $("kicker").textContent = config.payments_mode === "test" ? "open (test mode: only you can see this)" : "now open";
  $("join").classList.add("hidden");
  $("studio").classList.remove("hidden");
  $("prices").classList.remove("hidden");
  $("tiers").innerHTML = config.pricing.studio.map((t, i, all) => `
    <li><span class="t">${esc(t.name)}<small>${i === all.length - 1 ? `over ${(t.min_words - 1).toLocaleString()} words, up to about ${(Math.round(config.studio_max_chars / 6 / 1000) * 1000).toLocaleString()} words`
      : `up to ${t.max_words.toLocaleString()} words, about ${fmt(t.max_words / 150 * 60)} of listening`}</small></span><span class="dots"></span><b>${esc(t.price)}</b></li>`).join("");
  try {
    voices = await api("/api/voices");
    $("narrator").innerHTML = voiceOptions("bm_lewis");
    wirePreview(document.querySelector('.preview[data-for="narrator"]'), () => $("narrator").value);
  } catch {
    $("offline").classList.remove("hidden");
    $("analyze").disabled = true;
  }
}

function voiceOptions(selected) {
  return voices.map((v) => `<option value="${v.id}" ${v.id === selected ? "selected" : ""}>${esc(v.description)}</option>`).join("");
}

function wirePreview(btn, getVoice) {
  btn.innerHTML = ICON_PLAY;
  btn.addEventListener("click", () => {
    btn.classList.add("busy");
    sample.src = `/api/voices/${getVoice()}/sample`;
    sample.oncanplay = () => btn.classList.remove("busy");
    sample.onerror = () => btn.classList.remove("busy");
    sample.play().catch(() => btn.classList.remove("busy"));
  });
}

// ------------------------------------------------------------ step 1: the manuscript
const drop = $("drop");
["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("over")));
drop.addEventListener("drop", (ev) => {
  ev.preventDefault();
  if (ev.dataTransfer.files[0]) { $("file").files = ev.dataTransfer.files; onFile(); }
});
$("file").addEventListener("change", onFile);
function onFile() {
  const f = $("file").files[0];
  if (!f) return;
  $("fname").textContent = f.name;
  fileText = null;
  if (!$("title").value) $("title").value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
}

$("step1").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData();
  const f = $("file").files[0];
  if (f) fd.append("file", f); else fd.append("text", $("text").value);
  $("s1").textContent = "Reading it through…";
  $("s1").classList.remove("error");
  $("analyze").disabled = true;
  try {
    analysis = await api("/api/analyze", { method: "POST", body: fd });
    window.sbTrack?.("studio_analyzed", { source: f ? "file" : "paste", words: analysis.words, characters: analysis.cast?.length || 0, mood: analysis.mood, tier: analysis.quote?.tier });
    fileText = analysis.text;
    if (f && !$("text").value) $("text").value = analysis.text.slice(0, 20000);
    showCast();
    $("s1").textContent = "";
  } catch (e) {
    $("s1").textContent = e.message;
    window.sbTrack?.("studio_analyze_failed", { reason: String(e.message).slice(0, 80) });
    $("s1").classList.add("error");
  } finally {
    $("analyze").disabled = false;
  }
});

// ------------------------------------------------------------ step 2: the cast, the opening and the price
function showCast() {
  const a = analysis;
  $("stats").innerHTML = `
    <span><b>${a.words.toLocaleString()}</b>words</span>
    <span><b>~${fmt(a.minutes * 60)}</b>of listening</span>
    <span><b>${a.cast.length}</b>speaking parts</span>
    <span><b>${a.headings}</b>chapters</span>`;
  $("charsBox").classList.toggle("hidden", a.cast.length === 0);
  $("cast").innerHTML = a.cast.map((c) => `
    <li>
      <span class="name">${esc(c.name)}<small>${c.lines} line${c.lines === 1 ? "" : "s"}</small></span>
      <select data-key="${esc(c.key)}" aria-label="Voice for ${esc(c.name)}">${voiceOptions(c.voice)}</select>
      <button type="button" class="preview" aria-label="Preview voice for ${esc(c.name)}"></button>
    </li>`).join("");
  $("cast").querySelectorAll("li").forEach((li) => {
    const sel = li.querySelector("select");
    wirePreview(li.querySelector(".preview"), () => sel.value);
  });
  $("moods").innerHTML = Object.entries(a.moods).map(([k, label]) => `
    <label class="mood-opt" style="--wash:url('${new URL(`assets/paint/${MOOD_WASH[k] || "blob5"}.png`, location.href).href}')">
      <input type="radio" name="mood" value="${k}" ${k === a.mood ? "checked" : ""}>
      <span>${esc(label)}${k === a.mood ? '<span class="suggested">suggested</span>' : ""}</span>
    </label>`).join("");
  const q = a.quote;
  $("quote").innerHTML = `<p class="price">${esc(q.tier)} of ${q.words.toLocaleString()} words: <b>${esc(q.price)}</b> for the whole recording.</p>`;
  $("go").textContent = `Record it all · ${q.price}`;
  $("pvresult").classList.add("hidden");
  $("step1").classList.add("hidden");
  $("step2").classList.remove("hidden");
  $("step2").scrollIntoView({ behavior: "smooth", block: "start" });
}
const sp = () => ($("speedv").textContent = `${Math.round($("speed").value * 100)}%`);
$("speed").addEventListener("input", sp); sp();
$("back1").addEventListener("click", () => { $("step2").classList.add("hidden"); $("step1").classList.remove("hidden"); });

function jobBody() {
  const cast = {};
  $("cast").querySelectorAll("select").forEach((s) => (cast[s.dataset.key] = s.value));
  return {
    text: fileText || $("text").value,
    title: $("title").value.trim() || "Untitled",
    author: $("author").value.trim() || "Anonymous",
    narrator: $("narrator").value,
    cast,
    mood: (document.querySelector('input[name="mood"]:checked') || {}).value,
    effects: $("fx").checked,
    speed: parseFloat($("speed").value),
  };
}

// the free opening
let pvAudio = null;
$("pv").addEventListener("click", async () => {
  const body = jobBody();
  showError("e2", "");
  $("pv").disabled = true;
  $("pvresult").classList.add("hidden");
  pvAudio?.pause();
  $("pvprog").classList.remove("hidden");
  $("pvfill").style.setProperty("--p", "2%");
  $("s2").textContent = "Recording the opening…";
  window.sbTrack?.("studio_preview_requested", { mood: body.mood || "", tier: analysis.quote?.tier });
  try {
    const { id } = await api("/api/studio/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let j;
    for (;;) {
      j = await api(`/api/jobs/${id}`);
      $("pvfill").style.setProperty("--p", `${Math.max(2, j.progress * 100).toFixed(1)}%`);
      if (j.status === "done") break;
      if (j.status === "error") throw new Error("Sorry, the opening didn't record. Please try again.");
      $("s2").textContent = j.status === "queued" ? `Waiting for a storyteller (${j.message.toLowerCase()})…` : "Recording the opening…";
      await new Promise((r) => setTimeout(r, 1500));
    }
    $("pvresult").classList.remove("hidden");
    pvAudio = mountPlayer($("pvresult"), {
      title: `${body.title}: the opening`, audio: j.audio, timings: j.timings, duration: j.duration,
      castLabels: Object.fromEntries((analysis?.cast || []).map((c) => [c.key, { label: c.name }])),
    }, { track: { kind: "studio_preview", story: "studio" } });
    $("s2").textContent = `Here is the opening. Like it? Record it all for ${analysis.quote.price}.`;
    window.sbTrack?.("studio_preview_ready", { tier: analysis.quote?.tier });
    pvAudio.play().catch(() => {});
  } catch (e) {
    $("s2").textContent = "";
    showError("e2", e.message);
  } finally {
    $("pv").disabled = false;
    $("pvprog").classList.add("hidden");
  }
});

// checkout
$("step2").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = jobBody();
  showError("e2", "");
  $("go").disabled = true;
  $("s2").textContent = "Opening the checkout…";
  try {
    const { url } = await api("/api/checkout/studio", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    window.sbTrack?.("checkout_started", { kind: "studio", tier: analysis.quote?.tier });
    location.assign(url);
  } catch (e) {
    $("s2").textContent = "";
    showError("e2", e.message);
    $("go").disabled = false;
  }
});

// ------------------------------------------------------------ step 3: an owner's direct recording (#job=…)
async function watch(id) {
  const t0 = Date.now();
  for (;;) {
    let j;
    try { j = await api(`/api/jobs/${id}`); } catch (e) { $("s3").textContent = e.message; return; }
    $("pfill").style.setProperty("--p", `${(j.progress * 100).toFixed(1)}%`);
    if (j.status === "queued") $("s3").textContent = j.message;
    if (j.status === "running") {
      $("s3").textContent = j.progress < 0.92 && j.message ? `Voicing: “${j.message.slice(0, 70)}…”` : j.message;
      if (j.progress > 0.04) $("eta").textContent = `about ${fmt(((Date.now() - t0) / 1000 / j.progress) * (1 - j.progress))} to go`;
    }
    if (j.status === "done") {
      $("s3").textContent = "Ready. Put the lights out.";
      $("eta").textContent = "";
      $("result").classList.remove("hidden");
      $("dlScript").href = `/api/jobs/${id}/script`;
      $("dlAudio").href = j.audio;
      mountPlayer($("resPlayer"), { title: j.title, audio: j.audio, timings: j.timings, duration: j.duration, castLabels: {} },
        { track: { kind: "studio", story: "studio" } });
      return;
    }
    if (j.status === "error") { $("s3").innerHTML = `<span class="error">Something went wrong: ${esc(j.message)}</span>`; return; }
    await new Promise((r) => setTimeout(r, 1500));
  }
}
$("again").addEventListener("click", () => location.assign("studio.html"));
const m = location.hash.match(/job=([0-9a-f]{12})/);
if (m && config.payments) {
  $("step1").classList.add("hidden");
  $("step3").classList.remove("hidden");
  watch(m[1]);
}
