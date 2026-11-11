import { mountPlayer, esc, fmt } from "./player.js";

const $ = (id) => document.getElementById(id);
const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5c0-.8.9-1.3 1.6-.9l11 7a1.1 1.1 0 0 1 0 1.8l-11 7c-.7.4-1.6-.1-1.6-.9z" fill="currentColor"/></svg>';
const MOOD_WASH = { night: "blob4", storm: "blob2", hearth: "blob3", epic: "blob6", water: "blob2", pastoral: "blob1", quiet: "blob5" };

let voices = [];
let analysis = null;
let fileText = null;
const sample = new Audio();

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function voiceOptions(selected) {
  return voices.map((v) => `<option value="${v.id}" ${v.id === selected ? "selected" : ""}>${esc(v.description)}</option>`).join("");
}

function wirePreview(btn, getVoice) {
  btn.innerHTML = ICON_PLAY;
  btn.addEventListener("click", () => {
    const v = getVoice();
    btn.classList.add("busy");
    sample.src = `/api/voices/${v}/sample`;
    sample.oncanplay = () => btn.classList.remove("busy");
    sample.onerror = () => btn.classList.remove("busy");
    sample.play().catch(() => btn.classList.remove("busy"));
  });
}

// ------------------------------------------------------------ boot
try {
  voices = await api("/api/voices");
  $("narrator").innerHTML = voiceOptions("bm_lewis");
  wirePreview(document.querySelector('.preview[data-for="narrator"]'), () => $("narrator").value);
} catch {
  $("offline").classList.remove("hidden");
  $("analyze").disabled = true;
}

// ------------------------------------------------------------ step 1
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
    fileText = analysis.text;
    if (f && !$("text").value) $("text").value = analysis.text.slice(0, 20000);
    showCast();
    $("s1").textContent = "";
  } catch (e) {
    $("s1").textContent = e.message;
    $("s1").classList.add("error");
  } finally {
    $("analyze").disabled = false;
  }
});

// ------------------------------------------------------------ step 2
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
  $("step1").classList.add("hidden");
  $("step2").classList.remove("hidden");
  $("step2").scrollIntoView({ behavior: "smooth", block: "start" });
}
const sp = () => ($("speedv").textContent = `${Math.round($("speed").value * 100)}%`);
$("speed").addEventListener("input", sp); sp();
$("back1").addEventListener("click", () => { $("step2").classList.add("hidden"); $("step1").classList.remove("hidden"); });

$("step2").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cast = {};
  $("cast").querySelectorAll("select").forEach((s) => (cast[s.dataset.key] = s.value));
  const body = {
    text: fileText || $("text").value,
    title: $("title").value.trim() || "Untitled",
    author: $("author").value.trim() || "Anonymous",
    narrator: $("narrator").value,
    cast,
    mood: (document.querySelector('input[name="mood"]:checked') || {}).value,
    effects: $("fx").checked,
    speed: parseFloat($("speed").value),
  };
  $("go").disabled = true;
  try {
    const { id } = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("step2").classList.add("hidden");
    $("step3").classList.remove("hidden");
    $("recTitle").textContent = body.title;
    history.replaceState(null, "", `#job=${id}`);
    watch(id, body);
  } catch (e) {
    alert(e.message);
  } finally {
    $("go").disabled = false;
  }
});

// ------------------------------------------------------------ step 3
const LINES = ["Tuning the voices…", "Mixing the pigments…", "Letting the wash settle…", "Listening for footsteps…"];
async function watch(id, body) {
  let i = 0;
  const t0 = Date.now();
  for (;;) {
    let j;
    try { j = await api(`/api/jobs/${id}`); } catch (e) { $("s3").textContent = e.message; return; }
    $("pfill").style.setProperty("--p", `${(j.progress * 100).toFixed(1)}%`);
    if (j.status === "queued") $("s3").textContent = j.message;
    if (j.status === "running") {
      $("s3").textContent = !j.message ? LINES[i++ % LINES.length]
        : j.progress < 0.92 ? `Voicing: “${j.message.slice(0, 70)}…”` : j.message;
      if (j.progress > 0.04) {
        const el = (Date.now() - t0) / 1000;
        const left = (el / j.progress) * (1 - j.progress);
        $("eta").textContent = `about ${fmt(left)} to go`;
      }
    }
    if (j.status === "done") {
      $("s3").textContent = "Ready. Put the lights out.";
      $("eta").textContent = "";
      $("result").classList.remove("hidden");
      $("dlScript").href = `/api/jobs/${id}/script`;
      mountPlayer($("resPlayer"), {
        title: j.title, audio: j.audio, timings: j.timings, duration: j.duration,
        castLabels: Object.fromEntries((analysis?.cast || []).map((c) => [c.key, { label: c.name }])),
      });
      return;
    }
    if (j.status === "error") {
      $("s3").innerHTML = `<span class="error">Something went wrong: ${esc(j.message)}</span>`;
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}
$("again").addEventListener("click", () => location.assign("studio.html"));

// resume a job if the page was reloaded
const m = location.hash.match(/job=([0-9a-f]{12})/);
if (m) {
  $("step1").classList.add("hidden");
  $("step3").classList.remove("hidden");
  watch(m[1], {});
}
