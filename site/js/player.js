// StoryBook player: painted progress bar + read-along transcript that follows the voice.
const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5c0-.8.9-1.3 1.6-.9l11 7a1.1 1.1 0 0 1 0 1.8l-11 7c-.7.4-1.6-.1-1.6-.9z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4" width="4.2" height="16" rx="1.4" fill="currentColor"/><rect x="13.8" y="4" width="4.2" height="16" rx="1.4" fill="currentColor"/></svg>';

const fmt = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
};
const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const SPEAKER_NAMES = { narrator: "", host: "the host", oldman: "the old man" };
const whoLabel = (spk, cast) => (spk in SPEAKER_NAMES ? SPEAKER_NAMES[spk] : (cast?.[spk]?.label || spk.replace(/_/g, " ")));

export function mountPlayer(root, ep, opts = {}) {
  root.innerHTML = `
    <div class="player">
      <div class="row">
        <button class="play" aria-label="Play ${esc(ep.title)}">${ICON_PLAY}</button>
        <div class="track">
          <div class="bar" role="slider" tabindex="0" aria-label="Seek" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
            <div class="ground paint"></div><div class="fill paint"></div><div class="chapters"></div>
          </div>
          <div class="times"><span class="cur">0:00</span><span class="dur">${fmt(ep.duration)}</span></div>
        </div>
      </div>
      <div class="now-line" aria-live="off"></div>
      <div class="extras">
        <button class="back" type="button">− 15 s</button>
        <button class="fwd" type="button">+ 30 s</button>
        <button class="rate" type="button">speed 1×</button>
        ${ep.audio ? `<a href="${ep.audio}" download>download mp3</a>` : ""}
      </div>
      <audio preload="metadata" src="${ep.audio}"></audio>
    </div>
    ${opts.readalong === false ? "" : `<div class="readalong-wrap"><div class="readalong" aria-label="Read along"><p class="note">Loading the text…</p></div></div>`}`;

  const audio = root.querySelector("audio");
  const btn = root.querySelector(".play");
  const bar = root.querySelector(".bar");
  const cur = root.querySelector(".cur");
  const dur = root.querySelector(".dur");
  const now = root.querySelector(".now-line");
  const ra = root.querySelector(".readalong");
  const rates = [1, 1.15, 1.3, 0.85];
  let rateI = 0, phrases = [], paras = [], lastPh = -1, lastPara = -1, userScrolledAt = 0, timings = null;

  const setP = () => {
    const d = audio.duration || ep.duration || 1;
    const p = (audio.currentTime / d) * 100;
    bar.style.setProperty("--p", p.toFixed(2) + "%");
    bar.setAttribute("aria-valuenow", p.toFixed(0));
    cur.textContent = fmt(audio.currentTime);
    follow(audio.currentTime);
  };
  btn.addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
  // analytics: what was played, from where, and how far people get (no names, ever)
  const track = (ev, extra = {}) => window.sbTrack?.(ev, { story: ep.slug || opts.track?.story || "", kind: opts.track?.kind || "episode", ...extra });
  let played = false, reached = 0;
  audio.addEventListener("play", () => { if (!played) { played = true; track("story_play"); } });
  audio.addEventListener("timeupdate", () => {
    const d = audio.duration || ep.duration;
    if (!d) return;
    const pct = (audio.currentTime / d) * 100;
    for (const m of [25, 50, 75, 90]) if (pct >= m && reached < m) { reached = m; track("story_progress", { percent: m }); }
  });
  audio.addEventListener("ended", () => track("story_complete", { seconds: Math.round(audio.duration || 0) }));
  audio.addEventListener("play", () => { btn.innerHTML = ICON_PAUSE; btn.setAttribute("aria-label", "Pause"); opts.onplay?.(); });
  audio.addEventListener("pause", () => { btn.innerHTML = ICON_PLAY; btn.setAttribute("aria-label", "Play"); opts.onpause?.(); });
  audio.addEventListener("timeupdate", setP);
  audio.addEventListener("loadedmetadata", () => { dur.textContent = fmt(audio.duration); drawChapters(); });
  root.querySelector(".back").onclick = () => (audio.currentTime -= 15);
  root.querySelector(".fwd").onclick = () => (audio.currentTime += 30);
  root.querySelector(".rate").onclick = (e) => {
    rateI = (rateI + 1) % rates.length; audio.playbackRate = rates[rateI];
    e.target.textContent = `speed ${rates[rateI]}×`;
  };

  const seekFromEvent = (e) => {
    const r = bar.getBoundingClientRect();
    const x = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    audio.currentTime = x * (audio.duration || ep.duration);
    setP();
  };
  bar.addEventListener("pointerdown", (e) => {
    bar.setPointerCapture(e.pointerId); seekFromEvent(e);
    const mv = (ev) => seekFromEvent(ev);
    bar.addEventListener("pointermove", mv);
    bar.addEventListener("pointerup", () => bar.removeEventListener("pointermove", mv), { once: true });
  });
  bar.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") audio.currentTime += 10;
    if (e.key === "ArrowLeft") audio.currentTime -= 10;
    if (e.key === " ") { e.preventDefault(); btn.click(); }
  });

  function drawChapters() {
    const box = root.querySelector(".chapters");
    const d = audio.duration || ep.duration;
    if (!timings || !d) return;
    box.innerHTML = (timings.chapters || []).slice(1).map((c) => `<i style="left:${(c.start / d) * 100}%" title="${esc(c.title)}"></i>`).join("");
  }

  function follow(t) {
    if (!phrases.length) return;
    // binary search the phrase whose start <= t
    let lo = 0, hi = phrases.length - 1, k = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (phrases[m].s <= t) { k = m; lo = m + 1; } else hi = m - 1; }
    if (k !== lastPh) {
      if (lastPh >= 0) phrases[lastPh].el.classList.remove("on");
      if (k >= 0 && t <= phrases[k].e + 0.6) phrases[k].el.classList.add("on");
      lastPh = k;
    }
    let pk = -1;
    for (let i = 0; i < paras.length; i++) { if (paras[i].s <= t + 0.05) pk = i; else break; }
    if (pk !== lastPara) {
      paras.forEach((p, i) => { p.el.classList.toggle("done", i < pk); p.el.classList.toggle("current", i === pk); });
      lastPara = pk;
      if (pk >= 0) {
        const seg = paras[pk];
        const label = seg.who ? `— ${seg.who}` : "";
        now.textContent = label;
        if (ra && Date.now() - userScrolledAt > 4000) {
          const top = seg.el.offsetTop - ra.clientHeight * 0.3;
          ra.scrollTo({ top, behavior: "smooth" });
        }
      }
    }
  }

  if (ra && ep.timings) {
    ra.addEventListener("wheel", () => (userScrolledAt = Date.now()), { passive: true });
    ra.addEventListener("touchmove", () => (userScrolledAt = Date.now()), { passive: true });
    fetch(ep.timings).then((r) => r.json()).then((tj) => {
      timings = tj;
      drawChapters();
      const cast = ep.castLabels || {};
      ra.innerHTML = "";
      let lastSpk = null;
      tj.paragraphs.forEach((p) => {
        const el = document.createElement("p");
        if (p.heading) el.className = "heading";
        let html = "";
        p.segments.forEach((s) => {
          const who = s.speaker !== "narrator" && s.speaker !== lastSpk ? whoLabel(s.speaker, cast) : "";
          if (who) html += `<span class="who">${esc(who)}</span>`;
          lastSpk = s.speaker;
          const quoted = s.speaker !== "narrator" && s.speaker !== "host";
          if (quoted) html += "“";
          if (s.phrases.length) {
            s.phrases.forEach(([txt, a, b]) => {
              html += `<span class="ph" data-s="${a}" data-e="${b}">${esc(txt)}</span> `;
            });
          } else html += esc(s.text) + " ";
          if (quoted) html = html.trimEnd() + "” ";
        });
        el.innerHTML = html.trim();
        el.addEventListener("click", (e) => {
          const t = e.target.dataset?.s ?? p.start;
          audio.currentTime = parseFloat(t) + 0.01;
          if (audio.paused) audio.play();
        });
        ra.appendChild(el);
        const firstOther = p.segments.find((s) => s.speaker !== "narrator");
        paras.push({ s: p.start, el, who: firstOther ? whoLabel(firstOther.speaker, cast) : "" });
        el.querySelectorAll(".ph").forEach((ph) => phrases.push({ s: +ph.dataset.s, e: +ph.dataset.e, el: ph }));
      });
      phrases.sort((a, b) => a.s - b.s);
    }).catch(() => { ra.innerHTML = '<p class="note">The text for this recording is not available.</p>'; });
  }
  return audio;
}

export async function loadCatalog() {
  const r = await fetch("audio/catalog.json", { cache: "no-cache" });
  if (!r.ok) throw new Error("catalog");
  return r.json();
}
// plates: painted landscapes live in assets/land (webp); older washes in assets/paint (png)
const artUrl = (art) => (art || "").startsWith("land_") ? `assets/land/${art}.webp` : `assets/paint/${art || "blob2"}.png`;
export { fmt, esc, artUrl };
