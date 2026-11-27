#!/usr/bin/env python3
"""Match a text block on a flat design image to a font file by stroke thickness.

Weight-and-family tool for `references/workflow-loops.md` § Build from a supplied design source.
A flat board (PNG, JPEG) carries no font data, so its weight is measured: the board's text is
upscaled to a common measure scale, each candidate font file renders the same string at the
measured size and the same scale, and the median horizontal ink-run length (the stroke) of the
middle third of each is compared. The closest stroke is the weight; the ink width checks family
and size.

Usage:
  python3 ~/.claude/bin/design-type-match.py BOARD.png --box X,Y,W,H --scale 1.5 \
      --text "8,114" --size 62 --font Medium.otf --font DemiBold.otf --font Bold.otf \
      [--measure-scale 3] [--json]

  --box            the text's box in points (1x units, the board's CSS px or pt), scaled by --scale
  --scale          board pixels per point (585 px wide for a 390 pt frame is 1.5)
  --text           the exact string the box shows
  --size           the measured font size in points
  --font           a candidate font file, repeatable; PATH#N picks face N of a .ttc collection
  --measure-scale  pixels per point both sides are compared at (default 3)

Prints the board's stroke and ink width, each font's stroke, ink width and deltas, and the
closest font by stroke (ink width breaks a tie). A font whose ink width is off by more than 5%
is flagged: check its family or the measured size. Two fonts within 1 px of the board's stroke
are flagged ambiguous: re-measure at a larger --measure-scale.

Exit: 0 match printed, 1 no ink in the box, 2 bad arguments or an unreadable image or font.
Needs Pillow (Homebrew `python3`; `brew install pillow`).
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("design-type-match: Pillow missing for " + sys.executable + " (brew install pillow)")

WIDTH_TOLERANCE = 0.05  # ink-width delta that flags a family or size mismatch
AMBIGUOUS_PX = 1.0      # two strokes this close to the board's cannot be told apart


class InputError(Exception):
    pass


def parse_box(value):
    try:
        x, y, w, h = (float(v) for v in value.split(","))
    except ValueError:
        raise InputError(f"--box needs X,Y,W,H numbers, got {value!r}")
    if w <= 0 or h <= 0:
        raise InputError("--box width and height must be positive")
    return x, y, w, h


def load_font(spec, px):
    path, _, index = spec.partition("#")
    if not Path(path).is_file():
        raise InputError(f"font file not found: {path}")
    try:
        return ImageFont.truetype(path, px, index=int(index or 0))
    except (OSError, ValueError) as err:
        raise InputError(f"cannot load font {spec}: {err}")


def ink_mask(gray):
    """Ink = pixels past halfway from the background (the border's median) to the farthest tone."""
    w, h = gray.size
    px = gray.load()
    border = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
    border += [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    bg = statistics.median(border)
    lo, hi = gray.getextrema()
    far = lo if bg >= 128 else hi
    if abs(far - bg) < 32:
        return None
    cut = (bg + far) / 2
    dark_ink = far < bg
    return [[(px[x, y] < cut) if dark_ink else (px[x, y] > cut) for x in range(w)] for y in range(h)]


def measure(gray):
    """Median horizontal ink run over the middle third of the ink box, plus the ink box size."""
    mask = ink_mask(gray)
    if mask is None:
        return None
    rows = [y for y, row in enumerate(mask) if any(row)]
    cols = [x for x in range(len(mask[0])) if any(row[x] for row in mask)]
    if not rows:
        return None
    top, bottom = rows[0], rows[-1] + 1
    third = (bottom - top) / 3
    runs = []
    for y in range(int(top + third), max(int(top + 2 * third), int(top + third) + 1)):
        run = 0
        for on in mask[y] + [False]:
            if on:
                run += 1
            elif run:
                runs.append(run)
                run = 0
    if not runs:
        return None
    return {"stroke": statistics.median(runs), "ink_width": cols[-1] + 1 - cols[0], "ink_height": bottom - top}


def board_text(board, box, scale, m):
    x, y, w, h = box
    crop = board.crop((round(x * scale), round(y * scale), round((x + w) * scale), round((y + h) * scale)))
    if crop.size[0] < 2 or crop.size[1] < 2:
        raise InputError("--box lies outside the board")
    target = (max(1, round(w * m)), max(1, round(h * m)))
    return crop.convert("L").resize(target, Image.LANCZOS)


def render(font, text, m_pad):
    left, top, right, bottom = font.getbbox(text)
    img = Image.new("L", (right - left + 2 * m_pad, bottom - top + 2 * m_pad), 255)
    ImageDraw.Draw(img).text((m_pad - left, m_pad - top), text, font=font, fill=0)
    return img


def match(board_path, box, scale, text, size, fonts, m):
    try:
        board = Image.open(board_path)
        board.load()
    except (OSError, ValueError) as err:
        raise InputError(f"cannot read board {board_path}: {err}")
    loaded = [(spec, load_font(spec, round(size * m))) for spec in fonts]  # bad font: exit 2 first
    flat = Image.new("RGBA", board.size, (255, 255, 255, 255))
    flat.alpha_composite(board.convert("RGBA"))  # a transparent board reads as white, not black
    measured = measure(board_text(flat.convert("RGB"), box, scale, m))
    if measured is None:
        return None
    rows = []
    for spec, font in loaded:
        got = measure(render(font, text, round(4 * m)))
        if got is None:
            raise InputError(f"font {spec} rendered no ink for {text!r}")
        width_delta = (got["ink_width"] - measured["ink_width"]) / measured["ink_width"]
        rows.append({"font": spec, **got, "stroke_delta": got["stroke"] - measured["stroke"],
                     "width_delta_pct": round(100 * width_delta, 1),
                     "width_mismatch": abs(width_delta) > WIDTH_TOLERANCE})
    rows.sort(key=lambda r: (abs(r["stroke_delta"]), abs(r["width_delta_pct"])))
    near = [r for r in rows if abs(r["stroke_delta"]) <= AMBIGUOUS_PX]
    return {"board": str(board_path), "measure_scale": m, "text": text, "size_pt": size,
            "board_stroke": measured["stroke"], "board_ink_width": measured["ink_width"],
            "fonts": rows, "closest": rows[0]["font"], "ambiguous": len(near) > 1}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("board")
    p.add_argument("--box", required=True)
    p.add_argument("--scale", type=float, required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--size", type=float, required=True)
    p.add_argument("--font", action="append", required=True)
    p.add_argument("--measure-scale", type=float, default=3.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.scale <= 0 or args.size <= 0 or args.measure_scale <= 0:
            raise InputError("--scale, --size and --measure-scale must be positive")
        result = match(args.board, parse_box(args.box), args.scale, args.text, args.size,
                       args.font, args.measure_scale)
    except InputError as err:
        print(f"design-type-match: {err}", file=sys.stderr)
        return 2
    if result is None:
        print("design-type-match: no ink in the box; check --box and --scale", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"board stroke {result['board_stroke']:g} px, ink width {result['board_ink_width']} px "
          f"at {args.measure_scale:g}x for {args.text!r} at {args.size:g} pt")
    for r in result["fonts"]:
        flag = "  width mismatch: check family or size" if r["width_mismatch"] else ""
        print(f"  {r['font']}: stroke {r['stroke']:g} px ({r['stroke_delta']:+g}), "
              f"ink width {r['ink_width']} px ({r['width_delta_pct']:+g}%){flag}")
    print(f"closest: {result['closest']}")
    if result["ambiguous"]:
        print("ambiguous: two fonts within 1 px of the board stroke; re-run with a larger --measure-scale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
