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
TIMEOUT = 124
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z")
TOKEN = re.compile(r"[0-9a-f]{64}\Z")
SIMCTL_FIXTURE = None
PRESSURE_FIXTURE = None
GRANT_LAUNCHER = (
    "import os,sys; fd=int(sys.argv[1]); grant=os.read(fd,3); os.close(fd); "
    "[os.set_inheritable(int(x),True) for x in sys.argv[2].split(',') if x]; "
    "sys.exit(125) if grant != b'go\\n' else os.execvp(sys.argv[3],sys.argv[3:])"
)


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


def read_state(root, allow_old=False):
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
        old_fields = {"owner", "pid", "pid_start", "simulator", "token", "created", "child"}
        if isinstance(lease, dict) and set(lease) == old_fields and not allow_old:
            raise GateError("old capacity lease schema; run migrate before admission")
        if not isinstance(lease, dict) or set(lease) not in ((old_fields, old_fields | {"stages"}) if allow_old else (old_fields | {"stages"},)):
            raise ValueError("unexpected fields")
        if "stages" not in lease:
            lease["stages"] = []
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
        if not isinstance(lease["stages"], list) or len(lease["stages"]) > 64:
            raise ValueError("invalid stage receipts")
        for stage in lease["stages"]:
            if (not isinstance(stage, dict) or set(stage) != {"pid", "pgid", "pid_start"} or
                type(stage["pid"]) is not int or stage["pid"] <= 0 or
                type(stage["pgid"]) is not int or stage["pgid"] != stage["pid"] or
                not isinstance(stage["pid_start"], str) or not stage["pid_start"]):
                raise ValueError("invalid stage identity")
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


def migrate(root):
    with locked(root):
        lease = read_state(root, allow_old=True)
        if lease is None:
            return "no lease to migrate"
        fd = secure_open(root / "lease.json")
        try:
            raw = os.read(fd, 16385)
        finally:
            os.close(fd)
        old_shape = "stages" not in json.loads(raw)
        if not old_shape:
            return "lease already current"
        write_state(root, lease)
        return "lease migrated; owner and child receipt retained"


def pid_start(pid):
    try:
        result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def probe_devices():
    try:
        if SIMCTL_FIXTURE is not None:
            data = json.loads(SIMCTL_FIXTURE.read_text())
        else:
            result = subprocess.run(["/usr/bin/xcrun", "simctl", "list", "devices", "--json"],
                                    capture_output=True, text=True, timeout=5, check=False)
            if result.returncode:
                raise ValueError("simctl failed")
            data = json.loads(result.stdout)
        devices = data["devices"]
        if not isinstance(devices, dict):
            raise ValueError("unexpected devices")
        states = {}
        for group in devices.values():
            if not isinstance(group, list):
                raise ValueError("unexpected device group")
            for device in group:
                if not isinstance(device, dict):
                    raise ValueError("unexpected device")
                udid = device.get("udid")
                state = device.get("state")
                if not isinstance(udid, str) or not UDID.fullmatch(udid) or not isinstance(state, str):
                    raise ValueError("invalid simulator device")
                states[udid.upper()] = state
        return states
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise GateError("simulator probe failed; inspect simctl before retrying") from exc


def observe_booted():
    # The legacy name is retained for callers; Booting/Shutting Down also
    # consume capacity and block release.
    return sorted(udid for udid, state in probe_devices().items() if state != "Shutdown")


