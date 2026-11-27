#!/usr/bin/env python3
"""Event-driven safety net that removes what finished sessions leave behind, and nothing else.

Wired on SessionStart and SessionEnd (`hook`): it returns at once and starts ONE detached, one-shot `run`:
the simulator lifecycle (6 below) every time, and the repo sweep at most once an hour per repo, one at a time.
No cron, daemon or LaunchAgent: it runs only when a session starts or ends, then exits.

A sweep removes ONLY:
  1. an ordinary git worktree of that repo (never the main checkout, the session's own checkout, or a
     Conductor-managed workspace) that passes EVERY gate:
       - branch tip is an ancestor of the local origin/<default> (no fetch; a stale ref only means fewer
         removals), or a detached HEAD contained in origin/<default> or another remote-tracking ref;
       - `git status --porcelain` is empty, not locked, and idle 24 h (its git dir and root untouched);
       - no process has its cwd inside (one `lsof -nP -d cwd` snapshot; never `lsof +D`);
       - no other worktree nests inside it;
       - every ignored path is a generated cache, a byte-identical copy of the main checkout's file, or a
         `.context` of at most 20 MB;
       - every session that worked in it (its intent-ledger asks and its transcript folder) is covered by
         an end-of-session learning record (bin/session_learning.py); the ledger's coverage is copied out
         before the ledger goes;
     then `git worktree remove` WITHOUT --force, and its local branch with `git branch -D` once the tip
     is re-proven (never the default branch);
  2. a branch-only `worktree-agent-*` ref (Agent-tool isolation) whose tip is an ancestor of origin/<default>;
  3. an empty ~/.claude/session-env/<sid> dir older than a day whose session is covered;
  4. per-session config state via `session_learning.py prune-state` (age AND covered);
  5. Docker leftovers per `docker_sweep` (the one owner of that policy): idle rebuildable data only,
     never the working set the next local stack start needs;
  6. a simulator the session created (absent from its SessionStart snapshot, present at SessionEnd),
     deleted once shut down and its session is learned from, unless it is the shared `agent` device,
     is named "<purpose> for <person>", or local-capacity claims or leases it.
Never a remote, never `--force`, never a Conductor workspace (that is the app's archive flow).
`sweep --dry-run` prints the verdict for every candidate and changes nothing.
"""
import argparse
import fcntl
import filecmp
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_learning as learning  # noqa: E402

HOME = Path(os.path.expanduser("~"))
STATE = Path(os.environ.get("CLAUDE_SESSION_REAPER_STATE") or HOME / ".claude" / "state" / "session-reaper")
SESSION_ENV = Path(os.environ.get("CLAUDE_SESSION_ENV_DIR") or HOME / ".claude" / "session-env")
CONDUCTOR_DB = Path(os.environ.get("CONDUCTOR_DB") or
                    HOME / "Library" / "Application Support" / "com.conductor.app" / "conductor.db")
CONDUCTOR_ROOTS = [Path(p) for p in os.environ.get("CONDUCTOR_WORKSPACE_ROOTS", "").split(os.pathsep) if p] or \
    [HOME / "conductor" / "workspaces"]
IDLE_HOURS = float(os.environ.get("CLAUDE_SESSION_REAPER_IDLE_HOURS", "24"))
DEBOUNCE_S = 3600
MAX_REMOVALS = 30
BUDGET_S = 900
CONTEXT_CAP = 20 * 1024 * 1024
GENERATED_DIRS = {"node_modules", ".next", "out", "dist", "build", ".turbo", "coverage", "test-results",
                  "playwright-report", "blob-report", ".fallow", "__pycache__", ".pytest_cache", ".mypy_cache",
                  ".ruff_cache", "DerivedData", ".build", ".wrangler", ".swc", ".parcel-cache", ".vercel",
                  ".svelte-kit", ".expo", "Pods"}
GENERATED_FILES = re.compile(r"(^|/)(next-env\.d\.ts|[^/]*\.tsbuildinfo|\.DS_Store|[^/]*\.pyc)$")
LOG_KEEP = 1000


