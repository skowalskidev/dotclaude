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
COUNTER = [0]


def check(cond, msg):
    print(("ok    " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def hook(event, cmd, cwd, state, session, call, **extra):
    payload = {"hook_event_name": event, "tool_name": "Bash", "session_id": session, "cwd": str(cwd),
               "tool_use_id": call, "tool_input": {"command": cmd, **extra.pop("tin", {})}, **extra}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True,
                       env={**os.environ, "CLAUDE_CHECK_CACHE_DIR": str(state)})
    return "deny" if '"deny"' in r.stdout else "allow"


def run(cmd, cwd, state, session="s1", finish=True, interrupted=False, background=False):
    """One tool call: PreToolUse, then (when it finishes) PostToolUse. Returns the PreToolUse decision."""
    COUNTER[0] += 1
    call = f"toolu_{COUNTER[0]}"
    tin = {"run_in_background": True} if background else {}
    decision = hook("PreToolUse", cmd, cwd, state, session, call, tin=tin)
    if decision == "allow" and finish:
        hook("PostToolUse", cmd, cwd, state, session, call, tin=tin,
             tool_response={"stdout": "", "stderr": "", "interrupted": interrupted})
    return decision


with tempfile.TemporaryDirectory() as tmp:
    repo, state = Path(tmp) / "repo", Path(tmp) / "state"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    g("add", "a.py")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    t = "npx vitest run src/a.test.ts"

    check(run(t, repo, state) == "allow", "first run of a check passes")
    check(run(t, repo, state) == "deny", "the same check on identical inputs, after it finished, is refused")
    check(run(t, repo, state, session="s2") == "allow", "another session keeps its own cache")
    (repo / "a.py").write_text("x = 2\n")
    check(run(t, repo, state) == "allow", "an edited tracked file makes it a new run")
    (repo / "new.py").write_text("y = 1\n")
    check(run(t, repo, state) == "allow", "a new untracked file makes it a new run")
    (repo / "new.py").write_text("y = 2\n")  # same size, new content
    check(run(t, repo, state) == "allow", "a same-size edit to an untracked file makes it a new run")
    check(run(f"CLAUDE_RERUN_OK=1 {t}", repo, state) == "allow", "the flake override reruns")

    u = "npx vitest run src/b.test.ts"
    check(run(u, repo, state, interrupted=True) == "allow", "a check that gets interrupted ...")
    check(run(u, repo, state) == "allow", "... is not cached: its rerun passes")
    v = "npx vitest run src/c.test.ts"
    check(run(v, repo, state, finish=False) == "allow", "a check refused or killed before PostToolUse ...")
    check(run(v, repo, state) == "allow", "... is not cached either")
    w = "npx vitest run src/d.test.ts"
    run(w, repo, state, background=True)
    check(run(w, repo, state) == "allow", "a background run is never recorded as finished")

    check(run("npx playwright test e2e/login.spec.ts", repo, state) == "allow" and
          run("npx playwright test e2e/login.spec.ts", repo, state) == "allow",
          "a stateful check (browser, simulator, e2e) is never cached")
    check(run("cat src/a.test.ts", repo, state) == "allow" and run("cat src/a.test.ts", repo, state) == "allow",
          "reading a test file is not a check")
    check(run("grep -n vitest package.json", repo, state) == "allow" and
          run("grep -n vitest package.json", repo, state) == "allow", "grepping for a runner name is not a check")
    check(run("git status && ls", repo, state) == "allow", "a non-check command is never cached")

    sub = repo / "pkg"
    sub.mkdir()
    check(run("cd pkg && npx vitest run", repo, state) == "allow", "a check behind cd passes once")
    check(run("cd pkg && npx vitest run", repo, state) == "deny", "and is keyed to its cd target")

    out = "/private/tmp/claude-501/x/tasks/b123abc.output"
    check(run(f"until grep -q done {out}; do sleep 5; done", repo, state) == "deny", "an until-loop on task output is refused")
    check(run(f"for i in $(seq 1 50); do grep -q x {out} && break; sleep 10; done", repo, state) == "deny",
          "a sleep loop on task output is refused")
    check(run(f"tail -20 {out}", repo, state) == "allow", "one read of a task output file passes")
    check(run("sleep 2 && curl -s localhost:3000/health", repo, state) == "allow", "a sleep with no task output passes")
    check(run("npx vitest run", Path(tmp), state) == "allow", "outside a git repo it fails open")

print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
