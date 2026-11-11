"""The auto-director: turn an arbitrary manuscript into a .story production script.

Heuristics only (no network, no LLM): it finds chapters, attributes dialogue to
speakers, casts voices, chooses a soundscape for the mood and drops in effects where
the prose names a sound. The Studio lets the user correct the cast before rendering.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import yaml

SPEECH_VERBS = (
    "said|says|asked|asks|cried|cries|replied|replies|answered|whispered|shouted|exclaimed|muttered|"
    "murmured|called|continued|added|returned|repeated|began|observed|remarked|declared|demanded|"
    "screamed|sighed|laughed|growled|snapped|retorted|pleaded|insisted|inquired|rejoined|answered|"
    "groaned|sobbed|stammered|gasped|roared|thundered|hissed|breathed|went on"
)
_NAME = r"((?:Mr\.|Mrs\.|Miss|Dr\.|Sir|Lady|Lord|Captain|Uncle|Aunt|Old)?\s?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
RX_AFTER = re.compile(rf"(?:{SPEECH_VERBS})\s+{_NAME}")           # said Scrooge
RX_BEFORE = re.compile(rf"{_NAME}\s+(?:{SPEECH_VERBS})")          # Scrooge said
RX_PRONOUN = re.compile(rf"\b(he|she)\s+(?:{SPEECH_VERBS})|(?:{SPEECH_VERBS})\s+(he|she)\b", re.I)

NOT_NAMES = set("""The A An And But Or If Then When While I He She It We They You His Her Their Our My Your This That
These Those There Here What Who Why How Where Yes No Oh Ah Well Now So Not Nor For Yet Upon Into With Without
Chapter Book Part Stave Mr Mrs Miss Dr Sir Lady Lord God Heaven Christmas Monday Tuesday Wednesday Thursday Friday
Saturday Sunday January February March April May June July August September October November December
Project Gutenberg Ebook Old Nay Aye Alas Indeed Perhaps Very Do Does Did Is Was Be Let Come Go Ha Hush""".split())

MALE_POOL = ["bm_george", "am_michael", "bm_daniel", "am_onyx", "bm_fable", "am_fenrir", "am_puck", "bm_lewis"]
FEMALE_POOL = ["bf_emma", "af_bella", "bf_isabella", "af_heart", "bf_alice", "af_nicole", "bf_lily", "af_sky"]

# mood -> soundscape layers; the music beds are chosen to sit well under speech
MOODS = {
    "night": {"label": "Night & dread", "amb": "roomtone creaks=0.5 vol=-2", "music": "dread root=D2 vol=-13",
              "extra": "clock clock rate=1 vol=-19 duck=2"},
    "storm": {"label": "Storm & rain", "amb": "rain intensity=0.6 vol=-10", "music": "dread root=C2 vol=-15",
              "extra": "wind wind intensity=0.6 howl=0.4 vol=-14"},
    "hearth": {"label": "Fireside winter", "amb": "fire size=0.5 vol=-9", "music": "hearth vol=-14",
               "extra": "wind wind intensity=0.3 howl=0.2 vol=-18"},
    "epic": {"label": "Ancient & epic", "amb": "wind intensity=0.35 howl=0.15 vol=-15", "music": "elegy vol=-11"},
    "water": {"label": "River & sea", "amb": "river flow=0.6 vol=-12", "music": "elegy vol=-14"},
    "pastoral": {"label": "Countryside evening", "amb": "crickets density=0.5 vol=-8", "music": "hearth vol=-16",
                 "extra": "wind wind intensity=0.15 howl=0 vol=-20"},
    "quiet": {"label": "Quiet room (voice only)", "amb": "roomtone creaks=0.1 vol=-6"},
}

MOOD_WORDS = {
    "night": "night dark darkness midnight dread terror fear ghost grave corpse death shadow candle lantern horror",
    "storm": "rain raining storm thunder lightning tempest wet drenched downpour gale",
    "hearth": "fire hearth winter snow christmas frost cold chimney coal ember",
    "epic": "empire king army war battle legion emperor ancient city siege gods throne barbarian",
    "water": "sea ship ships river shore wave waves sailor ocean boat boats harbour harbor quay tide nets fisherman",
    "pastoral": "field meadow farm village garden cottage summer evening orchard hill",
}

# (regex, sfx cue) - an effect follows the paragraph that mentions it
SFX_RULES = [
    (r"\bknock(?:ed|ing|s)?\b", "knock count=3 vol=-10"),
    (r"\b(?:bell|bells)\b.*\b(?:toll|rang|ring|struck|chime)|\b(?:toll|tolled|tolling)\b", "bell count=3 vol=-12 distance=0.6"),
    (r"\bthunder\b", "thunder distance=0.5 vol=-8"),
    (r"\bdoor\b.*\b(?:open|opened|creak|creaked)\b", "door kind=open vol=-14"),
    (r"\b(?:slammed|slam)\b", "door kind=slam vol=-10"),
    (r"\bfootsteps?\b|\bfootfall", "footsteps count=8 vol=-16"),
    (r"\bchains?\b", "chains length=3 vol=-12"),
    (r"\bclock\b.*\bstr(?:uck|ike|ikes)\b", "chime count=3 vol=-12"),
    (r"\b(?:trumpet|horn)\b", "horn vol=-14"),
    (r"\bdrums?\b", "war_drums bars=2 vol=-14"),
    (r"\bscream(?:ed)?\b|\bshriek(?:ed)?\b", "sting vol=-14"),
    (r"\bcreak(?:ed|ing|s)?\b", "creak length=1 room=room vol=-14"),
]


def strip_gutenberg(text: str) -> str:
    s = re.search(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text, re.I)
    e = re.search(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG", text, re.I)
    if s:
        text = text[s.end():]
        if e:
            e = re.search(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG", text, re.I)
            text = text[: e.start()] if e else text
    return text


def paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_gutenberg(text)
    blocks = re.split(r"\n\s*\n", text)
    if len(blocks) < 3:  # one paragraph per line style
        blocks = text.split("\n")
    out = []
    for b in blocks:
        p = " ".join(l.strip() for l in b.strip().splitlines())
        p = re.sub(r"\s+", " ", p).strip()
        p = re.sub(r"\[(?:Illustration|Footnote)[^\]]*\]", "", p).strip()
        if p and not re.fullmatch(r"[\W_]+", p):
            out.append(p)
    return out


def is_heading(p: str) -> bool:
    if len(p) > 90:
        return False
    if re.match(r"^(chapter|stave|book|part|canto|section)\b[\s\w.:—-]*$", p, re.I):
        return True
    if re.match(r"^[IVXLC]+\.?(\s|$)", p) and len(p) < 60:
        return True
    letters = re.sub(r"[^A-Za-z]", "", p)
    return len(letters) > 3 and letters.isupper() and len(p.split()) <= 10


def _norm_name(n: str) -> str:
    return re.sub(r"\s+", " ", n.strip())


def _key(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_")[:24] or "voice"


def analyze(text: str) -> dict:
    """Inspect a manuscript: paragraphs, speakers, suggested cast and mood."""
    paras = paragraphs(text)
    full = " ".join(paras)
    words = len(full.split())
    # proper-noun candidates: capitalised mid-sentence words that recur
    caps = Counter(m.group(1) for m in re.finditer(r"(?<=[a-z,;] )([A-Z][a-z]{2,})", full))
    names = {n for n, c in caps.items() if c >= 2 and n not in NOT_NAMES}

    attributions = []  # per paragraph: list of speakers per quote (or None)
    counts = Counter()
    gender = defaultdict(lambda: [0, 0])
    prev_speakers = []
    for p in paras:
        quotes = re.findall(r"“[^”]*”|\"[^\"]*\"", p)
        if not quotes or is_heading(p):
            attributions.append(None)
            continue
        narration = re.sub(r"“[^”]*”|\"[^\"]*\"", " | ", p)
        spk = None
        for rx in (RX_AFTER, RX_BEFORE):
            for m in rx.finditer(narration):
                cand = _norm_name(m.group(1))
                base = cand.split()[-1]
                if cand.split()[0] in NOT_NAMES and len(cand.split()) == 1:
                    continue
                # beside a speech verb, any capitalised non-function word is a name
                if base in names or base not in NOT_NAMES:
                    spk = cand
                    break
            if spk:
                break
        starts_with_quote = bool(re.match(r"^\s*[“\"]", p))
        pm = RX_PRONOUN.search(narration) if not spk else None
        if not spk and not pm and not starts_with_quote:
            attributions.append(None)  # quoted phrase inside narration, not speech
            continue
        if not spk:
            if len(prev_speakers) >= 2 and prev_speakers[-1] != prev_speakers[-2]:
                spk = prev_speakers[-2]  # conversational alternation
            elif pm:
                spk = "A woman" if (pm.group(1) or pm.group(2)).lower() == "she" else "A man"
            else:
                spk = "Another voice"
        # gender evidence: pronouns in the narration around the speaker's own lines
        g = narration.lower()
        gender[spk][0] += len(re.findall(r"\b(he|his|him)\b", g))
        gender[spk][1] += len(re.findall(r"\b(she|her|hers)\b", g))
        counts[spk] += len(quotes)
        attributions.append(spk)
        prev_speakers.append(spk)

    cast = []
    mi = fi = 0
    for spk, n in counts.most_common(12):
        m_, f_ = gender[spk]
        fem = spk == "A woman" or (f_ > m_ * 1.3 and spk != "A man")
        if fem:
            v = FEMALE_POOL[fi % len(FEMALE_POOL)]
            fi += 1
        else:
            v = MALE_POOL[mi % len(MALE_POOL)]
            mi += 1
        cast.append({"name": spk, "key": _key(spk), "lines": n, "voice": v, "gender": "female" if fem else "male"})

    low = full.lower()
    scores = {m: sum(len(re.findall(rf"\b{w}\b", low)) for w in ws.split()) for m, ws in MOOD_WORDS.items()}
    mood = max(scores, key=scores.get) if max(scores.values()) >= 2 else "quiet"
    return {
        "paragraphs": len(paras),
        "words": words,
        "minutes": round(words / 140, 1),
        "headings": sum(is_heading(p) for p in paras),
        "cast": cast,
        "mood": mood,
        "moods": {k: v["label"] for k, v in MOODS.items()},
        "_attributions": attributions,
        "_paras": paras,
    }


def build_script(text: str, title: str = "Untitled", author: str = "Anonymous", narrator_voice: str = "bm_lewis",
                 cast_overrides: dict | None = None, mood: str | None = None, sound_effects: bool = True,
                 speed: float = 0.95) -> str:
    """Produce .story source for a manuscript."""
    info = analyze(text)
    mood = mood if mood in MOODS else info["mood"]
    cast_overrides = cast_overrides or {}
    cast = {"narrator": {"voice": narrator_voice, "speed": speed, "room": "room", "wet": 0.07}}
    keymap = {}
    for c in info["cast"]:
        v = cast_overrides.get(c["key"], c["voice"])
        keymap[c["name"]] = c["key"] if c["key"] != "narrator" else "narrator_char"
        cast[keymap[c["name"]]] = {"voice": v, "speed": 1.0, "room": "room", "wet": 0.06}
    front = {"title": title, "author": author, "cast": cast}
    out = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(), "---", ""]
    m = MOODS[mood]
    out += ["[bed music title_theme vol=-8 fade=2]", "[pause 2.5]",
            f"# {title}. By {author}.", "[sfx boom pitch=38 length=4 vol=-14]"]
    out.append("[stop music fade=5]")
    if "amb" in m:
        out.append(f"[bed amb {m['amb']} fade=5]")
    if "music" in m:
        out.append(f"[bed music {m['music']} fade=8]")
    if "extra" in m:
        out.append(f"[bed {m['extra']} fade=6]")  # "<layer> <bed> params"
    out += ["[pause 1.5]", ""]

    last_sfx = defaultdict(lambda: -99)
    for i, (p, spk) in enumerate(zip(info["_paras"], info["_attributions"])):
        if is_heading(p):
            out += ["[pause 1]", "[sfx swell length=2.5 vol=-20 wait=2.4]", f"# {p.rstrip('.')}", ""]
            continue
        safe = p.replace("[", "(").replace("]", ")")
        if safe.startswith(("@", "#", "//")):
            safe = " " + safe
        if spk:
            out.append(f"@{keymap.get(spk, 'narrator')}: {safe}")
        else:
            out.append(safe)
        out.append("")
        if sound_effects:
            for rx, cue in SFX_RULES:
                name = cue.split()[0]
                if re.search(rx, p, re.I) and i - last_sfx[name] > 6:
                    out += [f"[sfx {cue}]", ""]
                    last_sfx[name] = i
                    break
    out += ["[pause 2]", "[stop fade=7]", "[pause 3]"]
    return "\n".join(out) + "\n"