def git(cwd, *args, timeout=60):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def log(event: dict):
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / "log.jsonl"
    event = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    try:
        lines = path.read_text().splitlines()[-(LOG_KEEP - 1):] if path.exists() else []
        path.write_text("\n".join(lines + [json.dumps(event)]) + "\n")
    except OSError:
        pass


def project_dir(path: str) -> Path:
    """Claude Code's transcript folder for a cwd: every non-alphanumeric character becomes '-'."""
    return learning.PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", path)


def repo_root(cwd: str) -> str:
    rc, common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc or not common:
        return ""
    common = Path(common)
    return str(common.parent) if common.name == ".git" else ""


def worktrees(root: str) -> list:
    rc, out = git(root, "worktree", "list", "--porcelain")
    if rc:
        return []
    rows, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                rows.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val or True
    return rows


def conductor_managed() -> tuple:
    """(workspace paths the Conductor DB knows, in any state; workspace roots). Unreadable DB → paths empty,
    and the structural rule (a non-hidden direct child of a project folder) still protects them."""
    paths, roots = set(), {str(r) for r in CONDUCTOR_ROOTS}
    if CONDUCTOR_DB.exists():
        try:
            con = sqlite3.connect(f"file:{CONDUCTOR_DB}?mode=ro", uri=True, timeout=2)
            for (p,) in con.execute("select workspace_path from workspaces where workspace_path is not null"):
                paths.add(os.path.realpath(p))
                roots.add(str(Path(p).parent.parent))
            con.close()
        except sqlite3.Error:
            pass
    return paths, roots


def is_managed(path: str, managed: tuple) -> bool:
    paths, roots = managed
    real = os.path.realpath(path)
    p = Path(real)
    return real in paths or (str(p.parent.parent) in roots and not p.name.startswith("."))


