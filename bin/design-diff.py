#!/usr/bin/env python3
"""Pixel-diff a design image against a built capture and write a design | built | changed panel.

Any-engine overlay tool for `references/workflow-loops.md` § Build from a supplied design source.
Same-engine renders keep pixelmatch as the comparator; this script works on any two PNGs (a board
rendered by one tool, a capture from a browser or simulator) and reports where they differ.

Usage:
  python3 ~/.claude/bin/design-diff.py DESIGN.png BUILT.png --out PANEL.png \
      [--dpr 2] [--mask X,Y,W,H ...] [--threshold 0.1] [--max-changed 0.5] [--top 10] [--json]

  --dpr          device pixels per CSS px of both images (default 1); masks and regions are CSS px
  --mask         CSS-px rectangle excluded from the count (a recorded exception), repeatable
  --threshold    per-pixel colour threshold, pixelmatch's YIQ scale 0..1 (default 0.1)
  --max-changed  fail (exit 1) when changed % of compared pixels exceeds this
  --top          number of changed regions to list, largest first (default 10)

Prints sizes, changed %, the largest changed regions in CSS px and the panel path. Pixels present
in only one image count as changed. The panel shows the design, the built capture and an overlay:
the built capture faded, changed pixels red, masked areas blue, listed regions outlined orange.

Exit: 0 report written (and within --max-changed), 1 over --max-changed, 2 bad arguments or an
unreadable image. PNG input only (8/16-bit, any colour type, non-interlaced); convert anything else
first, e.g. `sips -s format png in.jpg --out in.png`. Python 3.9+, standard library only.
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CELL_CSS = 8  # region grid cell, CSS px
GAP = 16      # panel gutter, image px


class ImageError(Exception):
    pass


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, width, height, bpp):
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if len(line) != stride:
            raise ImageError("truncated image data")
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                if i >= bpp:
                    line[i] = (line[i] + _paeth(line[i - bpp], prev[i], prev[i - bpp])) & 255
                else:
                    line[i] = (line[i] + prev[i]) & 255
        elif ftype != 0:
            raise ImageError(f"unknown PNG filter {ftype}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def read_png(path):
    """Return (width, height, RGBA bytearray)."""
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise ImageError(f"{path}: {e.strerror}") from e
    if not data.startswith(PNG_SIG):
        raise ImageError(f"{path}: not a PNG; convert it first (sips -s format png IN --out OUT.png)")
    pos, idat, palette, trns = 8, bytearray(), None, None
    width = height = depth = ctype = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if interlace:
                raise ImageError(f"{path}: interlaced PNG; re-save it non-interlaced")
            if depth not in (8, 16) and not (ctype == 3 and depth in (1, 2, 4, 8)):
                raise ImageError(f"{path}: unsupported bit depth {depth}")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None:
        raise ImageError(f"{path}: missing IHDR")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ImageError(f"{path}: unknown colour type {ctype}")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise ImageError(f"{path}: corrupt image data ({e})") from e
    if ctype == 3 and depth < 8:
        bpp, stride = 1, (width * depth + 7) // 8
        rows = _unfilter(raw, stride, height, 1)
        per, mask = 8 // depth, (1 << depth) - 1
        idx = bytearray(width * height)
        for y in range(height):
            row = rows[y * stride:(y + 1) * stride]
            for x in range(width):
                idx[y * width + x] = (row[x // per] >> (8 - depth * (x % per + 1))) & mask
        samples, channels = idx, 1
    else:
        bpp = channels * depth // 8
        samples = _unfilter(raw, width, height, bpp)
        if depth == 16:
            samples = samples[0::2]
    n = width * height
    rgba = bytearray(n * 4)
    if ctype == 6:
        rgba[:] = samples
    elif ctype == 2:
        rgba[0::4], rgba[1::4], rgba[2::4] = samples[0::3], samples[1::3], samples[2::3]
        rgba[3::4] = b"\xff" * n
    elif ctype == 0:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = samples
        rgba[3::4] = b"\xff" * n
    elif ctype == 4:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = samples[0::2]
        rgba[3::4] = samples[1::2]
    else:
        if palette is None:
            raise ImageError(f"{path}: palette PNG without PLTE")
        alpha = trns or b""
        lut = [bytes(palette[i * 3:i * 3 + 3]) + bytes([alpha[i] if i < len(alpha) else 255])
               for i in range(len(palette) // 3)]
        try:
            rgba = bytearray(b"".join(lut[i] for i in samples))
        except IndexError as e:
            raise ImageError(f"{path}: palette index out of range") from e
    return width, height, rgba


def write_png(path, width, height, rgb):
    """Write an 8-bit RGB PNG from a flat RGB bytearray."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def _blend_white(r, g, b, a):
    if a == 255:
        return r, g, b
    k = a / 255
    return 255 + (r - 255) * k, 255 + (g - 255) * k, 255 + (b - 255) * k


