#!/usr/bin/env python3
"""Both directions for hooks/check-cache-guard.py, in a temp repo and a temp state dir."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name("check-cache-guard.py")
FAILS = []


def check(cond, msg):
    print(("ok    " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def run(cmd, cwd, state, session="s1"):
    payload = {"tool_name": "Bash", "session_id": session, "cwd": str(cwd), "tool_input": {"command": cmd}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True,
                       env={**os.environ, "CLAUDE_CHECK_CACHE_DIR": str(state)})
    return "deny" if '"deny"' in r.stdout else "allow"


with tempfile.TemporaryDirectory() as tmp:
    repo, state = Path(tmp) / "repo", Path(tmp) / "state"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    g("add", "a.py")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")

    check(run("npx vitest run src/a.test.ts", repo, state) == "allow", "first run of a check passes")
    check(run("npx vitest run src/a.test.ts", repo, state) == "deny", "the same check on identical inputs is refused")
    check(run("npx vitest run src/a.test.ts", repo, state, session="s2") == "allow", "another session keeps its own cache")
    (repo / "a.py").write_text("x = 2\n")
    check(run("npx vitest run src/a.test.ts", repo, state) == "allow", "an edited tracked file makes it a new run")
    (repo / "new.py").write_text("y = 1\n")
    check(run("npx vitest run src/a.test.ts", repo, state) == "allow", "a new untracked file makes it a new run")
    check(run("CLAUDE_RERUN_OK=1 npx vitest run src/a.test.ts", repo, state) == "allow", "the flake override reruns")
    check(run("python3 hooks/config-contract.test.py --only x", repo, state) == "allow", "a different check passes")
    check(run("git status && ls", repo, state) == "allow", "a non-check command is never cached")
    check(run("git status && ls", repo, state) == "allow", "a repeated non-check command passes")
    out = "/private/tmp/claude-501/x/tasks/b123abc.output"
    check(run(f"until grep -q done {out}; do sleep 5; done", repo, state) == "deny", "an until-loop on task output is refused")
    check(run(f"for i in $(seq 1 50); do grep -q x {out} && break; sleep 10; done", repo, state) == "deny",
          "a sleep loop on task output is refused")
    check(run(f"tail -20 {out}", repo, state) == "allow", "one read of a task output file passes")
    check(run("sleep 2 && curl -s localhost:3000/health", repo, state) == "allow", "a sleep with no task output passes")
    check(run("npx vitest run", Path(tmp), state) == "allow", "outside a git repo it fails open")

print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
