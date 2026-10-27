#!/usr/bin/env python3
"""Offline regression tests for bin/design-diff.py. Standard library only."""
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "design-diff.py"
spec = importlib.util.spec_from_file_location("design_diff", SCRIPT)
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)

FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def png_rgba(path, w, h, pixels, filters=(0,)):
    """Write an 8-bit RGBA PNG, cycling the given filter type per row."""
    stride, raw, prev = w * 4, bytearray(), bytearray(w * 4)
    for y in range(h):
        line = bytearray(pixels[y * stride:(y + 1) * stride])
        f = filters[y % len(filters)]
        enc = bytearray(stride)
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up, ul = prev[i], (prev[i - 4] if i >= 4 else 0)
            pred = {0: 0, 1: left, 2: up, 3: (left + up) >> 1, 4: dd._paeth(left, up, ul)}[f]
            enc[i] = (line[i] - pred) & 255
        raw += bytes([f]) + enc
        prev = line

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    Path(path).write_bytes(dd.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def canvas(w, h, rgb=(255, 255, 255)):
    return bytearray(bytes(rgb) * (w * h))


def fill(buf, w, x0, y0, x1, y1, rgb):
    for y in range(y0, y1):
        for x in range(x0, x1):
            buf[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes(rgb)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        # Every PNG filter type decodes to the exact pixels.
        w, h = 7, 10
        px = bytearray((x * 37 + y * 11 + c * 53) % 256 for y in range(h) for x in range(w) for c in range(4))
        png_rgba(t / "f.png", w, h, px, filters=(0, 1, 2, 3, 4))
        rw, rh, rgba = dd.read_png(t / "f.png")
        check((rw, rh, bytes(rgba)) == (w, h, bytes(px)), "filters 0-4 do not round-trip exactly")

        # Identical images: 0% changed, exit 0, panel is design | built | overlay wide.
        W, H, dpr = 80, 60, 2
        base = canvas(W, H)
        fill(base, W, 10, 10, 30, 20, (20, 20, 20))
        dd.write_png(t / "design.png", W, H, base)
        r = run(t / "design.png", t / "design.png", "--out", t / "same.png", "--dpr", dpr, "--json")
        rep = json.loads(r.stdout or "{}")
        check(r.returncode == 0 and rep.get("changed_pct") == 0 and rep.get("region_count") == 0,
              f"identical images not reported 0%: {r.returncode} {r.stdout} {r.stderr}")
        pw, ph, _ = dd.read_png(t / "same.png")
        check((pw, ph) == (3 * W + 2 * dd.GAP, H), f"panel size {pw}x{ph} is not three panels")

        # One changed block is found at its CSS-px position, and --max-changed gates it.
        built = bytearray(base)
        fill(built, W, 40, 30, 60, 50, (230, 30, 30))  # CSS 20,15 10x10 at dpr 2
        dd.write_png(t / "built.png", W, H, built)
        r = run(t / "design.png", t / "built.png", "--out", t / "p.png", "--dpr", dpr, "--json",
                "--max-changed", "1")
        rep = json.loads(r.stdout or "{}")
        top = (rep.get("regions") or [{}])[0]
        check(r.returncode == 1 and rep.get("pass") is False, f"over --max-changed did not exit 1: {r.returncode}")
        check(rep.get("changed_px") == 400 and rep.get("region_count") == 1,
              f"expected 400 changed px in one region: {rep}")
        check(top.get("x", 99) <= 20 and top.get("y", 99) <= 15 and top.get("x", 0) + top.get("w", 0) >= 30
              and top.get("y", 0) + top.get("h", 0) >= 25, f"region does not cover the CSS block: {top}")

        # A mask over a recorded exception removes the change; a sub-threshold shift does not count.
        r = run(t / "design.png", t / "built.png", "--out", t / "m.png", "--dpr", dpr, "--json",
                "--mask", "18,13,14,14", "--max-changed", "0")
        rep = json.loads(r.stdout or "{}")
        check(r.returncode == 0 and rep.get("changed_px") == 0 and rep.get("masked_px", 0) > 0,
              f"mask did not exclude the change: {r.returncode} {rep}")
        faint = bytearray(base)
        fill(faint, W, 0, 0, W, H, (253, 253, 253))
        fill(faint, W, 10, 10, 30, 20, (20, 20, 20))
        dd.write_png(t / "faint.png", W, H, faint)
        rep = json.loads(run(t / "design.png", t / "faint.png", "--out", t / "x.png", "--json").stdout or "{}")
        check(rep.get("changed_px") == 0, f"a 2-level grey shift counted as change: {rep.get('changed_px')}")

        # Size mismatch counts the extra area and warns.
        dd.write_png(t / "tall.png", W, H + 10, canvas(W, H + 10))
        r = run(t / "design.png", t / "tall.png", "--out", t / "s.png")
        check(r.returncode == 0 and "sizes differ" in r.stdout, f"size mismatch not reported: {r.stdout}")

        # Bad input exits 2 with a reason.
        (t / "x.jpg").write_bytes(b"\xff\xd8\xff\xe0 not a png")
        r = run(t / "x.jpg", t / "design.png", "--out", t / "e.png")
        check(r.returncode == 2 and "not a PNG" in r.stderr, f"non-PNG did not exit 2: {r.returncode} {r.stderr}")
        r = run(t / "design.png", t / "design.png", "--out", t / "e.png", "--mask", "1,2,3")
        check(r.returncode == 2, f"bad mask did not exit 2: {r.returncode}")

    for msg in FAILS:
        print("FAIL", msg)
    print(f"design-diff tests: {'FAIL' if FAILS else 'PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
