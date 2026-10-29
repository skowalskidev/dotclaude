#!/usr/bin/env python3
"""Offline regression tests for bin/pr-evidence.py: synthetic frames and clips, no network.

Asserts the template rules: layout dimensions, bands ABOVE frames (band colour in the band rows,
none of it in the frame rows below), outline-only callouts, video duration within the target plus
hold, and both sides ending together. Needs Pillow and ffmpeg, the engine's own dependencies.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "pr-evidence.py"
FAILS: list[str] = []

try:
    from PIL import Image
except ImportError:
    sys.exit("pr-evidence.test: Pillow missing for " + sys.executable + " (brew install pillow)")

RED, GREEN, BG = (205, 45, 45), (25, 140, 70), (18, 18, 18)
CONTENT = (200, 200, 205)
MARK = (40, 80, 200)  # the top stripe of every synthetic frame; must stay visible under the band


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def near(px, rgb, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], rgb))


def engine(*args):
    r = subprocess.run([sys.executable, str(ENGINE), *args], capture_output=True, text=True, timeout=300)
    check(r.returncode == 0, f"engine {args[0]} failed: {r.stdout}{r.stderr}")
    return r


def band_holds(img, x0, x1, y0, y1, colour):
    """True when most sampled band pixels are the band colour (text is white, so not all)."""
    hits = total = 0
    for y in range(y0 + 4, y1 - 4, 6):
        for x in range(x0 + 4, x1 - 4, 9):
            total += 1
            hits += near(img.getpixel((x, y)), colour)
    return total and hits / total > 0.5


def none_of(img, x0, x1, y0, y1, colour):
    return not any(near(img.getpixel((x, y)), colour, 25)
                   for y in range(y0, y1, 3) for x in range(x0, x1, 5))


def frame_png(path: Path, w: int, h: int):
    img = Image.new("RGB", (w, h), CONTENT)
    img.paste(MARK, (0, 0, w, 30))
    img.save(path)


def test_shots(tmp: Path):
    phone_b, phone_a = tmp / "pb.png", tmp / "pa.png"
    frame_png(phone_b, 390, 844)
    frame_png(phone_a, 390, 844)
    out = tmp / "phone.png"
    engine("shots", "--before", str(phone_b), "--after", str(phone_a), "--pr", "123",
           "--before-caption", "Asks instead of searching", "--after-caption", "Shows the result",
           "--before-callout", "20,600,370,800", "--after-callout", "20,600,370,800", "--out", str(out))
    if not out.is_file():
        return check(False, "shots phone output missing")
    img = Image.open(out).convert("RGB")
    check(img.size == (780 * 2 + 40, 150 + 1688), f"phone layout size {img.size}")
    check(band_holds(img, 0, 780, 0, 150, RED), "BEFORE band is not red above the left frame")
    check(band_holds(img, 820, 1600, 0, 150, GREEN), "AFTER band is not green above the right frame")
    check(near(img.getpixel((800, 75)), BG, 3), "40 px gap between phone frames is not background")
    check(none_of(img, 0, 780, 150, 1100, RED) and none_of(img, 820, 1600, 150, 1100, GREEN),
          "band colour found in the frame rows below the band (caption overlaid on the UI)")
    check(near(img.getpixel((390, 150 + 20)), MARK, 20) and near(img.getpixel((1210, 150 + 20)), MARK, 20),
          "the frame's top rows are hidden: the band must sit above the frame, not over it")
    # Callout: outline on the frame, interior untouched (outline only, never covering the change).
    check(near(img.getpixel((400, 150 + 1200 + 2)), RED, 30), "before callout outline missing")
    check(near(img.getpixel((390, 150 + 1400)), CONTENT, 3), "before callout covers the change")
    check(near(img.getpixel((820 + 400, 150 + 1200 + 2)), GREEN, 30), "after callout outline missing")

    desk_b, desk_a = tmp / "db.png", tmp / "da.png"
    frame_png(desk_b, 1440, 900)
    frame_png(desk_a, 1440, 900)
    out = tmp / "desktop.png"
    engine("shots", "--before", str(desk_b), "--after", str(desk_a), "--pr", "123",
           "--context", "opened a saved link", "--before-caption", "Lands on the wrong item",
           "--after-caption", "Stays on the linked item", "--out", str(out))
    if not out.is_file():
        return check(False, "shots desktop output missing")
    img = Image.open(out).convert("RGB")
    check(img.size == (1280, 130 + 800 + 30 + 130 + 800), f"desktop stacked size {img.size}")
    check(band_holds(img, 0, 1280, 0, 130, RED), "BEFORE band not above the first desktop frame")
    check(band_holds(img, 0, 1280, 960, 1090, GREEN), "AFTER band not above the second desktop frame")
    check(near(img.getpixel((640, 945)), BG, 3), "30 px gap between stacked frames is not background")
    check(none_of(img, 0, 1280, 130, 930, RED) and none_of(img, 0, 1280, 1090, 1890, GREEN),
          "band colour found inside a desktop frame")
    check(near(img.getpixel((640, 130 + 10)), MARK, 20) and near(img.getpixel((640, 1090 + 10)), MARK, 20),
          "a desktop frame's top rows are hidden under its band")


def clip(path: Path, size: str, seconds: int):
    # A grey frame with a moving square, so the clip has motion; no drawtext needed.
    src = f"color=c=0xc8c8cd:s={size}:d={seconds}:r=10"
    move = ("drawbox=x=0:y=0:w=iw:h=30:color=0x2850c8:t=fill,"
            "drawbox=x='mod(t*40,200)':y=60:w=60:h=60:color=0x806040:t=fill")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-vf", move,
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, text=True)
    check(r.returncode == 0, f"could not synthesize {path.name}: {r.stderr}")


def probe(path: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,codec_name,pix_fmt:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    data = json.loads(r.stdout)
    s = data["streams"][0]
    return s["width"], s["height"], s["codec_name"], s["pix_fmt"], float(data["format"]["duration"])


def frame_at(video: Path, t: float, png: Path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", str(png)], capture_output=True, check=True)
    return Image.open(png).convert("RGB")


def test_video(tmp: Path):
    long_b, short_a = tmp / "vb.mp4", tmp / "va.mp4"
    clip(long_b, "390x844", 20)  # 20 s at target 10 -> 2x speed
    clip(short_a, "390x844", 6)  # shorter side holds its last frame
    out = tmp / "phone.mp4"
    engine("video", "--before", str(long_b), "--after", str(short_a), "--pr", "123",
           "--before-caption", "Waits on a spinner", "--after-caption", "Result appears",
           "--target", "10", "--hold", "4", "--fps", "10", "--preset", "ultrafast", "--out", str(out))
    if not out.is_file():
        return check(False, "video phone output missing")
    w, h, codec, pix, dur = probe(out)
    check((w, h) == (1600, 150 + 1688), f"video phone layout {w}x{h}")
    check(codec == "h264" and pix == "yuv420p", f"video codec {codec}/{pix}, want h264/yuv420p")
    check(13.5 <= dur <= 14.5, f"video duration {dur:.2f}s, want 10 s sped-up play + 4 s hold")
    data = out.read_bytes()
    check(0 <= data.find(b"moov") < data.find(b"mdat"), "moov atom not before mdat (+faststart missing)")
    last = frame_at(out, dur - 0.3, tmp / "last.png")
    check(band_holds(last, 0, 780, 0, 150, RED) and band_holds(last, 820, 1600, 0, 150, GREEN),
          "video bands missing above the clips")
    check(none_of(last, 0, 780, 150, 1000, RED) and none_of(last, 820, 1600, 150, 1000, GREEN),
          "video band colour inside a clip (caption overlaid)")
    check(near(last.getpixel((390, 150 + 20)), MARK, 30) and near(last.getpixel((1210, 150 + 20)), MARK, 30),
          "a clip's top rows are hidden: the band must be stacked above the clip")
    # Both sides end together: at the last frame each side still shows its clip, not padding.
    check(near(last.getpixel((390, 1500)), CONTENT, 20) and near(last.getpixel((1210, 1500)), CONTENT, 20),
          "a side ended early (shows background at the final frame)")

    desk_b, desk_a = tmp / "db.mp4", tmp / "da.mp4"
    clip(desk_b, "1280x720", 12)
    clip(desk_a, "1280x720", 12)
    out = tmp / "desktop.mp4"
    engine("video", "--before", str(desk_b), "--after", str(desk_a), "--pr", "123",
           "--before-caption", "Opens the wrong item", "--after-caption", "Opens the linked item",
           "--target", "10", "--hold", "4", "--fps", "10", "--preset", "ultrafast", "--out", str(out))
    if not out.is_file():
        return check(False, "video desktop output missing")
    w, h, _, _, dur = probe(out)
    check((w, h) == (1280, 130 + 720 + 30 + 130 + 720), f"video desktop layout {w}x{h}")
    check(13.5 <= dur <= 14.5, f"desktop video duration {dur:.2f}s")


def test_fails_fast(tmp: Path):
    r = subprocess.run([sys.executable, str(ENGINE), "shots", "--before", str(tmp / "nope.png"),
                        "--after", str(tmp / "nope.png"), "--pr", "1", "--before-caption", "a",
                        "--after-caption", "b", "--out", str(tmp / "x.png")], capture_output=True, text=True)
    check(r.returncode != 0 and "missing input image" in r.stderr, "missing input did not fail loudly")
    check("drawtext" not in ENGINE.read_text().split('"""', 2)[2],
          "engine uses drawtext; it must render text with Pillow")


def main() -> int:
    for tool in ("ffmpeg", "ffprobe"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            print(f"pr-evidence.test: {tool} missing (brew install ffmpeg)", file=sys.stderr)
            return 1
    with tempfile.TemporaryDirectory(prefix="pr-evidence-test-") as d:
        tmp = Path(d)
        test_fails_fast(tmp)
        test_shots(tmp)
        test_video(tmp)
    for f in FAILS:
        print("FAIL", f, file=sys.stderr)
    print(f"pr-evidence: {'ok' if not FAILS else str(len(FAILS)) + ' failure(s)'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
