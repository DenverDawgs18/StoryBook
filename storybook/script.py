"""The .story production-script format.

    ---
    title: The Tell-Tale Heart
    author: Edgar Allan Poe
    cast:
      narrator: {voice: bm_lewis, speed: 0.9}
      officer:  {voice: am_michael, speed: 1.0}
    ---
    # A heading (spoken, and becomes a chapter marker)

    [bed amb roomtone vol=-6 fade=4]      start/replace a layer
    [stop amb fade=6]
    [sfx bell count=3 vol=-8 wait=1]      one-shot (wait=1: let it finish first)
    [pause 2.5]
    [voice narrator speed=0.84]           change a cast member from here on

    Plain paragraphs are read by the narrator.
    @officer: “Quoted words” go to officer; the rest, said the narrator, stays narration.
    @scrooge,fred: first quote to scrooge, second to fred, any further to fred.
    @@ghost: The entire paragraph is voiced by ghost, quotes or not.
    @wolf,pig!snap,wolf!rage: a "!delivery" on a speaker directs that one line
                              (see voices.DELIVERIES: snap, shout, rage).
                              Undirected lines are directed automatically (see `direct`);
                              "!plain" turns that off for one line.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

import yaml


@dataclass
class Line:
    speaker: str
    text: str
    para: int
    delivery: str | None = None


@dataclass
class Cue:
    kind: str  # bed | stop | sfx | pause | voice | heading | para_break
    args: list = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class Script:
    meta: dict
    cast: dict
    events: list  # of Line | Cue


QUOTE_RX = re.compile(r"“([^”]*)”|\"([^\"]*)\"")


def _params(tokens):
    args, params = [], {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k] = v
        else:
            args.append(tok)
    return args, params


def split_dialogue(text: str, speakers: list[str], narrator: str = "narrator"):
    """Split a paragraph into narration and quoted speech."""
    out = []
    pos = 0
    qi = 0
    for m in QUOTE_RX.finditer(text):
        before = text[pos:m.start()].strip(" ,")
        if before.strip():
            out.append((narrator, before))
        quote = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        if quote:
            spk = speakers[min(qi, len(speakers) - 1)] if speakers else narrator
            out.append((spk, quote))
            qi += 1
        pos = m.end()
    rest = text[pos:].strip(" ,")
    if rest.strip():
        out.append((narrator, rest))
    return out


# --------------------------------------------------------------------------
# automatic direction: read the cues a human reader would act on
# --------------------------------------------------------------------------
_RAGE = re.compile(r"\b(in a (?:rage|fury|passion)|furious(?:ly)?|scream(?:ed|ing)|shriek(?:ed|ing)|howl(?:ed|ing)|"
                   r"bellow(?:ed|ing)|roar(?:ed|ing)|with all (?:his|her|their) might)\b", re.I)
_SHOUT = re.compile(r"\b(cried|cries|cry(?:ing)?|shout(?:ed|ing)?|call(?:ed|ing) out|exclaim(?:ed|ing)?|yell(?:ed|ing)?)\b", re.I)
# exclamations that are sighs or wonder, not raised voices
_SIGH = re.compile(r"^(?:o|oh|ah|alas|ha|well)\b(?:[\s,!]*$|,)", re.I)


def _words(t: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", t))


def direct(events: list) -> list:
    """Give each undirected line of dialogue a delivery from its own text and the narration around it.

    rage   the narration says the speaker screams, roars, is in a rage...  ("...cried the little man, in a rage")
    shout  the narration says they cried out, shouted, exclaimed, and the line is an exclamation;
           or the narration uses a rage word but the line is calm; or several short exclamations in a row
    snap   a short exclamation on its own ("No, madam!", "Nonsense!") that isn't a sigh ("Alas!", "Ah!")
    Only the narration that tags the line counts: the bit just after it, or a lead-in that runs into it
    ("...and cried:"), never the end of an earlier sentence.
    """
    for i, e in enumerate(events):
        if not isinstance(e, Line) or e.speaker == "narrator" or e.delivery:
            if isinstance(e, Line) and e.delivery == "plain":
                e.delivery = None
            continue
        tag = ""
        nxt = events[i + 1] if i + 1 < len(events) else None
        if isinstance(nxt, Line) and nxt.speaker == "narrator" and nxt.para == e.para:
            tag += " " + " ".join(nxt.text.split()[:12])
        prv = events[i - 1] if i > 0 else None
        if isinstance(prv, Line) and prv.speaker == "narrator" and prv.para == e.para:
            tail = prv.text.rstrip()
            if not tail.endswith((".", "?", "!", ";")):
                tag += " " + " ".join(tail.split()[-8:])
        text = e.text.strip()
        excl = text.endswith("!") or text.count("!") >= 2
        if _RAGE.search(tag):
            e.delivery = "rage" if excl else "shout"
        elif _SHOUT.search(tag) and excl:
            e.delivery = "shout"
        elif excl and text.count("!") >= 3 and _words(text) <= 14:
            e.delivery = "shout"
        elif excl and _words(text) <= 3 and not _SIGH.match(text):
            e.delivery = "snap"
    return events


def parse(src: str) -> Script:
    meta, cast = {}, {}
    body = src
    if src.lstrip().startswith("---"):
        _, front, body = src.split("---", 2)
        meta = yaml.safe_load(front) or {}
        cast = meta.pop("cast", {}) or {}
    cast.setdefault("narrator", {"voice": "bm_george"})
    events = []
    para = 0
    blocks = re.split(r"\n\s*\n", body.strip())
    for block in blocks:
        lines = [l.rstrip() for l in block.strip().splitlines()]
        text_lines = []

        def flush():
            nonlocal para
            if not text_lines:
                return
            paragraph = " ".join(l.strip() for l in text_lines)
            text_lines.clear()
            m = re.match(r"^(@@?)([\w,!\-]+):\s*(.*)$", paragraph, re.S)
            if m and m.group(1) == "@@":
                spk, _, how = m.group(2).partition("!")
                events.append(Line(spk, m.group(3), para, how or None))
            elif m:
                for spk, txt in split_dialogue(m.group(3), m.group(2).split(",")):
                    spk, _, how = spk.partition("!")
                    events.append(Line(spk, txt, para, how or None))
            else:
                for spk, txt in split_dialogue(paragraph, []):
                    events.append(Line(spk, txt, para))
            events.append(Cue("para_break"))
            para += 1

        for l in lines:
            s = l.strip()
            if s.startswith("//"):
                continue
            if s.startswith("[") and s.endswith("]"):
                flush()
                toks = shlex.split(s[1:-1])
                args, params = _params(toks[1:])
                events.append(Cue(toks[0], args, params))
            elif s.startswith("# "):
                flush()
                events.append(Cue("heading", [s[2:].strip()]))
            else:
                text_lines.append(s)
        flush()
    for name, d in cast.items():
        if isinstance(d, str):
            cast[name] = {"voice": d}
    if meta.get("direct", True):
        direct(events)
    return Script(meta, cast, events)
