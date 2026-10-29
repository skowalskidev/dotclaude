#!/usr/bin/env python3
"""Verify a config-repo head before it lands on main, and record it for hooks/git-commit-guard.py.

The config repo's standing authorization (rules/self-healing-config.md) covers landing a validated
repair with no question. "Validated" is this script, so the guard can tell a checked head from an
accidental push without asking anyone:

  1. --diff            prints the full `git diff <remote>/main HEAD` and its sha256. Read all of it.
  2. --reviewed <hash> confirms that exact diff was reviewed, then runs the checks below and, only if
                       every one passes, records HEAD's sha in <git-common-dir>/claude-config-land.json.

Checks, all on the exact HEAD that will be pushed:
  - the checkout belongs to the ~/.claude repository (shared Git storage), never another repo;
  - no tracked change is uncommitted, so the suite ran against HEAD itself;
  - HEAD fast-forwards the freshly fetched remote main (merge it first otherwise);
  - the reviewed hash matches the current diff, so a later edit invalidates the review;
  - the contract suite passes: /usr/bin/python3 hooks/config-contract.test.py;
  - dotfiles/secret-scan.sh --range passes (gitleaks + the identity guard) on the landing commits.

The guard then lets `git push origin HEAD:main` through for that sha only. A new commit is a new sha
and needs a new run. The record is a seatbelt against an unchecked push, not a security boundary.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

MARKER = "claude-config-land.json"
KEEP = 20


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def fail(message):
    print(f"config-land-check: FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def common_dir(root):
    return os.path.realpath(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def diff_text(root, base):
    return subprocess.run(["git", "-C", root, "diff", base, "HEAD"], capture_output=True,
                          check=True).stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="the config checkout or worktree to land")
    ap.add_argument("--remote", default="origin")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--diff", action="store_true", help="print the landing diff and its sha256")
    mode.add_argument("--reviewed", metavar="SHA256", help="the --diff hash you read in full")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    config = os.path.expanduser("~/.claude")
    if not os.path.isdir(root) or common_dir(root) != common_dir(config):
        fail(f"{root} is not a checkout of the ~/.claude config repository")

    git(root, "fetch", "--quiet", args.remote, "main")
    base = f"refs/remotes/{args.remote}/main"
    git(root, "rev-parse", "--verify", base)
    head = git(root, "rev-parse", "HEAD")
    if subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", base, head]).returncode:
        fail(f"HEAD does not fast-forward {args.remote}/main. Merge {args.remote}/main, re-run checks.")
    raw = diff_text(root, base)
    digest = hashlib.sha256(raw).hexdigest()

    if args.diff:
        sys.stdout.buffer.write(raw)
        print(f"\ndiff-sha256: {digest}")
        return 0

    if git(root, "status", "--porcelain", "--untracked-files=no"):
        fail("tracked changes are uncommitted; commit them so the checks run on HEAD")
    if not raw:
        fail(f"HEAD adds nothing to {args.remote}/main")
    if args.reviewed != digest:
        fail("the reviewed hash does not match the current diff; run --diff and read it again")

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
                    "checks": ["contract-suite", "secret-scan", "diff-review"],
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"verified": entries[-KEEP:]}, f, indent=1)
    os.replace(tmp, path)
    print(f"verified {head}\nland with: git -C {root} push {args.remote} HEAD:main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
