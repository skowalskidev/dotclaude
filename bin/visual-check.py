#!/usr/bin/env python3
"""Open the exact visual artifact a human will open, in headless Chromium, and prove every state is not blank.

For each viewport x state it loads the SAME file:// path or URL fresh (entry state), runs the state's
JavaScript, takes a full-page PNG, and checks: no page error or failed request, every --expect string is
in the page text, the page has ink, and every --region element has ink.
Fully visible means: non-zero size, not hidden, inside the document, not cut by any overflow-hidden, clip,
auto or scroll ancestor, and its own overflow hides none of its content. A string in the DOM or a pixel
that is not white never counts as a pass on its own (the fix for a view that cropped every phone in half). Ink is the share of pixels whose
colour differs from the area's most common colour, so a flat grey or black blank fails as surely as white.

Usage:
    visual-check.py <artifact.html | URL> --out DIR
        [--viewport WxH]...        default 1440x900
        [--state NAME=JS]...       a state the viewer can switch to; "default" (no JS) is always first
        [--region CSS]...          every element matching must be fully visible AND show ink (inset 12%)
        [--visible CSS]...         every element matching must be fully visible (no ink test)
        [--regions-in NAME]...     only check regions in these states (default: every state)
        [--expect TEXT]...         strings the page text must contain
        [--min-ink 0.0005]         minimum ink share, 0.05% by default
        [--wait-for CSS]...        wait until every matching selector is attached and visible, after load and
                                   after each state's JS; use for a page that renders its data after load
        [--wait-timeout 30000]     --wait-for timeout in ms; a timeout fails that row ("wait-for timed out: CSS")
        [--route GLOB=FILE]...     serve FILE (path relative to the cwd) for every request whose URL matches GLOB,
                                   before navigation; use to give a local page a fixture for its API route
        [--split-hint TEXT]        the fix named when a full page is too large for one screenshot
                                   (default "split it into smaller pages")

A full page over node_playwright.SCREENSHOT_MAX_PIXELS (an area, about 527 Mpx), or one Chromium fails to capture
or decode, fails its row with the page size and the split hint instead of a browser error; the row's PNG is then
the viewport only, and its region checks still run. Under that area Chromium can still return a full-size PNG painted
only partway down, with no error; a flat bottom band at least a viewport (and 1024 px) tall is re-captured in clipped tiles,
and the tiled PNG replaces it when it shows content lower down, noted in the row's result. If the re-capture fails, the
row gets a warning note naming the flat band and the split hint; neither note fails a row.

Output: DIR/<viewport>-<state>.png per row, DIR/pass-table.md, the same table on stdout.
Exit code: 0 every row passes, 1 any row fails, 2 usage or browser-runtime error.

Python 3.9+, standard library only. Browser work runs in Node Playwright, found by bin/node_playwright.py
(explicit env, the current repo and its other worktrees, the global npm root, ~/.claude); when none is found it
exits 2 and lists every place it looked.
"""
import argparse
import json
import mimetypes
import subprocess
import sys
import tempfile
from pathlib import Path

import node_playwright
from node_playwright import LAUNCH_JS

SETTLE_MS = 800
MAX_ROWS = 24

