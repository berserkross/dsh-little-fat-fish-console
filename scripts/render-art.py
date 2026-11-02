#!/usr/bin/env python3
"""Rasterize the console mascot SVG sources into the shipped PNGs.

Every PNG is produced from dshconsole/data/art/src/*.svg through headless
Chrome, one browser launch per asset, at the exact pixel size it ships in.
No third-party rasterizer is involved: Pillow only composites the preview
and zoom sheets.

Usage:
    python scripts/render-art.py              # render everything
    python scripts/render-art.py --only mascot_idle@72
    python scripts/render-art.py --verify     # render, then print the QA table
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "dshconsole" / "data" / "art"
SRC = ART / "src"

# (source svg, output png, pixel size)
ASSETS = [
    ("mascot_idle@72.svg", "mascot_idle@72.png", 72),
    ("mascot_running@72.svg", "mascot_running@72.png", 72),
    ("mascot_error@72.svg", "mascot_error@72.png", 72),
    ("mascot_hero@256.svg", "mascot_hero@256.png", 256),
    ("mascot_logo@32.svg", "mascot_logo@32.png", 32),
]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden}"
    "svg{display:block}</style></head><body>%s</body></html>"
)


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise SystemExit("no Chrome/Edge binary found; edit CHROME_CANDIDATES")


def sized_svg(svg_text: str, size: int) -> str:
    """Return the SVG markup with the root element pinned to size x size."""
    text = re.sub(r"<\?xml[^>]*\?>", "", svg_text).strip()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()

    def fix(match: re.Match) -> str:
        tag = match.group(0)
        tag = re.sub(r'\s(width|height)="[^"]*"', "", tag)
        return tag[:-1] + ' width="%d" height="%d">' % (size, size)

    return re.sub(r"<svg\b[^>]*>", fix, text, count=1)


ATTEMPTS = 4
ATTEMPT_TIMEOUT = 25.0


def render_one(chrome: str, svg_path: Path, png_path: Path, size: int, work: Path) -> None:
    page_dir = work / ("%s_%d" % (svg_path.stem.replace("@", "-"), size))
    page_dir.mkdir(parents=True, exist_ok=True)
    page = page_dir / "index.html"
    page.write_text(PAGE % sized_svg(svg_path.read_text(encoding="utf-8"), size), encoding="utf-8")

    last_error = "unknown"
    for attempt in range(1, ATTEMPTS + 1):
        case = page_dir / ("run%d" % attempt)
        shutil.rmtree(case, ignore_errors=True)
        case.mkdir(parents=True, exist_ok=True)
        out = case / "shot.png"
        cmd = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--user-data-dir=%s" % (case / "profile"),
            "--window-size=%d,%d" % (size, size),
            "--screenshot=%s" % out,
            page.as_uri(),
        ]
        # Chrome detaches on Windows, so the PNG shows up asynchronously.
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + ATTEMPT_TIMEOUT
        stable = -1
        while time.time() < deadline:
            if out.exists():
                now = out.stat().st_size
                if now and now == stable:
                    break
                stable = now
            time.sleep(0.2)
        if out.exists() and out.stat().st_size:
            png_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, png_path)
            return
        last_error = (proc.stderr or b"").decode("utf-8", "replace").strip()[:400] or "no screenshot written"
        time.sleep(0.6)
    raise SystemExit("chrome failed for %s: %s" % (svg_path.name, last_error))


def build_preview() -> None:
    """Composite _zoom32.png and _preview.png from the rendered PNGs."""
    from PIL import Image, ImageDraw, ImageFont

    def load(name: str) -> Image.Image:
        return Image.open(ART / name).convert("RGBA")

    def font(px: int):
        try:
            return ImageFont.load_default(size=px)
        except TypeError:  # pragma: no cover - very old Pillow
            return ImageFont.load_default()

    cells = [("mascot_idle@72.png", 72), ("mascot_running@72.png", 72),
             ("mascot_error@72.png", 72), ("mascot_logo@32.png", 32),
             ("mascot_hero@256.png", 256)]

    # _zoom32.png: the 32 px logo at 6x, plus a checkerboard for alpha proof.
    base = load("mascot_logo@32.png")
    zoom = base.resize((32 * 6, 32 * 6), Image.NEAREST)
    pad = 24
    sheet = Image.new("RGBA", (zoom.width + pad * 2, zoom.height + pad * 2), (0, 0, 0, 0))
    checker = Image.new("RGBA", sheet.size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(checker)
    step = 12
    for y in range(0, sheet.height, step):
        for x in range(0, sheet.width, step):
            if ((x // step) + (y // step)) % 2:
                draw.rectangle([x, y, x + step - 1, y + step - 1], fill=(226, 232, 240, 255))
    checker.alpha_composite(Image.new("RGBA", sheet.size, (0, 0, 0, 0)))
    bg = Image.new("RGBA", sheet.size, (255, 255, 255, 255))
    bg.paste(Image.alpha_composite(Image.new("RGBA", sheet.size, (0, 0, 0, 0)), checker).convert("RGB"), (0, 0))
    bg.alpha_composite(zoom, (pad, pad))
    bg.save(ART / "_zoom32.png")

    # _preview.png: all five assets on one checkerboard sheet with labels.
    pad = 32
    cell_w = 144
    small = [c for c in cells if c[1] != 256]
    hero = [c for c in cells if c[1] == 256][0]
    row_w = cell_w * len(small)
    width = max(row_w + pad * 2, 660)
    row_y = 104
    label_y = row_y + 88
    hero_y = label_y + 46 + 40
    height = hero_y + 256 + pad + 58
    sheet = Image.new("RGBA", (width, height), (248, 250, 252, 255))
    draw = ImageDraw.Draw(sheet)
    step = 16
    for cy in range(0, height, step):
        for cx in range(0, width, step):
            if ((cx // step) + (cy // step)) % 2:
                draw.rectangle([cx, cy, cx + step - 1, cy + step - 1], fill=(237, 241, 246, 255))
    title = font(22)
    meta = font(14)
    draw.text((pad, 26), "DSH Console - original blue-whale mascot set", font=title, fill=(10, 30, 60, 255))
    draw.text((pad, 60), "project-owned art - MIT - regenerate with: python scripts/render-art.py",
              font=meta, fill=(90, 110, 140, 255))
    for i, (name, size) in enumerate(small):
        cell_x = pad + i * cell_w
        img = load(name)
        img_x = cell_x + (cell_w - size) // 2
        sheet.alpha_composite(img, (img_x, row_y))
        draw.rectangle([img_x - 1, row_y - 1, img_x + size, row_y + size], outline=(150, 170, 196, 255))
        stem, _, ext = name.partition("@")
        draw.text((cell_x, label_y), stem, font=meta, fill=(40, 60, 90, 255))
        draw.text((cell_x, label_y + 18), "@" + ext, font=meta, fill=(40, 60, 90, 255))
        draw.text((cell_x, label_y + 36), "%dpx RGBA" % size, font=meta, fill=(90, 110, 140, 255))
    hero_img = load("mascot_hero@256.png")
    sheet.alpha_composite(hero_img, (pad, hero_y))
    draw.rectangle([pad - 1, hero_y - 1, pad + 256, hero_y + 256], outline=(150, 170, 196, 255))
    draw.text((pad + 276, hero_y + 8), "mascot_hero@256.png", font=meta, fill=(40, 60, 90, 255))
    draw.text((pad + 276, hero_y + 28), "256x256 RGBA - empty-state hero", font=meta, fill=(90, 110, 140, 255))
    sheet.convert("RGB").save(ART / "_preview.png")


def verify() -> None:
    from PIL import Image

    print("%-24s %-9s %-5s %-7s %-7s %s" % ("file", "size", "mode", "alpha%", "corners", "bytes"))
    ok = True
    for _, name, size in ASSETS:
        path = ART / name
        if not path.exists():
            print("%-24s %-9s %-5s %-7s %-7s %s" % (name, "-", "-", "-", "-", "MISSING"))
            ok = False
            continue
        img = Image.open(path).convert("RGBA")
        alpha = img.getchannel("A")
        covered = sum(alpha.histogram()[1:]) / (size * size) * 100
        corners = [img.getpixel(p)[3] for p in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1))]
        good = img.size == (size, size) and 8 < covered < 95 and max(corners) == 0
        ok = ok and good
        print("%-24s %-9s %-5s %-7.2f %-7s %d%s" % (
            name, "%dx%d" % img.size, img.mode, covered,
            "clear" if max(corners) == 0 else "DIRTY", path.stat().st_size, "" if good else "  <-- FAIL"))
    print("result:", "PASS" if ok else "FAIL")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="render a single asset by source stem, e.g. mascot_idle@72")
    ap.add_argument("--verify", action="store_true", help="print the QA table after rendering")
    ap.add_argument("--no-sheet", action="store_true", help="skip _zoom32.png and _preview.png")
    ap.add_argument("--work", help="scratch directory for the headless pages (default: build/art-render)")
    args = ap.parse_args()

    chrome = find_chrome()
    # A plain directory under build/: Chrome refuses to start inside a
    # tempfile.mkdtemp() root on Windows (Python 3.12+ restricts its ACL).
    work = Path(args.work) if args.work else ROOT / "build" / "art-render"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        for src_name, png_name, size in ASSETS:
            if args.only and args.only not in (src_name, Path(src_name).stem):
                continue
            render_one(chrome, SRC / src_name, ART / png_name, size, work)
            print("rendered %s  %dx%d" % (png_name, size, size))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not args.no_sheet and not args.only:
        build_preview()
        print("composited _zoom32.png and _preview.png")
    if args.verify:
        verify()


if __name__ == "__main__":
    main()