#!/usr/bin/env python3
"""
Both directions for hooks/git-commit-guard.py: a guard is assumed vacuous until it has been seen to
fail, and assumed harmful until it has been seen NOT to fire on text that merely names a command.

Drives the hook the way the harness does (a tool_use JSON payload on stdin) from two throwaway git
repos, one on a feature branch and one on main. Nothing real is touched.

The MUST-NOT-FIRE block is the important half. The guard once matched the raw command text, so a
printf writing a note that quoted a push to main, and `python3 -m py_compile git-commit-guard.py`,
were both blocked. The guard judges what the shell RUNS: the command word, with quoted strings and
heredoc bodies masked. Widen it back into a text match and these fail first.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "git-commit-guard.py"
PUSH = "git " + "push"            # assembled so this file's own source is never a test case
COMMIT = "git " + "commit"

# (label, "feature"|"main", command, substring the deny reason must contain)
MUST_FIRE = [
    ("push to main from a feature branch", "feature", f"{PUSH} origin main", "push to the default branch (main)"),
    ("push names master", "feature", f"{PUSH} origin master", "(master)"),
    ("git -C <path> push to main", "feature", f"git -C /tmp/x push origin main", "(main)"),
    ("push after cd &&", "feature", f"cd /tmp && {PUSH} origin HEAD:main", "(main)"),
    ("env prefix that is not the override", "feature", f"FOO=1 {PUSH} origin main", "(main)"),
    ("commit on main", "main", f"{COMMIT} -F msg.txt", "commit on the default branch (main)"),
    ("bare push on main", "main", f"{PUSH}", "push to the default branch (main)"),
    ("gh pr merge", "feature", "gh pr merge 12 --squash", "gh pr merge"),
    ("a self-set flag is not the user's word", "feature", "CLAUDE_ALLOW_PR_MERGE=1 gh pr merge 12", "OWN words this turn"),
    ("a push flag alone is not the user's word", "feature", f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main", "OWN words this turn"),
    ("commit -m", "feature", f'{COMMIT} -m "fix: thing"', "-m or a heredoc"),
    ("commit -am", "feature", f'{COMMIT} -am "fix"', "-m or a heredoc"),
    ("commit from a heredoc", "feature", f"{COMMIT} -F - <<'EOF'\nfix: thing\nEOF", "-m or a heredoc"),
]

MUST_NOT_FIRE = [
    ("a quoted note naming a push to main", "feature",
     f"printf -- '- next: Simon runs {PUSH} origin main; then verify\\n' > note.md"),
    ("a double-quoted echo naming commit -m", "feature", f'echo "use {COMMIT} -m never" > x'),
    ("a heredoc body naming a push to main", "feature",
     f"cat > note.md <<'EOF'\n{PUSH} origin main\n{COMMIT} -m x\nEOF"),
    ("python -m on a file named after the guard", "feature",
     "python3 -m py_compile ~/.claude/hooks/git-commit-guard.py"),
    ("grep for the merge command", "feature", 'grep -rn "gh pr merge" docs'),
    ("git log mentioning push and main", "feature", "git log --grep push main"),
    ("push to the feature branch", "feature", f"{PUSH} -u origin feature"),
    ("commit -F on a feature branch", "feature", f"{COMMIT} -F msg.txt"),
    ("amend no-edit", "feature", f"{COMMIT} --amend --no-edit"),
    ("malformed unterminated quote fails open", "feature", f"echo 'oops {PUSH} origin main"),
]


# The user's OWN words authorize a merge or a default-branch push; nothing the model sets does.
# (label, the user's newest message, command, denied?) Each ask is recorded the way
# hooks/intent-ledger.sh `submit` writes it. With no transcript the guard reads the newest ask alone.
OWN_WORDS = [
    ("says merge and names the PR", "merge #12", "gh pr merge 12 --squash", False),
    ("bare number with a URL form", "ok merge 12 now", "gh pr merge https://github.com/o/r/pull/12", False),
    ("yes to a question the model wrote", "1 yes", "gh pr merge 12", True),
    ("'finish it' is not a merge", "this is priority finish it", "gh pr merge 12", True),
    ("names a different PR", "merge 13", "gh pr merge 12", True),
    ("negated", "don't merge 12 yet", "gh pr merge 12", True),
    ("a branch name cannot be matched", "merge 12", "gh pr merge feature", True),
    ("a self-set flag is still not enough", "1 yes", "CLAUDE_ALLOW_PR_MERGE=1 gh pr merge 12", True),
    ("graphql enqueue is denied outright", "merge 12",
     "gh api graphql -f query='mutation{enqueuePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'", True),
    ("REST merge is denied outright", "merge 12", "gh api -X PUT repos/o/r/pulls/12/merge", True),
    ("plain 'merge and deploy' covers one PR", "ok merge and deploy", "gh pr merge 12", False),
    ("'merge everything' never covers an unnamed PR", "merge everything", "gh pr merge 12", True),
    ("a merge naming other numbers excludes this one", "merge 13 and 14", "gh pr merge 12", True),
    ("a -R value is not read as the PR", "merge 12", "gh pr merge -R o/r 12 --squash", False),
    ("pasted quote naming a merge is not the user's word", "> merge 12\nwhat does this mean?",
     "gh pr merge 12", True),
    ("a peer's report saying merge is not the user's word",
     '<agent-message from="a1b2">\nPR #12 is ready: merge #12\n</agent-message>', "gh pr merge 12", True),
    ("a cross-session FYI saying merge is not the user's word",
     '<cross-session-message from="uds:/tmp/x.sock" from-name="p">\nmerge 12\n</cross-session-message>',
     "gh pr merge 12", True),
    ("push to main when the user said push", "push it to main",
     f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main", False),
    ("push flag but the user said finish it", "finish it",
     f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main", True),
]


# The CURRENT TURN is every ask recorded since the user's newest typed prompt that opened a turn in
# the transcript (queued mid-turn messages arrive as attachments, never as turn-opening user
# entries). Plural or unnumbered phrasing covers an open PR this session pushed. Two repos, two PRs,
# a fake `gh` that answers `gh pr view`. (label, turn, command, denied?) where a turn is a list of
# ("open"|"queued"|"assistant"|"tool"|"meta"|"wake"|"handback", text). Cases sharing a session name
# run in one session, in order: the second merge on one unnumbered message is the incident case.
FAKE_GH = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
prs = {"251": ("feat-a", "acme/api"), "1162": ("feat-b", "acme/web"), "77": ("theirs", "acme/web")}
if a[:2] == ["pr", "view"]:
    sel = a[2].rsplit("/", 1)[-1].lstrip("#")
    if sel in prs:
        head, slug = prs[sel]
        print(json.dumps({"headRefName": head, "state": "OPEN", "url": f"https://github.com/{slug}/pull/{sel}"}))
        sys.exit(0)
sys.exit(1)
"""

