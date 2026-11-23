#!/usr/bin/env python3
"""Label every test-browser tab Claude opens, and close the tabs no live walk still needs.

references/browser-debugging.md § Tab labels and stale tabs owns the rule; this is its engine.

Two failures it exists for: a walk label set once with `document.title = ...` was overwritten by the
app on its next render, so Simon saw a window titled only with the app name; and earlier walks' windows stayed
open beside the current one, so he could not tell which window to use.

Usage:
  test-browser-tabs.py label --task "PR 1272" [--persona "SENDER 0107"] [--owner NAME] [--out FILE]
      Print the label-keeper JavaScript. Pass it as `initScript` to every chrome-devtools
      `navigate_page`, and run it once with `evaluate_script` (format "script", or `sourcePath` of
      --out) right after `new_page`. It keeps the tab title at
        ▶ <task> · <persona> · <page title> · @<owner>
      whatever the page later writes to <title>. Idempotent: re-running it re-labels in place.
  test-browser-tabs.py list  [--port 9222] [--owner NAME] [--task "PR 1272"] [--json]
  test-browser-tabs.py sweep [--port 9222] [--owner NAME] [--task "PR 1272"] [--dry-run]
      Classify every page of the test browser, and (sweep) close each stale one.

Classes (one per page):
  own     labelled with this owner (and this --task, when given)       kept
  live    labelled by another owner whose session is live and whose
          walk was driven in the last IDLE_MIN minutes                  kept
  unknown labelled by another owner, but the session probe failed       kept
  stale   blank (about:blank, new-tab page), unlabelled, labelled by an
          owner with no live session, idle past IDLE_MIN, or an own tab
          of a different --task                                         closed by sweep

The owner is the session's workspace folder name (git top level of the cwd), e.g. a Conductor
workspace "auckland". A session is live when a running Claude/Codex process has its cwd in a folder
of that name (bin/port-registry.sh sessions, the shared detector). Every `label` and `sweep` call,
and hooks/test-browser-label-guard.py on every labelled `navigate_page`, touches the owner's
heartbeat file under HEARTBEAT_DIR.

Exit codes: 0 ok · 2 usage · 3 no browser answers on the port
            · 5 the port is not Chrome for Testing (nothing is listed or closed)
Python 3.9+, standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MARK = "▶ "                      # ▶, the label's first characters
SEP = " · "                      # " · "
GLOBAL = "__claudeTabLabel"           # the page global the keeper installs; the guard hook keys on it
IDLE_MIN = 30                         # minutes without a heartbeat before a live owner's tab is stale
BLANK = ("about:blank", "chrome://newtab/", "chrome://new-tab-page/", "")
HOME = Path(os.environ.get("HOME", str(Path.home())))
HEARTBEAT_DIR = Path(os.environ.get("CLAUDE_TEST_BROWSER_WALKS_DIR", str(HOME / ".claude" / "test-browser-walks")))
PORT_REGISTRY = Path(__file__).resolve().parent / "port-registry.sh"
OWNER_RE = re.compile(r"[^A-Za-z0-9._-]+")
LABEL_RE = re.compile(r"^" + re.escape(MARK) + r"(?P<body>.*)" + re.escape(SEP) + r"@(?P<owner>[A-Za-z0-9._-]+)$")

KEEPER = r"""(() => {
  const L = %(label)s;
  const w = window;
  if (w.%(glob)s) { w.%(glob)s.set(L); return; }
  let cur = L;
  const base = (t) => {
    t = t || "";
    if (t === cur.head + cur.suffix) return "";
    if (t.startsWith(cur.prefix)) t = t.slice(cur.prefix.length);
    if (t.endsWith(cur.suffix)) t = t.slice(0, t.length - cur.suffix.length);
    return t;
  };
  const make = (b) => (b ? cur.prefix + b : cur.head) + cur.suffix;
  const want = (t) => make(base(t));
  const apply = () => { const t = document.title; const n = want(t); if (t !== n) document.title = n; };
  let watching = null;
  const obs = new MutationObserver(() => { if (document.head && watching !== document.head) watch(); apply(); });
  const watch = () => {
    obs.disconnect();
    watching = document.head || null;
    obs.observe(watching || document, { childList: true, subtree: true, characterData: true });
  };
  w.%(glob)s = {
    set(next) { const b = base(document.title); cur = next; w.%(glob)s.label = next; document.title = make(b); },
    label: L,
  };
  watch();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { watch(); apply(); });
  apply();
})();"""


def owner_of(cwd: str) -> str:
    try:
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        top = ""
    return OWNER_RE.sub("-", Path(top or cwd).name).strip("-") or "session"


def label_parts(task: str, persona: str, owner: str) -> dict:
    head = SEP.join(p for p in (task.strip(), persona.strip()) if p)
    return {"head": MARK + head, "prefix": MARK + head + SEP, "suffix": SEP + "@" + owner, "task": task.strip(),
            "persona": persona.strip(), "owner": owner}


def keeper_js(parts: dict) -> str:
    return KEEPER % {"label": json.dumps(parts, ensure_ascii=False), "glob": GLOBAL}


def touch(owner: str, task: str = "") -> None:
    """Record that this owner drove its walk now. Best effort: a heartbeat never blocks a walk."""
    try:
        HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
        (HEARTBEAT_DIR / owner).write_text(json.dumps({"task": task, "at": int(time.time())}) + "\n")
    except OSError:
        pass


def heartbeat_age_min(owner: str):
    try:
        return (time.time() - (HEARTBEAT_DIR / owner).stat().st_mtime) / 60
    except OSError:
        return None


def live_owners():
    """Folder names holding a live Claude/Codex session, or None when the probe fails."""
    fixture = os.environ.get("CLAUDE_TEST_BROWSER_TABS_SESSIONS")
    if fixture == "!fail":                                              # test suite only
        return None
    if fixture is not None:
        cwds = [c for c in fixture.split("\n") if c]
    else:
        try:
            res = subprocess.run(["bash", str(PORT_REGISTRY), "sessions"], capture_output=True, text=True,
                                 timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if res.returncode:
            return None
        cwds = [c for c in res.stdout.splitlines() if c]
    names = set()
    for cwd in cwds:
        names.update(OWNER_RE.sub("-", part) for part in Path(cwd).parts)
    return names


def is_test_browser(port: int) -> bool:
    if os.environ.get("CLAUDE_TEST_BROWSER_TABS_ANY_BROWSER") == "1":   # test suite only
        return True
    try:
        pids = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                              text=True, timeout=5).stdout.split()
        for pid in pids:
            comm = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True,
                                  timeout=5).stdout
            if "Google Chrome for Testing" in comm:
                return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def pages(port: int):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as res:
        return [p for p in json.load(res) if p.get("type") == "page"]


def classify(page: dict, owner: str, task: str, live) -> tuple:
    url, title = page.get("url", ""), page.get("title", "")
    if url in BLANK:
        return "stale", "blank tab"
    m = LABEL_RE.match(title)
    if not m:
        return "stale", "unlabelled, so no live walk owns it"
    tab_owner = m.group("owner")
    if tab_owner == owner:
        if task and not m.group("body").startswith(task + SEP) and m.group("body") != task:
            return "stale", "own tab of an earlier task"
        return "own", "this session"
    if live is None:
        return "unknown", f"owner @{tab_owner}: session probe failed, kept"
    if tab_owner not in live:
        return "stale", f"owner @{tab_owner} has no live session"
    age = heartbeat_age_min(tab_owner)
    if age is not None and age > IDLE_MIN:
        return "stale", f"owner @{tab_owner} idle {int(age)} min (over {IDLE_MIN})"
    return "live", f"owner @{tab_owner} is live"


def close(port: int, target: str) -> bool:
    for method in ("GET", "PUT"):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json/close/{target}", method=method)
            with urllib.request.urlopen(req, timeout=5) as res:
                if res.status == 200:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code != 405:
                return False
        except (urllib.error.URLError, OSError):
            return False
    return False


def survey(args) -> int:
    owner = args.owner or owner_of(os.getcwd())
    try:
        found = pages(args.port)
    except (urllib.error.URLError, OSError, ValueError):
        print(f"test-browser-tabs: no browser answers on 127.0.0.1:{args.port}", file=sys.stderr)
        return 3
    if not is_test_browser(args.port):
        print(f"test-browser-tabs: port {args.port} is not Chrome for Testing; nothing listed or closed",
              file=sys.stderr)
        return 5
    touch(owner, args.task)
    live = live_owners()
    rows = []
    for page in found:
        verdict, reason = classify(page, owner, args.task, live)
        row = {"id": page.get("id"), "class": verdict, "reason": reason, "title": page.get("title", ""),
               "url": page.get("url", "")}
        if args.action == "sweep" and verdict == "stale" and not args.dry_run:
            row["closed"] = close(args.port, page.get("id", ""))
        rows.append(row)
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            done = {True: " -> closed", False: " -> CLOSE FAILED"}.get(row.get("closed"), "")
            print(f"{row['class']:<7} {row['title'][:70]!r} {row['url'][:60]} ({row['reason']}){done}")
        kept = sum(r["class"] != "stale" for r in rows)
        stale = sum(r["class"] == "stale" for r in rows)
        verb = "closed" if args.action == "sweep" and not args.dry_run else "stale"
        print(f"owner @{owner}: {kept} kept, {stale} {verb}")
    return 1 if any(r.get("closed") is False for r in rows) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    lab = sub.add_parser("label", help="print the label-keeper JavaScript")
    lab.add_argument("--task", required=True, help='the PR or ticket the tab serves, e.g. "PR 1272"')
    lab.add_argument("--persona", default="", help='who the tab is, e.g. "SENDER 0107"; omit for one-persona walks')
    lab.add_argument("--owner", default="", help="the session's workspace folder name (default: from the cwd)")
    lab.add_argument("--out", default="", help="also write the script here, for evaluate_script sourcePath")
    for name in ("list", "sweep"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=9222)
        p.add_argument("--owner", default="")
        p.add_argument("--task", default="", help="close own tabs labelled with any other task")
        if name == "list":
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "label":
        if not args.task.strip():
            parser.error("--task must name the PR or ticket")
        owner = OWNER_RE.sub("-", args.owner).strip("-") if args.owner else owner_of(os.getcwd())
        js = keeper_js(label_parts(args.task, args.persona, owner))
        if args.out:
            Path(args.out).write_text(js + "\n")
        touch(owner, args.task.strip())
        print(js)
        return 0
    return survey(args)


if __name__ == "__main__":
    sys.exit(main())
