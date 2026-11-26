#!/usr/bin/env python3
"""
Block a final message to Simon that names a PR, issue or ticket by a bare id instead of a link.

rules/communication.md § Five rules: every PR, issue, ticket, Slack thread, CI run or doc a message to
Simon mentions is a markdown link with its full URL, on every mention
(references/tldr-report-formats.md § Links). The rule existed and hand-backs still ended on
"Merge list: #1297, #1497", so Simon had to ask for the links. This is the backstop on the Stop path.

WHAT IT BLOCKS: a Stop whose `last_assistant_message` (else the transcript's last assistant text)
holds a bare `#NN` (two or more digits), an `owner/repo#N` or a ticket key `ABC-123` outside:
fenced code, an inline code span, a markdown link `[label](https://...)` (its label included), an
autolink `<https://...>` and a bare full URL. Commit shas never match. Standards and encodings that
look like keys (UTF-8, SHA-256, ISO-8601, GPT-5, ...) are in NOT_TICKETS.

LOOP SAFETY: it blocks at most once per stop chain. When it blocks it writes a marker; a continuation
(`stop_hook_active`) with the marker present passes and clears it, so a rewrite that still misses one
reference ends the turn instead of looping. A fresh stop (not a continuation) can block again.

Skips a delegated worker (AGENT_DELEGATED_WORKER=1): its message is for an agent, not Simon.
Fails OPEN on anything malformed: a guard that breaks the session gets switched off.

CLI: python3 ~/.claude/hooks/bare-reference-guard.py --check <file|->  prints each bare reference
and exits 1, or prints `ok` and exits 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / ".intent-ledger"
RULE = "rules/communication.md § Five rules and references/tldr-report-formats.md § Links"
MAX_LISTED = 12

FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.S | re.M)
OPEN_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*", re.S | re.M)  # an unclosed fence runs to the end
CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
MD_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?[a-z][a-z0-9+.-]*://[^)\s]*>?(?:\s+\"[^\"]*\")?\s*\)", re.I)
AUTOLINK = re.compile(r"<[a-z][a-z0-9+.-]*://[^>\s]+>", re.I)
BARE_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>()\[\]]+", re.I)

PR_REF = re.compile(r"(?<![&#\w])#\d{2,}\b|\b[\w.-]+/[\w.-]+#\d+\b")
TICKET = re.compile(r"(?<![\w/.-])([A-Z][A-Z0-9]{1,5})-\d+\b")
NOT_TICKETS = {
    "UTF", "UCS", "SHA", "MD", "AES", "RSA", "DES", "ECDSA", "ED", "HMAC", "CRC", "BLAKE", "PBKDF",
    "ISO", "IEC", "IEEE", "RFC", "ECMA", "ES", "CVE", "CWE", "GHSA", "PCI", "SOC", "WCAG", "HIPAA",
    "GPT", "HTTP", "TLS", "SSL", "IPV", "UTC", "GMT", "COVID", "IE", "MP", "PG", "WPA", "USB", "DDR",
    "LTE", "IP", "TCP", "UDP", "AV", "ARM", "AMD", "OS",
}


def strip_exempt(text: str) -> str:
    """The text with every exempt region blanked: code, links (labels included) and URLs."""
    for pattern in (FENCE, OPEN_FENCE, CODE_SPAN, MD_LINK, AUTOLINK, BARE_URL):
        text = pattern.sub(" ", text)
    return text


def bare_references(text: str) -> list[str]:
    """Each bare PR, issue or ticket reference, first occurrence order, deduplicated."""
    plain = strip_exempt(text or "")
    found = [m.group(0) for m in PR_REF.finditer(plain)]
    found += [m.group(0) for m in TICKET.finditer(plain) if m.group(1) not in NOT_TICKETS]
    ordered = sorted(set(found), key=lambda ref: plain.find(ref))
    return ordered


def repo_url(cwd: str) -> str | None:
    """https://github.com/<owner>/<repo> from the cwd's origin, or None."""
    try:
        out = subprocess.run(["git", "-C", cwd or ".", "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"^(?:https?://|ssh://git@|git@)github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", out)
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None


def last_message(payload: dict) -> str:
    text = payload.get("last_assistant_message")
    if isinstance(text, str):
        return text
    path = payload.get("transcript_path")
    if not path:
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") != "assistant" or entry.get("isSidechain"):
                    continue
                content = (entry.get("message") or {}).get("content")
                parts = [content] if isinstance(content, str) else [
                    c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
                joined = "\n".join(p for p in parts if p)
                if joined.strip():
                    last = joined
    except OSError:
        return ""
    return last


def reason(refs: list[str], base: str | None) -> str:
    listed = ", ".join(refs[:MAX_LISTED]) + (f" and {len(refs) - MAX_LISTED} more" if len(refs) > MAX_LISTED else "")
    example = f"[#123]({base}/pull/123)" if base else "[#123](https://github.com/<owner>/<repo>/pull/123)"
    source = (f"This repo's PRs and issues live under {base}/pull/<N> (GitHub redirects an issue number to /issues)."
              if base else "Resolve each PR's URL with `gh pr view <N> --json url`.")
    return (f"Your final message names {listed} without a link ({RULE}). Simon cannot click a bare id. "
            f"Rewrite the message with every mention as a markdown link on every mention, e.g. {example}. "
            f"{source} A ticket key links to the ticket's own URL (its tracker or the PR body); if none exists, "
            "say so in place of the id. Keep `Merge list:` as `Merge list: [#A](url), [#B](url)`. "
            "Change only the links, keep the rest of the message. This fires once per stop.")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        text = sys.stdin.read() if sys.argv[2] == "-" else Path(sys.argv[2]).read_text(encoding="utf-8")
        refs = bare_references(text)
        print("ok" if not refs else "bare: " + ", ".join(refs))
        return 1 if refs else 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict) or os.environ.get("AGENT_DELEGATED_WORKER") == "1":
        return 0
    sid = re.sub(r"[^\w.-]", "_", str(payload.get("session_id") or "unknown"))[:120]
    marker = STATE / f"{sid}.barelink"
    refs = bare_references(last_message(payload))
    if not refs or (payload.get("stop_hook_active") and marker.exists()):
        marker.unlink(missing_ok=True)
        return 0
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        marker.write_text(hashlib.sha256(",".join(refs).encode()).hexdigest() + "\n")
    except OSError:
        return 0  # no marker means no loop guard: fail open rather than risk a loop
    print(json.dumps({"decision": "block", "reason": reason(refs, repo_url(str(payload.get("cwd") or "")))}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - fail open
        sys.exit(0)