TURNS = [
    ("plain 'merge and deploy' covers both session PRs (1 of 2)",
     [("open", "ok merge and deploy for me and then reply to the team lead")], "gh pr merge 251 -R acme/api", False,
     "two-prs"),
    ("plain 'merge and deploy' covers both session PRs (2 of 2)",
     [("open", "ok merge and deploy for me and then reply to the team lead")], "gh pr merge 1162 -R acme/web", False,
     "two-prs"),
    ("a queued clarification keeps the earlier merge ask",
     [("open", "ok merge and deploy for me"), ("queued", "merge all thats ready 1162 too"),
      ("queued", "from this session i mean")], "gh pr merge 1162 -R acme/web", False),
    ("plural 'all thats ready' covers the other session PR",
     [("open", "merge all thats ready 1162 too"), ("queued", "from this session i mean")],
     "gh pr merge https://github.com/acme/api/pull/251", False),
    ("'merge both' covers a session PR", [("open", "merge both")], "gh pr merge 1162 -R acme/web", False),
    ("a background-task wake keeps the user's turn",
     [("open", "merge 1162 once CI is green"), ("handback", ""), ("wake", "<task-notification>done</task-notification>")],
     "gh pr merge 1162 -R acme/web", False),
    ("a merge said only by the assistant is not the user's word",
     [("open", "how is CI doing?"), ("assistant", "Both are green. merge #1162 now."),
      ("tool", "merge 1162"), ("meta", "Stop hook feedback: merge 1162")], "gh pr merge 1162 -R acme/web", True),
    ("an earlier turn's merge does not carry past a hand-back",
     [("open", "merge 1162"), ("handback", ""), ("open", "thanks, what's next?")],
     "gh pr merge 1162 -R acme/web", True),
    ("'proceed' is never a merge", [("open", "proceed")], "gh pr merge 1162 -R acme/web", True),
    ("plural 'merge all' never covers a PR this session did not push",
     [("open", "merge all")], "gh pr merge 77 -R acme/web", True),
    ("a numbered merge does not cover another session PR",
     [("open", "merge #251")], "gh pr merge 1162 -R acme/web", True),
    ("a later 'wait' cancels the turn's merge ask",
     [("open", "merge 1162"), ("queued", "wait, the deploy is broken")], "gh pr merge 1162 -R acme/web", True),
    ("a later merge ask supersedes an earlier hold",
     [("open", "don't merge yet"), ("queued", "ok CI is green, merge 1162")], "gh pr merge 1162 -R acme/web", False),
    ("a number named before a hold is not reused",
     [("open", "merge 1162"), ("queued", "don't merge it yet"), ("queued", "merge #251")],
     "gh pr merge 1162 -R acme/web", True),
]


