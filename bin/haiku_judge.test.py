#!/usr/bin/env python3
"""Offline tests for bin/haiku_judge.py and every hook that asks it (no model call: a stub table or a fake
`claude` on PATH stands in for the model).

Covers: the reply parser, the off switch, stub verdicts, the cache, the verdict log, the CLI exit codes, the
model argv (subscription login through --safe-mode, never --bare), a timeout, and each caller's two halves:
a verdict decides, and no verdict keeps the caller's old behaviour (security guards stay closed, the
workflow gates keep their keyword result). Today's cases are pinned: the multi-line "go", the typo'd
learning request, `pgrep -fl` for names, "go ahead and merge" still not a learning go, a status question
ending a turn with no reconciliation block.

Run: python3 bin/haiku_judge.test.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
FAILS: list = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TMP = Path(tempfile.mkdtemp(prefix="haiku-judge-test-"))
STUB = TMP / "stub.json"


def stub(table: dict) -> None:
    STUB.write_text(json.dumps(table))


def judged_env(extra=None) -> dict:
    env = {**os.environ, "CLAUDE_HAIKU_JUDGE": "on", "CLAUDE_HAIKU_JUDGE_STUB": str(STUB),
           "CLAUDE_HAIKU_JUDGE_HOME": str(TMP / "home")}
    env.pop("AGENT_DELEGATED_WORKER", None)
    env.update(extra or {})
    return env


def fresh_module(extra_env: dict):
    """haiku_judge loaded with this environment (it reads its paths and timeout at import)."""
    saved = {k: os.environ.get(k) for k in extra_env}
    os.environ.update(extra_env)
    try:
        return load(ROOT / "bin" / "haiku_judge.py", f"haiku_judge_{time.monotonic_ns()}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------ the helper itself

def test_helper() -> None:
    home = TMP / "helper-home"
    hj = fresh_module({"CLAUDE_HAIKU_JUDGE_HOME": str(home)})
    P = hj.parse_reply
    check(P('{"ok": true, "reason": "fine"}') == {"ok": True, "reason": "fine"}, "plain JSON verdict not parsed")
    check(P('```json\n{"ok": false, "reason": "no"}\n```')["ok"] is False, "a fenced verdict was not parsed")
    check(P('{"ok": "yes"}') is None, "a non-boolean ok was accepted")
    check(P("I think so") is None and P(None) is None, "prose or None was read as a verdict")

    os.environ["CLAUDE_HAIKU_JUDGE"] = "off"
    v = hj.judge("learning-go", {"messages": ["go"]})
    check(v["ok"] is None and v["source"] == "off", "CLAUDE_HAIKU_JUDGE=off returned a verdict")
    os.environ["CLAUDE_HAIKU_JUDGE"] = "on"
    check(hj.judge("no-such-kind", {})["ok"] is None, "an unknown kind returned a verdict")

    os.environ["CLAUDE_HAIKU_JUDGE_STUB"] = str(STUB)
    stub({"learning-go": {"ok": True, "reason": "said go"}, "status-only:rename": {"ok": False, "reason": "work"},
          "status-only": {"ok": True, "reason": "status"}, "push-order": "timeout", "merge-order": "error"})
    check(hj.judge("learning-go", {"messages": ["go"]}) == {"ok": True, "reason": "said go", "source": "stub"},
          "a stub verdict was not returned as is")
    check(hj.judge("status-only", {"messages": ["rename the button"]})["ok"] is False,
          "a kind:<substring> stub entry did not take precedence")
    check(hj.judge("status-only", {"messages": ["status?"]})["ok"] is True, "the kind-wide stub entry was not used")
    check(hj.judge("push-order", {"messages": ["push"]})["source"] == "timeout", "a stubbed timeout gave a verdict")
    check(hj.judge("merge-order", {"pr": "1"})["ok"] is None, "a stubbed error gave a verdict")
    os.environ.pop("CLAUDE_HAIKU_JUDGE_STUB")

    # A fake `claude` on PATH: the argv is the subscription route and a verdict is cached.
    fake = TMP / "fakebin"
    fake.mkdir(exist_ok=True)
    argv_log = TMP / "argv.txt"
    (fake / "claude").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > " + str(argv_log) + "\ncat >/dev/null\n"
        "[ -n \"$FAKE_SLEEP\" ] && sleep \"$FAKE_SLEEP\"\n"
        "echo '{\"is_error\": false, \"result\": \"{\\\"ok\\\": true, \\\"reason\\\": \\\"fake\\\"}\"}'\n")
    (fake / "claude").chmod((fake / "claude").stat().st_mode | stat.S_IEXEC)
    path_was = os.environ["PATH"]
    os.environ["PATH"] = f"{fake}:{path_was}"
    try:
        v = hj.judge("secret-output", {"command": "pgrep -fl docker", "rule": "x"})
        check(v == {"ok": True, "reason": "fake", "source": "model"}, f"the fake model verdict was not read: {v}")
        args = argv_log.read_text().split("\n")
        check("--safe-mode" in args and "haiku" in args and "--bare" not in args and "-p" in args,
              f"the model call is not `claude -p --safe-mode --model haiku` without --bare: {args}")
        argv_log.unlink()
        v = hj.judge("secret-output", {"command": "pgrep -fl docker", "rule": "x"})
        check(v["source"] == "cache" and not argv_log.exists(), "a repeated input was not served from the cache")
        os.environ["FAKE_SLEEP"] = "3"
        v = hj.judge("secret-output", {"command": "other", "rule": "x"}, timeout=1)
        check(v["ok"] is None and v["source"] == "timeout", f"a slow model gave a verdict: {v}")
    finally:
        os.environ["PATH"] = path_was
        os.environ.pop("FAKE_SLEEP", None)

    rows = [json.loads(x) for x in (home / "logs" / "haiku-judge.jsonl").read_text().splitlines()]
    check(any(r["source"] == "cache" for r in rows) and any(r["source"] == "timeout" for r in rows)
          and all({"kind", "hash", "input", "ok", "reason", "source", "ms"} <= set(r) for r in rows),
          "the verdict log misses a row or a field")

    # CLI exit codes: 0 ok, 1 not ok, 3 no verdict.
    stub({"learning-go": {"ok": True, "reason": "go"}, "status-only": {"ok": False, "reason": "work"},
          "push-order": "error"})
    for kind, want in (("learning-go", 0), ("status-only", 1), ("push-order", 3)):
        p = subprocess.run([sys.executable, str(ROOT / "bin" / "haiku_judge.py"), "ask", kind], input="{}",
                           text=True, capture_output=True, env=judged_env())
        check(p.returncode == want, f"`haiku_judge.py ask {kind}` exited {p.returncode}, want {want}")


# ------------------------------------------------------------------ security guards: verdict clears, none denies

def guard(script: str, command: str, env: dict) -> str:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(TMP)})
    runner = ["/bin/bash"] if script.endswith(".sh") else [sys.executable]
    return subprocess.run([*runner, str(HOOKS / script)], input=payload, text=True, capture_output=True,
                          env=env).stdout.strip()


def test_secret_echo() -> None:
    stub({"secret-output:docker": {"ok": True, "reason": "Docker Desktop paths only"},
          "secret-output": {"ok": False, "reason": "node servers take tokens"}})
    check(guard("secret-echo-guard.py", "pgrep -fl docker", judged_env()) == "",
          "pgrep -fl for Docker names stayed denied after the Haiku step cleared it")
    out = guard("secret-echo-guard.py", "pgrep -fl node", judged_env())
    check('"deny"' in out and "Haiku check: node servers take tokens" in out,
          "a Haiku-confirmed process-argument hit was not denied with the Haiku reason")
    check('"deny"' in guard("secret-echo-guard.py", "gh auth token", judged_env()),
          "a definite printer (gh auth token) was sent to the Haiku step and cleared")
    for failure in ("timeout", "error"):
        stub({"secret-output": failure})
        check('"deny"' in guard("secret-echo-guard.py", "pgrep -fl docker", judged_env()),
              f"a Haiku {failure} let a process-argument hit through: the guard must fail closed")
    check('"deny"' in guard("secret-echo-guard.py", "pgrep -fl docker", {**judged_env(), "CLAUDE_HAIKU_JUDGE": "off"}),
          "with the judge off the keyword deny did not stand")


def test_process_kill() -> None:
    uuid = "9f3c2a1e-77b0-4c1e-a2d2-3b0c6c1f00aa"
    stub({f"pattern-kill:{uuid}": {"ok": True, "reason": "a UUID only this agent holds"},
          "pattern-kill": {"ok": False, "reason": "shared tool name"}})
    check(guard("process-kill-guard.py", f"pkill -f {uuid}", judged_env()) == "",
          "a pkill -f on this agent's own UUID stayed denied after the Haiku step cleared it")
    out = guard("process-kill-guard.py", "pkill -f vitest", judged_env())
    check('"deny"' in out and "Haiku check: shared tool name" in out, "pkill -f vitest was not denied with the reason")
    stub({"pattern-kill": {"ok": True, "reason": "stub says yes"}})
    check('"deny"' in guard("process-kill-guard.py", "killall node", judged_env()),
          "a definite name kill (killall) was sent to the Haiku step and cleared")
    stub({"pattern-kill": "timeout"})
    check('"deny"' in guard("process-kill-guard.py", f"pkill -f {uuid}", judged_env()),
          "a Haiku timeout let a pattern kill through: the guard must fail closed")


def test_work_resource() -> None:
    home = TMP / "wrg-home"
    home.mkdir(exist_ok=True)
    project = "testpersonalproj"
    ident = home / "identity.local.json"
    ident.write_text(json.dumps({"workOrgMatch": "TestWorkOrg", "workEmail": "work@test.example",
                                 "personalEmail": "personal@test.example", "workCloudProjects": ["testworkprod"],
                                 "personalCloudProject": project}))
    repo = TMP / "work-repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:TestWorkOrg/app.git"], cwd=repo, check=True)
    env = judged_env({"CLAUDE_PROJECT_DIR": str(repo), "CLAUDE_IDENTITY_FILE": str(ident), "HOME": str(home)})
    keyfile = "personal-keys" + ".env"
    stub({"resource-mention:rg -n ": {"ok": True, "reason": "a search pattern, nothing read"},
          "resource-mention": {"ok": False, "reason": "the file is sourced"}})
    check(guard("work-resource-guard.sh", f"rg -n {keyfile} references/", env) == "",
          "a search that only mentions the personal key file stayed denied after the Haiku step cleared it")
    check('"deny"' in guard("work-resource-guard.sh", f"source ~/.config/{keyfile} && node x.js", env),
          "sourcing the personal key file in a work repo was let through")
    stub({"resource-mention": "error"})
    check('"deny"' in guard("work-resource-guard.sh", f"rg -n {keyfile} references/", env),
          "a Haiku error let a boundary literal through: the guard must fail closed")
    stub({"resource-mention": {"ok": True, "reason": "stub says yes"}})
    out = guard("work-resource-guard.sh", "curl https://api.openai.com/v1/responses", env)
    check('"deny"' in out, "a fact rule (model-API shell call) was cleared by the Haiku step")


# ------------------------------------------------------------------ git-commit-guard: merge and push words

def test_merge_and_push_words() -> None:
    os.environ.update({"CLAUDE_HAIKU_JUDGE": "on", "CLAUDE_HAIKU_JUDGE_STUB": str(STUB),
                       "CLAUDE_HAIKU_JUDGE_HOME": str(TMP / "home")})
    g = load(HOOKS / "git-commit-guard.py", "git_commit_guard_judged")
    g.HOOK_STARTED = time.monotonic()
    # The keyword rule refuses this numbered reply; the Haiku step reads it as the order.
    window = [("yep, send it", {"1551"}, 1)]
    check(g.words_allow("1551", window)[0] is False, "fixture drift: the keyword rule already allows this reply")
    stub({"merge-order": {"ok": True, "reason": "send it answers the merge ask"}})
    check(g.judged_merge("1551", window) == (True, ""), "a Haiku merge order was not honoured")
    stub({"merge-order": {"ok": False, "reason": "a later hold"}})
    allowed, cause = g.judged_merge("1551", [("merge #1551", set(), 0)])
    check(allowed is False and "a later hold" in cause, "a Haiku refusal did not override the keyword allow")
    stub({"merge-order": "timeout"})
    check(g.judged_merge("1551", [("merge #1551", set(), 0)])[0] is True,
          "with no verdict the keyword merge rule did not stand")
    stub({"merge-order": {"ok": True, "reason": "stub says yes"}})
    check(g.judged_merge("1551", [("thanks, all good", set(), 0)])[0] is False,
          "a window with no merge mention was sent to the Haiku step (the prefilter must decide it)")

    # The hook's own merge path (merge_denial) reads the judged rule, not the bare keyword one.
    os.environ.pop("AGENT_DELEGATED_WORKER", None)

    class _Mon:
        origin_slug = staticmethod(lambda _w: "o/r")
        spec_for = staticmethod(lambda _s: (None, ""))

    class _Scan:
        repo_env = False

    g.monitoring_merge = lambda *a, **k: (False, "", False)
    g._monitoring_module = lambda: _Mon
    g.typed_messages = lambda _p: ([("yep, send it", {"1551"}, 1)], 1)
    payload = {"tool_input": {"command": "gh pr merge 1551"}, "transcript_path": str(TMP / "t.jsonl")}
    stub({"merge-order": {"ok": True, "reason": "send it answers the merge ask"}})
    check(g.merge_denial(payload, [g.Word("1551")], str(TMP), _Scan()) == "",
          "the hook's merge path ignored a Haiku merge order")
    stub({"merge-order": {"ok": False, "reason": "no order"}})
    check("Blocked" in g.merge_denial(payload, [g.Word("1551")], str(TMP), _Scan()),
          "the hook's merge path merged without an order")

    g.typed_messages = lambda _p: ([("push it to main", set(), 0)], 0)
    g._push_default = lambda _r, _a: "main"
    stub({"push-order": {"ok": False, "reason": "a question"}})
    check("Blocked" in g.push_denial("/tmp", [], {"transcript_path": "x"}, True),
          "a Haiku refusal of the push word did not block the default-branch push")
    stub({"push-order": "error"})
    check(g.push_denial("/tmp", [], {"transcript_path": "x"}, True) == "",
          "with no verdict the keyword push rule did not stand")
    os.environ["CLAUDE_HAIKU_JUDGE"] = "off"


# ------------------------------------------------------------------ intent-ledger: learning go and status-only stops

def test_intent_ledger() -> None:
    base = TMP / "ledger"
    home, repo = base / "home", base / "repo"
    home.mkdir(parents=True)
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / ".git" / "info" / "exclude").write_text(".context/\n")
    env = judged_env({"HOME": str(home), "CLAUDE_CONFIG_ROOT": str(ROOT), "CLAUDE_INTENT_LEDGER": "on",
                      "CLAUDE_PROJECT_DIR": str(repo), "CLAUDE_CODE_SESSION_ID": "judge-test",
                      "CLAUDE_HAIKU_JUDGE_HOME": str(home / ".claude")})
    hook = HOOKS / "intent-ledger.sh"
    transcript = base / "t.jsonl"
    transcript.write_text("")

    def invoke(mode, prompt=None, active=False):
        payload = {"cwd": str(repo), "session_id": "judge-test", "stop_hook_active": active,
                   "transcript_path": str(transcript), "background_tasks": [], "last_assistant_message": "Done."}
        if prompt is not None:
            payload["prompt"] = prompt
        r = subprocess.run(["bash", str(hook), mode], input=json.dumps(payload), text=True, capture_output=True,
                           cwd=repo, env=env)
        check(r.returncode == 0, "ledger hook failed: " + r.stderr)
        return r.stdout

    def note(kind, body, extra=None):
        scratch = base / f"{kind}.md"
        scratch.write_text(body)
        return subprocess.run(["bash", str(hook), "note", kind, str(scratch)], text=True, capture_output=True,
                              cwd=repo, env={**env, **(extra or {})})

    stub({"learning-go:self imrpove": {"ok": True, "reason": "asks to update config from learnings"},
          "learning-go:go\\n2 yes": {"ok": True, "reason": "go on its own line"},
          "learning-go:go ahead and merge": {"ok": False, "reason": "aimed at merging"},
          "status-only:whats the status": {"ok": True, "reason": "a status question"},
          "status-only": {"ok": False, "reason": "new work"}})
    invoke("submit", "Build the importer.")
    note("reconcile", "Built.")
    time.sleep(1.1)
    invoke("submit", "ensure at the end you upfate the config based on learnings ... self imrpove")
    check(note("learning", "session learning: done").returncode == 0,
          "the typo'd explicit learning request was refused as Simon's go")
    # A done note's go stands until a skip note (intent-ledger.sh learning_state), so each refusal
    # check below starts after a skip, where only the judge can open the next note.
    check(note("learning", "session learning: skipped").returncode == 0, "a skip under a standing go was refused")
    time.sleep(1.1)
    invoke("submit", "go ahead and merge #12")
    check(note("learning", "session learning: done").returncode != 0, "'go ahead and merge' counted as a learning go")
    time.sleep(1.1)
    invoke("submit", "go\n2 yes tour-prices-ahead are you sure\n3 yes\n4 yes")
    check(note("learning", "session learning: done").returncode == 0, "the multi-line go was refused")
    check(note("learning", "session learning: skipped").returncode == 0, "a skip under a standing go was refused")
    time.sleep(1.1)
    invoke("submit", "ensure you learn from this, self imrpove")
    stub({"learning-go": "timeout"})
    check(note("learning", "session learning: done").returncode != 0,
          "with no verdict a non-bare request counted as a go: the fallback must be the keyword rule")
    time.sleep(1.1)
    invoke("submit", "go")
    check(note("learning", "session learning: done").returncode == 0,
          "with no verdict a bare go was refused: the keyword fallback must still pass it")

    # Stop: a status question after a reconcile ends the turn; new work or no verdict still blocks.
    stub({"status-only:rename": {"ok": False, "reason": "new work"},
          "status-only:whats the status": {"ok": True, "reason": "a status question"},
          "status-only": {"ok": False, "reason": "new work"}})
    note("reconcile", "All reconciled.")
    time.sleep(1.1)
    invoke("submit", "whats the status of the PR?")
    check('"block"' not in invoke("stop"), "a pure status question re-fired the reconciliation block")
    time.sleep(1.1)
    invoke("submit", "also rename the export button to Save")
    check('"block"' in invoke("stop"), "a new work ask did not get the reconciliation block")
    note("reconcile", "Renamed.")
    time.sleep(1.1)
    stub({"status-only": "error"})
    invoke("submit", "whats the status now?")
    check('"block"' in invoke("stop"), "with no verdict the reconciliation block did not keep its old behaviour")


def main() -> int:
    os.environ["CLAUDE_HAIKU_JUDGE_HOME"] = str(TMP / "home")
    try:
        for t in (test_helper, test_secret_echo, test_process_kill, test_work_resource, test_merge_and_push_words,
                  test_intent_ledger):
            try:
                t()
            except Exception as exc:  # a crash is a failure with its name, not a silent pass
                FAILS.append(f"{t.__name__} raised {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    for f in FAILS:
        print("FAIL:", f)
    print(f"haiku_judge: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failures)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
