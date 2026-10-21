#!/usr/bin/env python3
"""Cooperative, machine-wide admission for local heavy commands, simulators and dev stacks.

At most HEAVY_SLOTS owners hold a heavy lease at once, one lease per owner, and at most
MAX_BOOTED_SIMULATORS simulator is claimed, leased or booted machine-wide. A priority owner named
by `prioritize` is admitted ahead of every other new heavy request; it passes no cap, but the CPU,
load and memory guard still apply to it, and nothing already running is stopped. Local Docker dev stacks take a
separate stack lease capped by max_stacks(). `status` and `watchdog` flag hot processes, unleased
simulators, idle simulator claims and extra test browsers; `reclaim-sim` shuts down and unclaims an
unleased simulator only when its claim owner has no live session. This does not impose an OS CPU or
memory limit: every participating session must acquire before a heavy command, simulator boot
or stack start.
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
HEAVY_SLOTS = 3  # the one ceiling: how many owners may hold a heavy lease at once
LEASE_SLOT = "lease.json"
SECOND_SLOT = "priority-lease.json"  # file name kept so leases already on disk stay valid
THIRD_SLOT = "lease-3.json"
SLOTS = (LEASE_SLOT, SECOND_SLOT, THIRD_SLOT)
assert len(SLOTS) == HEAVY_SLOTS
MIN_IDLE_PERCENT = 20  # admission defers while current CPU idle is below this (top, second sample)
LOAD_PER_CORE = 1.5  # high load is above this many 1-minute load units per logical core
# High load defers only while CPU idle is also below this. macOS counts threads blocked in
# uninterruptible I/O, Spotlight and mobileassetd bursts and zombies in the load average, so it
# read 118 to 208 on 8 cores at 51 to 66% idle and refused every heavy step for hours. Idle is the
# direct saturation measure; 35 sits 15 points above MIN_IDLE_PERCENT, so load catches a
# machine heading for saturation, and is under the 51% idle seen with no saturation at all.
LOAD_CONFIRM_IDLE_PERCENT = 35
DEFER_PRESSURE_LEVEL = 2  # admission defers at this kern.memorystatus_vm_pressure_level or worse (1 normal, 2 warning, 4 critical)
MAX_COMPRESSED_SHARE = 0.4  # fallback only, when the sysctl is unavailable: defer above this share of RAM held by the compressor
PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}
MAX_BOOTED_SIMULATORS = 1  # the one simulator ceiling: claimed, leased or booted, all sessions
HOT_CPU_PERCENT = 200  # watchdog: ps %cpu at or above this...
HOT_MIN_SECONDS = 120  # ...on a process at least this old (younger is boot or startup)
MAX_TEST_BROWSERS = 1  # watchdog: more Chrome for Testing instances than this is flagged
STACK_GIB_EACH = 3  # Docker VM memory budgeted per local dev stack
STACK_CEILING = 2  # most local dev stacks at once, whatever the VM size
STACK_IDLE_MIN = 60  # a stack with no live session and no change for this long is idle
STACK_START_GRACE_MIN = 15  # a stack lease counts this long before its containers appear
PRIORITY_DEFAULT_MIN = 60
PRIORITY_MAX_MIN = 180
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z")
TOKEN = re.compile(r"[0-9a-f]{64}\Z")
SIMCTL_FIXTURE = None
PRESSURE_FIXTURE = None
HOST_FIXTURE = None
DEVICE_PATH = re.compile(r"/CoreSimulator/Devices/([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})/")
TEST_BROWSER = "/Contents/MacOS/Google Chrome for Testing"
SUPABASE_LABEL = "com.supabase.cli.project"
PORT_REGISTRY = Path(__file__).with_name("port-registry.sh")
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


def read_state(root, allow_old=False, slot=LEASE_SLOT):
    fd = secure_open(root / slot)
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


def write_state(root, lease, slot=LEASE_SLOT):
    # A partial write after process failure remains visibly corrupt and blocks admission.
    fd = secure_open(root / slot)
    try:
        data = (json.dumps(lease, sort_keys=True, separators=(",", ":")) + "\n").encode() if lease else b""
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
    finally:
        os.close(fd)


def find_lease(root, match):
    """Return (slot, lease) for the first held lease that `match` accepts, else (None, None)."""
    for slot in SLOTS:
        lease = read_state(root, slot=slot)
        if lease and match(lease):
            return slot, lease
    return None, None


def read_priority(root):
    """Return the live priority record, or None. Call under `locked`; clears an expired record."""
    fd = secure_open(root / "priority.json")
    try:
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    if not raw:
        return None
    try:
        record = json.loads(raw.decode("utf-8"))
        if (len(raw) > 4096 or not isinstance(record, dict) or set(record) != {"owner", "expires"} or
                not isinstance(record["owner"], str) or not OWNER.fullmatch(record["owner"]) or
                type(record["expires"]) not in (int, float) or not math.isfinite(record["expires"]) or
                record["expires"] > time.time() + PRIORITY_MAX_MIN * 60 + 60):
            raise ValueError("invalid priority record")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise GateError("priority record is corrupt; run prioritize --clear") from exc
    if record["expires"] <= time.time():
        write_priority(root, None)
        return None
    return record


def write_priority(root, record):
    fd = secure_open(root / "priority.json")
    try:
        data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode() if record else b""
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
    finally:
        os.close(fd)


def priority_text(record):
    until = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(record["expires"]))
    return "%s until %s (%d min left)" % (record["owner"], until, max(1, math.ceil((record["expires"] - time.time()) / 60)))


def prioritize(root, owner, minutes, clear):
    if clear:
        if owner is not None:
            raise GateError("prioritize --clear takes no --owner")
        with locked(root):
            write_priority(root, None)
        return "priority cleared"
    if owner is None or not OWNER.fullmatch(owner):
        raise GateError("prioritize needs --owner with a safe label, or --clear")
    if not math.isfinite(minutes) or minutes <= 0 or minutes > PRIORITY_MAX_MIN:
        raise GateError("--minutes must be above 0 and at most %d" % PRIORITY_MAX_MIN)
    record = {"owner": owner, "expires": time.time() + minutes * 60}
    with locked(root):
        write_priority(root, record)
    return "priority set: " + priority_text(record)


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
            if not isinstance(fixture, dict) or not {"load", "cores"} <= set(fixture) <= {"load", "cores", "memory_level", "idle"}:
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


def compressed_share():
    """Fraction of physical RAM the memory compressor occupies (vm_stat over hw.memsize). Fallback signal only."""
    result = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=3, check=False)
    if result.returncode:
        raise ValueError("vm_stat failed")
    page = re.search(r"page size of (\d+) bytes", result.stdout)
    pages = re.search(r"Pages occupied by compressor:\s+(\d+)", result.stdout)
    total = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3, check=False)
    if not page or not pages or total.returncode or int(total.stdout) <= 0:
        raise ValueError("vm_stat output changed")
    return int(pages.group(1)) * int(page.group(1)) / int(total.stdout)


def memory_pressure_level():
    """(level, source): the OS's own pressure level, 1 normal, 2 warning, 4 critical.

    Source is "sysctl" (kern.memorystatus_vm_pressure_level) or "compressed-share" (fallback when the
    sysctl is unavailable: warning when the compressor holds more than MAX_COMPRESSED_SHARE of RAM).
    """
    try:
        if PRESSURE_FIXTURE is not None:
            value = json.loads(PRESSURE_FIXTURE.read_text()).get("memory_level", 1)
            if value not in PRESSURE_NAMES:
                raise ValueError("invalid pressure level")
            return value, "sysctl"
        try:
            result = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                                    capture_output=True, text=True, timeout=3, check=False)
            if not result.returncode and int(result.stdout) in PRESSURE_NAMES:
                return int(result.stdout), "sysctl"
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return (DEFER_PRESSURE_LEVEL if compressed_share() > MAX_COMPRESSED_SHARE else 1), "compressed-share"
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError) as exc:
        raise GateError("memory probe failed; defer heavy work") from exc


def cpu_idle_percent():
    """Current CPU idle %: the second `top -l 2 -n 0 -s 1` sample (the first covers no interval)."""
    try:
        if PRESSURE_FIXTURE is not None:
            value = json.loads(PRESSURE_FIXTURE.read_text()).get("idle", 100)
        else:
            result = subprocess.run(["/usr/bin/top", "-l", "2", "-n", "0", "-s", "1"],
                                    capture_output=True, text=True, timeout=10, check=False)
            samples = re.findall(r"CPU usage:.*?([\d.]+)% idle", result.stdout)
            if result.returncode or len(samples) < 2:
                raise ValueError("top output changed")
            value = float(samples[-1])
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("invalid idle percent")
        return value
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise GateError("CPU probe failed; defer heavy work") from exc


def host_reading():
    """(verdict line, defer reason or None) from current CPU idle, 1-minute load confirmed by idle, and OS memory pressure."""
    idle = cpu_idle_percent()
    load, cores = simulator_pressure()
    level, source = memory_pressure_level()
    reasons = []
    if idle < MIN_IDLE_PERCENT:
        reasons.append("CPU idle %.0f%% is below %d%%" % (idle, MIN_IDLE_PERCENT))
    if load > LOAD_PER_CORE * cores and idle < LOAD_CONFIRM_IDLE_PERCENT:
        reasons.append("1-minute load %.1f exceeds %s x %s logical cores with CPU idle %.0f%% below %d%%" % (
            load, LOAD_PER_CORE, cores, idle, LOAD_CONFIRM_IDLE_PERCENT))
    if level >= DEFER_PRESSURE_LEVEL:
        reasons.append("memory pressure is %s (level %d, via %s), at or above warning" % (PRESSURE_NAMES[level], level, source))
    line = "%s idle=%.0f%% (min %d) load=%.1f (max %.1f on %d cores, counts below %d%% idle) memory-pressure=%s (level %d, defer at %d)" % (
        "DEFER" if reasons else "GO", idle, MIN_IDLE_PERCENT, load, LOAD_PER_CORE * cores, cores,
        LOAD_CONFIRM_IDLE_PERCENT, PRESSURE_NAMES[level], level, DEFER_PRESSURE_LEVEL)
    return line, "; ".join(reasons) or None


def admission_guard(what):
    """Refuse new heavy work while the host is choked. Applies to every owner, priority included."""
    _, reason = host_reading()
    if reason:
        raise Busy("%s deferred: %s; run serially or retry at the next task boundary" % (what, reason))


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
    admission_guard("simulator claim")
    with locked(root):
        legacy = legacy_claims()
        if udid in legacy:
            raise Busy("simulator %s has an unverified legacy claim by %s; inspect and migrate it" % (udid, legacy[udid]))
        claims = read_claims(root)
        if udid in claims and claims[udid] != owner:
            raise Busy("simulator %s is claimed by %s" % (udid, claims[udid]))
        states = [read_state(root, slot=name) for name in SLOTS]
        enforce_simulator_cap(root, states, observe_booted(), udid)
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


RECLAIM_COMMAND = "python3 ~/.claude/bin/local-capacity.py reclaim-sim --udid %s"


def owner_session_live(owner):
    """True when a live Claude session works in a directory named for the owner label.

    Claim owners are worktree basenames (native-slot.sh session()), and port-registry.sh `sessions` is the one
    detector of live sessions, so a path component equal to the label counts as live. A label that matches
    nothing is the only thing read as ended; a probe failure raises and is never read as ended."""
    return any(owner in Path(cwd).parts for cwd in live_session_cwds())


def reclaim_hint(root, states, udid):
    """The exact reclaim command when the simulator's claim owner has ended and no lease holds it, else ''."""
    try:
        owner = read_claims(root).get(udid)
        if owner is None or udid in legacy_claims() or any(lease and lease["simulator"] == udid for lease in states):
            return ""
        if owner_session_live(owner):
            return ""
    except GateError:
        return ""
    return "claim owner %s has no live session; reclaim it: %s" % (owner, RECLAIM_COMMAND % udid)


