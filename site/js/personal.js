// "A story for your child": examples, a free personalised preview, and the reserve sign-up.
import { mountPlayer, esc } from "./player.js";


const $ = (id) => document.getElementById(id);
const NAME_RX = /^[\p{L}]+(?:[ '’\-][\p{L}]+)*$/u;

async function api(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw new Error(body?.detail || `Something went wrong (${r.status}).`);
  return body;
}

// An episode object the shared player understands, built from a render's timings file.
async function episode(audio, timings, title) {
  const t = await (await fetch(timings)).json();
  const labels = Object.fromEntries(Object.entries(t.meta?.labels || {}).map(([k, v]) => [k, { label: v }]));
  return { title: title || t.meta?.title || "Your story", audio, timings, duration: t.duration, castLabels: labels };
}

// ------------------------------------------------------------------ examples
const EXAMPLES = {
  pigs: {
    base: "audio/personal/the_three_little_pigs_for_mia_preview", art: "assets/land/land_pigs.webp",
    cap: "Mia is the third little pig",
    blurb: "Mia is the clever third little pig. She builds her house of bricks, the wolf knocks on her door, and when he calls out it's her name he calls. The story opens with a dedication from Grandma.",
  },
  elves: {
    base: "audio/personal/elves_and_the_shoemaker_for_leo_preview", art: "assets/land/land_cottage.webp",
    cap: "Leo is the shoemaker's son",
    blurb: "Leo is the shoemaker's son. He begs to stay up on Christmas Eve, hides behind the curtain with his mother and father, and has to hold his breath not to laugh when the elves come in. A dedication from Mum and Dad.",
  },
};
let exAudio = null;
async function showExample(key) {
  const ex = EXAMPLES[key];
  document.querySelectorAll(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.ex === key)));
  $("ex-art").src = ex.art;
  $("ex-cap").textContent = ex.cap;
  $("ex-blurb").textContent = ex.blurb;
  exAudio?.pause();
  try {
    const ep = await episode(`${ex.base}.mp3`, `${ex.base}.json`);
    exAudio = mountPlayer($("ex-player"), ep, {
      track: { kind: "example", story: key },
      onplay: () => $("example").classList.add("playing"), onpause: () => $("example").classList.remove("playing"),
    });
  } catch {
    $("ex-player").innerHTML = '<p class="note">The example isn\'t available right now.</p>';
  }
}
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  window.sbTrack?.("example_switch", { example: b.dataset.ex });
  showExample(b.dataset.ex);
}));
// what we send about a request: the choices, never the name, spelling or dedication text
const choices = (req) => ({ tale: req.tale, pronouns: req.pronouns, voice: req.voice || "auto",
                            has_dedication: !!req.gift_from, has_say_as: !!req.say_as });
showExample("pigs");

// ------------------------------------------------------------------ the form
const choice = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value ?? "";
function request() {
  return {
    name: $("name").value.trim(), pronouns: choice("pronouns"), tale: choice("tale"),
    voice: choice("voice") || null, gift_from: $("from").value.trim(), say_as: $("sayas").value.trim(),
  };
}
function check(req) {
  if (!req.name) return "Please tell us their first name.";
  if (!NAME_RX.test(req.name)) return "Please use letters only for the name (hyphens and apostrophes are fine).";
  if (req.say_as && !NAME_RX.test(req.say_as)) return "Please spell the name with letters only.";
  return "";
}
const showError = (el, msg) => { $(el).textContent = msg; $(el).classList.toggle("hidden", !msg); };

let previewId = "";
let fullPrice = "$6"; // updated from /api/config
let previewAudio = null;

$("pform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const req = request();
  const problem = check(req);
  showError("perror", problem);
  if (problem) { window.sbTrack?.("preview_invalid", { tale: req.tale }); $("name").focus(); return; }
  window.sbTrack?.("preview_requested", choices(req));
  const startedAt = Date.now();
  $("go").disabled = true;
  $("presult").classList.add("hidden");
  previewAudio?.pause();
  $("pprog").classList.remove("hidden");
  $("pfill").style.setProperty("--p", "2%");
  $("pstatus").textContent = `Writing ${req.name} into the story…`;
  try {
    const { id } = await api("/api/personal/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    const job = await poll(id, req.name);
    previewId = id;
    const ep = await episode(job.audio, job.timings);
    $("presult").classList.remove("hidden");
    previewAudio = mountPlayer($("presult"), ep, { track: { kind: "preview", story: req.tale } });
    window.sbTrack?.("preview_ready", { ...choices(req), seconds: Math.round((Date.now() - startedAt) / 1000) });
    $("pstatus").textContent = `Here is ${req.name}'s story ~`;
    $("presult").insertAdjacentHTML("beforeend",
      `<div class="after-preview"><p>Like it? The full story runs five to seven minutes, from the dedication to the goodnight.</p>
       <button class="btn" type="button" id="pbuy">Buy ${esc(req.name)}'s full story · ${esc(fullPrice)}</button>
       <p class="note">Secure checkout by Stripe. You'll come straight back here while it's recorded, then play it or download the MP3.</p></div>`);
    previewAudio.play().catch(() => { /* autoplay may be blocked; the play button is there */ });
  } catch (err) {
    const offline = err instanceof TypeError || /\(404\)|\(405\)/.test(err.message);
    showError("perror", offline ? "Previews need the StoryBook server, which this copy of the site isn't connected to." : err.message);
    window.sbTrack?.("preview_failed", { tale: req.tale, reason: offline ? "offline" : err.message.slice(0, 80) });
    $("pstatus").textContent = "";
  } finally {
    $("go").disabled = false;
    $("pprog").classList.add("hidden");
  }
});

