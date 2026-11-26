#!/usr/bin/env python3
"""Pins hooks/outbound-message-guard.py and its one measure, bin/outbound_message.py, in both
directions: over-cap, dense-line and unbulleted sends denied; short or bulleted sends, non-send tools,
the one-shot override and the `check` CLI allowed or reported as documented."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "outbound-message-guard.py"
CHECK = Path(__file__).resolve().parent.parent / "bin" / "outbound_message.py"
FAILURES: list[str] = []

SHORT = "Hey there,\nThe cache migration (PR #812) is ready for your review.\nNeeds your yes before Monday.\nThanks,\nSimon"
LONG = "\n".join(f"- point {i}: one more fact the reader did not ask for" for i in range(1, 8))
WORDY = " ".join(["word"] * 130)
HTML_LONG = "".join(f"<p>paragraph {i} of a long email</p>" for i in range(1, 8))
# The 24 Nov teammate DM that passed the old 5-line/100-word cap (99 words, 3 lines): same line
# lengths and parenthesised figures; names and figures generalized for this public repo.
DENSE_DM = (
    "Suggest we set split_percent to 100 so new phone-browser visitors (iPhone and Android, in-app "
    "browsers too; not the native app, tablets or desktop) get variant B, ending the 5% A arm.\n"
    "Since 95/5 began 5 Nov, B makes $0.90 more per visitor at 7 days after refunds ($2.20 vs $1.30, "
    "95% range $0.10 to $1.80, processor-matched), +70% vs ABC-1's 20% bar. At 14 days the gap is "
    "$0.50, not clear of zero, with no late A payers.\n"
    "The arm costs about $250 a week (range $30 to $480) and is our only live comparison, so "
    "switching ends the read.")
BULLETED_DM = (
    "Suggest split_percent 100: every new phone-browser visitor gets variant B, ending the 5% A arm.\n"
    "- 7-day revenue per visitor after refunds: B $2.20, A $1.30\n"
    "- Gap $0.90, 95% range $0.10 to $1.80, past the 20% bar\n"
    "- At 14 days the gap is $0.50, not yet clear of zero\n"
    "- Keeping the A arm costs about $250 a week")
VERDICT = "All ok, nothing was broken: the fallback served every one of the 5 failed searches."
URL_LINE = ("PR #812 is ready for your review.\n"
            "https://github.com/example/repo/pull/812/files?diff=split&w=1#diff-" + "a" * 60 + "\n"
            "- Needs your yes before Monday")


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
    expect("24 Nov dense DM denied", decide(slack, {"channel_id": "C1", "message": DENSE_DM}), "deny")
    expect("its bulleted version passes",
           decide(slack, {"channel_id": "C1", "message": BULLETED_DM}), "allow")
    expect("one-line verdict passes", decide(slack, {"channel_id": "C1", "message": VERDICT}), "allow")
    expect("URL-only line is not a long line", decide(slack, {"message": URL_LINE}), "allow")
    expect("three plain lines with no bullets denied",
           decide(slack, {"message": "PR #812 is ready.\nIt adds one column.\nNeeds a yes by Monday."}),
           "deny")
    expect("one 30-word line denied", decide(slack, {"message": " ".join(["word"] * 30)}), "deny")
    expect("html list email keeps its bullets",
           decide("mcp__claude_ai_Gmail__send_message",
                  {"htmlBody": "<p>PR 812 is ready.</p><ul><li>Adds one column</li><li>Needs a yes</li></ul>"}),
           "allow")
    expect("three-word signature not counted",
           decide("mcp__claude_ai_Gmail__send_message",
                  {"body": "Please approve today.\nThanks,\nSimon Example Smith"}), "allow")
    expect("long gmail paragraph denied",
           decide("mcp__claude_ai_Gmail__send_message", {"body": " ".join(["word"] * 40)}), "deny")
    deny_reason = subprocess.run([sys.executable, str(HOOK)], text=True, capture_output=True, timeout=20,
                                 input=json.dumps({"tool_name": slack, "tool_input": {"message": DENSE_DM},
                                                   "cwd": "/tmp"})).stdout
    expect("deny reason shows the bullet shape",
           "ok" if "one fact per bullet" in deny_reason and "- Gap" in deny_reason else deny_reason, "ok")
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
        for label, text, want in (("over cap", LONG, "1:over"), ("dense DM", DENSE_DM, "1:over"),
                                  ("within cap", SHORT, "0:ok"), ("bulleted DM", BULLETED_DM, "0:ok")):
            draft.write_text(text)
            got = subprocess.run([sys.executable, str(CHECK), "check", str(draft)],
                                 text=True, capture_output=True, timeout=20)
            expect(f"check CLI {label}", f"{got.returncode}:{got.stdout.split(':')[0].strip()}", want)
        piped = subprocess.run([sys.executable, str(CHECK), "check", "-"], input=VERDICT,
                               text=True, capture_output=True, timeout=20)
        expect("check CLI reads stdin", f"{piped.returncode}:{piped.stdout.strip()}", "0:ok")
        old = subprocess.run([sys.executable, str(HOOK), "--check", str(draft)],
                             text=True, capture_output=True, timeout=20)
        expect("hook refuses the moved --check and names bin/outbound_message.py",
               f"{old.returncode}:{'bin/outbound_message.py' in old.stderr}", "2:True")

    for f in FAILURES:
        print(f"FAIL {f}")
    print(f"{'ok' if not FAILURES else 'FAILED'}: outbound-message-guard ({len(FAILURES)} failures)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
