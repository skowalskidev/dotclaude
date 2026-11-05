#!/usr/bin/env python3
"""Offline regression tests for bin/ci-gate-list.py. Standard library only; needs the system ruby."""
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ci-gate-list.py"
FAILS = []

PR_WORKFLOW = """\
name: ci
on:
  pull_request:
  merge_group:
defaults:
  run:
    working-directory: app
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint
        run: npm run lint
      - run: npm run typecheck
        working-directory: web
  db:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    services:
      postgres:
        image: postgres:17
    strategy:
      matrix:
        shard: [1/2, 2/2]
    steps:
      - name: Check migration order
        run: node scripts/db.mjs check-order
  docker:
    runs-on: ubuntu-latest
    steps:
      - name: Migration runner
        run: |
          docker run --detach postgres:17
          node test.mjs
  shared:
    uses: ./.github/workflows/shared.yml
"""

PUSH_ONLY = """\
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
"""


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def run(*files, events=None):
    args = [sys.executable, str(SCRIPT)] + (["--events", events] if events else []) + [str(f) for f in files]
    return subprocess.run(args, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    pr = Path(tmp) / "ci.yml"
    pr.write_text(PR_WORKFLOW)
    push = Path(tmp) / "deploy.yml"
    push.write_text(PUSH_ONLY)
    bad = Path(tmp) / "bad.yml"
    bad.write_text("on: [pull_request\n")

    r = run(pr, push)
    out = r.stdout
    check(r.returncode == 0, f"PR workflow should exit 0, got {r.returncode}: {r.stderr}")
    check("TOTAL 4 run steps in 4 jobs (2 need services)" in out, "total line wrong:\n" + out)
    check("triggers: pull_request, merge_group" in out, "bare on: key (YAML true) not read as triggers")
    check("working-directory: app" in out, "workflow default working-directory missing")
    check("wd: web" in out, "step working-directory override missing")
    check("2. npm run typecheck" in out, "unnamed run step not labelled by its command")
    check("CI-only? needs services: postgres" in out, "services job step not marked")
    check("CI-only? starts containers: docker" in out, "container-starting step not marked")
    check("matrix: shard" in out and "if: github.event_name == 'pull_request'" in out, "job matrix/if missing")
    check("calls reusable workflow ./.github/workflows/shared.yml" in out, "reusable workflow not pointed at")
    check("checkout" not in out, "uses: steps must not count as run steps")
    check("deploy.sh" not in out, "push-only workflow must be excluded")

    r = run(push)
    check(r.returncode == 1 and "no job runs on" in r.stderr, "push-only input must exit 1, never pass empty")
    r = run(push, events="push")
    check(r.returncode == 0 and "TOTAL 1 run steps" in r.stdout, "--events push should list the deploy step")
    r = run(bad)
    check(r.returncode == 2 and "cannot parse" in r.stderr, "malformed YAML must exit 2")
    r = run(Path(tmp) / "missing.yml")
    check(r.returncode == 2, "missing file must exit 2")

if FAILS:
    print("\n".join("FAIL " + f for f in FAILS))
    sys.exit(1)
print("ci-gate-list: all checks pass")