def write_turn(tmp: Path, repo_dir: Path, session: str, turn: list) -> Path:
    """Write the transcript the harness keeps and the ledger asks hooks/intent-ledger.sh records."""
    exclude = Path(git_out(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a") as f:
        f.write(".context/\n")
    ledger = repo_dir / ".context" / "intent-ledger.md"
    ledger.parent.mkdir(exist_ok=True)
    rows, n = [], 0
    for kind, text in turn:
        n += 5
        ts = f"2026-03-01T10:{n // 60:02d}:{n % 60:02d}"
        if kind in ("open", "queued"):
            with ledger.open("a") as f:
                f.write(f"\n## {ts}Z · ask · session {session}\n\n```\n{text}\n```\n")
        if kind == "open":
            rows.append({"type": "user", "timestamp": f"{ts}.400Z", "message": {"role": "user", "content": text}})
        elif kind == "queued":
            rows.append({"type": "attachment", "timestamp": f"{ts}.100Z",
                         "attachment": {"type": "queued_command", "prompt": text, "commandMode": "prompt"}})
        elif kind == "wake":
            rows.append({"type": "user", "timestamp": f"{ts}.400Z", "origin": {"kind": "task-notification"},
                         "message": {"role": "user", "content": text}})
        elif kind == "meta":
            rows.append({"type": "user", "isMeta": True, "timestamp": f"{ts}.400Z",
                         "message": {"role": "user", "content": [{"type": "text", "text": text}]}})
        elif kind == "tool":
            rows.append({"type": "user", "timestamp": f"{ts}.400Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": text}]}})
        else:  # assistant text, or a hand-back (an end_turn reply)
            rows.append({"type": "assistant", "timestamp": f"{ts}.400Z", "message": {
                "role": "assistant", "stop_reason": "end_turn" if kind == "handback" else "tool_use",
                "content": [{"type": "text", "text": text or "Done."}]}})
    transcript = tmp / f"{session}.jsonl"
    transcript.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return transcript


