#!/usr/bin/env python3
"""Pins hooks/bare-reference-guard.py in both directions: a bare PR, issue or ticket id in the final
message blocks the stop once; linked ids, code, URLs, shas and look-alike standards pass; a
continuation never loops."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "bare-reference-guard.py"
FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        FAILURES.append(msg)
        print("FAIL:", msg)


def stop(home: Path, message, active=False, cwd=".", sid="t", env=None, transcript=None) -> str:
    payload = {"session_id": sid, "stop_hook_active": active, "cwd": str(cwd)}
    if message is not None:
        payload["last_assistant_message"] = message
    if transcript:
        payload["transcript_path"] = str(transcript)
    run_env = {k: v for k, v in os.environ.items() if k != "AGENT_DELEGATED_WORKER"}
    run_env.update({"HOME": str(home), **(env or {})})
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                         capture_output=True, env=run_env)
    check(out.returncode == 0, f"hook exited {out.returncode}: {out.stderr}")
    return out.stdout


def blocks(out: str) -> bool:
    return '"decision": "block"' in out


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bare-ref-test-") as tmp:
        base = Path(tmp)
        home = base / "home"
        home.mkdir()
        repo = base / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:o/r.git"], check=True)

        must_block = [
            "Merge list: #1297, #1497, #1482, #1420",
            "#1497 and #1445 are green.",
            "Fixed in POI-1911.",
            "Action needed: say merge for **#1497**",
            "See o/r#12 for the other half.",
            "Linked [#1497](https://github.com/o/r/pull/1497) but not #1445.",
        ]
        must_pass = [
            "Merge list: [#1297](https://github.com/o/r/pull/1297), [#1497](https://github.com/o/r/pull/1497)",
            "Run `gh pr view #1497` to see it.",
            "```\nMerge list: #1497\nPOI-1911\n```\nDone.",
            "Fixed in [POI-1911](https://linear.app/x/issue/POI-1911).",
            "Landed a9a8619 and 479368dcd3f on main.",
            "The PR is https://github.com/o/r/pull/1497 and <https://github.com/o/r/pull/1445>.",
            "Uses UTF-8, SHA-256, ISO-8601 and GPT-5 under UTC-8.",
            "Step #1 then #2.",
            "Color &#160; entity and a heading\n## Done",
            "",
        ]
        for i, text in enumerate(must_block):
            out = stop(home, text, sid=f"b{i}", cwd=repo)
            check(blocks(out), f"bare reference did not block: {text!r}")
        for i, text in enumerate(must_pass):
            check(stop(home, text, sid=f"p{i}", cwd=repo) == "", f"clean message blocked: {text!r}")

        # The reason links through the repo's origin and lists the ids.
        out = stop(home, "Merge list: #1497", sid="reason", cwd=repo)
        reason = json.loads(out)["reason"] if out else ""
        check("https://github.com/o/r/pull/123" in reason and "#1497" in reason,
              f"reason lacks the origin link or the id: {reason[:200]}")

        # Loop safety: blocks once, the continuation passes even if a bare id remains, a fresh stop re-arms.
        check(blocks(stop(home, "#1497", sid="loop")), "first stop did not block")
        check(stop(home, "still #1497", sid="loop", active=True) == "", "continuation re-blocked: loop")
        check(blocks(stop(home, "#1497", sid="loop")), "a fresh stop did not re-arm")
        # A continuation caused by another Stop hook (no marker) still gets its one block.
        check(blocks(stop(home, "#1497", sid="other", active=True)), "continuation from another hook skipped the check")

        # Delegated workers are skipped; transcript fallback is read when the payload has no message.
        check(stop(home, "#1497", sid="w", env={"AGENT_DELEGATED_WORKER": "1"}) == "", "delegated worker blocked")
        transcript = base / "t.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Merge #1497"}]}}) + "\n")
        check(blocks(stop(home, None, sid="tr", transcript=transcript)), "transcript fallback missed a bare id")

        # Malformed payload fails open; --check CLI both ways.
        bad = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True,
                             env={**os.environ, "HOME": str(home)})
        check(bad.returncode == 0 and bad.stdout == "", "malformed payload did not fail open")
        for text, code in (("#1497", 1), ("[#1497](https://github.com/o/r/pull/1497)", 0)):
            res = subprocess.run([sys.executable, str(HOOK), "--check", "-"], input=text, text=True,
                                 capture_output=True)
            check(res.returncode == code, f"--check exit {res.returncode} for {text!r}")

    print(f"{'ok' if not FAILURES else 'FAILED'}: bare-reference-guard ({len(FAILURES)} failures)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
