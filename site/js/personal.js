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
      onplay: () => $("example").classList.add("playing"), onpause: () => $("example").classList.remove("playing"),
    });
  } catch {
    $("ex-player").innerHTML = '<p class="note">The example isn\'t available right now.</p>';
  }
}
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => showExample(b.dataset.ex)));
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
let previewAudio = null;
$("name").addEventListener("input", () => {
  const n = $("name").value.trim();
  $("r-title").textContent = n && NAME_RX.test(n) ? `Reserve ${n}'s full story` : "Reserve the full story";
});

$("pform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const req = request();
  const problem = check(req);
  showError("perror", problem);
  if (problem) { $("name").focus(); return; }
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
    previewAudio = mountPlayer($("presult"), ep);
    $("pstatus").textContent = `Here is ${req.name}'s story ~`;
    $("presult").insertAdjacentHTML("beforeend",
      `<p class="note" style="margin-top:1rem">Like it? <a href="#reserve">Reserve ${esc(req.name)}'s full story</a>.</p>`);
    previewAudio.play().catch(() => { /* autoplay may be blocked; the play button is there */ });
  } catch (err) {
    const offline = err instanceof TypeError || /\(404\)|\(405\)/.test(err.message);
    showError("perror", offline ? "Previews need the StoryBook server, which this copy of the site isn't connected to." : err.message);
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

// ------------------------------------------------------------------ reserve
if (PRICE) $("price").textContent = PRICE;
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
    $("rform").classList.add("hidden");
    $("rdone").classList.remove("hidden");
    const tale = document.querySelector('input[name="tale"]:checked').closest("label").querySelector("h3").textContent;
    $("rdone-text").textContent = `We've saved ${req.name}'s place for ${tale}. We'll email ${email} as soon as full stories open.`;
  } catch (err) {
    const offline = err instanceof TypeError || /\(404\)|\(405\)/.test(err.message);
    showError("rerror", offline ? "Sign-ups need the StoryBook server, which this copy of the site isn't connected to." : err.message);
  } finally {
    $("rgo").disabled = false;
  }
});
