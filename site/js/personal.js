// "A story for your child": examples, a free personalised preview, and the reserve sign-up.
import { mountPlayer, esc } from "./player.js";

// The launch price shown on the page. Set to "" to hide it.
const PRICE = "Planned launch price: $6 a story.";

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
let buying = false; // set once /api/config answers
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
      `<p class="note" style="margin-top:1rem">Like it? <a href="#reserve">${buying ? "Get" : "Reserve"} ${esc(req.name)}'s full story</a>.</p>`);
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

// ------------------------------------------------------------------ buy (when checkout is open) or reserve
let config = {};
try { config = await (await fetch("/api/config")).json(); } catch { /* static copy: reserve only */ }
buying = !!config.payments;
const fullPrice = config.pricing?.personal?.price || "";
const reserveTitle = (n) => buying ? (n ? `Get ${n}'s full story` : "Get the full story") : (n ? `Reserve ${n}'s full story` : "Reserve the full story");
if (buying) {
  $("rform").classList.add("hidden");
  $("buy").classList.remove("hidden");
  $("r-blurb").textContent = "The full tale runs about five to seven minutes, from the dedication to the goodnight, with the whole cast and soundscape, and your child as the hero all the way through.";
  $("price").textContent = `${fullPrice} a story${config.payments_mode === "test" ? " (test mode: only you can see this)" : ""}`;
  $("bgo").textContent = `Get the full story · ${fullPrice}`;
  $("r-title").textContent = reserveTitle("");
} else if (PRICE) $("price").textContent = PRICE;
$("name").addEventListener("input", () => {
  const n = $("name").value.trim();
  $("r-title").textContent = reserveTitle(n && NAME_RX.test(n) ? n : "");
});

$("bgo").addEventListener("click", async () => {
  const req = request();
  const problem = check(req);
  if (problem) {
    showError("berror", "First, tell us who the story is for, above.");
    $("make").scrollIntoView({ behavior: "smooth" });
    return;
  }
  showError("berror", "");
  $("bgo").disabled = true;
  try {
    const { url } = await api("/api/checkout/personal", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    window.sbTrack?.("checkout_started", { kind: "personal", ...choices(req), had_preview: !!previewId });
    location.assign(url);
  } catch (err) {
    showError("berror", err.message);
    $("bgo").disabled = false;
  }
});
$("rform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const req = request();
  const problem = check(req);
  if (problem) {
    showError("rerror", "First, tell us who the story is for, above.");
    $("make").scrollIntoView({ behavior: "smooth" });
    return;
  }
  const email = $("email").value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) { showError("rerror", "Please check your email address."); return; }
  showError("rerror", "");
  $("rgo").disabled = true;
  try {
    await api("/api/personal/signup", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...req, email, preview_id: previewId, website: $("website").value }),
    });
    window.sbTrack?.("signup_submitted", { ...choices(req), had_preview: !!previewId });
    $("rform").classList.add("hidden");
    $("rdone").classList.remove("hidden");
    const tale = document.querySelector('input[name="tale"]:checked').closest("label").querySelector("h3").textContent;
    $("rdone-text").textContent = `We've saved ${req.name}'s place for ${tale}. We'll email ${email} as soon as full stories open.`;
  } catch (err) {
    const offline = err instanceof TypeError || /\(404\)|\(405\)/.test(err.message);
    showError("rerror", offline ? "Sign-ups need the StoryBook server, which this copy of the site isn't connected to." : err.message);
    window.sbTrack?.("signup_failed", { tale: req.tale, reason: offline ? "offline" : err.message.slice(0, 80) });
  } finally {
    $("rgo").disabled = false;
  }
});

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