def reclaim_sim(root, udid):
    """Shut down and unclaim a simulator whose claim owner has no live session and which holds no lease."""
    if not UDID.fullmatch(udid):
        raise GateError("reclaim-sim needs a UUID simulator ID")
    udid = udid.upper()
    with locked(root):
        if udid in legacy_claims():
            raise GateError("simulator %s has an unverified legacy claim; inspect and migrate it" % udid)
        owner = read_claims(root).get(udid)
        if owner is None:
            raise GateError("simulator %s has no claim, so no ended owner can be proven; inspect it" % udid)
        for slot in SLOTS:
            lease = read_state(root, slot=slot)
            if lease and lease["simulator"] == udid:
                raise GateError("simulator %s holds a lease (%s); reclaim only acts on an unleased simulator" %
                                (udid, holder_text(lease)))
        if owner_session_live(owner):
            raise GateError("simulator %s is claimed by %s, which has a live session; only that owner runs "
                            "xcrun simctl shutdown %s then release-sim" % (udid, owner, udid))
        if probe_devices().get(udid) is not None:
            shutdown_owned(udid)
        claims = read_claims(root)
        claims.pop(udid, None)
        write_claims(root, claims)
        telemetry(root, event="reclaim-sim", udid=udid, owner=owner, result=0)
        return "simulator %s shut down and claim by %s dropped; the simulator is not deleted" % (udid, owner)


