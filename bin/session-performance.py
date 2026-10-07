#!/usr/bin/env python3
"""Local, bounded performance evidence and independent session reports."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


MAX_REPORT = 1_000_000
MAX_METADATA = 20_000
MAX_PROCESSES = 60
MAX_SESSIONS = 256
MAX_REPORTS_PER_SESSION = 100
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fail(message):
    raise ValueError(message)


def safe_dir(path, create=False):
    if ".." in Path(path).parts:
        fail("parent traversal in report path")
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            fail("symlink in report path")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        fail("report directory is missing")
    return path


def safe_file(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        fail("unsafe report file")
    return path


def read_bytes(path, limit=MAX_REPORT):
    path = safe_file(path)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        fail("file exceeds size limit")
    return data


def read_json(path):
    return json.loads(read_bytes(path, MAX_METADATA))


def atomic_exclusive(path, data):
    """Publish complete bytes without replacing a prior report."""
    parent = safe_dir(path.parent)
    safe_file(path)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)


def valid_uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        fail("session id must be a UUID")
    if str(parsed) != value:
        fail("session id must be a canonical UUID")
    return value


def batch_dir(args, create=False):
    if not NAME.fullmatch(args.batch):
        fail("invalid batch name")
    return safe_dir(safe_dir(args.root, create=create) / args.batch, create=create)


def session_dir(args, create=False):
    valid_uuid(args.id)
    return safe_dir(batch_dir(args, create=create) / args.id, create=create)


def register(args):
    if not Path(args.workspace).is_absolute():
        fail("workspace must be absolute")
    if not args.branch or not args.task or len(args.branch) > 300 or len(args.task) > 1000:
        fail("branch and task are required and bounded")
    args.id = valid_uuid(args.id or str(uuid.uuid4()))
    directory = session_dir(args, create=True)
    path = directory / "registration.json"
    metadata = {"sessionId": args.id, "workspace": args.workspace,
                "branch": args.branch, "task": args.task}
    if path.exists():
        prior = read_json(path)
        if not isinstance(prior, dict) or any(prior.get(key) != value for key, value in metadata.items()):
            fail("registration id already has different metadata")
        return {"id": args.id, "path": str(path), "existing": True}
    metadata["registeredAt"] = now()
    try:
        atomic_exclusive(path, json.dumps(metadata, indent=2).encode() + b"\n")
    except FileExistsError:
        prior = read_json(path)
        if not isinstance(prior, dict) or any(prior.get(key) != value for key, value in metadata.items() if key != "registeredAt"):
            fail("registration id already has different metadata")
    return {"id": args.id, "path": str(path), "existing": False}


def command_output(argv, timeout=3, limit=60_000):
    try:
        process = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        if process.returncode:
            return {"available": False, "reason": "command failed"}
        data = process.stdout[:limit]
        return {"available": True, "truncated": len(process.stdout) > limit,
                "text": data.decode("utf-8", errors="replace")}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
        return {"available": False, "reason": type(error).__name__}


def snapshot(args):
    directory = session_dir(args)
    try:
        load = list(os.getloadavg())
    except OSError:
        load = None
    ps = command_output(["ps", "-r", "-Ao", "pid=,ppid=,pcpu=,pmem=,etime=,comm="], limit=100_000)
    if ps["available"]:
        lines = ps.pop("text").splitlines()
        parsed = []
        for line in lines:
            fields = line.split(None, 5)
            if len(fields) != 6:
                continue
            try:
                parsed.append({"pid": int(fields[0]), "ppid": int(fields[1]),
                               "cpuPercent": float(fields[2]), "memoryPercent": float(fields[3]),
                               "elapsed": fields[4], "command": fields[5]})
            except ValueError:
                continue
        parsed.sort(key=lambda process: process["cpuPercent"], reverse=True)
        ps["processes"] = parsed[:MAX_PROCESSES]
        ps["observedLines"] = len(lines)
        ps["unparsedLines"] = len(lines) - len(parsed)
        ps["truncated"] = ps["truncated"] or len(parsed) > MAX_PROCESSES
    sims = command_output(["xcrun", "simctl", "list", "devices", "booted", "--json"], limit=30_000)
    if sims["available"]:
        try:
            payload = json.loads(sims.pop("text"))
            if not isinstance(payload, dict) or not isinstance(payload.get("devices"), dict):
                raise ValueError("invalid simulator JSON container")
            sims["devices"] = payload["devices"]
        except (json.JSONDecodeError, ValueError):
            sims = {"available": False, "reason": "invalid JSON"}
    hardware = {}
    for field in ("hw.ncpu", "hw.memsize"):
        result = command_output(["sysctl", "-n", field], limit=100)
        if result["available"]:
            value = result["text"].strip()
            if value.isdigit():
                hardware[field] = int(value)
    evidence = {"observedAt": now(), "loadAverage": load, "hardware": hardware,
                "processes": ps, "bootedSimulators": sims}
    path = directory / f"snapshot-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
    atomic_exclusive(path, json.dumps(evidence, indent=2).encode() + b"\n")
    return {"id": args.id, "path": str(path), "observedAt": evidence["observedAt"]}


def report_files(directory):
    names = ["report.md"]
    warnings = []
    for path in directory.glob("*.md"):
        if "addendum" not in path.name:
            continue
        if re.fullmatch(r"[A-Za-z0-9_-]+\.md", path.name):
            names.append(path.name)
        else:
            warnings.append("ignored invalid addendum name")
    additions = directory / "addenda"
    if additions.is_symlink():
        warnings.append("ignored symlinked addenda directory")
    elif additions.is_dir():
        for path in additions.glob("*.md"):
            if re.fullmatch(r"[A-Za-z0-9_-]+\.md", path.name):
                names.append(f"addenda/{path.name}")
            else:
                warnings.append("ignored invalid addenda filename")
    return sorted(set(names)), warnings


def report_name(name):
    if name == "report.md" or ("addendum" in name and re.fullmatch(r"[A-Za-z0-9_-]+\.md", name)):
        return name
    if re.fullmatch(r"addenda/[A-Za-z0-9_-]+\.md", name):
        return name
    fail("invalid report name")


def publish(args):
    directory = session_dir(args)
    if not (directory / "registration.json").exists():
        fail("registration is missing")
    data = read_bytes(args.file)
    if not data.strip():
        fail("report is empty")
    data.decode("utf-8")
    if args.addendum:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"addendum-{stamp}-{uuid.uuid4().hex[:8]}.md"
    else:
        name = "report.md"
    path = directory / name
    atomic_exclusive(path, data)
    return {"id": args.id, "path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def reviewed(args):
    directory = session_dir(args)
    name = report_name(args.report)
    path = directory / name
    digest = hashlib.sha256(read_bytes(path)).hexdigest()
    if args.sha256 != digest:
        fail("report hash changed since inspection")
    receipts = safe_dir(directory / "reviewed", create=True)
    receipt = receipts / f"{hashlib.sha256((name + ':' + digest).encode()).hexdigest()}.json"
    value = {"report": name, "sha256": digest, "reviewedAt": now()}
    try:
        atomic_exclusive(receipt, json.dumps(value, indent=2).encode() + b"\n")
    except FileExistsError:
        prior = read_json(receipt)
        if not isinstance(prior, dict) or prior.get("report") != name or prior.get("sha256") != digest:
            fail("review receipt hash collision")
    return {"id": args.id, **value, "path": str(receipt)}


def status(args):
    directory = batch_dir(args)
    sessions = []
    for participant in sorted(directory.iterdir()):
        if participant.is_symlink() or not participant.is_dir():
            continue
        if len(sessions) >= MAX_SESSIONS:
            fail("session limit exceeded")
        try:
            valid_uuid(participant.name)
            registration = read_json(participant / "registration.json") if (participant / "registration.json").exists() else None
            if registration is not None and not isinstance(registration, dict):
                fail("invalid registration")
            reports = []
            names, warnings = report_files(participant)
            if len(names) > MAX_REPORTS_PER_SESSION:
                fail("report limit exceeded")
            for name in names:
                path = participant / name
                if path.is_symlink():
                    warnings.append(f"ignored symlinked {name}")
                    continue
                if not path.exists():
                    continue
                try:
                    contents = read_bytes(path)
                    contents.decode("utf-8")
                except (OSError, ValueError, UnicodeError):
                    warnings.append(f"ignored unreadable {name}")
                    continue
                if not contents.strip():
                    warnings.append(f"ignored empty {name}")
                    continue
                digest = hashlib.sha256(contents).hexdigest()
                receipt_key = hashlib.sha256((name + ':' + digest).encode()).hexdigest()
                receipt = participant / "reviewed" / f"{receipt_key}.json"
                try:
                    saved = read_json(receipt) if receipt.exists() and not receipt.is_symlink() else None
                    is_reviewed = isinstance(saved, dict) and saved.get("report") == name and saved.get("sha256") == digest
                except (OSError, ValueError, json.JSONDecodeError):
                    is_reviewed = False
                    warnings.append(f"ignored invalid review receipt for {name}")
                reports.append({"name": name, "sha256": digest, "reviewed": is_reviewed})
            sessions.append({"id": participant.name, "registered": registration is not None,
                             "reports": reports, "warnings": warnings,
                             "complete": registration is not None and any(r["name"] == "report.md" for r in reports),
                             "pendingReview": any(not r["reviewed"] for r in reports)})
        except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as error:
            sessions.append({"id": participant.name, "error": type(error).__name__, "complete": False})
    registered = sum(bool(s.get("registered")) for s in sessions)
    complete = sum(bool(s.get("complete")) for s in sessions)
    pending = sum(bool(s.get("pendingReview")) for s in sessions)
    return {"batch": args.batch, "expected": args.expected, "registered": registered,
            "complete": complete, "missingRegistrations": max(0, args.expected - registered),
            "missingReports": max(0, args.expected - complete), "pendingReviewSessions": pending,
            "allComplete": complete > 0 and complete >= args.expected and registered >= args.expected and pending == 0
            and all(s.get("complete") for s in sessions), "sessions": sessions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path.home() / ".claude/logs/performance-reviews"))
    parser.add_argument("--batch", default="sessions")
    sub = parser.add_subparsers(dest="action", required=True)
    registration = sub.add_parser("register")
    registration.add_argument("--id")
    registration.add_argument("--workspace", required=True)
    registration.add_argument("--branch", required=True)
    registration.add_argument("--task", required=True)
    for action in ("snapshot", "publish", "reviewed"):
        item = sub.add_parser(action)
        item.add_argument("--id", required=True)
        if action == "publish":
            item.add_argument("--file", required=True)
            item.add_argument("--addendum", action="store_true")
        elif action == "reviewed":
            item.add_argument("--report", default="report.md")
            item.add_argument("--sha256", required=True)
    state = sub.add_parser("status")
    state.add_argument("--expected", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.action == "status" and args.expected < 0:
            fail("expected must be nonnegative")
        result = globals()[args.action](args)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, FileExistsError) as error:
        print(json.dumps({"error": str(error)[:200]}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