def cwd_snapshot():
    """Every process cwd, or None when lsof is unavailable (then nothing is removed)."""
    try:
        r = subprocess.run(["lsof", "-nP", "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, 1):
        return None
    return {os.path.realpath(line[1:]) for line in r.stdout.splitlines() if line.startswith("n/")}


def inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def newest_activity(path: str, gitdir: str) -> float:
    stamps = []
    for p in (path, os.path.join(path, ".git"), gitdir, *(os.path.join(gitdir, n) for n in
                                                          ("HEAD", "index", "logs/HEAD"))):
        try:
            stamps.append(os.stat(p).st_mtime)
        except OSError:
            pass
    return max(stamps) if stamps else time.time()


def dir_size_capped(path: Path, cap: int) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
            if total > cap:
                return total
    return total


def ignored_verdict(path: str, main: str) -> str:
    """'' when every ignored path is disposable, else the first path that is not."""
    try:
        r = subprocess.run(["git", "-C", path, "--no-optional-locks", "status", "--porcelain", "--ignored", "-z"],
                           capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "ignored-file scan timed out"
    for entry in r.stdout.decode(errors="replace").split("\0"):
        if not entry.startswith("!! "):
            continue
        rel = entry[3:].rstrip("/")
        top = rel.split("/")
        if top[-1] in GENERATED_DIRS or GENERATED_FILES.search(rel):
            continue
        if rel == ".context":
            if dir_size_capped(Path(path) / rel, CONTEXT_CAP) > CONTEXT_CAP:
                return ".context is over 20 MB"
            continue
        src, twin = Path(path) / rel, Path(main) / rel
        if src.is_file() and twin.is_file() and filecmp.cmp(src, twin, shallow=False):
            continue
        return f"unclassified ignored path {rel}"
    return ""


def sessions_in(path: str) -> tuple:
    """(sessions that worked in this worktree, the ledger). Ledger asks plus its transcript folder."""
    ledger = Path(path) / ".context" / "intent-ledger.md"
    sids = set()
    if ledger.is_file():
        sids |= set(learning.record_ledger(ledger))
    folder = project_dir(os.path.realpath(path))
    if folder.is_dir():
        sids |= {p.stem for p in folder.glob("*.jsonl")}
    return sids, ledger


def unlearned(sids: set, path: str) -> list:
    folder = project_dir(os.path.realpath(path))
    out = []
    for sid in sorted(sids):
        t = folder / f"{sid}.jsonl"
        if not learning.classify(sid, t if t.is_file() else None):
            out.append(sid)
    return out


def tip_merged(root: str, tip: str, default: str, detached: bool) -> bool:
    if git(root, "merge-base", "--is-ancestor", tip, default)[0] == 0:
        return True
    if detached:
        rc, out = git(root, "for-each-ref", "--count=1", "--contains", tip, "--format=%(refname)", "refs/remotes")
        return rc == 0 and bool(out)
    return False


def judge(wt: dict, ctx: dict) -> str:
    """'' when removable, else the reason it is retained."""
    path = wt["worktree"]
    real = os.path.realpath(path)
    if real == ctx["main"]:
        return "main checkout"
    if any(inside(x, real) for x in ctx["exclude"]):
        return "current session checkout"
    if wt.get("bare"):
        return "bare"
    if wt.get("locked"):
        return "locked"
    if wt.get("prunable") or not os.path.isdir(path):
        return "missing directory"
    if is_managed(path, ctx["managed"]):
        return "Conductor-managed workspace"
    branch = str(wt.get("branch", "")).removeprefix("refs/heads/")
    tip = str(wt.get("HEAD", ""))
    if not tip:
        return "no HEAD"
    if not tip_merged(ctx["root"], tip, ctx["default"], not branch):
        return "tip not merged"
    rc, gitdir = git(path, "rev-parse", "--absolute-git-dir")
    if rc:
        return "unreadable git dir"
    if ctx["now"] - newest_activity(path, gitdir) < IDLE_HOURS * 3600:
        return f"active in the last {IDLE_HOURS:g} h"
    if ctx["cwds"] is None:
        return "process cwd list unavailable"
    if any(inside(c, real) for c in ctx["cwds"]):
        return "a process has its cwd inside"
    others = [os.path.realpath(w["worktree"]) for w in ctx["all"] if w is not wt]
    if any(o != real and inside(o, real) for o in others) or \
            any(Path(path).glob(".context/*/.git")) or any(Path(path).glob(".claude/worktrees/*/.git")):
        return "another worktree nests inside"
    rc, status = git(path, "--no-optional-locks", "status", "--porcelain", timeout=120)
    if rc or status:
        return "uncommitted or untracked changes"
    why = ignored_verdict(path, ctx["main"])
    if why:
        return why
    sids, _ = sessions_in(path)
    left = unlearned(sids, path)
    if left:
        return f"unlearned: {len(left)} session(s) await end-of-session learning"
    return ""


def remove(wt: dict, ctx: dict) -> str:
    path = wt["worktree"]
    branch = str(wt.get("branch", "")).removeprefix("refs/heads/")
    tip = str(wt.get("HEAD", ""))
    rc, out = git(ctx["root"], "worktree", "remove", path, timeout=900)
    if rc:
        return f"git worktree remove refused: {out[:120]}"
    if branch and branch != ctx["default_name"]:
        rc2, now_tip = git(ctx["root"], "rev-parse", f"refs/heads/{branch}")
        if rc2 == 0 and now_tip == tip and git(ctx["root"], "merge-base", "--is-ancestor", tip, ctx["default"])[0] == 0:
            git(ctx["root"], "branch", "-D", branch)
    return "removed"


def agent_refs(root: str, default: str, checked_out: set) -> list:
    rc, out = git(root, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/worktree-agent-*")
    rows = []
    for line in out.splitlines() if rc == 0 else []:
        name, _, tip = line.partition(" ")
        if name not in checked_out and git(root, "merge-base", "--is-ancestor", tip, default)[0] == 0:
            rows.append((name, tip))
    return rows


def sweep_session_env(now: float, dry: bool) -> dict:
    kept = removed = 0
    if not SESSION_ENV.is_dir():
        return {"removed": 0, "unlearned": 0}
    for d in SESSION_ENV.iterdir():
        try:
            if not d.is_dir() or any(d.iterdir()) or now - d.stat().st_mtime < 86400:
                continue
        except OSError:
            continue
        if not learning.classify(d.name, unrecoverable_ok=True):
            kept += 1
            continue
        if not dry:
            try:
                d.rmdir()
            except OSError:
                continue
        removed += 1
    return {"removed": removed, "unlearned": kept}


# ---------------------------------------------------------------- Docker leftovers
DOCKER_EVERY_S = 6 * 3600
SUPA_ID_RE = re.compile(r"^(?P<prefix>[a-z0-9]+(?:-[a-z0-9]+)*?)-(?P<slug>[a-z0-9][a-z0-9-]*)-(?P<slot>\d+)$")


def slug(name: str) -> str:
    """The folder part of a per-worktree Supabase project id: lowercase, non-alphanumeric runs to '-',
    trimmed, at most 30 characters (the convention a repo's local-stack config derives its id with)."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))[:30]


def docker(*args, timeout=60):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return r.returncode, r.stdout.strip()


def known_repos(swept: str) -> dict:
    """{repo name: root} from Conductor's repo table plus the swept repo."""
    repos = {Path(swept).name.lower(): swept}
    if CONDUCTOR_DB.exists():
        try:
            con = sqlite3.connect(f"file:{CONDUCTOR_DB}?mode=ro", uri=True, timeout=2)
            for name, root in con.execute("select name, root_path from repos where root_path is not null"):
                if name and os.path.isdir(root):
                    repos[name.lower()] = root
            con.close()
        except sqlite3.Error:
            pass
    return repos


def live_folder_slugs(repos: dict) -> set:
    """Slugs of every folder a per-worktree stack could belong to: each known repo's worktrees and
    `.claude/worktrees/*`, and every folder up to two levels under a Conductor root, `.context/*` included."""
    names = set()
    for root in repos.values():
        names.add(Path(root).name)
        names |= {Path(w["worktree"]).name for w in worktrees(root)}
        names |= {p.name for p in Path(root).glob(".claude/worktrees/*") if p.is_dir()}
    for base in CONDUCTOR_ROOTS:
        for pattern in ("*", "*/*", "*/*/*", "*/*/.context/*"):
            try:
                names |= {p.name for p in base.glob(pattern) if p.is_dir()}
            except OSError:
                pass
    return {slug(n) for n in names if slug(n)}


def folder_sessions(folder_slug: str) -> set:
    """Sessions whose transcript folder names a cwd ending in that folder (the path is gone, so only
    its encoded name is left to match)."""
    sids = set()
    try:
        for d in learning.PROJECTS.iterdir():
            if d.is_dir() and slug(d.name).endswith("-" + folder_slug):
                sids |= {p.stem for p in d.glob("*.jsonl")}
    except OSError:
        pass
    return sids


STACK_IMAGE_RE = re.compile(r"^(?:public\.ecr\.aws/)?supabase/")


def image_sweep(dry: bool) -> tuple:
    """(images removed, stack images kept). Plain `docker image rm` (no -f), so Docker itself still refuses an
    image a container uses; the used set is also excluded up front."""
    rc, ids = docker("ps", "-a", "-q")
    used = set()
    if rc == 0 and ids:
        rc2, out = docker("inspect", "--format", "{{.Image}}", *ids.split())
        if rc2:
            return [], []  # cannot prove which images are in use: remove none
        used = set(out.split())
    rc, listing = docker("image", "ls", "--no-trunc", "--format", "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}")
    if rc:
        return [], []
    rows = [line.split("\t") for line in listing.splitlines() if line.count("\t") == 3]
    newest = {}
    for repo, tag, iid, created in rows:
        if STACK_IMAGE_RE.match(repo) and tag != "<none>" and created > newest.get(repo, ("", ""))[0]:
            newest[repo] = (created, iid)
    keep_ids = {iid for _, iid in newest.values()} | used
    removed, kept = [], sorted(f"{r}:{t}" for r, t, i, _ in rows if i in keep_ids and STACK_IMAGE_RE.match(r))
    for repo, tag, iid, _ in rows:
        if iid in keep_ids:
            continue
        ref = iid if tag == "<none>" or repo == "<none>" else f"{repo}:{tag}"
        if dry or docker("image", "rm", ref, timeout=120)[0] == 0:
            removed.append(ref)
    return removed, kept


def docker_sweep(swept: str, dry: bool, now: float) -> dict:
    """THE Docker cleanup policy (the one owner; the cleanup skill and references/dev-server-hygiene.md point
    here). Delete what is rebuildable and idle, never churn the working set:
      - only when the daemon already runs (a hook never starts Docker Desktop), at most every 6 h;
      - unused ANONYMOUS volumes, always (`docker volume prune -f`; never `-a`);
      - build cache unused for 7 days (`docker builder prune -f --filter until=168h`);
      - unused images, except the current stack image set (the newest tag per `supabase/*` or
        `public.ecr.aws/supabase/*` repository) so the next local stack start downloads nothing; older
        tags of that set go; an image any container (running or stopped) uses is never removed;
      - a named per-worktree Supabase volume only when its folder is gone, no container references it and
        its folder's sessions are learned from.
    Never `system prune -a --volumes`, never a named volume of a live folder."""
    stamp = STATE / "docker.stamp"
    try:
        if not dry and now - stamp.stat().st_mtime < DOCKER_EVERY_S:
            return {"skipped": "ran in the last 6 h"}
    except OSError:
        pass
    if docker("info", "--format", "{{.ServerVersion}}", timeout=5)[0]:
        return {"skipped": "Docker daemon not running"}
    out = {"orphan_stack_volumes": [], "retained": {}}
    if not dry:
        STATE.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        out["volume_prune"] = docker("volume", "prune", "-f", timeout=180)[1].splitlines()[-1:]  # anonymous only
        out["builder_prune"] = docker("builder", "prune", "-f", "--filter", "until=168h", timeout=180)[1].splitlines()[-1:]
    out["images_removed"], out["images_kept_stack"] = image_sweep(dry)
    rc, listing = docker("volume", "ls", "--filter", "label=com.supabase.cli.project",
                         "--format", '{{.Name}}\t{{.Label "com.supabase.cli.project"}}')
    if rc:
        return out
    repos, live = known_repos(swept), None
    for line in listing.splitlines():
        name, _, pid = line.partition("\t")
        m = SUPA_ID_RE.match(pid)
        prefix = next((r for r in repos if m and pid.startswith(r + "-")), "")
        if not m or not prefix:
            out["retained"][name] = "project id is not a per-worktree id of a known repo"
            continue
        folder = slug(pid[len(prefix) + 1:pid.rfind("-")])
        if live is None:
            live = live_folder_slugs(repos)
        if folder in live:
            continue  # its folder still exists
        if docker("ps", "-a", "-q", "--filter", f"volume={name}")[1]:
            out["retained"][name] = "a container references it"
            continue
        left = [sid for sid in folder_sessions(folder) if not learning.classify(sid)]
        if left:
            out["retained"][name] = f"unlearned: {len(left)} session(s) of its folder"
            continue
        if not dry and docker("volume", "rm", name)[0]:
            out["retained"][name] = "docker volume rm refused"
            continue
        out["orphan_stack_volumes"].append(name)
    return out


def sweep(root: str, exclude: list, dry: bool) -> dict:
    root = os.path.realpath(root)
    rc, default = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    report = {"repo": root, "removed": [], "retained": {}, "dry": dry}
    started = time.time()
    if rc or not default:
        report["skipped"] = "no origin/HEAD"
    else:
        all_wt = worktrees(root)
        ctx = {"root": root, "main": root, "default": default, "default_name": default.split("/", 1)[1],
               "exclude": [os.path.realpath(x) for x in exclude if x], "managed": conductor_managed(),
               "cwds": cwd_snapshot(), "now": time.time(), "all": all_wt}
        for wt in all_wt:
            if len(report["removed"]) >= MAX_REMOVALS or time.time() - started > BUDGET_S:
                report["retained"][wt["worktree"]] = "sweep budget reached"
                continue
            try:
                why = judge(wt, ctx)
            except Exception as e:  # one bad candidate never stops the sweep
                why = f"check failed: {type(e).__name__}"
            if not why and not dry:
                why = "" if remove(wt, ctx) == "removed" else "git worktree remove refused"
            if why:
                report["retained"][wt["worktree"]] = why
            else:
                report["removed"].append(wt["worktree"])
        checked = {str(w.get("branch", "")).removeprefix("refs/heads/") for w in worktrees(root)}
        refs = agent_refs(root, default, checked)
        if not dry:
            for name, tip in refs:
                git(root, "branch", "-D", name)
        report["agent_refs"] = [n for n, _ in refs]
    now = time.time()
    report["session_env"] = sweep_session_env(now, dry)
    report["state_classified"] = learning.classify_state(now)
    report["state"] = {} if dry else learning.prune_state(now)
    report["docker"] = docker_sweep(root, dry, now) if os.environ.get("CLAUDE_SESSION_REAPER_DOCKER") != "off" else {}
    report["unlearned_sessions"] = len(learning.pending())
    return report


def lock(root: str):
    STATE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(root.encode()).hexdigest()[:16]
    fh = open(STATE / f"{key}.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None, key
    return fh, key


# ---------------------------------------------------------------- simulators a session created
SIM_DEVICES = Path(os.environ.get("CLAUDE_SIM_DEVICES_DIR") or
                   HOME / "Library" / "Developer" / "CoreSimulator" / "Devices")
CAPACITY_STATE = Path(os.environ.get("CLAUDE_LOCAL_CAPACITY_STATE") or HOME / ".claude" / "state" / "local-capacity")
SHUTDOWN = 1
HUMAN_NAMED = re.compile(r"\bfor\b", re.I)  # "<purpose> for <person>" (references/ios-simulator.md) is kept


def sims() -> dict:
    """{UDID: (name, state)} read from each device.plist, so no simulator service is started to read it."""
    import plistlib
    out = {}
    try:
        for plist in SIM_DEVICES.glob("*/device.plist"):
            try:
                d = plistlib.loads(plist.read_bytes())
            except Exception:
                continue
            if d.get("UDID") and not d.get("isDeleted"):
                out[d["UDID"]] = (str(d.get("name", "")), d.get("state"))
    except OSError:
        pass
    return out


def sim_keep_reason(udid: str, name: str, state) -> str:
    if name.startswith("agent"):
        return "the shared warmed agent device"
    if HUMAN_NAMED.search(name):
        return "named for a person"
    if state != SHUTDOWN:
        return "not shut down"
    try:
        for f in CAPACITY_STATE.glob("*.json"):
            if udid in f.read_text(errors="replace"):
                return "claimed or leased in local-capacity"
    except OSError:
        return "local-capacity state unreadable"
    return ""


def sim_lifecycle(event: str, sid: str, dry: bool = False) -> dict:
    """SessionStart snapshots the devices; SessionEnd records the ones created since as that session's.
    Every run deletes recorded devices once their session is learned from and each passes sim_keep_reason."""
    d = STATE / "sims"
    out = {"deleted": [], "retained": {}}
    if not SIM_DEVICES.is_dir():
        return out
    d.mkdir(parents=True, exist_ok=True)
    now_sims = sims()
    if sid and learning.SID_RE.match(sid):
        start = d / f"{sid}.start.json"
        if event == "SessionStart" and not start.exists():
            start.write_text(json.dumps(sorted(now_sims)))
        elif event == "SessionEnd" and start.exists():
            before = set(json.loads(start.read_text() or "[]"))
            made = sorted(set(now_sims) - before)
            if made:
                (d / f"{sid}.created.json").write_text(json.dumps(made))
            start.unlink()
    for rec in d.glob("*.created.json"):
        owner = rec.name.split(".", 1)[0]
        left = []
        for udid in json.loads(rec.read_text() or "[]"):
            if udid not in now_sims:
                continue
            name, state = now_sims[udid]
            why = sim_keep_reason(udid, name, state)
            if not why and not learning.classify(owner):
                why = "unlearned: its session awaits end-of-session learning"
            if why:
                out["retained"][f"{name} ({udid})"] = why
                if not why.startswith(("the shared", "named for")):
                    left.append(udid)
                continue
            if dry:
                out["deleted"].append(f"{name} ({udid})")
                continue
            try:
                r = subprocess.run(["xcrun", "simctl", "delete", udid], capture_output=True, timeout=120)
                ok = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            (out["deleted"] if ok else left).append(f"{name} ({udid})" if ok else udid)
        if not dry:
            if left:
                rec.write_text(json.dumps(left))
            else:
                rec.unlink()
    for old in d.glob("*.start.json"):  # a session that never ended cleanly: its snapshot expires in 14 days
        try:
            if time.time() - old.stat().st_mtime > 14 * 86400:
                old.unlink()
        except OSError:
            pass
    return out


def hook() -> int:
    """SessionStart/SessionEnd: start one detached `run` for this session, return at once."""
    if os.environ.get("CLAUDE_SESSION_REAPER") == "off":
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    argv = [sys.executable, str(Path(__file__).resolve()), "run", "--event", str(payload.get("hook_event_name", "")),
            "--sid", str(payload.get("session_id", "")), "--exclude", cwd]
    root = repo_root(cwd) if os.path.isdir(cwd) else ""
    if root:
        argv += ["--repo", root]
    STATE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)
    return 0


def run_once(repo: str, exclude: list, event: str, sid: str) -> None:
    """The detached body of the hook: simulator lifecycle every time, the repo sweep at most hourly."""
    report = {"event": event, "sims": sim_lifecycle(event, sid)}
    if repo:
        key = hashlib.sha1(os.path.realpath(repo).encode()).hexdigest()[:16]
        stamp = STATE / f"{key}.stamp"
        try:
            fresh = time.time() - stamp.stat().st_mtime < DEBOUNCE_S
        except OSError:
            fresh = False
        if not fresh:
            fh, _ = lock(os.path.realpath(repo))
            if fh is not None:
                stamp.touch()
                report.update(sweep(repo, exclude, False))
                fh.close()
    log(report)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    r = sub.add_parser("run")
    r.add_argument("--repo", default="")
    r.add_argument("--exclude", action="append", default=[])
    r.add_argument("--event", default="")
    r.add_argument("--sid", default="")
    s = sub.add_parser("sweep")
    s.add_argument("--repo", required=True)
    s.add_argument("--exclude", action="append", default=[])
    s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get("CLAUDE_SESSION_REAPER_TRACE"):  # debugging aid: dump the stack if a sweep stalls
        import faulthandler
        faulthandler.dump_traceback_later(int(os.environ["CLAUDE_SESSION_REAPER_TRACE"]), exit=True)
    if a.cmd == "hook":
        return hook()
    try:
        os.nice(10)
    except OSError:
        pass
    if a.cmd == "run":
        run_once(a.repo, a.exclude, a.event, a.sid)
        return 0
    fh, _ = lock(os.path.realpath(a.repo))
    if fh is None:
        return 0  # another sweep of this repo is running
    report = sweep(a.repo, a.exclude, a.dry_run)
    report["sims"] = sim_lifecycle("", "", a.dry_run)
    if a.dry_run:
        print(json.dumps(report, indent=2))
    else:
        log(report)
    fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