def simulators_in_use(root, states, booted):
    """Map every simulator that counts against MAX_BOOTED_SIMULATORS to a holder description."""
    owners = {}
    for udid, owner in legacy_claims().items():
        owners[udid] = "legacy claim by %s" % owner
    for udid, owner in read_claims(root).items():
        owners[udid] = "claimed by %s" % owner
    for lease in states:
        if lease and lease["simulator"]:
            owners[lease["simulator"]] = "leased by holder=%s pid=%s" % (lease["owner"], lease["pid"])
    for udid in booted:
        owners.setdefault(udid, "booted with no claim or lease")
    return {udid: "%s (%s, %s)" % (udid, text, "booted" if udid in booted else "shut down")
            for udid, text in owners.items()}


def enforce_simulator_cap(root, states, booted, target):
    others = {udid: text for udid, text in simulators_in_use(root, states, booted).items() if udid != target}
    if len(others) >= MAX_BOOTED_SIMULATORS:
        hints = [hint for hint in (reclaim_hint(root, states, udid) for udid in sorted(others)) if hint]
        raise Busy("simulator deferred: %d of %d machine-wide simulator(s) already in use: %s; stage ONE simulator "
                   "and switch its backend between runs, or wait until that holder shuts down and runs release-sim%s"
                   % (len(others), MAX_BOOTED_SIMULATORS, "; ".join(sorted(others.values())),
                      "".join("; " + hint for hint in hints)))


