#!/usr/bin/env python3
"""The ONE need-to-know minimization layer for dotclaude metrics.

Every path that stores or commits a metrics event routes through here BEFORE anything leaves the
machine, so redaction lives in one place and cannot be half-applied. It enforces, in order:

  1. Secret scrub   — keys, tokens, passwords, private keys, connection strings.
  2. PII scrub      — emails, phone numbers.
  3. Content minimization (field allowlist) — for config optimization we need to know WHICH part
     fired, HOW it was triggered (the request's shape), the OUTCOME and the ERROR. We do NOT need
     the sensitive specifics: file/code contents, command bodies, tool-output payloads, diffs.
     Those are dropped, never stored.
  4. Fail-closed    — a field that cannot be confidently classified as safe is dropped, not kept.

Why DROP, not tokenize: config optimization never needs to RECOVER a specific, so a token vault
would add risk for no benefit. Dropping is simpler and lower-risk.

Pure functions, no I/O, no network — so it is unit-testable in isolation and imported by
dotclaude-log.py and config-metrics-record.py. Run as a script (`echo '{...}' | dotclaude-redact.py`)
it reads one JSON event on stdin and prints the minimized event, for shell hooks without Python glue.
"""
from __future__ import annotations

import json
import re
import sys

REDACTED = "[REDACTED]"
DROPPED = "[DROPPED:content]"

# --- 1. Secret patterns (gitleaks-grade, mainstream). Order matters: specific before generic. ---
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                         # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                         # AWS temp key id
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),                   # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z\-_]+"),                      # Google OAuth token
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,255}\b"),           # GitHub tokens
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),            # Slack tokens
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                      # OpenAI-style keys
    re.compile(r"\bsk_(live|test)_[0-9A-Za-z]{16,}\b"),         # Stripe secret keys
    re.compile(r"\beyJ[0-9A-Za-z\-_]+\.[0-9A-Za-z\-_]+\.[0-9A-Za-z\-_]+"),  # JWT
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b(?=.{0,20}(secret|token|key))", re.I),
    # connection strings with embedded credentials: scheme://user:pass@host
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s]+", re.I),
    # key=value / "key": "value" where the key name implies a secret
    re.compile(
        r'(?i)\b(pass(word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|'
        r'client[_-]?secret|auth|bearer|credential)s?\b\s*[:=]\s*["\']?[^\s"\',;]{6,}',
    ),
]

# --- 2. PII patterns ---
_PII_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),       # email
    re.compile(r"(?<!\d)(\+?\d[\d\-\s().]{7,}\d)(?!\d)"),                       # phone-ish
]


def redact_text(s: str) -> str:
    """Scrub secrets then PII from a free-text string. Keeps the surrounding words (the request
    shape) so config diagnosis still works; only the sensitive spans are replaced."""
    if not isinstance(s, str) or not s:
        return s
    for pat in _SECRET_PATTERNS:
        s = pat.sub(REDACTED, s)
    for pat in _PII_PATTERNS:
        s = pat.sub(REDACTED, s)
    return s


# --- 3. Field allowlist (need-to-know). Only these keys may be stored per event; everything else
# is dropped. `intent` is the one free-text field, and it is redact_text()'d and length-capped. ---
_ALLOWED_FIELDS: set[str] = {
    "schema_version", "seq", "ts", "session_id", "machine", "boundary", "end_reason",
    "kind", "part_type", "part_name", "tool_name", "outcome", "error_type", "count",
    "expireAt", "captured_at", "optimized", "started", "ended", "event_count", "outbox_depth",
    # run-analytics fields (from superspeed), all non-content metrics
    "run_id", "slices", "duration_ms", "tokens", "cache", "findings_count", "instrumentation_gaps",
}
_INTENT_CAP = 2000  # chars; the request SHAPE, not a transcript dump


def minimize_event(event: dict, *, allow_intent: bool = True) -> dict:
    """Return a new event holding only need-to-know fields, secrets/PII scrubbed, content dropped.

    allow_intent=False (work-boundary sessions) drops the free-text `intent` entirely — work request
    text must never reach the personal metrics project; only the config-part signal survives.
    Fail-closed: any field not on the allowlist and not the handled `intent` is dropped.
    """
    if not isinstance(event, dict):
        return {}
    out: dict = {}
    for k, v in event.items():
        if k in _ALLOWED_FIELDS:
            out[k] = redact_text(v) if isinstance(v, str) else v
        elif k == "intent" and allow_intent:
            text = v if isinstance(v, str) else json.dumps(v, default=str)
            out["intent"] = redact_text(text)[:_INTENT_CAP]
        # else: dropped (fail-closed) — file contents, command bodies, payloads, unknown fields.
    return out


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Not JSON: treat the whole thing as free text and scrub it.
        sys.stdout.write(redact_text(raw))
        return 0
    if isinstance(obj, list):
        print(json.dumps([minimize_event(e) for e in obj], default=str))
    else:
        print(json.dumps(minimize_event(obj), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