NODE_RUNNER = r"""
import { createRequire } from "node:module";
import { readFileSync, mkdirSync, writeFileSync, openSync, writeSync, closeSync, renameSync, rmSync } from "node:fs";
import { join } from "node:path";
import { createDeflate, inflateSync } from "node:zlib";
import { once } from "node:events";
const job = JSON.parse(readFileSync(process.argv[2], "utf8"));
""" + LAUNCH_JS + r"""
mkdirSync(job.outdir, { recursive: true });
const browser = await launchChromium(job.playwright);
try {
const probe = await browser.newPage();
// Ink share of a PNG: pixels differing from the most common colour by more than 8 on any channel, after an inset.
// flatFrom is the first row of the bottom band whose every pixel is within 8 of the bottom-right pixel (height when none).
async function inkScan(png, inset) {
  return await probe.evaluate(async ([b64, inset]) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const w = img.naturalWidth, h = img.naturalHeight;
    const x0 = Math.floor(w * inset), y0 = Math.floor(h * inset);
    const cw = Math.max(1, w - 2 * x0), ch = Math.max(1, h - 2 * y0);
    // Full-page screenshots can exceed canvas dimension/area limits even when the PNG decodes.
    // Read every pixel at 1:1 scale through bounded tiles; choose one mode for the entire inset.
    const tile = 1024;
    const c = document.createElement("canvas"); c.width = Math.min(tile, cw); c.height = Math.min(tile, ch);
    const g = c.getContext("2d");
    if (!g) throw new Error("ink canvas context unavailable");
    g.drawImage(img, x0 + cw - 1, y0 + ch - 1, 1, 1, 0, 0, 1, 1);
    const [rr, rg, rb] = g.getImageData(0, 0, 1, 1).data;
    let lastVaried = -1;
    const counts = new Map();
    for (let ty = 0; ty < ch; ty += tile) for (let tx = 0; tx < cw; tx += tile) {
      const tw = Math.min(tile, cw - tx), th = Math.min(tile, ch - ty);
      g.clearRect(0, 0, tw, th);
      g.drawImage(img, x0 + tx, y0 + ty, tw, th, 0, 0, tw, th);
      const d = g.getImageData(0, 0, tw, th).data;
      if (g.isContextLost() || d.length !== tw * th * 4) throw new Error("ink canvas read failed");
      for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
        const i = (y * tw + x) * 4, pos = (ty + y) * cw + tx + x;
        const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
        if (ty + y > lastVaried && (Math.abs(d[i] - rr) > 8 || Math.abs(d[i + 1] - rg) > 8 || Math.abs(d[i + 2] - rb) > 8)) lastVaried = ty + y;
        const entry = counts.get(k);
        if (entry) { entry.n++; entry.first = Math.min(entry.first, pos); }
        else counts.set(k, { n: 1, first: pos });
      }
    }
    // Preserve the original row-major tie-break, independent of tile traversal order.
    let mode = 0, best = -1, first = Infinity;
    for (const [k, entry] of counts) if (entry.n > best || (entry.n === best && entry.first < first)) {
      best = entry.n; first = entry.first; mode = k;
    }
    const mr = mode >> 16, mg = (mode >> 8) & 255, mb = mode & 255;
    let diff = 0;
    for (const [k, entry] of counts) if (Math.abs((k >> 16) - mr) > 8 || Math.abs(((k >> 8) & 255) - mg) > 8 || Math.abs((k & 255) - mb) > 8) diff += entry.n;
    return { share: diff / (cw * ch), flatFrom: lastVaried + 1, height: ch };
  }, [png.toString("base64"), inset]);
}
async function ink(png, inset) { return (await inkScan(png, inset)).share; }
// PNG plumbing for a tiled capture: 8-bit, non-interlaced, as Chromium writes it.
const PNG_SIG = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const CRC = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
function pngChunk(fd, kind, data) {
  const head = Buffer.alloc(8), tail = Buffer.alloc(4);
  head.writeUInt32BE(data.length); head.write(kind, 4, "latin1");
  let c = -1;
  for (const b of [head.subarray(4), data]) for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8);
  tail.writeUInt32BE((c ^ -1) >>> 0);
  writeSync(fd, head); writeSync(fd, data); writeSync(fd, tail);
}
function pngParts(buf) {
  const idat = [];
  let head = null;
  for (let i = 8; i + 8 <= buf.length;) {
    const n = buf.readUInt32BE(i), kind = buf.toString("latin1", i + 4, i + 8);
    if (kind === "IHDR") head = buf.subarray(i + 8, i + 21);
    else if (kind === "IDAT") idat.push(buf.subarray(i + 8, i + 8 + n));
    i += 12 + n;
  }
  if (!head) throw new Error("tile is not a PNG");
  return { w: head.readUInt32BE(0), h: head.readUInt32BE(4), depth: head[8], ct: head[9], il: head[12], head, raw: inflateSync(Buffer.concat(idat)) };
}
// Capture the full page as clipped tiles of `rows` rows and join their scanlines into one PNG at `file`, without decoding
// pixels: a scanline is filtered only against the row above it inside its own tile, so each tile's first row is rewritten
// unfiltered. Returns the tile count.
async function captureTiles(page, file, w, h, rows) {
  const fd = openSync(file, "w"), deflate = createDeflate();
  let ct = null, n = 0;
  try {
    for (let y = 0; y < h; y += rows) {
      const th = Math.min(rows, h - y);
      const t = pngParts(await page.screenshot({ fullPage: true, clip: { x: 0, y, width: w, height: th } }));
      const bpp = { 0: 1, 2: 3, 4: 2, 6: 4 }[t.ct];
      if (t.w !== w || t.h !== th || t.depth !== 8 || t.il !== 0 || !bpp || (ct !== null && t.ct !== ct)) {
        throw new Error(`tile at y=${y} came back ${t.w}x${t.h}, depth ${t.depth}, colour type ${t.ct}, interlace ${t.il}`);
      }
      if (ct === null) {
        ct = t.ct;
        const ihdr = Buffer.from(t.head);
        ihdr.writeUInt32BE(h, 4);
        writeSync(fd, PNG_SIG);
        pngChunk(fd, "IHDR", ihdr);
        deflate.on("data", (c) => pngChunk(fd, "IDAT", c));
      }
      const f = t.raw[0], row = t.raw.subarray(1, 1 + w * bpp);
      // With no row above, Sub and Paeth predict from the left pixel, Average from half of it, Up from zero.
      if (f === 1 || f === 4) for (let x = bpp; x < row.length; x++) row[x] = (row[x] + row[x - bpp]) & 255;
      else if (f === 3) for (let x = bpp; x < row.length; x++) row[x] = (row[x] + (row[x - bpp] >> 1)) & 255;
      t.raw[0] = 0;
      if (!deflate.write(t.raw)) await once(deflate, "drain");
      n++;
    }
    const done = once(deflate, "end");
    deflate.end();
    await done;
    pngChunk(fd, "IEND", Buffer.alloc(0));
  } finally { closeSync(fd); }
  return n;
}
// Chromium can return a full-page PNG at the right size whose lower part is one flat colour, with no error, while the page
// has content there (a 3866x83332 page came back painted to about y=32500). A flat bottom band at least a viewport tall
// (and 1024 px) is therefore re-captured in tiles of at most TILE_PIXELS; the tiled PNG replaces the one-shot PNG only when
// it shows content lower down, so a page that really ends in empty space keeps its PNG and gets no note.
const TILE_PIXELS = 32e6;
async function fullPageShot(page, file, viewportH, splitHint, tileRows) {
  const shot = await page.screenshot({ path: file, fullPage: true });
  const scan = await inkScan(shot, 0), w = shot.readUInt32BE(16), h = shot.readUInt32BE(20);
  if (h - scan.flatFrom < Math.max(viewportH, 1024)) return { scan, note: "" };
  const tiled = file.replace(/\.png$/, "") + ".tiled.png";
  const rows = tileRows || Math.max(256, Math.min(8192, Math.floor(TILE_PIXELS / w)));
  try {
    const n = await captureTiles(page, tiled, w, h, rows);
    const again = await inkScan(readFileSync(tiled), 0);
    if (again.flatFrom <= scan.flatFrom + 64) { rmSync(tiled); return { scan, note: "" }; }
    renameSync(tiled, file);
    return { scan: again, note: `Chromium cut the full-page capture at y=${scan.flatFrom} of ${h} px; the PNG and page ink come from ${n} tiles` };
  } catch (e) {
    rmSync(tiled, { force: true });
    return { scan, note: `warning: the full-page PNG is one flat colour from y=${scan.flatFrom} to ${h} px and the tiled re-capture failed `
      + `(${String(e.message).split("\n")[0]}); if the page has content there, the PNG and page ink cover only the top (region checks still ran). Fix: ${splitHint}` };
  }
}
// Why an element is not fully visible, or "" when it is: size, hiding, document bounds, clipping ancestors, own clipped content.
// getBoundingClientRect is viewport-relative: compare it to document bounds only after adding the window scroll offset,
// so the verdict does not depend on where an earlier element screenshot left the page scrolled.
const clipped = (el) => {
  const clip = (v) => ["hidden", "clip", "auto", "scroll"].includes(v);
  const name = (n) => n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") + (typeof n.className === "string" && n.className.trim() ? "." + n.className.trim().split(/\s+/)[0] : "");
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el), out = [];
  if (r.width < 2 || r.height < 2) out.push("zero size");
  if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) out.push("hidden");
  const d = document.documentElement, sx = window.scrollX, sy = window.scrollY;
  if (r.left + sx < -1 || r.top + sy < -1 || r.right + sx > d.scrollWidth + 1 || r.bottom + sy > d.scrollHeight + 1) out.push("outside the document");
  for (let a = el.parentElement; a; a = a.parentElement) {
    const s = getComputedStyle(a);
    if (!clip(s.overflowX) && !clip(s.overflowY)) continue;
    const b = a.getBoundingClientRect(), cut = [];
    if (clip(s.overflowX) && r.left < b.left - 1) cut.push(`left ${Math.round(b.left - r.left)}px`);
    if (clip(s.overflowX) && r.right > b.right + 1) cut.push(`right ${Math.round(r.right - b.right)}px`);
    if (clip(s.overflowY) && r.top < b.top - 1) cut.push(`top ${Math.round(b.top - r.top)}px`);
    if (clip(s.overflowY) && r.bottom > b.bottom + 1) cut.push(`bottom ${Math.round(r.bottom - b.bottom)}px`);
    if (cut.length) out.push(`cut by ${name(a)} (${cut.join(", ")})`);
  }
  if ((clip(cs.overflowX) || clip(cs.overflowY)) && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1)) out.push("its own content is cut");
  return out.join("; ");
};
const rows = [];
for (const vp of job.viewports) for (const st of job.states) {
  const row = { viewport: vp, state: st.name, problems: [], notes: [], regions: 0, clipped: 0, minRegionInk: null, ink: 0, expectMissing: [] };
  const [w, h] = vp.split("x").map(Number);
  // reducedMotion: entrance animations finish at once, so a screenshot never catches a mid-fade frame.
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "reduce" });
  page.on("pageerror", (e) => row.problems.push("page error: " + e.message));
  // Set just before this check closes the page: a request still in flight then, such as a link prefetch, is cut off
  // by the check itself. A request the page aborted while it was open still counts.
  let closing = false;
  const abortedFetches = [];
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText || "unknown error";
    if (closing && why === "net::ERR_ABORTED") return;
    // A framework prefetches the pages a page links to and cancels those fetches freely, so an aborted fetch is judged
    // against the page's links just before closing: a fetch of anything else still counts.
    if (r.resourceType() === "fetch" && why === "net::ERR_ABORTED") { abortedFetches.push(r.url()); return; }
    // Chromium cancels a media preload and re-requests it by byte range, so an aborted media request is not a
    // failed load. A missing media file fails with its own error (net::ERR_FILE_NOT_FOUND) and still counts.
    if (r.resourceType() === "media" && why === "net::ERR_ABORTED") return;
    const url = r.url();
    row.problems.push(`request failed (${why}): ${url.length > 80 ? "…" + url.slice(-79) : url}`);
  });
  let waitFailed = false;
  const waitAll = async () => {
    for (const sel of job.waitFor) {
      try { await page.waitForSelector(sel, { state: "visible", timeout: job.waitTimeout }); }
      catch { waitFailed = true; row.problems.push(`wait-for timed out: ${sel}`); }
    }
  };
  try {
    for (const rt of job.routes) {
      const body = readFileSync(rt.file);
      await page.route(rt.glob, (route) => route.fulfill({ status: 200, contentType: rt.contentType, headers: { "access-control-allow-origin": "*" }, body }));
    }
    await page.goto(job.url, { waitUntil: "load" });
    await waitAll();
    await page.waitForTimeout(job.settleMs);
    if (st.js) { await page.evaluate(st.js); await waitAll(); await page.waitForTimeout(job.settleMs); }
    const file = join(job.outdir, `${vp}-${st.name}.png`);
    // One screenshot holds at most job.maxPixels; past it Chromium fails to capture or the PNG fails to decode,
    // so name the page size and the fix instead of passing on a browser error.
    const [pw, ph] = await page.evaluate(() => {
      const d = document.documentElement, b = document.body || d;
      return [Math.max(d.scrollWidth, b.scrollWidth), Math.max(d.scrollHeight, b.scrollHeight)];
    });
    const tooBig = (why) => `full page ${pw}x${ph} px (${Math.round(pw * ph / 1e6)} Mpx) ${why}: ${job.splitHint}`;
    row.file = file;
    if (pw * ph > job.maxPixels) {
      row.problems.push(tooBig(`is over the ${Math.round(job.maxPixels / 1e6)} Mpx one-screenshot limit`));
      row.ink = await ink(await page.screenshot({ path: file }), 0);
    } else {
      try {
        const shot = await fullPageShot(page, file, h, job.splitHint);
        row.ink = shot.scan.share;
        if (shot.note) row.notes.push(shot.note);
        if (row.ink < job.minInk) row.problems.push(`page blank (ink ${(row.ink * 100).toFixed(3)}%)`);
      } catch (e) {
        const why = String(e.message).split("\n")[0];
        if (!/Unable to capture screenshot|EncodingError|cannot be decoded/.test(why)) throw e;
        row.problems.push(tooBig(`could not be captured or decoded (${why})`));
      }
    }
    let text = "";
    for (const f of page.frames()) { try { text += "\n" + await f.evaluate(() => document.body ? document.body.innerText : ""); } catch {} }
    row.expectMissing = job.expect.filter((s) => !text.includes(s));
    if (row.expectMissing.length) row.problems.push("missing text: " + row.expectMissing.join(" | "));
    if (!waitFailed && (!job.regionsIn || job.regionsIn.includes(st.name))) {
      for (const sel of job.visible) {
        const els = await page.locator(sel).all();
        if (!els.length) { row.problems.push(`element not found: ${sel}`); continue; }
        for (let i = 0; i < els.length; i++) {
          row.regions++;
          const why = await els[i].evaluate(clipped);
          if (why) { row.clipped++; row.problems.push(`${sel}[${i}] not fully visible: ${why}`); }
        }
      }
      // Measure every region before any region screenshot: a screenshot scrolls its element (and any scroll ancestor)
      // into view, which would otherwise judge later regions in a scroll state the viewer never opened.
      const shots = [];
      for (const sel of job.regions) {
        const els = await page.locator(sel).all();
        if (!els.length) { row.problems.push(`region not found: ${sel}`); continue; }
        for (let i = 0; i < els.length; i++) {
          row.regions++;
          const why = await els[i].evaluate(clipped);
          if (why) { row.clipped++; row.problems.push(`region ${sel}[${i}] not fully visible: ${why}`); }
          shots.push([sel, i, els[i]]);
        }
      }
      for (const [sel, i, el] of shots) {
        let share = 0;
        try { share = await ink(await el.screenshot({ timeout: 5000 }), 0.12); }
        catch (e) { row.problems.push(`region ${sel}[${i}] not capturable: ${String(e.message).split("\n")[0]}`); continue; }
        row.minRegionInk = row.minRegionInk === null ? share : Math.min(row.minRegionInk, share);
        if (share < job.minInk) row.problems.push(`region ${sel}[${i}] blank (ink ${(share * 100).toFixed(3)}%)`);
      }
    }
  } catch (e) { row.problems.push("load failed: " + String(e.message).split("\n")[0]); }
  const links = await page.evaluate(() => [...document.links].map((a) => a.origin + a.pathname)).catch(() => []);
  for (const url of abortedFetches) {
    const { origin, pathname } = new URL(url);
    const target = origin + pathname;
    // Next.js also fetches a linked page's segment files, /page/__next.*.
    if (links.some((l) => target === l || target.startsWith(l + "/__next."))) continue;
    row.problems.push(`request failed (net::ERR_ABORTED): ${url.length > 80 ? "…" + url.slice(-79) : url}`);
  }
  closing = true;
  await page.close();
  rows.push(row);
}
console.log(JSON.stringify({ rows }));
} finally { await browser.close(); }
"""