def parse_elapsed(value):
    """Seconds from ps etime: [[dd-]hh:]mm:ss."""
    days, _, clock = value.rpartition("-")
    parts = [int(part) for part in clock.split(":")]
    if not 2 <= len(parts) <= 3 or (days and not days.isdigit()):
        raise ValueError("invalid elapsed time")
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds + (int(days) * 86400 if days else 0)


def host_fixture(key, default):
    if HOST_FIXTURE is None:
        return None
    data = json.loads(HOST_FIXTURE.read_text())
    if not isinstance(data, dict):
        raise ValueError("invalid host fixture")
    return data.get(key, default)


def process_table():
    """Rows of (pid, ppid, cpu percent, age seconds, command) for every process."""
    try:
        text = host_fixture("ps", "")
        if text is None:
            result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,pcpu=,etime=,command="],
                                    capture_output=True, text=True, timeout=5, check=False)
            if result.returncode:
                raise ValueError("ps failed")
            text = result.stdout
        rows = []
        for line in text.splitlines():
            fields = line.split(None, 4)
            if len(fields) < 5:
                continue
            rows.append((int(fields[0]), int(fields[1]), float(fields[2]), parse_elapsed(fields[3]), fields[4]))
        return rows
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError) as exc:
        raise GateError("process probe failed") from exc


def process_name(command):
    """Display name; app bundle and runtime paths contain spaces, so argv splitting alone misnames them."""
    bundle = re.search(r"\.app/Contents/MacOS/(.+?)(?= -|$)", command)
    if bundle:
        return bundle.group(1)
    rest = command.rsplit("RuntimeRoot/", 1)[-1]
    return os.path.basename(rest.split()[0]) if rest.split() else "?"


def simulator_of(rows):
    """Map pid -> simulator UDID for each launchd_sim and every process below it."""
    parents = {pid: ppid for pid, ppid, _, _, _ in rows}
    roots = {}
    for pid, _, _, _, command in rows:
        match = DEVICE_PATH.search(command)
        if match and os.path.basename(command.split()[0]) == "launchd_sim":
            roots[pid] = match.group(1).upper()
    owned = {}
    for pid in parents:
        current, depth = pid, 0
        while current not in roots and current in parents and depth < 64 and parents[current] != current:
            current, depth = parents[current], depth + 1
        if current in roots:
            owned[pid] = roots[current]
    return owned


def watchdog_lines(root):
    """Read-only runaway report. Names each owner; never stops anything."""
    states = [read_state(root, slot=name) for name in SLOTS]
    claims = read_claims(root)
    leased = {lease["simulator"]: lease["owner"] for lease in states if lease and lease["simulator"]}
    try:
        rows = process_table()
    except GateError:
        return ["watchdog: process probe failed (unknown); inspect with ps before starting heavy work"]
    lines = []
    sims = simulator_of(rows)
    for pid, _, cpu, age, command in rows:
        if cpu < HOT_CPU_PERCENT or age < HOT_MIN_SECONDS:
            continue
        line = "watchdog: HOT pid=%d %s cpu=%.0f%% age=%ds" % (pid, process_name(command), cpu, age)
        udid = sims.get(pid)
        if udid:
            owner = leased.get(udid) or claims.get(udid) or "nobody"
            hint = "" if udid in leased else reclaim_hint(root, states, udid)
            if hint:
                line += " simulator=%s owner=%s; %s" % (udid, owner, hint)
            else:
                line += (" simulator=%s owner=%s; that owner runs xcrun simctl shutdown %s then release-sim; "
                         "another session never stops it" % (udid, owner, udid))
        else:
            line += "; if your session started it, stop it"
        lines.append(line)
    for udid in sorted(set(sims.values())):
        if udid not in leased:
            hint = reclaim_hint(root, states, udid)
            lines.append("watchdog: simulator %s is booted with no lease (claim owner=%s); %s" % (
                udid, claims.get(udid, "nobody"),
                hint or "that owner runs xcrun simctl shutdown %s then release-sim" % udid))
    for udid, owner in sorted(claims.items()):
        if udid not in leased and udid not in sims.values():
            hint = reclaim_hint(root, states, udid)
            lines.append("watchdog: simulator claim %s owner=%s is idle and holds the simulator cap; %s" % (
                udid, owner,
                hint or "release it: local-capacity.py release-sim --udid %s --owner %s" % (udid, owner)))
    browsers = sorted(pid for pid, _, _, _, command in rows if TEST_BROWSER in command and "Helper" not in command)
    if len(browsers) > MAX_TEST_BROWSERS:
        lines.append("watchdog: %d Chrome for Testing instances (pids %s), above %d; each session closes the one it "
                     "launched when its batch ends" % (len(browsers), ",".join(map(str, browsers)), MAX_TEST_BROWSERS))
    return lines or ["watchdog: clear"]