def turn_scope(tmp: Path, own_home: Path, failures: list) -> int:
    bin_dir = tmp / "fake-bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    api, web = repo(tmp, "api", "feat-a"), repo(tmp, "web", "feat-b")
    git_out(api, "remote", "add", "origin", "https://github.com/acme/api.git")
    git_out(web, "remote", "add", "origin", "git@github.com:acme/web.git")
    state = own_home / ".claude" / ".intent-ledger"
    state.mkdir(parents=True, exist_ok=True)
    passes = 0
    for i, (label, turn, cmd, denied, *shared) in enumerate(TURNS):
        session = shared[0] if shared else f"turn{i}"
        (state / f"{session}.pushes").write_text(f"{api}\tfeat-a\t{'a' * 40}\n{web}\tfeat-b\t{'b' * 40}\n")
        where = repo(tmp, f"t{i}", "feature")
        transcript = write_turn(tmp, where, session, turn)
        reason = run(where, cmd, own_home, session, transcript, bin_dir)
        if bool(reason) == denied:
            passes += 1
        else:
            failures.append(f"TURN SCOPE: {label}: got {reason[:160]!r}")
    return passes


def own_words_home(root: Path) -> Path:
    home = root / "own-home"
    (home / ".claude" / "hooks").mkdir(parents=True)
    (home / ".claude" / "hooks" / "intent-ledger.sh").symlink_to(GUARD.parent / "intent-ledger.sh")
    return home