def to_url(target: str) -> str:
    if "://" in target:
        return target
    p = Path(target).resolve()
    if not p.is_file():
        raise SystemExit(f"not a file: {p}")
    return p.as_uri()


def table(rows: list, out: Path) -> str:
    lines = [
        f"Screenshots: {out}",
        "",
        "| viewport | state | page ink | elements checked | not fully visible | min region ink | result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        mn = "-" if r["minRegionInk"] is None else f"{r['minRegionInk'] * 100:.2f}%"
        res = "PASS" if not r["problems"] else "FAIL: " + "; ".join(r["problems"])
        if r.get("notes"):
            res += "; note: " + "; ".join(r["notes"])
        lines.append(f"| {r['viewport']} | {r['state']} | {r['ink'] * 100:.2f}% | {r['regions']} | {r['clipped']} | {mn} | {res} |")
    return "\n".join(lines)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifact")
    ap.add_argument("--out", required=True)
    ap.add_argument("--viewport", action="append", default=[])
    ap.add_argument("--state", action="append", default=[])
    ap.add_argument("--region", action="append", default=[])
    ap.add_argument("--visible", action="append", default=[])
    ap.add_argument("--regions-in", action="append", default=None)
    ap.add_argument("--expect", action="append", default=[])
    ap.add_argument("--min-ink", type=float, default=0.0005)
    ap.add_argument("--wait-for", action="append", default=[])
    ap.add_argument("--wait-timeout", type=int, default=30000)
    ap.add_argument("--route", action="append", default=[])
    ap.add_argument("--split-hint", default="split it into smaller pages")
    a = ap.parse_args(argv)
    states = [{"name": "default", "js": ""}]
    for s in a.state:
        name, sep, js = s.partition("=")
        if not sep or not name or name == "default":
            print(f"bad --state {s!r}: use NAME=JS, NAME not 'default'", file=sys.stderr)
            return 2
        states.append({"name": name, "js": js})
    routes = []
    for r in a.route:
        glob, sep, file = r.rpartition("=")
        if not sep or not glob or not file:
            print(f"bad --route {r!r}: use GLOB=FILE", file=sys.stderr)
            return 2
        path = Path(file).resolve()
        if not path.is_file():
            print(f"bad --route {r!r}: fixture file not found: {path}", file=sys.stderr)
            return 2
        ctype = "application/json" if path.suffix == ".json" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        routes.append({"glob": glob, "file": str(path), "contentType": ctype})
    out = Path(a.out).resolve()
    if len(a.viewport or [1]) * len(states) > MAX_ROWS:
        print(f"{len(a.viewport or [1]) * len(states)} rows exceeds the cap of {MAX_ROWS}; split the check", file=sys.stderr)
        return 2
    job = {
        "url": to_url(a.artifact),
        "outdir": str(out),
        "viewports": a.viewport or ["1440x900"],
        "states": states,
        "regions": a.region,
        "visible": a.visible,
        "regionsIn": a.regions_in,
        "expect": a.expect,
        "minInk": a.min_ink,
        "settleMs": SETTLE_MS,
        "waitFor": a.wait_for,
        "waitTimeout": a.wait_timeout,
        "routes": routes,
        "maxPixels": node_playwright.SCREENSHOT_MAX_PIXELS,
        "splitHint": a.split_hint,
    }
    job["playwright"], searched = node_playwright.find()
    if not job["playwright"]:
        print(node_playwright.not_found_message(searched), file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        job_path, run_path = Path(tmp) / "job.json", Path(tmp) / "run.mjs"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        run_path.write_text(NODE_RUNNER, encoding="utf-8")
        proc = subprocess.run(["node", str(run_path), str(job_path)], capture_output=True, text=True)
    if proc.returncode == 2:
        print(proc.stderr.strip(), file=sys.stderr)
        return 2
    try:
        rows = json.loads(proc.stdout.strip().splitlines()[-1])["rows"]
    except (IndexError, ValueError, KeyError):
        print(proc.stdout + proc.stderr, file=sys.stderr)
        return 2
    text = table(rows, out)
    (out / "pass-table.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if any(r["problems"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
