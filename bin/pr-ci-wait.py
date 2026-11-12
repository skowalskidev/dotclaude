#!/usr/bin/env python3
"""Wait on a pull request's CI for one head commit, and say why when it cannot finish.

The one way to wait on PR CI after a push (references/git-pr-deploy.md § After a push, and after
merging the base in). It refuses the two quiet states an ad-hoc loop reads as done:

  * a PR that conflicts with its base: GitHub starts no pull_request run, so "no checks reported"
    lasts forever. Exit 3 at once with the instruction to merge the base in and push.
  * no workflow run for the head sha yet: "no checks" is never done. Exit 4 after --start-min.

--once reads the PR and its checks a single time and exits with the same codes, 6 meaning a check is
still pending: the CI-green leg of `hooks/intent-ledger.sh gate PASS`.

Checks are judged by the newest entry per check identity (latest_checks in
hooks/git-commit-guard.py, imported, not copied), so a cancelled run superseded by a rerun never
fails the wait. Standard library only; needs gh.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_CONFLICT, EXIT_NO_RUN, EXIT_HEAD_MOVED, EXIT_TIMEOUT = 0, 1, 2, 3, 4, 5, 6
EXIT_PENDING = EXIT_TIMEOUT  # --once: a check is still running, the same state a wait times out in
TRANSIENT_RE = re.compile(r"HTTP 5\d\d|\b50[0234]\b|Bad Gateway|Service Unavailable|Gateway Time-?out|"
                          r"timed out|connection reset|EOF", re.I)
GH_ATTEMPTS = 4
SHA_RE = re.compile(r"[0-9a-f]{7,40}")

_spec = importlib.util.spec_from_file_location(
    "git_commit_guard", Path(__file__).resolve().parent.parent / "hooks" / "git-commit-guard.py")
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)
latest_checks = _guard.latest_checks
PASSED_CONCLUSIONS = _guard.PASSED_CONCLUSIONS


class GhError(Exception):
    pass


def gh_json(args: list):
    """Run gh and parse its JSON stdout; retry a transient 5xx or network error up to GH_ATTEMPTS times."""
    delay = float(os.environ.get("PR_CI_WAIT_RETRY_SEC", "5"))
    err = ""
    for attempt in range(1, GH_ATTEMPTS + 1):
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
        if p.returncode == 0:
            try:
                return json.loads(p.stdout or "null")
            except json.JSONDecodeError as e:
                raise GhError(f"gh {' '.join(args[:2])} printed non-JSON: {e}")
        err = (p.stderr or p.stdout).strip()
        if not TRANSIENT_RE.search(err) or attempt == GH_ATTEMPTS:
            break
        print(f"gh {' '.join(args[:2])} transient error (attempt {attempt}/{GH_ATTEMPTS}): {err[:160]}",
              file=sys.stderr)
        time.sleep(delay * attempt)
    raise GhError(f"gh {' '.join(args[:2])} failed: {err[:300]}")


def read_pr(repo: str, pr: int) -> dict:
    return gh_json(["pr", "view", str(pr), "--repo", repo,
                    "--json", "mergeable,mergeStateStatus,headRefOid,statusCheckRollup"]) or {}


def read_runs(repo: str, sha: str) -> list:
    return gh_json(["run", "list", "--repo", repo, "--commit", sha, "--limit", "100",
                    "--json", "databaseId,status,conclusion,workflowName,name"]) or []


def conflicted(pr: dict) -> bool:
    return pr.get("mergeable") == "CONFLICTING" or pr.get("mergeStateStatus") == "DIRTY"


def merge_state(pr: dict) -> str:
    return f"mergeable={pr.get('mergeable') or 'UNKNOWN'} mergeStateStatus={pr.get('mergeStateStatus') or 'UNKNOWN'}"


def check_state(c: dict) -> str:
    """SUCCESS, SKIPPED, NEUTRAL, PENDING or a failing conclusion, for a CheckRun or a StatusContext."""
    if "state" in c and "status" not in c:
        state = str(c.get("state") or "PENDING").upper()
        return "PENDING" if state in ("PENDING", "EXPECTED") else state
    if str(c.get("status") or "").upper() != "COMPLETED":
        return "PENDING"
    return str(c.get("conclusion") or "PENDING").upper()


def check_name(c: dict) -> str:
    wf = c.get("workflowName") or ""
    name = c.get("name") or c.get("context") or "a check"
    return f"{wf} / {name}" if wf else name


def latest_runs(runs: list) -> list:
    """The newest run per workflow: a rerun or a superseding push replaces the older run."""
    newest: dict = {}
    for r in runs:
        key = r.get("workflowName") or r.get("name") or ""
        if key not in newest or int(r.get("databaseId") or 0) > int(newest[key].get("databaseId") or 0):
            newest[key] = r
    return list(newest.values())


def summary(sha: str, checks: list) -> str:
    counts: dict = {}
    for c in checks:
        s = check_state(c)
        counts[s] = counts.get(s, 0) + 1
    parts = ", ".join(f"{n} {s.lower()}" for s, n in sorted(counts.items()))
    failing = [check_name(c) for c in checks if check_state(c) not in PASSED_CONCLUSIONS | {"PENDING"}]
    line = f"{sha[:12]}: {len(checks)} checks ({parts or 'none'})"
    if failing:
        line += "; failing: " + ", ".join(sorted(failing))
    return line


def parse_args(argv: list) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="pr-ci-wait.py",
        description="Wait until every CI check on a PR's head commit is terminal. Exit codes: "
                    "0 every check succeeded or was skipped; 1 a check failed or was cancelled; "
                    "2 bad arguments or a gh failure after retries; 3 the PR conflicts with its base "
                    "(merge the base in and push); 4 no workflow run for the head sha within --start-min; "
                    "5 the PR head moved off --sha; 6 --timeout-min reached with checks still pending "
                    "(with --once: a check still pending).")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int, help="pull request number")
    ap.add_argument("--sha", help="head commit to wait on, full or abbreviated (7-40 hex characters); "
                                  "default: the PR's current head")
    ap.add_argument("--require", action="append", default=[], metavar="CHECK",
                    help="a check name that must appear before the wait can pass (repeatable); use a "
                         "required job that starts at push time, so a fast side workflow cannot pass early")
    ap.add_argument("--timeout-min", type=float, default=50.0,
                    help="overall wait, default 50 (keep it 5+ minutes under the background tool's cap)")
    ap.add_argument("--start-min", type=float, default=10.0,
                    help="how long to wait for the first workflow run for the sha, default 10")
    ap.add_argument("--poll-sec", type=float, default=30.0, help="seconds between polls, default 30")
    ap.add_argument("--once", action="store_true",
                    help="read the PR and its checks once and exit, without waiting; a failed check exits 1 "
                         "even while others still run, and a pass needs no second poll")
    args = ap.parse_args(argv)
    if "/" not in args.repo:
        ap.error("--repo must be owner/name")
    if args.sha is not None:
        args.sha = args.sha.strip().lower()
        if not SHA_RE.fullmatch(args.sha):
            ap.error(f"--sha must be a commit id of 7-40 hex characters, got {args.sha!r}")
    return args


def read_once_verdict(sha: str, checks: list, missing: list, pending: bool) -> int:
    """--once: a failed check wins over a pending one, so the gate names what to fix first."""
    if any(check_state(c) not in PASSED_CONCLUSIONS | {"PENDING"} for c in checks):
        print("FAILED " + summary(sha, checks))
        return EXIT_FAILED
    if pending or missing:
        print("PENDING " + summary(sha, checks)
              + (f"; required check not seen: {', '.join(missing)}" if missing else ""))
        return EXIT_PENDING
    print("PASSED " + summary(sha, checks))
    return EXIT_OK


def same_commit(sha: str, head: str) -> bool:
    """True when --sha (full, or an abbreviated prefix) names the PR head commit."""
    return head.lower().startswith(sha)


def wait(args: argparse.Namespace) -> int:
    start = time.monotonic()
    deadline = start + args.timeout_min * 60
    start_deadline = start + args.start_min * 60
    sha = args.sha
    clean_polls = 0
    while True:
        pr = read_pr(args.repo, args.pr)
        head = pr.get("headRefOid") or ""
        if conflicted(pr):
            print(f"CONFLICTING: PR #{args.pr} {merge_state(pr)}; GitHub starts no pull_request run on a "
                  f"conflicting PR. Merge the base in and push; reruns and empty commits start nothing.")
            return EXIT_CONFLICT
        if not sha:
            sha = head
            if not sha:
                print(f"PR #{args.pr} reported no head commit", file=sys.stderr)
                return EXIT_USAGE
        if head and not same_commit(sha, head):
            print(f"HEAD MOVED: PR #{args.pr} head is {head[:12]}, not {sha[:12]}; wait on the new head.")
            return EXIT_HEAD_MOVED
        if len(sha) < 40:
            if not head:
                print(f"PR #{args.pr} reported no head commit to expand --sha {sha} against", file=sys.stderr)
                return EXIT_USAGE
            sha = head  # every read below needs the full id: gh run list --commit matches no prefix
        runs = latest_runs(read_runs(args.repo, sha))
        checks = latest_checks(pr.get("statusCheckRollup") or [])
        now = time.monotonic()
        missing: list = []
        if not runs and not checks:
            if args.once or now >= start_deadline:
                waited = "" if args.once else f" after {args.start_min:g} min"
                print(f"NO RUN: no workflow run for {sha[:12]}{waited}; "
                      f"PR #{args.pr} {merge_state(pr)}. Read the merge state and the workflow triggers "
                      f"before any rerun or empty commit.")
                return EXIT_NO_RUN
        else:
            names = {c.get("name") or c.get("context") for c in checks}
            missing = [n for n in args.require if n not in names]
            pending_runs = [r for r in runs if str(r.get("status") or "").lower() != "completed"]
            pending = [c for c in checks if check_state(c) == "PENDING"]
            if args.once:
                return read_once_verdict(sha, checks, missing, bool(pending_runs or pending or not checks))
            if checks and not missing and not pending_runs and not pending:
                clean_polls += 1
                failing = [c for c in checks if check_state(c) not in PASSED_CONCLUSIONS]
                if failing:
                    print("FAILED " + summary(sha, checks))
                    return EXIT_FAILED
                # One more poll before passing: a workflow that registers late must not be missed.
                if clean_polls >= 2:
                    print("PASSED " + summary(sha, checks))
                    return EXIT_OK
            else:
                clean_polls = 0
        if now >= deadline:
            print(f"TIMEOUT after {args.timeout_min:g} min: " + summary(sha or "?", checks)
                  + (f"; required check not seen: {', '.join(missing)}" if missing else ""))
            return EXIT_TIMEOUT
        time.sleep(args.poll_sec)


def main(argv: list) -> int:
    args = parse_args(argv)
    try:
        return wait(args)
    except GhError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
