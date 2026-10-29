#!/usr/bin/env python3
"""PR evidence template: one look for every before/after screenshot and video posted to a PR.

  pr-evidence.py shots --before B.png --after A.png --before-caption TEXT --after-caption TEXT
                       --pr N [--base main] [--context TEXT] [--before-callout x0,y0,x1,y1 ...]
                       [--after-callout x0,y0,x1,y1 ...] [--layout auto|side|stack] --out OUT.png
  pr-evidence.py video --before B.mp4 --after A.mp4 --before-caption TEXT --after-caption TEXT
                       --pr N [--base main] [--context TEXT] [--target 12] [--hold 4.5]
                       [--layout auto|side|stack] [--fps 30] --out OUT.mp4

Every caption sits in a coloured band STACKED ABOVE its frame (never overlaid on the UI): red
BEFORE band titled with the base, green AFTER band titled with the PR number. Portrait (phone)
frames sit side by side with a 40 px gap; landscape (desktop) frames stack with a 30 px gap.
Callouts are outline-only rounded rectangles drawn around the change. Text is rendered with Pillow,
so ffmpeg needs no drawtext filter. Method and posting rules: references/screenshot-review.md
§ PR evidence template.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # fail fast, before any work
    sys.exit("pr-evidence: Pillow is required. Install it: brew install pillow "
             "(or python3 -m pip install Pillow), then re-run.")

BG = (0x12, 0x12, 0x12)
BEFORE_RGB = (205, 45, 45)
AFTER_RGB = (25, 140, 70)
TEXT_RGB = (255, 255, 255)
PHONE_W = 780          # each portrait frame is scaled to this width
DESKTOP_W = 1280       # each landscape frame is scaled to this width
SIDE_GAP = 40          # px between side-by-side portrait frames
STACK_GAP = 30         # px between stacked landscape pairs
BAND_SIDE_H = 150      # band height above a portrait frame
BAND_STACK_H = 130     # band height above a landscape frame
TITLE_PX = 44
SUB_PX = 30
PAD_X = 28
CALLOUT_RADIUS = 28
CALLOUT_WIDTH = 8
FONT_CANDIDATES = (
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/Library/Fonts/Arial Bold.ttf", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 0),
)


def die(msg: str) -> None:
    sys.exit(f"pr-evidence: {msg}")


def font(size: int):
    for path, index in FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return ImageFont.load_default(size)


def fitted(draw, text: str, size: int, max_w: int):
    """Largest font at most `size` px whose rendering of `text` fits `max_w`."""
    while size > 16:
        f = font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(16)


def band(width: int, height: int, colour, title: str, subtitle: str) -> Image.Image:
    img = Image.new("RGB", (width, height), colour)
    d = ImageDraw.Draw(img)
    max_w = width - 2 * PAD_X
    tf = fitted(d, title, TITLE_PX, max_w)
    sf = fitted(d, subtitle, SUB_PX, max_w)
    title_y = 16
    d.text((PAD_X, title_y), title, font=tf, fill=TEXT_RGB)
    sub_y = title_y + TITLE_PX + 22
    d.text((PAD_X, sub_y), subtitle, font=sf, fill=TEXT_RGB)
    return img


def titles(args) -> tuple[str, str]:
    suffix = f"  -  {args.context}" if args.context else ""
    return f"BEFORE  {args.base}{suffix}", f"AFTER  #{args.pr}{suffix}"


def portrait(sizes) -> bool:
    return all(h > w for w, h in sizes)


def resolve_layout(choice: str, sizes) -> str:
    if choice != "auto":
        return choice
    return "side" if portrait(sizes) else "stack"


def parse_box(text: str) -> tuple[int, int, int, int]:
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in text.split(","))
    except ValueError:
        die(f"callout must be x0,y0,x1,y1 in source pixels, got {text!r}")
    if x1 <= x0 or y1 <= y0:
        die(f"callout {text!r} has no area (need x1>x0 and y1>y0)")
    return x0, y0, x1, y1


def callouts(img: Image.Image, boxes, scale: float, colour) -> None:
    d = ImageDraw.Draw(img)
    inset = CALLOUT_WIDTH // 2
    for x0, y0, x1, y1 in boxes:
        box = (max(inset, round(x0 * scale)), max(inset, round(y0 * scale)),
               min(img.width - 1 - inset, round(x1 * scale)), min(img.height - 1 - inset, round(y1 * scale)))
        d.rounded_rectangle(box, radius=CALLOUT_RADIUS, outline=colour, width=CALLOUT_WIDTH)


def cmd_shots(args) -> int:
    srcs = []
    for p in (args.before, args.after):
        if not Path(p).is_file():
            die(f"missing input image: {p}")
        srcs.append(Image.open(p).convert("RGB"))
    layout = resolve_layout(args.layout, [s.size for s in srcs])
    width = PHONE_W if layout == "side" else DESKTOP_W
    band_h = BAND_SIDE_H if layout == "side" else BAND_STACK_H
    frames = []
    for src, boxes, colour in ((srcs[0], args.before_callout, BEFORE_RGB),
                               (srcs[1], args.after_callout, AFTER_RGB)):
        scale = width / src.width
        frame = src.resize((width, round(src.height * scale)), Image.LANCZOS)
        callouts(frame, [parse_box(b) for b in boxes], scale, colour)
        frames.append(frame)
    t_before, t_after = titles(args)
    bands = [band(width, band_h, BEFORE_RGB, t_before, args.before_caption),
             band(width, band_h, AFTER_RGB, t_after, args.after_caption)]
    if layout == "side":
        frame_h = max(f.height for f in frames)
        out = Image.new("RGB", (2 * width + SIDE_GAP, band_h + frame_h), BG)
        for i, (b, f) in enumerate(zip(bands, frames)):
            x = i * (width + SIDE_GAP)
            out.paste(b, (x, 0))
            out.paste(f, (x, band_h))
    else:
        total = sum(band_h + f.height for f in frames) + STACK_GAP
        out = Image.new("RGB", (width, total), BG)
        y = 0
        for b, f in zip(bands, frames):
            out.paste(b, (0, y))
            out.paste(f, (0, y + band_h))
            y += band_h + f.height + STACK_GAP
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out, optimize=True)
    print(f"{args.out} {out.width}x{out.height} layout={layout}")
    return 0


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        die(f"{tool} is required for video. Install it: brew install ffmpeg, then re-run.")
    return path


def probe(ffprobe: str, path: str) -> tuple[int, int, float]:
    if not Path(path).is_file():
        die(f"missing input video: {path}")
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"ffprobe could not read {path}: {r.stderr.strip()}")
    data = json.loads(r.stdout)
    stream = data["streams"][0]
    w, h = int(stream["width"]), int(stream["height"])
    for side in stream.get("side_data_list", []):
        if abs(int(side.get("rotation", 0))) % 180 == 90:
            w, h = h, w
    duration = float(data["format"]["duration"])
    if duration <= 0:
        die(f"{path} has no duration")
    return w, h, duration


def even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def cmd_video(args) -> int:
    ffmpeg, ffprobe = need("ffmpeg"), need("ffprobe")
    clips = [probe(ffprobe, args.before), probe(ffprobe, args.after)]
    layout = resolve_layout(args.layout, [(w, h) for w, h, _ in clips])
    width = PHONE_W if layout == "side" else DESKTOP_W
    band_h = BAND_SIDE_H if layout == "side" else BAND_STACK_H
    speeds = [max(1.0, d / args.target) for _, _, d in clips]
    played = [d / s for (_, _, d), s in zip(clips, speeds)]
    total = max(played) + args.hold
    heights = [even(h * width / w) for w, h, _ in clips]
    frame_h = max(heights) if layout == "side" else None
    t_before, t_after = titles(args)
    with tempfile.TemporaryDirectory(prefix="pr-evidence-") as tmp:
        bands = [Path(tmp, "band-before.png"), Path(tmp, "band-after.png")]
        band(width, band_h, BEFORE_RGB, t_before, args.before_caption).save(bands[0])
        band(width, band_h, AFTER_RGB, t_after, args.after_caption).save(bands[1])
        inputs = ["-i", args.before, "-i", args.after]
        for b in bands:
            inputs += ["-loop", "1", "-framerate", str(args.fps), "-t", f"{total:.3f}", "-i", str(b)]
        parts = []
        for i in range(2):
            pad_h = frame_h if layout == "side" else heights[i]
            tail = total - played[i]  # final-state hold plus the wait for the longer side
            parts.append(
                f"[{i}:v]setpts=(PTS-STARTPTS)/{speeds[i]:.6f},fps={args.fps},"
                f"scale={width}:{heights[i]}:flags=lanczos,setsar=1,"
                f"pad={width}:{pad_h}:0:0:color=0x121212,"
                f"tpad=stop_mode=clone:stop_duration={tail:.3f},"
                f"trim=duration={total:.3f},setpts=PTS-STARTPTS[c{i}]")
            parts.append(f"[{i + 2}:v]format=rgb24,setsar=1[b{i}]")
            parts.append(f"[b{i}][c{i}]vstack=inputs=2[s{i}]")
        if layout == "side":
            parts.append(f"[s0]pad=iw+{SIDE_GAP}:ih:0:0:color=0x121212[s0g]")
            parts.append("[s0g][s1]hstack=inputs=2,scale=out_range=tv,format=yuv420p[out]")
        else:
            parts.append(f"[s0]pad=iw:ih+{STACK_GAP}:0:0:color=0x121212[s0g]")
            parts.append("[s0g][s1]vstack=inputs=2,scale=out_range=tv,format=yuv420p[out]")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts),
               "-map", "[out]", "-an", "-c:v", "libx264", "-preset", args.preset, "-crf", "23",
               "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart", "-t", f"{total:.3f}", args.out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            die(f"ffmpeg failed:\n{r.stderr.strip()}")
    print(f"{args.out} layout={layout} duration={total:.2f}s "
          f"speed before={speeds[0]:.2f}x after={speeds[1]:.2f}x hold={args.hold}s")
    return 0


def common(p) -> None:
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--before-caption", required=True, help="one line: what happens on the base")
    p.add_argument("--after-caption", required=True, help="one line: the result on this PR")
    p.add_argument("--pr", required=True, help="PR number, without #")
    p.add_argument("--base", default="main", help="base branch named in the BEFORE band")
    p.add_argument("--context", default="", help="optional shared action, appended to both titles")
    p.add_argument("--layout", choices=("auto", "side", "stack"), default="auto")
    p.add_argument("--out", required=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pr-evidence.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shots", help="before/after screenshot pair -> one PNG")
    common(s)
    s.add_argument("--before-callout", action="append", default=[], metavar="x0,y0,x1,y1")
    s.add_argument("--after-callout", action="append", default=[], metavar="x0,y0,x1,y1")
    v = sub.add_parser("video", help="before/after clips -> one side-by-side MP4")
    common(v)
    v.add_argument("--target", type=float, default=12.0, help="seconds each side plays before the hold (10-15)")
    v.add_argument("--hold", type=float, default=4.5, help="seconds the final state is held (4-5)")
    v.add_argument("--fps", type=int, default=30)
    v.add_argument("--preset", default="medium", help="libx264 preset")
    args = ap.parse_args(argv)
    if args.cmd == "video" and not (10 <= args.target <= 15 and 4 <= args.hold <= 5):
        die("--target must be 10-15 s and --hold 4-5 s")
    return cmd_shots(args) if args.cmd == "shots" else cmd_video(args)


if __name__ == "__main__":
    sys.exit(main())