def docker_json_lines(args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise ValueError("docker %s failed" % args[0])
    return result.stdout


def observe_stacks():
    """Running local dev stacks keyed by workspace: {workspace: {"project", "supabase"}}."""
    try:
        fixture = host_fixture("stacks", [])
        if fixture is None:
            text = docker_json_lines(["ps", "--format", "{{json .Labels}}"])
            fixture = []
            for line in text.splitlines():
                labels = dict(item.split("=", 1) for item in json.loads(line).split(",") if "=" in item)
                project = labels.get(SUPABASE_LABEL) or labels.get("com.docker.compose.project")
                if not project:
                    continue
                workdir = (labels.get("com.supabase.cli.workdir") or
                           labels.get("com.docker.compose.project.working_dir") or project)
                fixture.append({"project": project, "workdir": workdir, "supabase": SUPABASE_LABEL in labels})
        stacks = {}
        for item in fixture:
            stacks[item["workdir"]] = {"project": item["project"], "supabase": bool(item["supabase"])}
        return stacks
    except FileNotFoundError:
        return {}  # no docker CLI: no stack can run
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise GateError("docker stack probe failed; inspect docker before starting a stack") from exc


def docker_vm_gib():
    try:
        value = host_fixture("vm_gib", None)
        if value is None and HOST_FIXTURE is None:
            value = int(docker_json_lines(["info", "--format", "{{.MemTotal}}"]).strip()) / 2 ** 30
        return float(value) if value is not None else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None


def max_stacks(vm_gib):
    """floor(Docker VM GiB / STACK_GIB_EACH), at least 1, at most STACK_CEILING; unknown VM -> 1."""
    if vm_gib is None or not math.isfinite(vm_gib):
        return 1
    return max(1, min(STACK_CEILING, int(vm_gib // STACK_GIB_EACH)))


def live_session_cwds():
    """Working directories of live Claude sessions, from port-registry.sh (the one detector)."""
    try:
        fixture = host_fixture("sessions", [])
        if fixture is not None:
            return list(fixture)
        result = subprocess.run(["bash", str(PORT_REGISTRY), "sessions"], capture_output=True, text=True,
                                timeout=10, check=False)
        if result.returncode:
            raise ValueError("session probe failed")
        return [line for line in result.stdout.splitlines() if line]
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise GateError("live-session probe failed; idle stacks are unknown") from exc


def workspace_activity(workspace):
    """Newest of the last commit, the index and every changed file in the workspace (epoch seconds)."""
    fixture = host_fixture("activity", {})
    if fixture is not None:
        return fixture.get(workspace, 0)
    path = Path(workspace)
    if not path.is_dir():
        return 0
    times = []
    def git(*args):
        result = subprocess.run(["git", "-C", workspace, *args], capture_output=True, text=True, timeout=5, check=False)
        return result.stdout if result.returncode == 0 else ""
    try:
        commit = git("log", "-1", "--format=%ct").strip()
        if commit.isdigit():
            times.append(int(commit))
        index = git("rev-parse", "--path-format=absolute", "--git-path", "index").strip()
        changed = [line[3:].split(" -> ")[-1] for line in git("status", "--porcelain").splitlines()[:200]]
        for item in ([index] if index else []) + [str(path / name) for name in changed]:
            try:
                times.append(os.stat(item).st_mtime)
            except OSError:
                pass
    except subprocess.TimeoutExpired:
        return time.time()  # unknown activity is treated as active, never as idle
    return max(times, default=0)


def idle_stacks(stacks, exclude=None):
    """Supabase stacks with no live session in their workspace and no change for STACK_IDLE_MIN."""
    cwds = live_session_cwds()
    idle = []
    for workspace, stack in sorted(stacks.items()):
        if workspace == exclude or not stack["supabase"]:
            continue
        if any(cwd == workspace or cwd.startswith(workspace.rstrip("/") + "/") for cwd in cwds):
            continue
        quiet = (time.time() - workspace_activity(workspace)) / 60
        if quiet >= STACK_IDLE_MIN:
            idle.append((workspace, stack["project"], int(quiet)))
    return idle


def stop_stack(project):
    """Do what `supabase stop` does without --no-backup: stop and prune containers and network, keep volumes."""
    label = "label=%s=%s" % (SUPABASE_LABEL, project)
    ids = docker_json_lines(["ps", "-q", "--filter", label]).split()
    if ids:
        docker_json_lines(["stop", *ids])
    docker_json_lines(["container", "prune", "-f", "--filter", label])
    docker_json_lines(["network", "prune", "-f", "--filter", label])


def stack_sweep(apply, exclude=None):
    lines = []
    for workspace, project, quiet in idle_stacks(observe_stacks(), exclude):
        if apply:
            try:
                stop_stack(project)
                lines.append("stopped idle stack %s (%s): no live session, quiet %d min; data volumes kept" % (project, workspace, quiet))
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                lines.append("idle stack %s (%s) did not stop: %s" % (project, workspace, exc))
        else:
            lines.append("idle stack %s (%s): no live session, quiet %d min; stop it: local-capacity.py stack-sweep --apply"
                         % (project, workspace, quiet))
    return lines


def read_stack_leases(root):
    fd = secure_open(root / "stacks.json")
    try:
        raw = os.read(fd, 16385)
    finally:
        os.close(fd)
    if not raw:
        return {}
    try:
        leases = json.loads(raw)
        if len(raw) > 16384 or not isinstance(leases, dict):
            raise ValueError("invalid stack leases")
        for workspace, lease in leases.items():
            if (not Path(workspace).is_absolute() or not isinstance(lease, dict) or set(lease) != {"owner", "created"} or
                    not isinstance(lease["owner"], str) or not OWNER.fullmatch(lease["owner"]) or
                    type(lease["created"]) not in (int, float)):
                raise ValueError("invalid stack lease")
        return leases
    except (ValueError, UnicodeError, TypeError) as exc:
        raise GateError("stack leases are corrupt; inspect them") from exc


def write_stack_leases(root, leases):
    fd = secure_open(root / "stacks.json")
    try:
        data = (json.dumps(leases, sort_keys=True) + "\n").encode()
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
    finally:
        os.close(fd)


def stacks_in_use(leases, running):
    """Running stacks plus leases still inside their start grace, keyed by workspace."""
    fresh = time.time() - STACK_START_GRACE_MIN * 60
    use = {workspace: "%s running" % stack["project"] for workspace, stack in running.items()}
    for workspace, lease in leases.items():
        if workspace not in use and lease["created"] >= fresh:
            use[workspace] = "leased by %s, starting" % lease["owner"]
    return use


def stack_acquire(root, owner, workspace):
    if not OWNER.fullmatch(owner):
        raise GateError("owner must be 1-80 safe label characters")
    if not Path(workspace).is_absolute() or ".." in Path(workspace).parts:
        raise GateError("--workspace must be an absolute path without '..'")
    swept = stack_sweep(True, exclude=workspace)
    running = observe_stacks()
    if workspace not in running:
        admission_guard("stack start")
    with locked(root):
        running = observe_stacks()
        leases = read_stack_leases(root)
        if workspace not in running:
            others = {ws: text for ws, text in stacks_in_use(leases, running).items() if ws != workspace}
            ceiling = max_stacks(docker_vm_gib())
            if len(others) >= ceiling:
                raise Busy("stack start deferred: %d of %d local dev stacks in use: %s; stop one you own, or retry when "
                           "one stops" % (len(others), ceiling, "; ".join("%s (%s)" % item for item in sorted(others.items()))))
        leases = {ws: lease for ws, lease in leases.items() if ws in stacks_in_use(leases, running)}
        leases[workspace] = {"owner": owner, "created": time.time()}
        write_stack_leases(root, leases)
    return swept


def stack_release(root, workspace):
    with locked(root):
        leases = read_stack_leases(root)
        leases.pop(workspace, None)
        write_stack_leases(root, leases)


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


def other_owner_holds_first_slot(root, owner):
    """True when a different owner's run holds the first heavy lease, so a held legacy lock is theirs."""
    with locked(root):
        lease = read_state(root)
        return bool(lease and lease["owner"] != owner)


@contextmanager
def legacy_bridge(root, owner=None):
    """Hold every bridged lock; yield (fds, skipped).

    Only an owner, while another owner's run holds the first heavy lease, may pass a held
    lock. `skipped` then tells acquire to use a slot other than the first.
    """
    fds = []
    skipped = False
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
                if owner is not None and other_owner_holds_first_slot(root, owner):
                    fds.remove(fd)
                    os.close(fd)
                    skipped = True
                    continue
                raise Busy("legacy native lock is held; defer this heavy job") from exc
            except OSError as exc:
                raise GateError("legacy native lock cannot be checked: %s" % exc) from exc
        yield tuple(fds), skipped
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


def acquire(root, owner, pid, simulator, child_pending=False, allow_bridge=False, second_slot_only=False):
    if not OWNER.fullmatch(owner):
        raise GateError("owner must be 1-80 safe label characters")
    if pid <= 0:
        raise GateError("pid must be positive")
    if simulator is not None and not UDID.fullmatch(simulator):
        raise GateError("simulator must be a UDID")
    if bridge_paths(root) and not allow_bridge:
        raise GateError("legacy lock bridge is active; use foreground run so its lock remains held")
    admission_guard("heavy work")  # sampled before the lock: top takes about 2 seconds
    with locked(root):
        if (legacy_slot_dir() / "slot.d").exists():
            raise Busy("legacy native slot exists; inspect its holder before migration")
        priority = read_priority(root)
        is_priority = bool(priority and priority["owner"] == owner)
        if priority and not is_priority:
            raise Busy("heavy work deferred: priority owner is %s; retry after it finishes" % priority_text(priority))
        states = [read_state(root, slot=name) for name in SLOTS]
        held = [lease for lease in states if lease]
        mine = next((lease for lease in held if lease["owner"] == owner), None)
        if mine:
            raise Busy("heavy slot busy: %s; one owner holds at most one lease" % holder_text(mine))
        if second_slot_only and not states[0]:
            raise Busy("the run holding the legacy native lock finished while this one waited; retry once")
        free = [name for name, lease in zip(SLOTS, states) if not lease and not (second_slot_only and name == LEASE_SLOT)]
        if not free:
            raise Busy("all %d heavy slots busy: %s; keep editing or inspect and release an exact token" %
                       (HEAVY_SLOTS, "; ".join(holder_text(lease) for lease in held)))
        slot = free[0]
        start = pid_start(pid)
        if not start:
            raise GateError("owner PID is not running or cannot be identified")
        other_sims = {lease["simulator"] for lease in held if lease["simulator"]}
        observed = observe_booted()
        if simulator:
            target = simulator.upper()
            if target in other_sims:
                raise Busy("simulator %s is in use by another heavy lease" % target)
            enforce_simulator_cap(root, held, observed, target)
            claims = read_claims(root)
            legacy = legacy_claims()
            if target in legacy:
                raise Busy("simulator %s has an unverified legacy claim by %s" % (target, legacy[target]))
            if target in claims and claims[target] != owner:
                raise Busy("simulator %s is claimed by %s" % (target, claims[target]))
        booted = [udid for udid in observed if udid not in other_sims]
        if booted:
            hints = ["%s: %s" % (udid, hint) for udid, hint in ((udid, reclaim_hint(root, held, udid)) for udid in booted) if hint]
            raise Busy("heavy slot unavailable: booted simulators %s; inspect their owner and shut them down before acquiring%s"
                       % (",".join(booted), "".join("; " + hint for hint in hints)))
        lease = {"owner": owner, "pid": pid, "pid_start": start,
                 "simulator": simulator.upper() if simulator else None,
                 "token": secrets.token_hex(32), "created": time.time(),
                 "child": {"state": "pending"} if child_pending else None, "stages": []}
        write_state(root, lease, slot)
        return lease["token"]


def release(root, token, orphan_inspected=False):
    if not TOKEN.fullmatch(token):
        raise GateError("invalid release token")
    with locked(root):
        slot, lease = find_lease(root, lambda item: secrets.compare_digest(item["token"], token))
        if not lease:
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
        other_sims = {item["simulator"] for item in (read_state(root, slot=name) for name in SLOTS if name != slot)
                      if item and item["simulator"]}
        booted = [udid for udid in observe_booted() if udid not in other_sims]
        if lease["simulator"] in booted:
            raise Busy("owned simulator %s is still booted; shut it down, then release this token" % lease["simulator"])
        if booted:
            raise Busy("booted simulators %s remain; inspect them before releasing" % ",".join(booted))
        write_state(root, None, slot)


def require_groups_stopped(root, token):
    with locked(root):
        _, lease = find_lease(root, lambda item: secrets.compare_digest(item["token"], token))
        if not lease:
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
        slot, lease = find_lease(root, lambda item: secrets.compare_digest(item["token"], token))
        if not lease or lease["child"] != {"state": "pending"}:
            raise GateError("command lease changed before its child could be recorded")
        lease["child"] = {"pid": pid, "pgid": pid, "pid_start": start}
        write_state(root, lease, slot)


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


def owns_group(lease):
    return isinstance(lease["child"], dict) and lease["child"].get("pgid") == os.getpgrp()


def record_stage(root, pid, start):
    if not start:
        raise GateError("stage identity could not be recorded")
    with locked(root):
        slot, lease = find_lease(root, owns_group)
        if not lease:
            raise GateError("stage must run inside an owned foreground run")
        if pid_start(lease["pid"]) != lease["pid_start"]:
            raise GateError("stage owner is no longer live")
        if len(lease["stages"]) >= 64:
            raise GateError("stage receipt limit reached; finish existing stages before starting another")
        stage = {"pid": pid, "pgid": pid, "pid_start": start}
        lease["stages"].append(stage)
        write_state(root, lease, slot)
        return stage


def finish_stage(root, stage):
    if group_alive(stage["pgid"]):
        return
    with locked(root):
        slot, lease = find_lease(root, lambda item: stage in item["stages"])
        if lease:
            lease["stages"].remove(stage)
            write_state(root, lease, slot)


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
    with locked(root):
        slot, lease = find_lease(root, owns_group)
        if not lease:
            raise GateError("stage must run inside an owned foreground run")
    if bridge_paths(root) and not legacy_fds and slot == LEASE_SLOT:
        raise GateError("stage would lose the legacy lock bridge")
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


def _run_command(root, owner, simulator, command, max_seconds, metrics, legacy_fds, second_slot_only=False):
    if not command:
        raise GateError("run requires a foreground command after --")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise GateError("run requires a foreground command after --")
    token = acquire(root, owner, os.getpid(), simulator, child_pending=True, allow_bridge=True,
                    second_slot_only=second_slot_only)
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
        with legacy_bridge(root, owner) as (legacy_fds, bridge_skipped):
            code = _run_command(root, owner, simulator, command, max_seconds, metrics, legacy_fds, bridge_skipped)
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


def print_stacks(leases):
    try:
        running = observe_stacks()
    except GateError as exc:
        print("dev stacks: %s" % exc)
        return
    vm_gib = docker_vm_gib()
    use = stacks_in_use(leases, running)
    print("dev stacks: %d of %d (Docker VM %s GiB)%s" % (
        len(use), max_stacks(vm_gib), "unknown" if vm_gib is None else "%.1f" % vm_gib,
        (": " + "; ".join("%s (%s)" % item for item in sorted(use.items()))) if use else ""))
    try:
        for line in stack_sweep(False):
            print(line)
    except GateError as exc:
        print("dev stacks: %s" % exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="capacity state directory (tests or deliberate override)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("cpu", help="one read-only line: GO or DEFER from CPU idle, load (when idle confirms it) and OS memory pressure; exit 75 on DEFER")
    sub.add_parser("watchdog", help="read-only runaway report: hot processes, unleased simulators, extra test browsers, idle stacks")
    stack_parser = sub.add_parser("stack-acquire", help="lease a local Docker dev stack before starting it")
    stack_parser.add_argument("--owner", required=True)
    stack_parser.add_argument("--workspace", required=True)
    unstack_parser = sub.add_parser("stack-release", help="drop this workspace's stack lease after stopping it")
    unstack_parser.add_argument("--workspace", required=True)
    sweep_parser = sub.add_parser("stack-sweep", help="list idle stacks; --apply stops them, keeping data volumes")
    sweep_parser.add_argument("--apply", action="store_true")
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
    reclaim_parser = sub.add_parser("reclaim-sim", help="shut down and unclaim an unleased simulator whose claim owner has no live session")
    reclaim_parser.add_argument("--udid", required=True)
    sub.add_parser("migrate")
    priority_parser = sub.add_parser("prioritize")
    priority_parser.add_argument("--owner")
    priority_parser.add_argument("--minutes", type=float, default=PRIORITY_DEFAULT_MIN)
    priority_parser.add_argument("--clear", action="store_true")
    args = parser.parse_args(argv)
    root = root_path(args.root or (os.environ.get("LOCAL_CAPACITY_RUN_ROOT") if args.action == "stage" else None))
    global SIMCTL_FIXTURE, PRESSURE_FIXTURE, HOST_FIXTURE
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
        if args.root and os.environ.get("LOCAL_CAPACITY_HOST_JSON"):
            candidate = Path(os.environ["LOCAL_CAPACITY_HOST_JSON"]).resolve()
            if candidate.parent != root.resolve():
                raise GateError("host fixture must be inside the explicit test root")
            HOST_FIXTURE = candidate
        if args.action == "status":
            with locked(root):
                states = [read_state(root, slot=name) for name in SLOTS]
                priority = read_priority(root)
                booted = observe_booted()
                owned = {lease["simulator"] for lease in states if lease and lease["simulator"]}
                free_text = "unavailable (booted simulator without a lease)" if set(booted) - owned else "free"
                for number, lease in enumerate(states, 1):
                    print("heavy slot %d of %d: %s" % (number, HEAVY_SLOTS, holder_text(lease) if lease else free_text))
                if priority:
                    print("priority: " + priority_text(priority))
                print("booted simulators: " + (", ".join(booted) if booted else "none"))
                for udid, owner in sorted(read_claims(root).items()):
                    print("simulator claim: %s owner=%s" % (udid, owner))
                for udid, owner in sorted(legacy_claims().items()):
                    print("legacy simulator claim (inspect): %s owner=%s" % (udid, owner))
                if (legacy_slot_dir() / "slot.d").exists():
                    print("legacy native slot exists; inspect its holder")
                in_use = simulators_in_use(root, states, booted)
                print("simulators in use: %d of %d%s" % (len(in_use), MAX_BOOTED_SIMULATORS,
                                                         (": " + "; ".join(sorted(in_use.values()))) if in_use else ""))
                for line in watchdog_lines(root):
                    print(line)
                stack_leases = read_stack_leases(root)
            print_stacks(stack_leases)
        elif args.action == "cpu":
            line, reason = host_reading()
            print(line + ("" if reason is None else "; " + reason))
            return BUSY if reason else 0
        elif args.action == "watchdog":
            with locked(root):
                lines = [line for line in watchdog_lines(root) if line != "watchdog: clear"]
            try:
                lines += stack_sweep(False)
            except GateError as exc:
                lines.append("watchdog: %s" % exc)
            for line in lines:
                print(line)
        elif args.action == "stack-acquire":
            for line in stack_acquire(root, args.owner, args.workspace):
                print(line)
            print("stack lease held for %s" % args.workspace)
        elif args.action == "stack-release":
            stack_release(root, args.workspace)
            print("stack lease released")
        elif args.action == "stack-sweep":
            for line in stack_sweep(args.apply) or ["no idle stacks"]:
                print(line)
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
        elif args.action == "reclaim-sim":
            print(reclaim_sim(root, args.udid))
        elif args.action == "migrate":
            print(migrate(root))
        elif args.action == "prioritize":
            print(prioritize(root, args.owner, args.minutes, args.clear))
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