def _delta(p, q):
    """pixelmatch's YIQ colour delta between two RGBA tuples, both blended on white."""
    r1, g1, b1 = _blend_white(*p)
    r2, g2, b2 = _blend_white(*q)
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    y = dr * 0.29889531 + dg * 0.58662247 + db * 0.11448223
    i = dr * 0.59597799 - dg * 0.27417610 - db * 0.32180189
    k = dr * 0.21147017 - dg * 0.52261711 + db * 0.31114694
    return 0.5053 * y * y + 0.299 * i * i + 0.1957 * k * k


def parse_mask(text):
    try:
        x, y, w, h = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"mask must be X,Y,W,H in CSS px, got {text!r}") from None
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"mask needs a positive width and height: {text!r}")
    return x, y, w, h


def compare(design, built, dpr, masks, threshold):
    (wa, ha, a), (wb, hb, b) = design, built
    width, height = max(wa, wb), max(ha, hb)
    masked = bytearray(width * height)
    for x, y, w, h in masks:
        x0, y0 = max(0, int(x * dpr)), max(0, int(y * dpr))
        x1, y1 = min(width, int(round((x + w) * dpr))), min(height, int(round((y + h) * dpr)))
        for yy in range(y0, y1):
            masked[yy * width + x0:yy * width + x1] = b"\x01" * max(0, x1 - x0)
    changed = bytearray(width * height)
    max_delta = 35215 * threshold * threshold
    for y in range(height):
        ra = a[y * wa * 4:(y + 1) * wa * 4] if y < ha else b""
        rb = b[y * wb * 4:(y + 1) * wb * 4] if y < hb else b""
        if wa == wb and ra == rb and ra:
            continue
        base = y * width
        for x in range(width):
            in_a, in_b = x < wa and y < ha, x < wb and y < hb
            if in_a and in_b:
                pa, pb = ra[x * 4:x * 4 + 4], rb[x * 4:x * 4 + 4]
                if pa == pb or _delta(tuple(pa), tuple(pb)) <= max_delta:
                    continue
            changed[base + x] = 1
    n_masked = sum(masked)
    hits = 0
    for i in range(width * height):
        if changed[i] and masked[i]:
            changed[i] = 0
        elif changed[i]:
            hits += 1
    return width, height, changed, masked, hits, width * height - n_masked


