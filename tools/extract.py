"""Pull a passage out of a Project Gutenberg text as clean, unwrapped paragraphs.

    python tools/extract.py pg2148.txt 4646 4900 > draft.txt
Drops Gibbon-style footnote blocks ("12 (return) [ ... ]") and inline note numbers.
"""
import re
import sys


def main(path, a, b):
    lines = open(path, encoding="utf-8-sig").read().replace("\r", "").split("\n")[int(a) - 1:int(b)]
    text = "\n".join(lines)
    text = re.sub(r"\n\s*\d+ \(return\) \[.*?\]\s*(?=\n\s*\n|\Z)", "\n", text, flags=re.S)
    paras = [" ".join(l.strip() for l in p.splitlines()) for p in re.split(r"\n\s*\n", text)]
    out = []
    for p in paras:
        p = re.sub(r"(?<=[a-z.,;:!?’”)])\s\d{1,3}(?=\s|$)", "", p)  # inline footnote markers
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            out.append(p)
    print("\n\n".join(out))


if __name__ == "__main__":
    main(*sys.argv[1:])