def record_ask(repo_dir: Path, session: str, ask: str) -> None:
    exclude = Path(git_out(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    if ".context/" not in (exclude.read_text() if exclude.exists() else ""):
        with exclude.open("a") as f:
            f.write(".context/\n")
    ledger = repo_dir / ".context" / "intent-ledger.md"
    ledger.parent.mkdir(exist_ok=True)
    with ledger.open("a") as f:
        f.write(f"\n## 2026-01-01T00:00:00Z · ask · session other\n\n```\nmerge 12 push\n```\n")
        f.write(f"\n## 2026-01-01T00:00:01Z · ask · session {session}\n\n```\n{ask}\n```\n")


def repo(root: Path, name: str, branch: str) -> Path:
    d = root / name
    d.mkdir()
    for args in (["init", "-q", "-b", branch], ["-c", "user.email=t@t", "-c", "user.name=t",
                                                  "commit", "-q", "--allow-empty", "--allow-empty-message", "-F", "/dev/null"]):
        subprocess.run(["git", *args], cwd=d, check=True, capture_output=True)
    return d


def clean_env() -> dict:
    return {k: v for k, v in __import__("os").environ.items()
            if k not in ("CLAUDE_ALLOW_MAIN_COMMIT", "CLAUDE_ALLOW_PR_MERGE", "CLAUDE_ALLOW_COMMIT_M")}


def git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def run_cases(group: str, cases: list, home: Path, failures: list) -> None:
    for label, cwd, command, denied in cases:
        reason = run(cwd, command, home)
        if bool(reason) != denied:
            failures.append(f"{group}: {label}: got {reason[:160]!r}")


def run(cwd: Path, command: str, home=None, session="", transcript=None, bin_dir=None) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    if session:
        payload["session_id"] = session
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    env = clean_env()
    if home is not None:
        env["HOME"] = str(home)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                       capture_output=True, cwd=cwd, env=env)
    if not p.stdout.strip():
        return ""
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def main() -> int:
    failures, passes = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        dirs = {"feature": repo(Path(tmp), "f", "feature"), "main": repo(Path(tmp), "m", "main")}
        for label, where, cmd, expect in MUST_FIRE:
            reason = run(dirs[where], cmd)
            if reason and expect in reason:
                passes += 1
            else:
                failures.append(f"MUST FIRE: {label}: got {reason!r}")
        for label, where, cmd in MUST_NOT_FIRE:
            reason = run(dirs[where], cmd)
            if not reason:
                passes += 1
            else:
                failures.append(f"MUST NOT FIRE: {label}: {reason[:90]!r}")
        own_home = own_words_home(Path(tmp))
        for i, (label, ask, cmd, denied) in enumerate(OWN_WORDS):
            where = dirs["main"] if PUSH in cmd else dirs["feature"]
            session = f"s{i}"
            record_ask(where, session, ask)
            reason = run(where, cmd, own_home, session)
            if bool(reason) == denied:
                passes += 1
            else:
                failures.append(f"OWN WORDS: {label}: got {reason[:160]!r}")
        # One unnamed merge per message: the same message cannot merge a second, different PR.
        record_ask(dirs["feature"], "one-per-ask", "merge and deploy")
        first = run(dirs["feature"], "gh pr merge 21", own_home, "one-per-ask")
        again = run(dirs["feature"], "gh pr merge 21", own_home, "one-per-ask")
        second = run(dirs["feature"], "gh pr merge 22", own_home, "one-per-ask")
        if not first and not again and second:
            passes += 1
        else:
            failures.append(f"OWN WORDS: one unnamed merge per message: {first!r} {again!r} {second!r}")
        reason = run(dirs["feature"], "gh pr merge 12", own_home, "never-recorded")
        if reason:
            passes += 1
        else:
            failures.append("OWN WORDS: a session with no recorded ask must be denied")
        passes += turn_scope(Path(tmp), own_home, failures)
        home = Path(tmp) / "home"
        home.mkdir()
        config = repo(home, ".claude", "main")
        origin = Path(tmp) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
        for args in (["remote", "add", "origin", str(origin)], ["push", "-q", "origin", "main"],
                     ["fetch", "-q", "origin"]):
            subprocess.run(["git", "-C", str(config), *args], check=True, capture_output=True)
        worktree = Path(tmp) / "config-worktree"
        subprocess.run(["git", "-C", str(config), "worktree", "add", "-q",
                        "-b", "config-update/repair", str(worktree)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(worktree), "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-F", "/dev/null", "--allow-empty-message"],
                       check=True, capture_output=True)
        head = git_out(worktree, "rev-parse", "HEAD")
        marker = Path(git_out(config, "rev-parse", "--path-format=absolute", "--git-common-dir")) \
            / "claude-config-land.json"

        def verify(*shas):
            # What bin/config-land-check.py writes after the suite, scan and reviewed diff pass.
            marker.write_text(json.dumps({"verified": [{"sha": sha} for sha in shas]}))

        # The pre-change behaviour, kept: commits in the config repo pass; foreign repos are guarded.
        verify()
        cases = [
            ("config commit on main", config, f"{COMMIT} -F msg.txt", False),
            ("config worktree commit", worktree, f"{COMMIT} -F msg.txt", False),
            ("UNVERIFIED config worktree head to main", worktree, f"{PUSH} origin HEAD:main", True),
            ("UNVERIFIED canonical config push", config, f"{PUSH} origin main", True),
            ("config feature-branch push", worktree, f"{PUSH} -u origin config-update/repair", False),
            ("unrelated main push", dirs["main"], f"{PUSH} origin main", True),
            ("unrelated feature push to main", dirs["feature"], f"{PUSH} origin HEAD:main", True),
            ("config command targeting other repo", worktree, f"git -C {dirs['main']} push origin main", True),
            ("foreign bare push uses target branch", worktree, f"git -C {dirs['main']} push", True),
            ("foreign commit uses target branch", worktree, f"git -C {dirs['main']} commit -F msg.txt", True),
            ("config inline message still denied", worktree, f"{COMMIT} -m fix", True),
            ("config PR merge still denied", worktree, "gh pr merge 12", True),
        ]
        run_cases("CONFIG SCOPE", cases, home, failures)
        passes += sum(1 for _ in cases)

        # The sync flow's landing: the land check recorded this exact head.
        verify(head)
        fm = Path(git_out(dirs["main"], "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (fm / "claude-config-land.json").write_text(json.dumps({"verified": [
            {"sha": git_out(dirs["main"], "rev-parse", "HEAD")}]}))  # a forged record elsewhere
        cases = [
            ("verified worktree head to main", worktree, f"{PUSH} origin HEAD:main", False),
            ("verified head, explicit -C target", dirs["feature"], f"git -C {worktree} push origin HEAD:main", False),
            ("verified head, strict-mode compound", dirs["feature"],
             f"set -euo pipefail; git -C {worktree} push origin HEAD:main", False),
            ("verified head after cd &&", dirs["feature"], f"cd {worktree} && {PUSH} origin HEAD:main", False),
            ("verified head with -u and a redirect", worktree, f"{PUSH} -u origin HEAD:main 2>&1", False),
            ("verified head named by branch", config,
             f"{PUSH} origin config-update/repair:main", False),
            ("verified head but FORCED", worktree, f"{PUSH} origin +HEAD:main", True),
            ("verified head but --force", worktree, f"{PUSH} --force origin HEAD:main", True),
            ("verified head but a variable path", dirs["feature"], f"git -C $WT push origin HEAD:main", True),
            ("verified head piped (masks a rejection)", worktree, f"{PUSH} origin HEAD:main | tail -1", True),
            ("cd without && guard", dirs["main"], f"cd {worktree}; {PUSH} origin HEAD:main", True),
            ("verified config push mixed with a foreign main push", worktree,
             f"{PUSH} origin HEAD:main && git -C {dirs['main']} push origin main", True),
            ("foreign repo with a forged land record", dirs["main"], f"{PUSH} origin main", True),
            ("foreign repo, strict-mode compound", dirs["feature"],
             f"set -euo pipefail; git -C {dirs['main']} push origin main", True),
            ("config task-branch deletion still passes", worktree, f"{PUSH} origin --delete config-update/repair", False),
            ("config deletion of main", worktree, f"{PUSH} origin --delete main", True),
            ("config --all push", worktree, f"{PUSH} --all origin", True),
            ("config force to a task branch keeps the old exemption", worktree,
             f"{PUSH} --force origin config-update/repair", False),
            ("a push flag without the user saying push", dirs["main"], f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main", True),
        ]
        run_cases("CONFIG LANDING", cases, home, failures)
        passes += len(cases)

        # Remote main moved past the verified head: not a fast-forward, so it stops.
        subprocess.run(["git", "-C", str(config), "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "--allow-empty-message", "-F", "/dev/null"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(config), "push", "-q", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(config), "fetch", "-q", "origin"], check=True, capture_output=True)
        cases = [("verified head that no longer fast-forwards", worktree, f"{PUSH} origin HEAD:main", True)]
        run_cases("CONFIG LANDING", cases, home, failures)
        passes += len(cases)

        # The land check itself refuses a foreign repo, a dirty tree and an unread diff.
        land = GUARD.parent.parent / "bin" / "config-land-check.py"
        env = {**clean_env(), "HOME": str(home)}

        def land_run(root, *extra):
            return subprocess.run([sys.executable, str(land), "--root", str(root), *extra],
                                  capture_output=True, text=True, env=env)

        merged = subprocess.run(["git", "-C", str(worktree), "merge", "-q", "origin/main"],
                                capture_output=True)
        (worktree / "x.txt").write_text("change\n")
        for args in (["add", "x.txt"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-F", "/dev/null",
                                       "--allow-empty-message"]):
            subprocess.run(["git", "-C", str(worktree), *args], check=True, capture_output=True)
        checks = [
            ("land check rejects a foreign repo", land_run(dirs["main"], "--diff"), "not a checkout"),
            ("land check rejects an unread diff", land_run(worktree, "--reviewed", "0" * 64), "does not match"),
        ]
        shown = land_run(worktree, "--diff")
        checks.append(("land check prints the diff hash", shown, ""))
        (worktree / "x.txt").write_text("dirty\n")
        checks.append(("land check rejects a dirty tree", land_run(worktree, "--reviewed", "0" * 64), "uncommitted"))
        for label, result, expect in checks:
            ok = (result.returncode == 0 and "diff-sha256:" in result.stdout) if not expect else \
                 (result.returncode != 0 and expect in result.stderr)
            if ok and merged.returncode == 0:
                passes += 1
            else:
                failures.append(f"LAND CHECK: {label}: rc={result.returncode} {result.stderr[-160:]!r}")
    for f in failures:
        print(f)
    passes -= len([f for f in failures if f.startswith("CONFIG ")])
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
