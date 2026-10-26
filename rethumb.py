#!/usr/bin/env python3
"""Redo only the thumbnails of an existing run (no video re-render).

    python rethumb.py --text "HWM #7"                      # chic : Hello World Mix / HWM #7
    python rethumb.py --text "Hello World Mix | HWM #7"
    python rethumb.py --text "HWM #7" --style modern --outputs outputs
"""

import argparse
import glob
import os
import re
from types import SimpleNamespace

from clipping import studio


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--text", required=True, help="Text written on every thumbnail.")
    p.add_argument("--outputs", default="outputs", help="Folder with highlight_rank_N_ready.mp4.")
    p.add_argument("--style", choices=["chic", "modern", "classic"], default="chic")
    p.add_argument("--font", default=None, help="Optional .ttf/.otf for the title.")
    p.add_argument("--title", default="Hello World Mix", help="Chic style: main title line.")
    p.add_argument("--hook-duration", type=float, default=3.0)
    p.add_argument("--mire-duration", type=float, default=1.0)
    a = p.parse_args()

    base = os.getcwd()
    cfg = SimpleNamespace(
        thumb_style=a.style, thumb_font=a.font, thumb_title=a.title,
        durasi_hook=a.hook_duration, mire_duration=a.mire_duration,
        file_font_thumbnail=os.path.join(base, "Montserrat-Black.ttf"),
        url_font_thumbnail="https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf",
    )
    videos = sorted(glob.glob(os.path.join(a.outputs, "highlight_rank_*_ready.mp4")))
    if not videos:
        raise SystemExit(f"Aucun clip trouvé dans {a.outputs}/")
    for v in videos:
        rank = re.search(r"highlight_rank_(\w+?)_ready", v).group(1)
        out = os.path.join(a.outputs, f"thumbnail_rank_{rank}.jpg")
        studio.buat_thumbnail(v, out, a.text, cfg)
        print(f"✅ {out}")


if __name__ == "__main__":
    main()