def regions(changed, width, height, dpr):
    cell = max(1, int(round(CELL_CSS * dpr)))
    cols, rows = (width + cell - 1) // cell, (height + cell - 1) // cell
    counts = [0] * (cols * rows)
    for y in range(height):
        row = changed[y * width:(y + 1) * width]
        if not any(row):
            continue
        cy = (y // cell) * cols
        for x in range(width):
            if row[x]:
                counts[cy + x // cell] += 1
    seen, found = [False] * len(counts), []
    for start, n in enumerate(counts):
        if not n or seen[start]:
            continue
        stack, seen[start] = [start], True
        x0 = x1 = start % cols
        y0 = y1 = start // cols
        total = 0
        while stack:
            c = stack.pop()
            cx, cy = c % cols, c // cols
            total += counts[c]
            x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < cols and 0 <= ny < rows:
                        nc = ny * cols + nx
                        if counts[nc] and not seen[nc]:
                            seen[nc] = True
                            stack.append(nc)
        px0, py0 = x0 * cell, y0 * cell
        px1, py1 = min(width, (x1 + 1) * cell), min(height, (y1 + 1) * cell)
        found.append({"x": round(px0 / dpr), "y": round(py0 / dpr), "w": round((px1 - px0) / dpr),
                      "h": round((py1 - py0) / dpr), "changed_px": total,
                      "_box": (px0, py0, px1, py1)})
    found.sort(key=lambda r: -r["changed_px"])
    return found


def panel(design, built, width, height, changed, masked, boxes, dpr):
    (wa, ha, a), (wb, hb, b) = design, built
    total_w, total_h = wa + wb + width + 2 * GAP, max(ha, hb, height)
    out = bytearray(b"\xff" * (total_w * total_h * 3))

    def paste(src_w, src_h, src, ox):
        for y in range(src_h):
            row = src[y * src_w * 4:(y + 1) * src_w * 4]
            rgb = bytearray(src_w * 3)
            for x in range(src_w):
                r, g, bl = _blend_white(row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3])
                rgb[x * 3:x * 3 + 3] = bytes((int(r), int(g), int(bl)))
            start = (y * total_w + ox) * 3
            out[start:start + src_w * 3] = rgb

    paste(wa, ha, a, 0)
    paste(wb, hb, b, wa + GAP)
    ox = wa + wb + 2 * GAP
    for y in range(height):
        for x in range(width):
            i = y * width + x
            if changed[i]:
                px = (230, 0, 60)
            elif masked[i]:
                px = (190, 210, 255)
            else:
                src = (b, wb, hb) if (x < wb and y < hb) else (a, wa, ha)
                if x < src[1] and y < src[2]:
                    j = (y * src[1] + x) * 4
                    r, g, bl = _blend_white(*src[0][j:j + 4])
                    grey = 0.299 * r + 0.587 * g + 0.114 * bl
                    v = int(255 - (255 - grey) * 0.25)
                else:
                    v = 255
                px = (v, v, v)
            o = (y * total_w + ox + x) * 3
            out[o:o + 3] = bytes(px)
    line = max(1, int(round(dpr)))
    for x0, y0, x1, y1 in boxes:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if x - x0 < line or x1 - 1 - x < line or y - y0 < line or y1 - 1 - y < line:
                    o = (y * total_w + ox + x) * 3
                    out[o:o + 3] = b"\xff\x8c\x00"
    return total_w, total_h, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("design")
    ap.add_argument("built")
    ap.add_argument("--out", required=True, help="three-panel PNG path")
    ap.add_argument("--dpr", type=float, default=1.0)
    ap.add_argument("--mask", type=parse_mask, action="append", default=[])
    ap.add_argument("--threshold", type=float, default=0.1)
    ap.add_argument("--max-changed", type=float, default=None)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.dpr <= 0 or not 0 <= args.threshold <= 1 or args.top < 0:
        ap.error("--dpr must be > 0, --threshold within 0..1, --top >= 0")
    try:
        design, built = read_png(args.design), read_png(args.built)
    except ImageError as e:
        print(f"design-diff: {e}", file=sys.stderr)
        return 2
    width, height, changed, masked, hits, compared = compare(design, built, args.dpr, args.mask,
                                                             args.threshold)
    found = regions(changed, width, height, args.dpr)
    listed = found[:args.top]
    pw, ph, rgb = panel(design, built, width, height, changed, masked,
                        [r["_box"] for r in listed], args.dpr)
    write_png(args.out, pw, ph, rgb)
    pct = 100.0 * hits / compared if compared else 0.0
    over = args.max_changed is not None and pct > args.max_changed
    report = {
        "design": {"path": args.design, "width": design[0], "height": design[1]},
        "built": {"path": args.built, "width": built[0], "height": built[1]},
        "dpr": args.dpr, "size_match": design[:2] == built[:2],
        "changed_pct": round(pct, 4), "changed_px": hits, "compared_px": compared,
        "masked_px": width * height - compared, "region_count": len(found),
        "regions": [{k: v for k, v in r.items() if k != "_box"} for r in listed],
        "panel": args.out, "max_changed": args.max_changed, "pass": not over,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        css = lambda w, h: f"{w / args.dpr:g}x{h / args.dpr:g} CSS px"  # noqa: E731
        print(f"design   {args.design} {design[0]}x{design[1]} ({css(*design[:2])} @{args.dpr:g}x)")
        print(f"built    {args.built} {built[0]}x{built[1]} ({css(*built[:2])})")
        if not report["size_match"]:
            print("WARNING  sizes differ; pixels present in only one image count as changed")
        print(f"changed  {pct:.3f}% ({hits} of {compared} compared px, {report['masked_px']} masked)")
        print(f"regions  {len(found)} (CSS px, largest first)")
        for n, r in enumerate(report["regions"], 1):
            print(f"  {n:>2}. x={r['x']} y={r['y']} w={r['w']} h={r['h']}  changed={r['changed_px']} px")
        print(f"panel    {args.out}  (design | built | changed)")
        if args.max_changed is not None:
            print(f"result   {'FAIL' if over else 'PASS'} (max {args.max_changed:g}%)")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
