"""python -m storybook render scripts/tell_tale_heart.story [-o audiobooks/]"""
import argparse
import sys
import time
from pathlib import Path

from .render import render
from .script import parse


def main(argv=None):
    ap = argparse.ArgumentParser(prog="storybook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render a .story script to a mastered MP3")
    r.add_argument("scripts", nargs="+", type=Path)
    r.add_argument("-o", "--out", type=Path, default=Path("site/audio"))
    r.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("serve", help="run the website + Studio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    if a.cmd == "render":
        for sc in a.scripts:
            t = time.time()
            last = [0.0]

            def prog(frac, msg):
                if time.time() - last[0] > 5:
                    print(f"  [{frac*100:5.1f}%] {msg}", flush=True)
                    last[0] = time.time()
            info = render(parse(sc.read_text()), a.out / sc.stem, a.seed, prog)
            print(f"{sc.stem}: {info['duration']/60:.1f} min rendered in {(time.time()-t)/60:.1f} min")
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("server.app:app", host=a.host, port=a.port)


if __name__ == "__main__":
    sys.exit(main())
