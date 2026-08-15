#!/usr/bin/env python3
"""
Deny ONE thing: a Bash command whose verb reads a file, pointed at a crown-jewel secret.

WHY THIS IS NOT THE GUARD THAT WAS RETIRED

`security-guard.py` was a broad denylist of attack-shaped regexes over the whole command
TEXT. It fired 208 times on real work, caught zero real threats, was switched off three
times, and in one session falsely blocked four ordinary commands. Its defect was
structural: matching on text, a command that merely NAMED a sensitive path was
indistinguishable from one that read it.

This is deliberately not that. It asks two questions, and denies only when BOTH are yes:

  1. Is the command's verb one that reads a file out? (cat, less, head, xxd, base64 …)
  2. Does one of a SHORT list of crown-jewel paths appear in it?

Every one of the four historical false positives fails question 1 or 2, and each is a
test case in `crown-jewel-read-guard.test.py` so this cannot regress into the old guard.

WHAT IT DOES NOT DO, STATED PLAINLY

It stops the naive form: `cat ~/.ssh/id_ed25519`. It does not stop obfuscation
(`cd ~/.ssh && cat id_*`), nor an interpreter reading the file itself
(`python3 -c "open('~/.ssh/id_rsa')"`). Making it try would rebuild the retired guard and
reacquire its false-positive rate.

Passing a credential path to a TOOL stays allowed on purpose — e.g.
`GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/… node migrate.mjs`. The verb is `node`,
not a reader. That is a legitimate, frequent operation and blocking it would be the old
guard's mistake in a new coat.

So this is a seatbelt against the careless or injected LITERAL read, not a boundary. The
boundary is the provenance rule in rules/security.md, and the harness-enforced
`permissions.deny` path matchers in settings.json. This only covers Bash, which those
path matchers structurally cannot reach.
"""

import json
import re
import sys

# Commands whose whole job is to emit a file's contents. A verb NOT on this list is never
# blocked, which is what keeps `git commit -m "...~/.gnupg..."` and `nvm use` clear.
READ_VERBS = {
    "cat", "bat", "less", "more", "head", "tail", "nl", "tac",
    "xxd", "od", "hexdump", "strings", "base64", "openssl",
    "cp", "scp", "rsync", "install",
}

# Crown jewels only. Nothing here has a legitimate `cat`. Notably ABSENT: .npmrc, .env,
# ~/.config/gcloud — each has real uses, and one of them was a historical false positive.
CROWN_JEWELS = [
    r"\.ssh/",
    r"\.aws/credentials",
    r"\.gnupg/",
    r"Library/Keychains/",
    r"\.config/op/",
    r"personal-keys\.env",
    r"\.claude/\.credentials\.json",
    r"id_rsa\b", r"id_ed25519\b", r"id_ecdsa\b",
    r"\.netrc\b", r"\.pgpass\b",
]
JEWEL_RE = re.compile("|".join(CROWN_JEWELS))

# Split on shell separators so `foo && cat ~/.ssh/x` is judged by the cat, not the foo.
SEGMENT_RE = re.compile(r"(?:\|\||&&|;|\||\n)")
# Leading VAR=value assignments and `sudo`/`env` prefixes are not the verb.
PREFIX_RE = re.compile(r"^(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*|sudo|env|command|nohup)\s+)*")


def verb_of(segment: str) -> str:
    stripped = PREFIX_RE.sub("", segment.strip())
    first = stripped.split()[0] if stripped.split() else ""
    return first.rsplit("/", 1)[-1]  # /bin/cat -> cat


def offending_segment(command: str):
    """Return the segment that reads a crown jewel, or None."""
    for segment in SEGMENT_RE.split(command):
        if not segment.strip():
            continue
        if verb_of(segment) in READ_VERBS and JEWEL_RE.search(segment):
            return segment.strip()
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never break the session on a malformed payload.

    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0

    hit = offending_segment(command)
    if not hit:
        return 0

    print(
        json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Blocked: this reads a crown-jewel secret out through Bash — `{hit}`.\n"
                    "The Read tool denies these paths; this closes the same hole for Bash.\n"
                    "If you asked for this directly, you can run it yourself, or narrow "
                    "CROWN_JEWELS in ~/.claude/hooks/crown-jewel-read-guard.py.\n"
                    "To point a TOOL at a credential file instead of printing it (e.g. "
                    "GOOGLE_APPLICATION_CREDENTIALS=... node script.mjs), that is already allowed."
                ),
            }
        })
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
