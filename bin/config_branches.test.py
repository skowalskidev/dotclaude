#!/usr/bin/env python3
"""Offline tests for bin/config_branches.py and hooks/config-branch-gate.py.

Each case builds a throwaway config repo with a bare origin. Covers: a worktree-add command claims its
branch for the session; the Stop gate blocks the owner while the branch is unlanded and lets it end once a
blocker with a next action, a supersede record, or a landing exists (and never blocks another session or a
delegated worker); the block is bounded; an idle branch with a stale owner is adoptable, a fresh heartbeat
or a supersede record is not; adopting transfers ownership.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config_branches as cb  # noqa: E402

HOOK = HERE.parent / "hooks" / "config-branch-gate.py"
FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def git(cwd, *args, env=None):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def make_repo(tmp):
    origin, config = Path(tmp) / "origin.git", Path(tmp) / "config"
    config.mkdir()
    git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
    git(config, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(config, "config", k, v)
    (config / "a.txt").write_text("seed\n")
    git(config, "add", "-A")
    git(config, "commit", "-q", "-m", "chore: seed")
    git(config, "remote", "add", "origin", str(origin))
    git(config, "push", "-q", "origin", "main")
    git(config, "fetch", "-q", "origin")
    return config


def draft(config, slug, days_ago=0):
    git(config, "branch", f"config-update/{slug}", "origin/main")
    wt = config.parent / slug
    git(config, "worktree", "add", "-q", str(wt), f"config-update/{slug}")
    (wt / f"{slug}.txt").write_text(slug)
    git(wt, "add", "-A")
    when = f"{int(time.time() - days_ago * 86400)} +0000"
    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", f"fix({slug}): draft"], env=env, check=True)
    return wt


ARCHIVE = "Done.\n\nYou can archive this session: everything here is done."


def hook(config, event, session, state, **extra):
    if event == "Stop":
        extra.setdefault("last_assistant_message", ARCHIVE)
    payload = dict(hook_event_name=event, session_id=session, **extra)
    env = dict(os.environ, CLAUDE_CONFIG_ROOT=str(config), CLAUDE_CONFIG_STATE=str(state))
    env.pop("AGENT_DELEGATED_WORKER", None)
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                       capture_output=True, env=env)
    return r.stdout.strip()


def test_claim_from_worktree_add_and_stop_gate():
    with tempfile.TemporaryDirectory() as tmp:
        config, state = make_repo(tmp), Path(tmp) / "state"
        draft(config, "alpha")
        cmd = "git -C ~/.claude worktree add ~/x/wt -b config-update/alpha origin/main"
        hook(config, "PostToolUse", "s1", state, tool_name="Bash", tool_input={"command": cmd})
        check(cb.load(config, "config-update/alpha").get("session") == "s1", "claim: worktree add did not claim the branch")
        check(hook(config, "Stop", "s1", state, last_assistant_message="Built the importer.") == "",
              "gate: a normal task turn was blocked for config landing (it waits for the session's end)")
        out = hook(config, "Stop", "s1", state)
        check('"decision": "block"' in out and "config-update/alpha" in out, f"gate: owner was not blocked: {out!r}")
        check(hook(config, "Stop", "s2", state) == "", "gate: another session was blocked")
        try:
            cb.block(config, "config-update/alpha", "s1", "later")
            check(False, "block: a blocker with no next action was accepted")
        except ValueError:
            pass
        cb.block(config, "config-update/alpha", "s1", "suite queued behind load; rerun when idle")
        check(hook(config, "Stop", "s1", state) == "", "gate: a recorded blocker did not release the owner")
        cb.claim(config, "config-update/alpha", "s1")
        cb.supersede(config, "config-update/alpha", "landed abc1234 replaces this draft")
        check(hook(config, "Stop", "s1", state) == "", "gate: a supersede record did not release the owner")


def test_gate_is_bounded_and_releases_on_landing():
    with tempfile.TemporaryDirectory() as tmp:
        config, state = make_repo(tmp), Path(tmp) / "state"
        draft(config, "beta")
        cb.claim(config, "config-update/beta", "s1")
        blocks = [bool(hook(config, "Stop", "s1", state)) for _ in range(5)]
        check(blocks == [True, True, True, False, False], f"bounded: expected 3 blocks then release, got {blocks}")
        git(config, "push", "-q", "origin", "config-update/beta:main")
        git(config, "fetch", "-q", "origin")
        check(hook(config, "Stop", "s1", state) == "", "landed: a landed branch still blocked its owner")


def test_delegated_worker_is_never_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        config, state = make_repo(tmp), Path(tmp) / "state"
        draft(config, "gamma")
        cb.claim(config, "config-update/gamma", "s1")
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "s1", "last_assistant_message": ARCHIVE})
        env = dict(os.environ, CLAUDE_CONFIG_ROOT=str(config), CLAUDE_CONFIG_STATE=str(state), AGENT_DELEGATED_WORKER="1")
        r = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, env=env)
        check(r.stdout.strip() == "", f"worker: a delegated worker was blocked: {r.stdout!r}")


def test_adoptable_after_idle_window_and_adopt_transfers():
    with tempfile.TemporaryDirectory() as tmp:
        config = make_repo(tmp)
        draft(config, "old", days_ago=2)
        draft(config, "fresh", days_ago=0)
        draft(config, "gone", days_ago=3)
        cb.claim(config, "config-update/old", "dead", now=time.time() - 2 * 86400)
        cb.supersede(config, "config-update/gone", "landed abc1234 replaces this draft")
        names = [r[0] for r in cb.adoptable(config)]
        check(names == ["config-update/old"], f"adoptable: expected only the idle owned branch, got {names}")
        cb.heartbeat(config, "dead")
        check([r[0] for r in cb.adoptable(config)] == [], "adoptable: a fresh heartbeat did not keep the claim")
        cb.claim(config, "config-update/old", "heir", how="adopted")
        check(cb.load(config, "config-update/old")["session"] == "heir", "adopt: ownership did not transfer")
        cli = subprocess.run([sys.executable, str(HERE / "config_branches.py"), "--root", str(config),
                              "adoptable", "--hours", "0"], capture_output=True, text=True)
        check("config-update/fresh" in cli.stdout and "config-update/gone" not in cli.stdout,
              f"cli: adoptable list wrong: {cli.stdout!r}")


def main():
    tests = [test_claim_from_worktree_add_and_stop_gate, test_gate_is_bounded_and_releases_on_landing,
             test_delegated_worker_is_never_blocked, test_adoptable_after_idle_window_and_adopt_transfers]
    for t in tests:
        try:
            t()
        except Exception as e:
            FAILS.append(f"{t.__name__} crashed: {e!r}")
    if FAILS:
        print("\n".join(f"FAIL: {f}" for f in FAILS))
        return 1
    print(f"config-branches: {len(tests)} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
