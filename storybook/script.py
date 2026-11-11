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
            m = re.match(r"^(@@?)([\w,\-]+):\s*(.*)$", paragraph, re.S)
            if m and m.group(1) == "@@":
                events.append(Line(m.group(2), m.group(3), para))
            elif m:
                for spk, txt in split_dialogue(m.group(3), m.group(2).split(",")):
                    events.append(Line(spk, txt, para))
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
    return Script(meta, cast, events)