def shutdown_owned(udid):
    state = probe_devices().get(udid)
    if state is None:
        raise GateError("owned simulator %s is absent from simctl; inspect it before release" % udid)
    if state != "Shutdown":
        try:
            result = subprocess.run(["/usr/bin/xcrun", "simctl", "shutdown", udid],
                                    capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError("shutdown of owned simulator %s did not finish within 30 seconds" % udid) from exc
        if result.returncode:
            raise GateError("shutdown of owned simulator %s failed; inspect it" % udid)
    if probe_devices().get(udid) != "Shutdown":
        raise GateError("owned simulator %s is not confirmed Shutdown; inspect it" % udid)


def simulator_pressure():
    try:
        if PRESSURE_FIXTURE is not None:
            fixture = json.loads(PRESSURE_FIXTURE.read_text())
            if not isinstance(fixture, dict) or set(fixture) != {"load", "cores"}:
                raise ValueError("invalid pressure fixture")
            load, cores = fixture["load"], fixture["cores"]
        else:
            cores = os.cpu_count()
            load = os.getloadavg()[0]
        if type(cores) is not int or cores <= 0 or type(load) not in (int, float) or not math.isfinite(load):
            raise ValueError("missing load or core count")
        return load, cores
    except (OSError, ValueError) as exc:
        raise GateError("host load probe failed; defer simulator work") from exc


def legacy_slot_dir():
    return Path(os.environ.get("LOCAL_CAPACITY_LEGACY_SLOT_DIR", str(Path.home() / ".claude/native-slot"))).expanduser()


def legacy_claims():
    path = legacy_slot_dir() / "sims.tsv"
    if not path.exists():
        return {}
    if path.is_symlink():
        raise GateError("legacy simulator ledger is a symlink; inspect it")
    try:
        result = {}
        for line in path.read_text().splitlines():
            fields = line.split("\t")
            if len(fields) < 2 or not UDID.fullmatch(fields[0]) or not OWNER.fullmatch(fields[1]):
                raise ValueError("invalid legacy simulator row")
            result[fields[0].upper()] = fields[1]
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        raise GateError("legacy simulator ledger is unreadable; inspect it") from exc


def read_claims(root):
    fd = secure_open(root / "claims.json")
    try:
        raw = os.read(fd, 16385)
    finally:
        os.close(fd)
    if len(raw) > 16384:
        raise GateError("simulator claims are oversized; inspect them")
    if not raw:
        return {}
    try:
        claims = json.loads(raw)
        if not isinstance(claims, dict):
            raise ValueError("invalid claims")
        for udid, owner in claims.items():
            if not UDID.fullmatch(udid) or not isinstance(owner, str) or not OWNER.fullmatch(owner):
                raise ValueError("invalid claim")
        return claims
    except (ValueError, UnicodeError, TypeError) as exc:
        raise GateError("simulator claims are corrupt; inspect them") from exc


def write_claims(root, claims):
    fd = secure_open(root / "claims.json")
    try:
        data = (json.dumps(claims, sort_keys=True) + "\n").encode()
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
    finally:
        os.close(fd)


def claim_sim(root, udid, owner):
    if not UDID.fullmatch(udid) or not OWNER.fullmatch(owner):
        raise GateError("claim-sim needs a UUID simulator ID and a safe owner label")
    udid = udid.upper()
    with locked(root):
        legacy = legacy_claims()
        if udid in legacy:
            raise Busy("simulator %s has an unverified legacy claim by %s; inspect and migrate it" % (udid, legacy[udid]))
        claims = read_claims(root)
        if udid in claims and claims[udid] != owner:
            raise Busy("simulator %s is claimed by %s" % (udid, claims[udid]))
        claims[udid] = owner
        write_claims(root, claims)


def release_sim(root, udid, owner):
    if not UDID.fullmatch(udid) or not OWNER.fullmatch(owner):
        raise GateError("release-sim needs a UUID simulator ID and a safe owner label")
    udid = udid.upper()
    with locked(root):
        if udid in legacy_claims():
            raise Busy("simulator %s has an unverified legacy claim; inspect and migrate it" % udid)
        claims = read_claims(root)
        if claims.get(udid) != owner:
            raise GateError("simulator claim owner does not match")
        if udid in observe_booted():
            raise Busy("simulator %s is still booted; shut it down before releasing its claim" % udid)
        del claims[udid]
        write_claims(root, claims)


def telemetry(root, **fields):
    secure_root(root)
    path = root / "telemetry.jsonl"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise GateError("capacity telemetry cannot be opened") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or path.is_symlink():
            raise GateError("capacity telemetry file is unsafe")
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(dict(time=time.time(), **fields), sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)


def bridge_paths(root):
    secure_root(root)
    path = root / "bridge.json"
    paths = []
    if path.exists():
        if path.is_symlink():
            raise GateError("capacity bridge config is a symlink; inspect it")
        try:
            config = json.loads(path.read_text())
            if not isinstance(config, dict) or set(config) != {"lockPaths"} or not isinstance(config["lockPaths"], list):
                raise ValueError("invalid bridge config")
            paths.extend(config["lockPaths"])
        except (OSError, ValueError, UnicodeError) as exc:
            raise GateError("capacity bridge config is invalid; inspect it") from exc
    if os.environ.get("LOCAL_CAPACITY_LEGACY_LOCK"):
        paths.append(os.environ["LOCAL_CAPACITY_LEGACY_LOCK"])
    for item in paths:
        if not isinstance(item, str) or not Path(item).is_absolute() or ".." in Path(item).parts:
            raise GateError("legacy lock paths must be absolute and contain no '..'")
    return sorted(set(paths))


@contextmanager
def legacy_bridge(root):
    fds = []
    try:
        for name in bridge_paths(root):
            flags = os.O_RDONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(name, flags, 0o600)
                fds.append(fd)
                if not stat.S_ISREG(os.fstat(fd).st_mode) or Path(name).is_symlink():
                    raise GateError("legacy lock is not a regular file: %s" % name)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy("legacy native lock is held; defer this heavy job") from exc
            except OSError as exc:
                raise GateError("legacy native lock cannot be checked: %s" % exc) from exc
        yield tuple(fds)
    finally:
        for fd in reversed(fds):
            # Inherited children keep the same flock after supervisor exit.
            os.close(fd)


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


def acquire(root, owner, pid, simulator, child_pending=False, allow_bridge=False):
    if not OWNER.fullmatch(owner):
        raise GateError("owner must be 1-80 safe label characters")
    if pid <= 0:
        raise GateError("pid must be positive")
    if simulator is not None and not UDID.fullmatch(simulator):
        raise GateError("simulator must be a UDID")
    if bridge_paths(root) and not allow_bridge:
        raise GateError("legacy lock bridge is active; use foreground run so its lock remains held")
    with locked(root):
        if (legacy_slot_dir() / "slot.d").exists():
            raise Busy("legacy native slot exists; inspect its holder before migration")
        lease = read_state(root)
        if lease:
            raise Busy("heavy slot busy: %s; keep editing or inspect and release its exact token" % holder_text(lease))
        start = pid_start(pid)
        if not start:
            raise GateError("owner PID is not running or cannot be identified")
        load, cores = simulator_pressure()
        if load > 2 * cores:
            raise Busy("heavy work deferred: 1-minute load %.1f exceeds 2 x %s logical cores; retry at the next task boundary" % (load, cores))
        if simulator:
            target = simulator.upper()
            claims = read_claims(root)
            legacy = legacy_claims()
            if target in legacy:
                raise Busy("simulator %s has an unverified legacy claim by %s" % (target, legacy[target]))
            if target in claims and claims[target] != owner:
                raise Busy("simulator %s is claimed by %s" % (target, claims[target]))
        booted = observe_booted()
        if booted:
            raise Busy("heavy slot unavailable: booted simulators %s; inspect their owner and shut them down before acquiring" % ",".join(booted))
        lease = {"owner": owner, "pid": pid, "pid_start": start,
                 "simulator": simulator.upper() if simulator else None,
                 "token": secrets.token_hex(32), "created": time.time(),
                 "child": {"state": "pending"} if child_pending else None, "stages": []}
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
        for stage in lease["stages"]:
            if group_alive(stage["pgid"]):
                raise Busy("recorded stage group %s is still running; inspect it before releasing" % stage["pgid"])
        booted = observe_booted()
        if lease["simulator"] in booted:
            raise Busy("owned simulator %s is still booted; shut it down, then release this token" % lease["simulator"])
        if booted:
            raise Busy("booted simulators %s remain; inspect them before releasing" % ",".join(booted))
        write_state(root, None)


def require_groups_stopped(root, token):
    with locked(root):
        lease = read_state(root)
        if not lease or not secrets.compare_digest(lease["token"], token):
            raise GateError("command lease changed before simulator cleanup")
        child = lease["child"]
        if child is None or "state" in child:
            raise GateError("command launch is unresolved; simulator cleanup needs inspection")
        if group_alive(child["pgid"]):
            raise Busy("command group %s still runs; simulator cleanup deferred" % child["pgid"])
        for stage in lease["stages"]:
            if group_alive(stage["pgid"]):
                raise Busy("stage group %s still runs; simulator cleanup deferred" % stage["pgid"])


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


def launch_granted(command, read_fd, legacy_fds=(), env=None):
    return subprocess.Popen([sys.executable, "-c", GRANT_LAUNCHER, str(read_fd),
                             ",".join(str(fd) for fd in legacy_fds), *command],
                            pass_fds=(read_fd, *legacy_fds), start_new_session=True, env=env)


def record_stage(root, pid, start):
    if not start:
        raise GateError("stage identity could not be recorded")
    with locked(root):
        lease = read_state(root)
        if not lease or not isinstance(lease["child"], dict) or lease["child"].get("pgid") != os.getpgrp():
            raise GateError("stage must run inside an owned foreground run")
        if pid_start(lease["pid"]) != lease["pid_start"]:
            raise GateError("stage owner is no longer live")
        if len(lease["stages"]) >= 64:
            raise GateError("stage receipt limit reached; finish existing stages before starting another")
        stage = {"pid": pid, "pgid": pid, "pid_start": start}
        lease["stages"].append(stage)
        write_state(root, lease)
        return stage


def finish_stage(root, stage):
    if group_alive(stage["pgid"]):
        return
    with locked(root):
        lease = read_state(root)
        if lease and stage in lease["stages"]:
            lease["stages"].remove(stage)
            write_state(root, lease)


def stage_command(root, seconds, command):
    if command and command[0] == "--":
        command = command[1:]
    if not command or seconds <= 0:
        raise GateError("stage needs positive --timeout-seconds and a foreground command")
    if os.environ.get("LOCAL_CAPACITY_RUN_ROOT") != str(root):
        raise GateError("stage must run inside local-capacity run")
    try:
        legacy_fds = tuple(int(item) for item in os.environ.get("LOCAL_CAPACITY_LEGACY_FDS", "").split(",") if item)
        for fd in legacy_fds:
            os.fstat(fd)
    except (ValueError, OSError) as exc:
        raise GateError("stage legacy lock descriptors are unavailable") from exc
    if bridge_paths(root) and not legacy_fds:
        raise GateError("stage would lose the legacy lock bridge")
    with locked(root):
        lease = read_state(root)
        if not lease or not isinstance(lease["child"], dict) or lease["child"].get("pgid") != os.getpgrp():
            raise GateError("stage must run inside an owned foreground run")
    interrupted = [None]
    old_handlers = {}
    def stop(sig, _frame):
        if interrupted[0] is None:
            interrupted[0] = sig
    child = None
    read_fd, write_fd = os.pipe()
    stage = None
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, stop)
        child = launch_granted(command, read_fd, legacy_fds)
        os.close(read_fd)
        read_fd = -1
        if interrupted[0] is None:
            stage = record_stage(root, child.pid, pid_start(child.pid))
        if interrupted[0] is not None:
            terminate_group(child)
            return 128 + interrupted[0]
        os.write(write_fd, b"go\n")
        deadline = time.monotonic() + seconds
        while True:
            if interrupted[0] is not None:
                terminate_group(child)
                return 128 + interrupted[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_group(child)
                print("stage timed out after %s seconds; stop this run and inspect its lease" % seconds, file=sys.stderr)
                return TIMEOUT
            try:
                code = child.wait(timeout=min(0.2, remaining))
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                continue
    except (GateError, OSError) as exc:
        if child is not None:
            terminate_group(child)
        print("stage failed safely: %s" % exc, file=sys.stderr)
        return BUSY
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        os.close(write_fd)
        if stage is not None:
            try:
                finish_stage(root, stage)
            except GateError:
                pass  # A retained receipt blocks release until inspected.
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def _run_command(root, owner, simulator, command, max_seconds, metrics, legacy_fds):
    if not command:
        raise GateError("run requires a foreground command after --")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise GateError("run requires a foreground command after --")
    token = acquire(root, owner, os.getpid(), simulator, child_pending=True, allow_bridge=True)
    metrics["token"] = token
    metrics["start"] = time.monotonic()
    metrics["wait"] = metrics["start"] - metrics["requested"]
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
            child_env = os.environ.copy()
            child_env["LOCAL_CAPACITY_RUN_ROOT"] = str(root)
            child_env["LOCAL_CAPACITY_LEGACY_FDS"] = ",".join(str(fd) for fd in legacy_fds)
            child = launch_granted(command, read_fd, legacy_fds, child_env)
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
        deadline = metrics["start"] + max_seconds
        while True:
            if interrupted[0] is not None:
                terminate_group(child)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_group(child)
                print("run exceeded %s seconds; lease retained for inspection; token=%s" % (max_seconds, token), file=sys.stderr)
                return TIMEOUT
            try:
                code = child.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if interrupted[0] is not None:
            print("command interrupted; lease retained for inspection; token=%s" % token, file=sys.stderr)
            return 128 + interrupted[0]
        if group_alive(child.pid):
            print("command group still running; lease retained for inspection; token=%s" % token, file=sys.stderr)
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


def run_command(root, owner, simulator, command, max_seconds=3600):
    metrics = {"requested": time.monotonic()}
    try:
        with legacy_bridge(root) as legacy_fds:
            code = _run_command(root, owner, simulator, command, max_seconds, metrics, legacy_fds)
            if "token" in metrics:
                try:
                    if simulator:
                        require_groups_stopped(root, metrics["token"])
                        shutdown_owned(simulator.upper())
                    release(root, metrics["token"])
                except GateError as exc:
                    print("lease retained: %s; token=%s" % (exc, metrics["token"]), file=sys.stderr)
                    code = BUSY
        try:
            telemetry(root, event="result", owner=owner, result=code,
                      wait_seconds=round(metrics.get("wait", 0), 3),
                      hold_seconds=round(time.monotonic() - metrics["start"], 3) if "start" in metrics else 0)
        except GateError:
            print("capacity telemetry could not be written", file=sys.stderr)
        return code
    except Busy as exc:
        try:
            telemetry(root, event="deferred", owner=owner, result=BUSY,
                      wait_seconds=round(time.monotonic() - metrics["requested"], 3), reason=str(exc)[:120])
        except GateError:
            pass
        raise


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
    run_parser.add_argument("--max-min", type=float, default=60)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--timeout-seconds", type=float, required=True)
    stage_parser.add_argument("command", nargs=argparse.REMAINDER)
    claim_parser = sub.add_parser("claim-sim")
    claim_parser.add_argument("--udid", required=True)
    claim_parser.add_argument("--owner", required=True)
    unclaim_parser = sub.add_parser("release-sim")
    unclaim_parser.add_argument("--udid", required=True)
    unclaim_parser.add_argument("--owner", required=True)
    sub.add_parser("migrate")
    args = parser.parse_args(argv)
    root = root_path(args.root or (os.environ.get("LOCAL_CAPACITY_RUN_ROOT") if args.action == "stage" else None))
    global SIMCTL_FIXTURE, PRESSURE_FIXTURE
    try:
        if args.root and os.environ.get("LOCAL_CAPACITY_SIMCTL_JSON"):
            candidate = Path(os.environ["LOCAL_CAPACITY_SIMCTL_JSON"]).resolve()
            if candidate.parent != root.resolve():
                raise GateError("simctl fixture must be inside the explicit test root")
            SIMCTL_FIXTURE = candidate
        if args.root and os.environ.get("LOCAL_CAPACITY_PRESSURE_JSON"):
            candidate = Path(os.environ["LOCAL_CAPACITY_PRESSURE_JSON"]).resolve()
            if candidate.parent != root.resolve():
                raise GateError("pressure fixture must be inside the explicit test root")
            PRESSURE_FIXTURE = candidate
        if args.action == "status":
            with locked(root):
                lease = read_state(root)
                booted = observe_booted()
                print(holder_text(lease) if lease else ("heavy slot unavailable" if booted else "heavy slot free"))
                print("booted simulators: " + (", ".join(booted) if booted else "none"))
                for udid, owner in sorted(read_claims(root).items()):
                    print("simulator claim: %s owner=%s" % (udid, owner))
                for udid, owner in sorted(legacy_claims().items()):
                    print("legacy simulator claim (inspect): %s owner=%s" % (udid, owner))
                if (legacy_slot_dir() / "slot.d").exists():
                    print("legacy native slot exists; inspect its holder")
        elif args.action == "acquire":
            print(acquire(root, args.owner, args.pid, args.simulator))
        elif args.action == "release":
            release(root, args.token, args.orphan_inspected)
            print("heavy slot released")
        elif args.action == "run":
            if not math.isfinite(args.max_min) or args.max_min <= 0:
                raise GateError("--max-min must be a positive number")
            return run_command(root, args.owner, args.simulator, args.command, args.max_min * 60)
        elif args.action == "stage":
            if not math.isfinite(args.timeout_seconds):
                raise GateError("--timeout-seconds must be finite")
            return stage_command(root, args.timeout_seconds, args.command)
        elif args.action == "claim-sim":
            claim_sim(root, args.udid, args.owner)
            print("simulator claimed")
        elif args.action == "migrate":
            print(migrate(root))
        else:
            release_sim(root, args.udid, args.owner)
            print("simulator claim released")
        return 0
    except Busy as exc:
        print(str(exc), file=sys.stderr)
        return BUSY
    except GateError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
