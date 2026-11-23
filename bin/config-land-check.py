#!/usr/bin/env python3
"""Verify a config-repo head, land it on main, and record it for hooks/git-commit-guard.py.

The config repo's standing authorization (rules/self-healing-config.md) covers landing a validated
repair with no question. "Validated" is this script, so the guard can tell a checked head from an
accidental push without asking anyone:

  1. --diff            prints the full `git diff <remote>/main...HEAD` and its sha256. Read all of it.
  2. --reviewed <hash> confirms that exact diff was reviewed, then, holding the landing lock, merges
                       the fresh remote main, runs the checks below and, only if every one passes,
                       records HEAD's sha in <git-common-dir>/claude-config-land.json and pushes it.

The landing lock serializes concurrent landers on this machine (fcntl.flock on
<git-common-dir>/claude-config-land.lock, shared by every worktree). A lander holds it from the fetch
and merge of the remote main through the checks to the push, so a second lander queues instead of
racing and rerunning the whole check. While it waits it prints who holds the lock and since when;
after --lock-wait seconds (default 1800) it exits 75 naming the holder. The kernel releases the lock
when its holder exits, killed included.

Checks, all on the exact HEAD that will be pushed:
  - the checkout belongs to the ~/.claude repository (shared Git storage), never another repo;
  - no tracked change is uncommitted, so the suite runs against HEAD itself;
  - HEAD fast-forwards the freshly fetched remote main (merged inside the lock; a conflict stops);
  - the reviewed hash matches the diff after that merge, so a later edit, or a main change that
    touches the reviewed lines, invalidates the review (the hash covers file headers and +/- lines,
    not context, blob ids or hunk positions, so main work elsewhere in a touched file keeps it);
  - the contract suite passes: /usr/bin/python3 hooks/config-contract.test.py;
  - dotfiles/secret-scan.sh --range passes (gitleaks + the identity guard) on the landing commits.

The push goes to <remote> main for that sha only and is verified on the remote. The guard still
lets a manual `git push origin HEAD:main` through for a recorded sha. A new commit is a new sha and
needs a new run. The record is a seatbelt against an unchecked push, not a security boundary.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time

MARKER = "claude-config-land.json"
LOCK = "claude-config-land.lock"
KEEP = 20
LOCK_WAIT_S = 1800
LOCK_POLL_S = 0.5
LOCK_NOTE_EVERY_S = 60
EXIT_LOCK_TIMEOUT = 75


class LockTimeout(Exception):
    pass


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def fail(message):
    print(f"config-land-check: FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def note(message):
    print(f"config-land-check: {message}", file=sys.stderr, flush=True)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def common_dir(root):
    return os.path.realpath(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def diff_text(root, base, *extra):
    # Three-dot: the change HEAD adds since it left base. It equals the two-dot diff once base is merged.
    return subprocess.run(["git", "-C", root, "diff", *extra, f"{base}...HEAD"], capture_output=True,
                          check=True).stdout


def review_digest(root, base):
    """sha256 of the reviewed change itself: its file headers and +/- lines, with no context lines,
    blob ids or hunk positions. A clean merge of main work elsewhere in a touched file keeps the
    review; any change to an added or removed line, or a new file, needs a new one."""
    raw = diff_text(root, base, "--unified=0")
    kept = [ln for ln in raw.splitlines(keepends=True) if not ln.startswith((b"index ", b"@@"))]
    return hashlib.sha256(b"".join(kept)).hexdigest()


def describe_holder(path):
    try:
        with open(path, encoding="utf-8") as f:
            info = json.loads(f.read() or "{}")
    except (OSError, ValueError):
        info = {}
    if not isinstance(info, dict) or not info.get("pid"):
        return "an unknown holder"
    return (f"pid {info.get('pid')} ({info.get('branch') or 'unknown branch'} at "
            f"{info.get('root') or 'unknown root'}) since {info.get('since') or 'an unknown time'}")


@contextlib.contextmanager
def landing_lock(path, wait_s, owner):
    """Hold an exclusive flock on path for the block; wait at most wait_s, then raise LockTimeout."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    held = False
    try:
        start = time.monotonic()
        next_note = start
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                waited = time.monotonic() - start
                if waited >= wait_s:
                    raise LockTimeout(f"gave up after {int(waited)} s waiting for the landing lock held by "
                                      f"{describe_holder(path)}; land again once it finishes")
                if time.monotonic() >= next_note:
                    note(f"waiting for the landing lock held by {describe_holder(path)} "
                         f"({int(waited)} s of {int(wait_s)} s)")
                    next_note = time.monotonic() + LOCK_NOTE_EVERY_S
                time.sleep(max(0.0, min(LOCK_POLL_S, wait_s - waited)))
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps({**owner, "pid": os.getpid(), "since": now_iso()}).encode(), 0)
        yield
    finally:
        if held:
            os.ftruncate(fd, 0)
        os.close(fd)  # closing the descriptor releases the flock; process death does the same


