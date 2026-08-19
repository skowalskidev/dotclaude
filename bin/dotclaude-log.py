#!/usr/bin/env python3
"""The ONE shared writer for dotclaude metrics — every collector routes its events through here.

DRY/SRP: one place owns the cloud sink, the redaction call, the boundary rule, the outbox fallback,
the fail-closed project check, and the TTL stamp. Each collector keeps its own responsibility for
WHAT it logs; this owns HOW it lands.

Contract it must never break:
  - NEVER raises to the caller and NEVER blocks a session — a SessionEnd/Stop hook calls this, so a
    Firestore hiccup, a missing key, or being offline must all end in exit 0.
  - Capture-first: events are ALWAYS appended to the local outbox first (fast, never fails), THEN a
    best-effort, time-boxed flush to Firestore runs; whatever doesn't flush drains next time. So no
    event is ever lost, even with no project configured (the default state until setup).
  - Fail-closed on project: refuses to write if the key's project_id doesn't match the configured
    personal project — config telemetry never lands in the wrong (e.g. work) project.
  - Minimized before it leaves the machine: every event passes dotclaude_redact.minimize_event; a
    work-boundary event drops its free-text intent (work content never reaches a personal project).

Public-template-safe: nothing here names a specific project, account, or org. The project id comes
from the key itself (or CLAUDE_METRICS_PROJECT); paths come from env with conventional defaults. A
fork with no key configured simply no-ops to the outbox.

Usage (CLI):  echo '<event-json-or-list>' | dotclaude-log.py <collection>
Usage (lib):  from dotclaude_log import write_events; write_events("retro_triggers", [event])
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

# Load the sibling redaction layer by path (filename is hyphenated, so not importable by name).
def _load_redact():
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dotclaude-redact.py")
    try:
        spec = importlib.util.spec_from_file_location("dotclaude_redact", path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        return mod.minimize_event
    except Exception:  # never let a bad import block a session
        return lambda e, allow_intent=True: (e if isinstance(e, dict) else {})


minimize_event = _load_redact()

_HOME = os.path.expanduser("~")
KEY_PATH = os.environ.get("CLAUDE_METRICS_SA_KEY") or os.path.join(
    _HOME, ".config", "firebase-keys", "dotclaude.json"
)
OUTBOX = os.environ.get("CLAUDE_METRICS_OUTBOX") or os.path.join(_HOME, ".claude", "metrics", "outbox.jsonl")
RETENTION_DAYS = int(os.environ.get("CLAUDE_METRICS_RETENTION_DAYS", "365"))
FLUSH_BUDGET_S = float(os.environ.get("CLAUDE_METRICS_FLUSH_BUDGET_S", "5"))
# Optional explicit expected project; when unset we trust the key's own project_id.
_EXPECTED_PROJECT = os.environ.get("CLAUDE_METRICS_PROJECT")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(event: dict, strict: bool = True) -> dict:
    """Add ts/expireAt if absent; honor the event's boundary for intent redaction."""
    allow_intent = event.get("boundary") != "work"
    e = minimize_event(event, allow_intent=allow_intent, strict=strict)
    e.setdefault("schema_version", 1)
    e.setdefault("ts", _iso(_now()))
    e.setdefault("expireAt", _iso(_now() + _dt.timedelta(days=RETENTION_DAYS)))
    return e


def _append_outbox(collection: str, events: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
        with open(OUTBOX, "a", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps({"_collection": collection, **e}, default=str) + "\n")
    except Exception:
        pass  # last-resort: never raise from the logger


def _key_project_id() -> str | None:
    try:
        with open(KEY_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("project_id")
    except Exception:
        return None


def _firestore_client():
    """Return an Admin-SDK Firestore client, or None if unavailable/misconfigured (→ outbox)."""
    proj = _key_project_id()
    if not proj:
        return None
    if _EXPECTED_PROJECT and proj != _EXPECTED_PROJECT:
        return None  # fail-closed: key points at an unexpected project, do not write
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials, firestore  # type: ignore
    except Exception:
        return None  # firebase-admin not installed (default state) → outbox only
    try:
        app_name = "dotclaude"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            cred = credentials.Certificate(KEY_PATH)
            app = firebase_admin.initialize_app(cred, {"projectId": proj}, name=app_name)
        return firestore.client(app)
    except Exception:
        return None


def _drain_outbox(db) -> int:
    """Best-effort flush of the outbox to Firestore in batched commits (one round-trip per ≤500 docs,
    not one per doc). Returns rows written. Rewrites the outbox with whatever didn't flush within the
    time budget, so nothing is lost."""
    if not os.path.exists(OUTBOX):
        return 0
    try:
        with open(OUTBOX, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except Exception:
        return 0
    start = _now()
    written, leftover, i, n = 0, [], 0, len(lines)
    while i < n:
        if (_now() - start).total_seconds() > FLUSH_BUDGET_S:
            leftover.extend(lines[i:])
            break
        chunk = lines[i:i + 450]  # under the 500-op WriteBatch cap
        batch = db.batch()
        staged = []
        for ln in chunk:
            try:
                rec = json.loads(ln)
            except Exception:
                continue  # unparseable row: drop it, it will never parse
            coll = rec.pop("_collection", "events")
            ref = db.collection(coll).document()  # auto-ID (scatter-allocated, no hotspot)
            batch.set(ref, rec)
            staged.append(ln)
        try:
            if staged:
                batch.commit()
                written += len(staged)
        except Exception:
            leftover.extend(chunk)  # whole chunk failed: keep for next time
        i += 450
    try:
        if leftover:
            with open(OUTBOX, "w", encoding="utf-8") as fh:
                fh.write("\n".join(leftover) + "\n")
        elif os.path.exists(OUTBOX):
            os.remove(OUTBOX)
    except Exception:
        pass
    return written


def write_events(collection: str, events: list[dict], strict: bool = True) -> dict:
    """Minimize + stamp events, append to outbox, then best-effort flush. Never raises.
    strict=False keeps trusted counts-only log schemas (see minimize_event). Returns a health summary."""
    events = [_stamp(e, strict=strict) for e in events if isinstance(e, dict)]
    _append_outbox(collection, events)
    health = {"queued": len(events), "flushed": 0, "sink": "outbox"}
    db = _firestore_client()
    if db is not None:
        try:
            health["flushed"] = _drain_outbox(db)
            health["sink"] = "firestore"
        except Exception as exc:  # noqa: BLE001 — record, never raise
            health["error_type"] = type(exc).__name__
    return health


def main() -> int:
    collection = sys.argv[1] if len(sys.argv) > 1 else "events"
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    events = obj if isinstance(obj, list) else [obj]
    write_events(collection, events)
    return 0  # ALWAYS 0 — a logger must never fail a session


if __name__ == "__main__":
    raise SystemExit(main())
