#!/usr/bin/env python3
"""Cooperative, machine-wide admission for local heavy commands and simulators.

The default is one heavy lease. This does not impose an OS CPU or memory limit:
every participating session must acquire before a heavy command or simulator boot.
"""

import argparse
import fcntl
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


BUSY = 75
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z")
TOKEN = re.compile(r"[0-9a-f]{64}\Z")


class GateError(Exception):
    pass


class Busy(GateError):
    pass


def root_path(value):
    if value is None:
        return Path.home().resolve() / ".claude/state/local-capacity"
    return Path(value).expanduser()


def secure_root(root):
    if not root.is_absolute() or ".." in root.parts:
        raise GateError("capacity state directory must be an absolute canonical path without '..'")
    def check_components():
        part = Path(root.anchor)
        for component in root.parts[1:]:
            part = part / component
            if part.is_symlink():
                raise GateError("capacity state path contains a symlink: %s" % part)
    check_components()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_components()
    if not root.is_dir():
        raise GateError("capacity state directory is unsafe")
    os.chmod(root, 0o700)


def secure_open(path):
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except OSError as exc:
        raise GateError("capacity state file is unsafe or inaccessible: %s" % exc) from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode) or path.is_symlink():
        os.close(fd)
        raise GateError("capacity state file is not a regular file")
    os.fchmod(fd, 0o600)
    return fd


@contextmanager
def locked(root):
    secure_root(root)
    fd = secure_open(root / "lock")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Busy("capacity state is being checked by another session; retry once shortly") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_state(root):
    fd = secure_open(root / "lease.json")
    try:
        raw = os.read(fd, 16385)
    finally:
        os.close(fd)
    if len(raw) > 16384:
        raise GateError("capacity lease is oversized; inspect it before retrying")
    if not raw:
        return None
    try:
        lease = json.loads(raw.decode("utf-8"))
        if not isinstance(lease, dict) or set(lease) != {"owner", "pid", "pid_start", "simulator", "token", "created", "child"}:
            raise ValueError("unexpected fields")
        if not isinstance(lease["owner"], str) or not OWNER.fullmatch(lease["owner"]) or type(lease["pid"]) is not int or lease["pid"] <= 0:
            raise ValueError("invalid owner or pid")
        if not isinstance(lease["pid_start"], str) or not lease["pid_start"] or len(lease["pid_start"]) > 80:
            raise ValueError("invalid pid identity")
        if lease["simulator"] is not None and (not isinstance(lease["simulator"], str) or not UDID.fullmatch(lease["simulator"])):
            raise ValueError("invalid simulator")
        if not isinstance(lease["token"], str) or not TOKEN.fullmatch(lease["token"]) or type(lease["created"]) not in (int, float) or not math.isfinite(lease["created"]):
            raise ValueError("invalid token or time")
        child = lease["child"]
        if child is not None:
            if not isinstance(child, dict) or set(child) not in ({"state"}, {"pid", "pgid", "pid_start"}):
                raise ValueError("invalid child receipt")
            if "state" in child:
                if child["state"] != "pending":
                    raise ValueError("invalid child state")
            elif (type(child["pid"]) is not int or child["pid"] <= 0 or
                  type(child["pgid"]) is not int or child["pgid"] != child["pid"] or
                  not isinstance(child["pid_start"], str) or not child["pid_start"] or len(child["pid_start"]) > 80):
                raise ValueError("invalid child identity")
        return lease
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise GateError("capacity lease is corrupt; inspect it before retrying") from exc


def write_state(root, lease):
    # A partial write after process failure remains visibly corrupt and blocks admission.
    fd = secure_open(root / "lease.json")
    try:
        data = (json.dumps(lease, sort_keys=True, separators=(",", ":")) + "\n").encode() if lease else b""
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
    finally:
        os.close(fd)


def pid_start(pid):
    try:
        result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def observe_booted():
    try:
        result = subprocess.run(["/usr/bin/xcrun", "simctl", "list", "devices", "booted", "--json"],
                                capture_output=True, text=True, timeout=5, check=False)
        if result.returncode:
            raise ValueError("simctl failed")
        data = json.loads(result.stdout)
        devices = data["devices"]
        if not isinstance(devices, dict):
            raise ValueError("unexpected devices")
        booted = set()
        for group in devices.values():
            if not isinstance(group, list):
                raise ValueError("unexpected device group")
            for device in group:
                if not isinstance(device, dict):
                    raise ValueError("unexpected device")
                if device.get("state") == "Booted":
                    udid = device.get("udid")
                    if not isinstance(udid, str) or not UDID.fullmatch(udid):
                        raise ValueError("invalid booted device id")
                    booted.add(udid.upper())
        return sorted(booted)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise GateError("simulator probe failed; inspect simctl before retrying") from exc


def holder_text(lease):
    current = pid_start(lease["pid"])
    condition = "live" if current == lease["pid_start"] else "orphan / PID reused; inspect processes and simulator"
    sim = " simulator=" + lease["simulator"] if lease["simulator"] else ""
    child = lease["child"]
    if child is None:
        command = ""
    elif "state" in child:
        command = " command=launch unresolved"
    else:
        command = " command_group=%s (%s)" % (child["pgid"], "running" if group_alive(child["pgid"]) else "exited")
    return "holder=%s pid=%s %s%s%s" % (lease["owner"], lease["pid"], condition, sim, command)