def merge_base_in(root, remote, base):
    """Merge the fetched remote main into HEAD when HEAD does not already contain it."""
    head = git(root, "rev-parse", "HEAD")
    if not subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", base, head]).returncode:
        return head
    merged = subprocess.run(["git", "-C", root, "merge", "--no-edit", base], capture_output=True, text=True)
    if merged.returncode:
        conflicts = git(root, "diff", "--name-only", "--diff-filter=U", check=False)
        subprocess.run(["git", "-C", root, "merge", "--abort"], capture_output=True)
        fail(f"merging {remote}/main conflicts ({conflicts.replace(chr(10), ', ') or merged.stderr.strip()}); "
             f"merge it, resolve within the owned change, then run --diff again")
    head = git(root, "rev-parse", "HEAD")
    note(f"merged {remote}/main into HEAD ({head[:12]})")
    return head


def land(root, remote, reviewed, base):
    head = merge_base_in(root, remote, base)
    if not diff_text(root, base):
        fail(f"HEAD adds nothing to {remote}/main")
    digest = review_digest(root, base)
    if reviewed != digest:
        fail("the reviewed hash does not match the current diff (an edit, or a merged main change to the "
             "same lines, changed it); run --diff and read it again")

    suite = subprocess.run(["/usr/bin/python3", os.path.join(root, "hooks", "config-contract.test.py")],
                           cwd=root, capture_output=True, text=True)
    if suite.returncode:
        sys.stderr.write(suite.stdout[-4000:] + suite.stderr[-2000:])
        fail("the contract suite failed")
    scan = subprocess.run(["bash", os.path.join(root, "dotfiles", "secret-scan.sh"),
                           "--range", f"{base}..{head}"], cwd=root, capture_output=True, text=True)
    if scan.returncode:
        sys.stderr.write(scan.stderr)
        fail("the secret scan blocked the landing commits")
    if git(root, "rev-parse", "HEAD") != head:
        fail("HEAD moved while the checks ran")

    path = os.path.join(common_dir(root), MARKER)
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    entries = [e for e in record.get("verified", []) if isinstance(e, dict) and e.get("sha") != head]
    entries.append({"sha": head, "base": git(root, "rev-parse", base), "diffSha256": digest,
                    "checks": ["contract-suite", "secret-scan", "diff-review"], "at": now_iso()})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"verified": entries[-KEEP:]}, f, indent=1)
    os.replace(tmp, path)
    print(f"verified {head}")

    pushed = subprocess.run(["git", "-C", root, "push", "--quiet", remote, f"{head}:refs/heads/main"],
                            capture_output=True, text=True)
    if pushed.returncode:
        fail(f"the push to {remote}/main was rejected: {pushed.stderr.strip()}. Something landed outside "
             f"the lock; run --diff and land again, never force")
    git(root, "fetch", "--quiet", remote, "main")
    if git(root, "rev-parse", base) != head:
        fail(f"{remote}/main does not point at {head[:12]} after the push")
    print(f"landed {head} on {remote}/main")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="the config checkout or worktree to land")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--lock-wait", type=float, default=LOCK_WAIT_S, metavar="SECONDS",
                    help=f"longest wait for another lander's lock before exit {EXIT_LOCK_TIMEOUT}")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--diff", action="store_true", help="print the landing diff and its sha256")
    mode.add_argument("--reviewed", metavar="SHA256", help="the --diff hash you read in full; lands it")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    config = os.path.expanduser("~/.claude")
    if not os.path.isdir(root) or common_dir(root) != common_dir(config):
        fail(f"{root} is not a checkout of the ~/.claude config repository")
    base = f"refs/remotes/{args.remote}/main"

    if args.diff:
        git(root, "fetch", "--quiet", args.remote, "main")
        git(root, "rev-parse", "--verify", base)
        sys.stdout.buffer.write(diff_text(root, base))
        print(f"\ndiff-sha256: {review_digest(root, base)}")
        return 0

    if git(root, "status", "--porcelain", "--untracked-files=no"):
        fail("tracked changes are uncommitted; commit them so the checks run on HEAD")
    owner = {"root": root, "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)}
    try:
        with landing_lock(os.path.join(common_dir(root), LOCK), args.lock_wait, owner):
            git(root, "fetch", "--quiet", args.remote, "main")
            git(root, "rev-parse", "--verify", base)
            land(root, args.remote, args.reviewed, base)
    except LockTimeout as e:
        print(f"config-land-check: TIMEOUT: {e}", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    return 0


if __name__ == "__main__":
    sys.exit(main())
