#!/usr/bin/env python3
"""
A durable ledger of the decisions Simon types ("merge it when you're done", "not 1528, the one you're
working on now", "hold"), so a merge order that describes work instead of naming a PR number still binds to
the PR that work becomes, and a logged order is carried out without being told twice.

WHY: on 28 Nov 2026 "ok when you're done auto merge", "no not <A>, the one you're working on now" and "ie the
new rule after the split" were typed while a PR did not exist yet. The merge guard saw only a number and the
messages, so it could not connect the order to the PR that opened later, and Simon had to repeat it.

WHAT IT DOES (one engine, hook events, no daemon):
  UserPromptSubmit  a cheap prefilter (merge, land, ship, push, deploy, hold, wait, stop, cancel, go, ok, yes,
                    don't, or an order still waiting for its PR) gates ONE Haiku step (bin/haiku_judge.py kind decision-extract) that reads the
                    message, the agent's last reply and the open PRs and extracts decisions: action, target
                    (a PR number, else the described work verbatim), exclusions, condition, quote. They are
                    appended to <project>/.context/decisions.jsonl. A later hold or cancel supersedes. Then it
                    surfaces every logged merge decision that is ready to carry out.
  Stop              binds descriptive decisions to PRs that now exist (kind decision-bind) and, once per
                    decision, blocks the stop with "carry out the logged merge".
  PostToolUse Bash  `gh pr merge N` marks the decisions for N executed.
  Guard             hooks/git-commit-guard.py calls decision_for(): an unsuperseded merge decision bound to #N
                    whose quote is in a message Simon typed allows the merge (the guard also checks no later
                    typed message holds it). The words rule and the judged rule stay as fallbacks.

TRUST: only this engine, from a typed prompt, writes decisions. Every line carries an HMAC (a key under
state/, mode 600) and a line that fails it is ignored; the guard also re-finds the quote in the typed
messages. A determined agent can read the key, so this blocks a mistake or a copied line, not an attacker.

Fails open on extraction errors (prints nothing, exits 0); the guard's use of it fails closed as before.
Skips AGENT_DELEGATED_WORKER=1. CLI: list | cancel <id>  [--root DIR].
Env: DECISION_LEDGER_HOME (key dir, default ~/.claude/state), DECISION_LEDGER_NOW (ISO clock, tests).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

STORE = Path(".context") / "decisions.jsonl"
BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))

DECISION_WORDS = re.compile(
    r"\b(?:merg\w*|land\w*|ship\w*|push\w*|deploy\w*|hold|wait|stop|cancel\w*|go|ok(?:ay)?|yes|approve\w*"
    r"|don'?t|do not|auto)\b", re.I)
ACTIONS = {"merge", "hold", "cancel", "approve"}
HAIKU_S = 8.0


def now() -> str:
    return os.environ.get("DECISION_LEDGER_NOW") or dt.datetime.now().replace(microsecond=0).isoformat()


def root_of(cwd: str | None) -> Path:
    import scheduled_tasks
    return scheduled_tasks.root_of(cwd)


# ------------------------------------------------------------------ signed append-only store
def _key() -> bytes:
    home = Path(os.environ.get("DECISION_LEDGER_HOME") or Path.home() / ".claude" / "state")
    path = home / "decision-ledger.key"
    try:
        return path.read_bytes()
    except OSError:
        home.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32))
        return path.read_bytes()


def _sig(entry: dict) -> str:
    body = json.dumps({k: v for k, v in entry.items() if k != "sig"}, sort_keys=True, ensure_ascii=False)
    return hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()


def append(root: Path, entry: dict) -> None:
    entry = {**entry, "ts": entry.get("ts") or now()}
    entry["sig"] = _sig(entry)
    path = root / STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def replay(root: Path) -> dict:
    """id -> decision state after replaying every valid line: status pending|superseded|executed|cancelled,
    pr (the number it is bound to), surfaced (count)."""
    out: dict = {}
    try:
        lines = (root / STORE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
            if not isinstance(e, dict) or not hmac.compare_digest(str(e.get("sig", "")), _sig(e)):
                continue
        except Exception:
            continue
        t = e.get("t")
        if t == "decision" and e.get("action") in ACTIONS:
            d = {**e, "status": "pending", "pr": e["target"] if re.fullmatch(r"\d+", str(e.get("target", ""))) else "",
                 "surfaced": 0}
            if e["action"] in ("hold", "cancel"):
                d["status"] = "recorded"
                covers = set(e.get("supersedes") or [])
                for prev in out.values():
                    if prev["status"] == "pending" and prev["action"] in ("merge", "approve") and (
                            "all" in covers or prev["id"] in covers or (d["pr"] and d["pr"] == prev["pr"])
                            or (not d["pr"] and not covers and not e.get("target_text"))):
                        prev["status"] = "superseded"
            out[e["id"]] = d
        elif t == "bind" and e.get("id") in out and out[e["id"]]["status"] == "pending":
            out[e["id"]]["pr"] = str(e.get("pr", ""))
        elif t == "surfaced" and e.get("id") in out:
            out[e["id"]]["surfaced"] += 1
        elif t == "executed":
            for d in out.values():
                if d["status"] == "pending" and d["pr"] == str(e.get("pr", "")) and d["action"] == "merge":
                    d["status"] = "executed"
        elif t == "cancel" and e.get("id") in out:
            out[e["id"]]["status"] = "cancelled"
    return out


# ------------------------------------------------------------------ the Haiku step
def _haiku(kind: str, data: dict) -> dict:
    try:
        import haiku_judge
        v = haiku_judge.judge(kind, data, timeout=HAIKU_S)
        return v if v.get("ok") is True and isinstance(v.get("data"), dict) else {}
    except Exception:
        return {}


def open_prs(root: Path) -> list:
    try:
        p = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "30", "--json",
                            "number,title,headRefName"], cwd=root, capture_output=True, text=True, timeout=6)
        rows = json.loads(p.stdout) if p.returncode == 0 else []
    except Exception:
        rows = []
    return [{"number": str(r["number"]), "title": str(r.get("title", ""))[:200], "branch": str(r.get("headRefName", ""))[:120]}
            for r in rows if isinstance(r, dict) and "number" in r]


def last_assistant_text(path: str) -> str:
    text = ""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines()[-400:]:
            e = json.loads(line)
            if e.get("type") == "assistant" and not e.get("isSidechain"):
                parts = (e.get("message") or {}).get("content")
                got = "\n".join(c.get("text", "") for c in parts if isinstance(c, dict) and c.get("type") == "text") \
                    if isinstance(parts, list) else str(parts or "")
                if got.strip():
                    text = got
    except Exception:
        pass
    return text[-1500:]


# ------------------------------------------------------------------ record, bind, surface
def record(root: Path, payload: dict) -> None:
    prompt = str(payload.get("prompt") or "").strip()
    state = replay(root)
    unbound = any(d["status"] == "pending" and d["action"] == "merge" and not d["pr"] for d in state.values())
    if not prompt or not (DECISION_WORDS.search(prompt) or unbound):  # a clarification follows an unbound order
        return
    prs = open_prs(root)
    pending = [{k: d.get(k) for k in ("id", "action", "target", "target_text")}
               for d in state.values() if d["status"] == "pending"]
    got = _haiku("decision-extract", {"message": prompt[:2000], "previous_assistant": last_assistant_text(
        str(payload.get("transcript_path") or "")), "open_prs": prs, "pending": pending})
    for item in (got.get("data") or {}).get("decisions", []) or []:
        if not isinstance(item, dict) or item.get("action") not in ACTIONS:
            continue
        quote = " ".join(str(item.get("quote") or "").split())
        if not quote or quote.lower() not in " ".join(prompt.split()).lower():
            continue  # a quote that is not in the typed message is not a decision
        target = re.sub(r"\D", "", str(item.get("target") or ""))
        append(root, {"t": "decision", "id": uuid.uuid4().hex[:8], "session": payload.get("session_id", ""),
                      "action": item["action"], "target": target, "target_text": str(item.get("target_text") or "")[:300],
                      "exclude": [re.sub(r"\D", "", str(x)) for x in (item.get("exclude") or []) if re.sub(r"\D", "", str(x))],
                      "condition": str(item.get("condition") or "now")[:80], "quote": quote[:300],
                      "supersedes": [str(x) for x in (item.get("supersedes") or [])][:10],
                      "open_before": [p["number"] for p in prs]})


def bind(root: Path, candidates: list) -> None:
    """Bind each pending descriptive merge decision to the one candidate PR that matches it (never an excluded
    number)."""
    for d in replay(root).values():
        if d["status"] != "pending" or d["action"] != "merge" or d["pr"] or not d.get("target_text"):
            continue
        cands = [{**c, "opened_after": c["number"] not in d.get("open_before", [])}
                 for c in candidates if c["number"] not in d.get("exclude", [])]
        if not cands:
            continue
        got = _haiku("decision-bind", {"decision": {"target_text": d["target_text"], "exclude": d.get("exclude", []),
                                                    "quote": d["quote"]}, "candidates": cands})
        pr = re.sub(r"\D", "", str((got.get("data") or {}).get("pr", "")))
        if pr and pr in {c["number"] for c in cands}:
            append(root, {"t": "bind", "id": d["id"], "pr": pr})


def ready(root: Path) -> list:
    return [d for d in replay(root).values() if d["status"] == "pending" and d["action"] == "merge" and d["pr"]]


def surface_text(decisions: list) -> str:
    return "\n".join(
        f"Logged decision {d['id']}: Simon ordered #{d['pr']} merged ({d['condition']}; \"{d['quote'][:80]}\"). "
        f"Carry it out without being told again: when the ship gate passes and CI is green on its head, run "
        f"`gh pr merge {d['pr']} --match-head-commit <head sha>`. A later hold supersedes it." for d in decisions)


def decision_for(root: Path, number: str, typed: list, pr: dict | None = None) -> dict | None:
    """The unsuperseded merge decision bound to #N whose quote is in a message Simon typed, or None. When a
    descriptive decision is still unbound, the PR being merged is offered to the bind step first."""
    if pr and (pr.get("title") or pr.get("headRefName")):
        bind(root, [{"number": number, "title": str(pr.get("title", ""))[:200], "branch": str(pr.get("headRefName", ""))[:120]}])
    flat = [" ".join(t.lower().replace("’", "'").split()) for t in typed]
    for d in replay(root).values():
        if (d["status"] == "pending" and d["action"] == "merge" and d["pr"] == str(number)
                and number not in d.get("exclude", []) and any(d["quote"].lower() in t for t in flat)):
            return d
    return None


# ------------------------------------------------------------------ hook
def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "hook":
        if os.environ.get("AGENT_DELEGATED_WORKER") == "1":
            return 0
        try:
            payload = json.loads(sys.stdin.read() or "{}")
            root = root_of(payload.get("cwd"))
            event = payload.get("hook_event_name")
            if event == "UserPromptSubmit":
                record(root, payload)
                bind(root, open_prs(root)) if any(
                    d["status"] == "pending" and not d["pr"] and d["action"] == "merge"
                    for d in replay(root).values()) else None
                out = surface_text(ready(root))
                if out:
                    print(out)
            elif event == "Stop":
                bind(root, open_prs(root))
                todo = [d for d in ready(root) if d["surfaced"] == 0]
                if todo and not payload.get("stop_hook_active"):
                    for d in todo:
                        append(root, {"t": "surfaced", "id": d["id"]})
                    print(json.dumps({"decision": "block", "reason": surface_text(todo)}))
            elif event == "PostToolUse" and payload.get("tool_name") == "Bash":
                m = re.search(r"\bgh\s+pr\s+merge\s+(?:\S+\s+)*?(\d+)\b", str((payload.get("tool_input") or {}).get("command", "")))
                if m and not (payload.get("tool_response") or {}).get("interrupted"):
                    append(root, {"t": "executed", "pr": m.group(1)})
        except Exception:
            pass
        return 0
    root = root_of(argv[argv.index("--root") + 1] if "--root" in argv else None)
    if argv[0] == "list":
        for d in replay(root).values():
            print(f"{d['id']}\t{d['status']}\t{d['action']}\t#{d['pr'] or '-'}\t{d.get('target_text', '')[:50]}\t{d['quote'][:60]}")
        return 0
    if argv[0] == "cancel" and len(argv) > 1:
        append(root, {"t": "cancel", "id": argv[1]})
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