def acquire(root, owner, pid, simulator, child_pending=False):
    if not OWNER.fullmatch(owner):
        raise GateError("owner must be 1-80 safe label characters")
    if pid <= 0:
        raise GateError("pid must be positive")
    if simulator is not None and not UDID.fullmatch(simulator):
        raise GateError("simulator must be a UDID")
    with locked(root):
        lease = read_state(root)
        if lease:
            raise Busy("heavy slot busy: %s; keep editing or inspect and release its exact token" % holder_text(lease))
        start = pid_start(pid)
        if not start:
            raise GateError("owner PID is not running or cannot be identified")
        booted = observe_booted()
        if booted:
            raise Busy("heavy slot unavailable: booted simulators %s; inspect their owner and shut them down before acquiring" % ",".join(booted))
        lease = {"owner": owner, "pid": pid, "pid_start": start,
                 "simulator": simulator.upper() if simulator else None,
                 "token": secrets.token_hex(32), "created": time.time(),
                 "child": {"state": "pending"} if child_pending else None}
        write_state(root, lease)
        return lease["token"]


def release(root, token, orphan_inspected=False):
    if not TOKEN.fullmatch(token):
        raise GateError("invalid release token")
    with locked(root):
        lease = read_state(root)
        if not lease or not secrets.compare_digest(lease["token"], token):
            raise GateError("release token does not match the current lease")
        child = lease["child"]
        if child is not None:
            if "state" in child:
                if not orphan_inspected:
                    raise Busy("command launch is unresolved; inspect its owner, then use release --orphan-inspected after the owner exits")
                if pid_start(lease["pid"]) == lease["pid_start"]:
                    raise Busy("pending command owner is still live; wait for it to exit before inspected release")
            elif group_alive(child["pgid"]):
                raise Busy("recorded command group %s is still running; inspect it before releasing" % child["pgid"])
        booted = observe_booted()
        if lease["simulator"] in booted:
            raise Busy("owned simulator %s is still booted; shut it down, then release this token" % lease["simulator"])
        if booted:
            raise Busy("booted simulators %s remain; inspect them before releasing" % ",".join(booted))
        write_state(root, None)


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def record_child(root, token, pid, start):
    if not start:
        raise GateError("launched command identity could not be recorded")
    with locked(root):
        lease = read_state(root)
        if not lease or not secrets.compare_digest(lease["token"], token) or lease["child"] != {"state": "pending"}:
            raise GateError("command lease changed before its child could be recorded")
        lease["child"] = {"pid": pid, "pgid": pid, "pid_start": start}
        write_state(root, lease)


def terminate_group(child):
    # The child starts a new session, so its PID is its process group ID.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    if group_alive(child.pid):
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def run_command(root, owner, simulator, command):
    if not command:
        raise GateError("run requires a foreground command after --")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise GateError("run requires a foreground command after --")
    token = acquire(root, owner, os.getpid(), simulator, child_pending=True)
    child = None
    interrupted = [None]
    old_handlers = {}

    def stop(sig, _frame):
        if interrupted[0] is None:
            interrupted[0] = sig

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, stop)
        # The shell waits on a private pipe until its PID/start/PGID are durably
        # recorded. exec preserves the identity when the real command begins.
        read_fd, write_fd = os.pipe()
        try:
            child = subprocess.Popen(["/bin/sh", "-c", 'IFS= read -r ready <&%d && [ "$ready" = go ] && exec "$@"' % read_fd,
                                      "local-capacity", *command], pass_fds=(read_fd,),
                                     start_new_session=True)
        except OSError:
            os.close(write_fd)
            raise
        finally:
            os.close(read_fd)
        try:
            if interrupted[0] is None:
                record_child(root, token, child.pid, pid_start(child.pid))
            if interrupted[0] is not None:
                terminate_group(child)
                print("command interrupted; lease retained for inspection; token=%s" % token, file=sys.stderr)
                return 128 + interrupted[0]
            os.write(write_fd, b"go\n")
        except (GateError, OSError) as exc:
            terminate_group(child)
            print("command receipt failed; lease retained for inspection: %s; token=%s" % (exc, token), file=sys.stderr)
            return BUSY
        finally:
            os.close(write_fd)
        while True:
            if interrupted[0] is not None:
                terminate_group(child)
                break
            try:
                code = child.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if interrupted[0] is not None:
            print("command interrupted; lease retained for inspection; token=%s" % token, file=sys.stderr)
            return 128 + interrupted[0]
        if group_alive(child.pid):
            print("command group still running; lease retained for inspection; token=%s" % token, file=sys.stderr)
            return BUSY
        try:
            release(root, token)
        except GateError as exc:
            print("lease retained: %s; token=%s" % (exc, token), file=sys.stderr)
            return BUSY
        return code if code >= 0 else 128 - code
    except OSError as exc:
        if child is not None:
            terminate_group(child)
        print("command could not start; lease retained for inspection: %s; token=%s" % (exc, token), file=sys.stderr)
        return BUSY
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="capacity state directory (tests or deliberate override)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--owner", required=True)
    acquire_parser.add_argument("--pid", required=True, type=int)
    acquire_parser.add_argument("--simulator")
    release_parser = sub.add_parser("release")
    release_parser.add_argument("--token", required=True)
    release_parser.add_argument("--orphan-inspected", action="store_true",
                                help="release an unresolved launch only after inspecting a dead owner and simulators")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--owner", required=True)
    run_parser.add_argument("--simulator")
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    root = root_path(args.root)
    try:
        if args.action == "status":
            with locked(root):
                lease = read_state(root)
                booted = observe_booted()
                print(holder_text(lease) if lease else ("heavy slot unavailable" if booted else "heavy slot free"))
                print("booted simulators: " + (", ".join(booted) if booted else "none"))
        elif args.action == "acquire":
            print(acquire(root, args.owner, args.pid, args.simulator))
        elif args.action == "release":
            release(root, args.token, args.orphan_inspected)
            print("heavy slot released")
        else:
            return run_command(root, args.owner, args.simulator, args.command)
        return 0
    except Busy as exc:
        print(str(exc), file=sys.stderr)
        return BUSY
    except GateError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
