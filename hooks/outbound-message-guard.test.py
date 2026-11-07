#!/usr/bin/env python3
"""Pins hooks/outbound-message-guard.py in both directions: over-cap sends denied, short sends,
non-send tools, the one-shot override and the --check CLI allowed or reported as documented."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "outbound-message-guard.py"
FAILURES: list[str] = []

SHORT = "Hey there,\nThe cache migration (PR #812) is ready for your review.\nNeeds your yes before Monday.\nThanks,\nSimon"
LONG = "\n".join(f"- point {i}: one more fact the reader did not ask for" for i in range(1, 8))
WORDY = " ".join(["word"] * 130)
HTML_LONG = "".join(f"<p>paragraph {i} of a long email</p>" for i in range(1, 8))


def decide(tool: str, tool_input: dict, cwd: str = "/tmp") -> str:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                          "tool_input": tool_input, "cwd": cwd})
    result = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                            capture_output=True, timeout=20)
    if result.returncode != 0:
        return f"rc={result.returncode}"
    if not result.stdout.strip():
        return "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def expect(label: str, got: str, want: str) -> None:
    if got != want:
        FAILURES.append(f"{label}: expected {want}, got {got}")


def main() -> int:
    slack = "mcp__claude_ai_Slack__slack_send_message"
    expect("long slack send", decide(slack, {"channel_id": "C1", "message": LONG}), "deny")
    expect("wordy slack send", decide(slack, {"channel_id": "C1", "message": WORDY}), "deny")
    expect("short slack send, greeting and sign-off not counted",
           decide(slack, {"channel_id": "C1", "message": SHORT}), "allow")
    expect("long slack draft", decide("mcp__claude_ai_Slack__slack_send_message_draft",
                                      {"channel_id": "C1", "message": LONG}), "deny")
    expect("long slack thread reply via text key",
           decide("mcp__slack__slack_reply_to_thread", {"text": LONG}), "deny")
    expect("long gmail send", decide("mcp__claude_ai_Gmail__send_message", {"body": LONG}), "deny")
    expect("long gmail draft html only",
           decide("mcp__claude_ai_Gmail__create_draft", {"htmlBody": HTML_LONG}), "deny")
    expect("long gmail forward note",
           decide("mcp__claude_ai_Gmail__forward", {"messageId": "m", "forwardText": LONG}), "deny")
    expect("gmail send of an existing draft id", decide("mcp__claude_ai_Gmail__send_message",
                                                        {"draftId": "d1"}), "allow")
    expect("quoted email reply lines not counted",
           decide("mcp__claude_ai_Gmail__reply",
                  {"messageId": "m", "body": "Yes, Monday works.\n" + "\n".join(f"> old {i}" for i in range(9))}),
           "allow")
    expect("slack canvas is not a message", decide("mcp__claude_ai_Slack__slack_create_canvas",
                                                   {"content": LONG}), "allow")
    expect("slack read passes", decide("mcp__claude_ai_Slack__slack_read_thread", {"text": LONG}), "allow")
    expect("gmail delete draft passes", decide("mcp__claude_ai_Gmail__delete_draft", {"body": LONG}), "allow")
    expect("non-messaging tool passes", decide("mcp__chrome-devtools__fill", {"value": LONG}), "allow")

    malformed = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True,
                               capture_output=True, timeout=20)
    expect("malformed payload fails open",
           "allow" if malformed.returncode == 0 and not malformed.stdout.strip() else "blocked", "allow")

    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / ".context" / "long-message-ok"
        marker.parent.mkdir()
        marker.write_text("Simon: write the full write-up for the team\n")
        expect("override allows one long send", decide(slack, {"message": LONG}, cwd=td), "allow")
        expect("override file consumed", "gone" if not marker.exists() else "present", "gone")
        expect("next long send denied again", decide(slack, {"message": LONG}, cwd=td), "deny")
        marker.write_text("   \n")
        expect("empty override does not count", decide(slack, {"message": LONG}, cwd=td), "deny")

        draft = Path(td) / "draft.txt"
        draft.write_text(LONG)
        over = subprocess.run([sys.executable, str(HOOK), "--check", str(draft)],
                              text=True, capture_output=True, timeout=20)
        expect("--check over cap", f"{over.returncode}:{over.stdout.split(':')[0]}", "1:over")
        draft.write_text(SHORT)
        ok = subprocess.run([sys.executable, str(HOOK), "--check", str(draft)],
                            text=True, capture_output=True, timeout=20)
        expect("--check within cap", f"{ok.returncode}:{ok.stdout.strip()}", "0:ok")

    for f in FAILURES:
        print(f"FAIL {f}")
    print(f"{'ok' if not FAILURES else 'FAILED'}: outbound-message-guard ({len(FAILURES)} failures)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