const MOMENTS = ["Casting the voices…", "Lighting the fire…", "Tuning the harp…", "The wolf is practising his lines…",
                 "Painting the soundscape…", "Mixing it all together…"];
async function poll(id, name) {
  let k = 0;
  for (;;) {
    const j = await api(`/api/jobs/${id}`);
    $("pfill").style.setProperty("--p", `${Math.max(2, j.progress * 100).toFixed(1)}%`);
    if (j.status === "done") return j;
    if (j.status === "error") throw new Error("Sorry, that preview didn't work. Please try again.");
    $("pstatus").textContent = j.status === "queued" ? `Waiting for a storyteller (${j.message.toLowerCase()})…`
      : (k++ % 4 === 0 ? MOMENTS[Math.floor(k / 4) % MOMENTS.length] : $("pstatus").textContent);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

// ------------------------------------------------------------------ buy
const firstName = () => { const n = $("name").value.trim(); return n && NAME_RX.test(n) ? n : ""; };
function labelButtons() {
  const n = firstName();
  const who = n ? `${n}'s` : "the";
  $("r-title").textContent = n ? `Get ${n}'s full story` : "Get the full story";
  $("bgo").textContent = `Buy ${who} full story · ${fullPrice}`;
  $("go-buy").textContent = `Skip the preview: buy now · ${fullPrice}`;
  document.querySelectorAll('[data-price="personal"]').forEach((el) => (el.textContent = fullPrice));
  const after = $("pbuy"); if (after) after.textContent = `Buy ${who} full story · ${fullPrice}`;
}
try {
  const config = await (await fetch("/api/config")).json();
  if (config.pricing?.personal?.price) fullPrice = config.pricing.personal.price;
} catch { /* static copy of the site */ }
labelButtons();
$("name").addEventListener("input", labelButtons);

async function buy(errEl, btn, where) {
  const req = request();
  const problem = check(req);
  if (problem) {
    showError("perror", problem);
    if (errEl !== "perror") showError(errEl, "First, tell us who the story is for, above.");
    $("make").scrollIntoView({ behavior: "smooth" });
    $("name").focus();
    return;
  }
  showError(errEl, "");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Opening the secure checkout…";
  try {
    const { url } = await api("/api/checkout/personal", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    window.sbTrack?.("checkout_started", { kind: "personal", where, ...choices(req), had_preview: !!previewId });
    location.assign(url);
  } catch (err) {
    showError(errEl, err.message);
    btn.disabled = false;
    btn.textContent = label;
  }
}
$("bgo").addEventListener("click", () => buy("berror", $("bgo"), "panel"));
$("go-buy").addEventListener("click", () => buy("perror", $("go-buy"), "form"));
$("presult").addEventListener("click", (e) => { if (e.target.id === "pbuy") buy("perror", e.target, "after_preview"); });

// ------------------------------------------------------------------ custom stories: interest list
$("cform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("cemail").value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) { showError("cerror", "Please check your email address."); $("cemail").focus(); return; }
  showError("cerror", "");
  $("cgo").disabled = true;
  const age = choice("age");
  try {
    await api("/api/subscribe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, source: "custom_story", age, note: $("cnote").value.trim(), website: $("cwebsite").value }),
    });
    window.sbTrack?.("subscribe", { source: "custom_story", age: age || "none", has_note: !!$("cnote").value.trim() });
    $("cform").classList.add("hidden");
    $("cdone").classList.remove("hidden");
  } catch (err) {
    showError("cerror", err instanceof TypeError ? "Sign-ups need the StoryBook server, which this copy of the site isn't connected to." : err.message);
  } finally {
    $("cgo").disabled = false;
  }
});
