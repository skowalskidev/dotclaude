#!/usr/bin/env python3
"""One record per session saying the end-of-session config learning covers it, so cleanup can ask.

Every cleanup path that removes something a session leaves behind (its transcript folder, its config
state files, its worktree `.context` with the intent ledger, its `session-env` dir) gates on
`covered(sid)` first. Unlearned sessions are retained and listed by `pending`, which the
end-of-session learning drains on Simon's go (references/session-performance.md § End-of-session
learning).

The record lives OUTSIDE every worktree, at state/session-learning/<sid>.json, because the marker the
harness already writes (a `## <ts> · learning` note in the worktree's .context/intent-ledger.md, after
which that session has no asks) dies with the worktree. Verdicts:
  done | skipped   a learning note covers the session's asks (copied from the ledger, or recorded by
                   the learning pass over a queued session's transcript)
  empty            the session holds no message Simon typed, so a learning pass has nothing to read: no
                   typed message at all, a delegated worker (recorded by hooks/task-intake.sh at its first
                   prompt, which is a supervisor's brief), or a transcript whose cwd sits under an
                   `automatedSessionPaths` entry of the identity overlay (a pipeline that prompts Claude)
  unrecoverable    no transcript and no ledger ask of the session remain anywhere the config reads, so
                   no learning pass can ever run (counted apart; only empty dirs and markers go on it)

Commands:
  record <sid> --verdict done|skipped|empty --source <text>
  record-ledger <ledger.md>      record every session a learning note in that ledger covers
  covered <sid>                  exit 0 when a record exists
  classify <sid> [--transcript P] record `empty` when the transcript has no typed message; exit 0 = covered
  pending [--idle-hours H] [--limit N] [--classify]   ended sessions with a transcript and no record, oldest
                   first; --classify first records `empty` for each one with no message Simon typed
  prune-state                    the one owner of per-session config state pruning (age AND covered)
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CONFIG = HOME / ".claude"
CODE = Path(__file__).resolve().parents[1]  # this checkout's hooks/, so a worktree tests its own copy
STORE = Path(os.environ.get("CLAUDE_SESSION_LEARNING_DIR") or CONFIG / "state" / "session-learning")
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR") or CONFIG / "projects")
SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,80}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ASK_RE = re.compile(r"^## (\S+Z) · (ask|peer) · session (\S+)\s*$")
HEAD_RE = re.compile(r"^## (\S+Z) · ([a-z-]+)\s*$")
FENCE_RE = re.compile(r"^(`{3,})\s*$")
VERDICT_RE = re.compile(r"session learning: (done|skipped)")
VERDICTS = ("done", "skipped", "empty", "unrecoverable")
DAY = 86400
# Per-session config state, pruned only once its session is covered: (dir, minimum age in days).
STATE_DIRS = ((".intent-ledger", 7), (".session-root", 14), (".session-intake", 1))
LONG_KEEP = (".unrecorded", ".monitoring-only-listed")  # 30-day evidence markers (hooks/intent-ledger.sh)
MAX_TRANSCRIPT = 64 * 1024 * 1024  # a bigger transcript is retained, never read in a sweep


def _path(sid: str) -> Path:
    if not SID_RE.match(sid or ""):
        raise ValueError(f"invalid session id: {sid!r}")
    return STORE / f"{sid}.json"


def covered(sid: str) -> bool:
    try:
        return _path(sid).is_file()
    except ValueError:
        return False


def record(sid: str, verdict: str, source: str) -> bool:
    """Write the record once; an existing record stands. Returns True when this call wrote it."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    path = _path(sid)
    if path.exists():
        return False
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps({"session": sid, "verdict": verdict, "source": source[:300],
                               "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    os.replace(tmp, path)
    return True


def ledger_sessions(text: str) -> tuple:
    """(sessions with asks, {sid: verdict} for those a later learning note covers). Headings count only
    outside fences, so a heading pasted inside a prompt is never a boundary (same rule as the hook)."""
    asked, last_ask, notes = set(), {}, []  # notes: [(index, verdict)]
    fence, idx, in_learning, verdict = "", 0, False, ""
    for line in text.splitlines():
        if fence:
            if line.rstrip() == fence:
                fence = ""
            elif in_learning and VERDICT_RE.search(line):
                verdict = verdict or VERDICT_RE.search(line).group(1)
            continue
        m = FENCE_RE.match(line)
        if m:
            fence = m.group(1)
            continue
        a, h = ASK_RE.match(line), HEAD_RE.match(line)
        if a or h:
            if in_learning:
                notes.append((idx, verdict or "done"))
            in_learning, verdict = False, ""
            idx += 1
            if a and a.group(2) == "ask":
                asked.add(a.group(3))
                last_ask[a.group(3)] = idx
            elif h and h.group(2) == "learning":
                in_learning = True
            continue
        if in_learning and VERDICT_RE.search(line):
            verdict = verdict or VERDICT_RE.search(line).group(1)
    if in_learning:
        notes.append((idx, verdict or "done"))
    done = {}
    for sid in asked:
        after = [v for i, v in notes if i > last_ask[sid]]
        if after:
            done[sid] = after[0]
    return asked, done


def record_ledger(ledger: Path) -> dict:
    """Copy each covered session's verdict out of the ledger before the ledger can disappear."""
    try:
        asked, done = ledger_sessions(Path(ledger).read_text(errors="replace"))
    except OSError:
        return {}
    for sid, verdict in done.items():
        if SID_RE.match(sid):
            record(sid, verdict, f"ledger {ledger}")
    return {sid: (covered(sid)) for sid in asked}


def _typed_messages():
    """hooks/git-commit-guard.py owns what counts as a message Simon typed; reuse it, never a copy."""
    spec = importlib.util.spec_from_file_location("_guard", CODE / "hooks" / "git-commit-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.typed_messages


def transcripts(sid: str = "") -> list:
    """[(sid, path)] for every main-session transcript (subagent transcripts live under <sid>/)."""
    pattern = f"{sid}.jsonl" if sid else "*.jsonl"
    try:
        return [(p.stem, p) for p in PROJECTS.glob(f"*/{pattern}") if p.is_file()]
    except OSError:
        return []


def _root_ledger_asks(sid: str):
    """True/False: the ledger at the session's remembered root (bin/session-root.sh) has/lacks its asks
    (and records coverage on the way); None when no root is remembered or its ledger is gone."""
    try:
        root = (_state_dir(".session-root") / sid).read_text().strip()
    except OSError:
        return None
    ledger = Path(root) / ".context" / "intent-ledger.md"
    if not ledger.is_file():
        return None
    return sid in record_ledger(ledger)


def automated_paths() -> list:
    """Resolved `automatedSessionPaths` from the identity overlay: folders whose sessions a program
    prompts (a lead or batch runner), never Simon. Private data, so the public repo names none."""
    overlay = Path(os.environ.get("CLAUDE_IDENTITY_FILE") or CONFIG / "identity.local.json")
    try:
        values = json.loads(overlay.read_text()).get("automatedSessionPaths") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [Path(os.path.expanduser(v)).resolve() for v in values if isinstance(v, str) and v.strip()]


def transcript_cwd(path: Path) -> str:
    """The working directory a transcript recorded first, or ""."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(200), handle):
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        pass
    return ""


def automated_root(path: Path) -> str:
    """The automatedSessionPaths entry a transcript's cwd sits under, or ""."""
    cwd = transcript_cwd(path)
    if not cwd:
        return ""
    where = Path(cwd).resolve()
    for root in automated_paths():
        if where == root or root in where.parents:
            return str(root)
    return ""


def classify(sid: str, transcript: Path = None, unrecoverable_ok: bool = False) -> bool:
    """True when covered. A transcript with zero typed messages records `empty`; a missing, oversized or
    unreadable transcript stays uncovered (retain). With unrecoverable_ok (only for a caller removing
    nothing but an empty dir or a marker), a session with no transcript and no ledger ask anywhere
    records `unrecoverable`."""
    if covered(sid):
        return True
    paths = [Path(transcript)] if transcript else [p for _, p in transcripts(sid)]
    if not paths:
        if not unrecoverable_ok or not SID_RE.match(sid or ""):
            return False
        asks = _root_ledger_asks(sid)
        if asks is None or asks is False:
            record(sid, "unrecoverable", "no transcript and no ledger ask remain")
        return covered(sid)
    runner = automated_root(paths[0])
    if runner:
        record(sid, "empty", f"automated session path {runner}")
        return True
    try:
        typed = _typed_messages()
        for p in paths:
            if p.stat().st_size > MAX_TRANSCRIPT or typed(str(p))[0]:
                return False
    except Exception:
        return False
    record(sid, "empty", f"no typed message in {paths[0].name}")
    return True


def pending(idle_hours: float = 24, limit: int = 0, now: float = None, classify_first: bool = False) -> list:
    """Ended sessions (transcript untouched for idle_hours) with no record, oldest first, so the ones
    nearest Claude Code's own cleanupPeriodDays expiry are learned first. classify_first records `empty`
    for each one holding no message Simon typed, so the queue lists only sessions with words to learn."""
    now = now or time.time()
    rows = []
    for sid, path in transcripts():
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age >= idle_hours * 3600 and not covered(sid) and not (classify_first and classify(sid, path)):
            rows.append((age, sid, path))
    rows.sort(reverse=True)
    return rows[:limit] if limit else rows


def _state_dir(name: str) -> Path:
    if name == ".session-root" and os.environ.get("CLAUDE_SESSION_ROOT_DIR"):  # bin/session-root.sh's override
        return Path(os.environ["CLAUDE_SESSION_ROOT_DIR"])
    return CONFIG / name


def _sid_of(name: str) -> str:
    return name.split(".", 1)[0]


def classify_state(now: float = None, limit: int = 60, budget_s: float = 60) -> int:
    """Classify the uncovered sessions whose state files are past their age, so prune_state can act on
    the ones with nothing to learn. Bounded per sweep; the rest wait for the next one."""
    now, started, seen, n = now or time.time(), time.time(), set(), 0
    for dirname, min_days in STATE_DIRS:
        d = _state_dir(dirname)
        try:
            files = list(d.iterdir()) if d.is_dir() else []
        except OSError:
            continue
        for f in files:
            sid = _sid_of(f.name)
            if sid in seen or not UUID_RE.match(sid) or covered(sid):
                continue
            try:
                if now - f.stat().st_mtime <= min_days * DAY:
                    continue
            except OSError:
                continue
            seen.add(sid)
            if n >= limit or time.time() - started > budget_s:
                return n
            classify(sid, unrecoverable_ok=True)
            n += 1
    return n


def prune_state(now: float = None) -> dict:
    """Delete per-session config state only when it is old enough AND its session is covered.
    A file not named for a session (a test fixture leak such as contract-*) goes after a day."""
    now = now or time.time()
    removed = {}
    for dirname, min_days in STATE_DIRS:
        d = _state_dir(dirname)
        if not d.is_dir():
            continue
        count = 0
        for f in d.iterdir():
            try:
                if not f.is_file():
                    continue
                age = now - f.stat().st_mtime
                sid = _sid_of(f.name)
                if not UUID_RE.match(sid):
                    ok = age > DAY
                else:
                    days = 30 if f.name.endswith(LONG_KEEP) else min_days
                    ok = age > days * DAY and covered(sid)
                if ok:
                    f.unlink()
                    count += 1
            except OSError:
                continue
        removed[dirname] = count
        if dirname == ".session-intake":  # retired: no hook writes it since the intake approval gate went
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("sid")
    r.add_argument("--verdict", required=True, choices=VERDICTS)
    r.add_argument("--source", required=True)
    sub.add_parser("record-ledger").add_argument("ledger")
    sub.add_parser("covered").add_argument("sid")
    c = sub.add_parser("classify")
    c.add_argument("sid")
    c.add_argument("--transcript")
    p = sub.add_parser("pending")
    p.add_argument("--idle-hours", type=float, default=24)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--classify", action="store_true")
    sub.add_parser("prune-state")
    a = ap.parse_args(argv)
    if a.cmd == "record":
        record(a.sid, a.verdict, a.source)
        return 0
    if a.cmd == "record-ledger":
        for sid, ok in sorted(record_ledger(Path(a.ledger)).items()):
            print(f"{sid}\t{'covered' if ok else 'unlearned'}")
        return 0
    if a.cmd == "covered":
        return 0 if covered(a.sid) else 1
    if a.cmd == "classify":
        return 0 if classify(a.sid, a.transcript) else 1
    if a.cmd == "pending":
        rows = pending(a.idle_hours, a.limit, classify_first=a.classify)
        for age, sid, path in rows:
            print(f"{sid}\t{age / DAY:.1f}d\t{path}")
        print(f"pending: {len(rows)} ended session(s) await end-of-session learning", file=sys.stderr)
        return 0
    if a.cmd == "prune-state":
        print(json.dumps(prune_state()))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
