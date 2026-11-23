#!/usr/bin/env python3
"""Pins hooks/test-browser-label-guard.py in both directions: an unlabelled navigate_page is denied,
a labelled one (any navigation type) and about:blank are allowed and record the owner's heartbeat,
other tools and malformed payloads pass."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "test-browser-label-guard.py"
ENGINE = Path(__file__).resolve().parent.parent / "bin" / "test-browser-tabs.py"
FAILURES: list[str] = []
WALKS = tempfile.mkdtemp()
ENV = dict(os.environ, CLAUDE_TEST_BROWSER_WALKS_DIR=WALKS)


def keeper(owner: str) -> str:
    return subprocess.run([sys.executable, str(ENGINE), "label", "--task", "PR 1272", "--owner", owner],
                          capture_output=True, text=True, timeout=20, env=ENV).stdout


def decide(tool: str, tool_input, raw: str = "") -> str:
    payload = raw or json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input})
    result = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True, capture_output=True,
                            timeout=20, env=ENV)
    if result.returncode != 0:
        return f"rc={result.returncode}"
    if not result.stdout.strip():
        return "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def expect(label: str, got: str, want: str) -> None:
    if got != want:
        FAILURES.append(f"{label}: expected {want}, got {got}")


def main() -> int:
    nav = "mcp__chrome-devtools__navigate_page"
    url = "http://127.0.0.1:3010/app"
    expect("unlabelled url", decide(nav, {"pageId": 1, "url": url}), "deny")
    expect("unlabelled reload", decide(nav, {"pageId": 1, "type": "reload"}), "deny")
    expect("foreign init script", decide(nav, {"pageId": 1, "url": url, "initScript": "document.title='x'"}), "deny")
    script = keeper("tokyo")
    heartbeat = Path(WALKS) / "tokyo"
    heartbeat.unlink(missing_ok=True)
    expect("labelled url", decide(nav, {"pageId": 1, "url": url, "initScript": script}), "allow")
    if not heartbeat.is_file():
        FAILURES.append("a labelled navigation must record its owner's heartbeat")
    for kind in ("reload", "back", "forward"):
        expect(f"labelled {kind}", decide(nav, {"pageId": 1, "type": kind, "initScript": script}), "allow")
    expect("about:blank", decide(nav, {"pageId": 1, "url": "about:blank"}), "allow")
    expect("other tool", decide("mcp__chrome-devtools__new_page", {"url": url}), "allow")
    expect("malformed json", decide(nav, None, raw="{not json"), "allow")
    expect("non-dict input", decide(nav, "oops"), "allow")
    for msg in FAILURES:
        print("FAIL", msg)
    print("test-browser-label-guard: " + ("OK" if not FAILURES else f"{len(FAILURES)} failure(s)"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
