#!/usr/bin/env python3
"""Offline tests for the cooperative capacity lease."""

import contextlib
import importlib.util
import fcntl
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("local-capacity.py")
spec = importlib.util.spec_from_file_location("local_capacity", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SIM = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
SIM2 = "11111111-2222-3333-4444-555555555555"


def competing(root, queue, event, owner):
    with mock.patch.object(gate, "observe_booted", return_value=[]), \
         mock.patch.object(gate, "memory_pressure_level", return_value=(1, "sysctl")), \
         mock.patch.object(gate, "cpu_idle_percent", return_value=90):
        event.wait()
        for _ in range(200):
            try:
                queue.put(("ok", gate.acquire(Path(root), owner, os.getpid(), None)))
            except gate.Busy as exc:
                if "being checked by another session" in str(exc):
                    time.sleep(0.01)  # state-lock contention is a retry; only a full ceiling is the answer
                    continue
                queue.put(("busy", ""))
            return


def hold_lock(root, ready, done):
    gate.secure_root(Path(root))
    fd = gate.secure_open(Path(root) / "lock")
    fcntl.flock(fd, fcntl.LOCK_EX)
    ready.set()
    done.wait(10)
    os.close(fd)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        self.probe = mock.patch.object(gate, "observe_booted", return_value=[])
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.pressure = mock.patch.object(gate, "simulator_pressure", return_value=(0, 8))
        self.pressure.start()
        self.addCleanup(self.pressure.stop)
        self.memory = mock.patch.object(gate, "memory_pressure_level", return_value=(1, "sysctl"))
        self.memory.start()
        self.addCleanup(self.memory.stop)
        self.idle = mock.patch.object(gate, "cpu_idle_percent", return_value=90)
        self.idle.start()
        self.addCleanup(self.idle.stop)
        sessions = mock.patch.object(gate, "live_session_cwds", return_value=["/w/alpha", "/w/beta"])
        sessions.start()
        self.addCleanup(sessions.stop)

    def test_competing_processes_get_exactly_the_ceiling(self):
        ctx = multiprocessing.get_context("fork")
        queue, event = ctx.Queue(), ctx.Event()
        children = [ctx.Process(target=competing, args=(str(self.root), queue, event, "competitor%d" % number))
                    for number in range(gate.HEAVY_SLOTS + 1)]
        for child in children:
            child.start()
        event.set()
        answers = [queue.get(timeout=10) for _ in children]
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sorted(item[0] for item in answers), ["busy"] + ["ok"] * gate.HEAVY_SLOTS)
        admitted = {value for kind, value in answers if kind == "ok"}
        self.assertEqual({gate.read_state(self.root, slot=name)["token"] for name in gate.SLOTS}, admitted)

    def test_busy_lock_returns_without_waiting_for_holder(self):
        ctx = multiprocessing.get_context("fork")
        ready, done = ctx.Event(), ctx.Event()
        child = ctx.Process(target=hold_lock, args=(str(self.root), ready, done))
        child.start()
        self.assertTrue(ready.wait(5))
        start = time.monotonic()
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "mine", os.getpid(), None)
        self.assertLess(time.monotonic() - start, 1)
        done.set()
        child.join(5)
        self.assertEqual(child.exitcode, 0)

    def test_wrong_token_and_orphan_never_auto_clear(self):
        token = gate.acquire(self.root, "my session", os.getpid(), None)
        with self.assertRaises(gate.GateError):
            gate.release(self.root, "0" * 64)
        lease = gate.read_state(self.root)
        lease["pid"] = 999999
        gate.write_state(self.root, lease)
        self.assertIn("orphan", gate.holder_text(lease))
        other = gate.acquire(self.root, "another", os.getpid(), None)
        filler = gate.acquire(self.root, "filler", os.getpid(), None)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "fourth", os.getpid(), None)
        self.assertIn("orphan", str(refused.exception))
        gate.release(self.root, filler)
        gate.release(self.root, other)
        gate.release(self.root, token)

    def test_pid_reuse_is_visible(self):
        gate.acquire(self.root, "mine", os.getpid(), None)
        lease = gate.read_state(self.root)
        lease["pid_start"] = "old process start"
        gate.write_state(self.root, lease)
        self.assertIn("PID reused", gate.holder_text(lease))
        gate.acquire(self.root, "other", os.getpid(), None)
        gate.acquire(self.root, "filler", os.getpid(), None)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "fourth", os.getpid(), None)
        self.assertIn("PID reused", str(refused.exception))

    def test_foreign_booted_simulator_and_probe_failure_block(self):
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "mine", os.getpid(), SIM)
        with mock.patch.object(gate, "observe_booted", side_effect=gate.GateError("probe failed")):
            with self.assertRaises(gate.GateError):
                gate.acquire(self.root, "mine", os.getpid(), None)
        self.assertIsNone(gate.read_state(self.root))

    def test_load_preflight_blocks_every_heavy_command(self):
        with mock.patch.object(gate, "simulator_pressure", return_value=(17, 8)), \
             mock.patch.object(gate, "cpu_idle_percent", return_value=30):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "build", os.getpid(), None)
        self.assertIsNone(gate.read_state(self.root))

    def test_three_owners_are_admitted_and_a_fourth_is_refused_naming_all(self):
        first = gate.acquire(self.root, "alpha", os.getpid(), None)
        second = gate.acquire(self.root, "beta", os.getpid(), None)
        third = gate.acquire(self.root, "gamma", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root)["token"], first)
        self.assertEqual(gate.read_state(self.root, slot=gate.SECOND_SLOT)["token"], second)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["token"], third)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "delta", os.getpid(), None)
        for name in ("alpha", "beta", "gamma"):
            self.assertIn("holder=" + name, str(refused.exception))
        self.assertIn("all %d heavy slots busy" % gate.HEAVY_SLOTS, str(refused.exception))
        gate.release(self.root, first)
        fourth = gate.acquire(self.root, "delta", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root)["token"], fourth)
        for token in (second, third, fourth):
            gate.release(self.root, token)

    def test_ceiling_is_the_named_constant_and_matches_the_slot_files(self):
        self.assertEqual(gate.HEAVY_SLOTS, 3)
        self.assertEqual(len(gate.SLOTS), gate.HEAVY_SLOTS)

    def test_one_owner_holds_at_most_one_lease(self):
        gate.acquire(self.root, "alpha", os.getpid(), None)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "alpha", os.getpid(), None)
        self.assertIn("one owner holds at most one lease", str(refused.exception))
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))

    def test_load_guard_defers_the_second_admission_too(self):
        gate.acquire(self.root, "alpha", os.getpid(), None)
        with mock.patch.object(gate, "simulator_pressure", return_value=(17, 8)), \
             mock.patch.object(gate, "cpu_idle_percent", return_value=30):
            with self.assertRaises(gate.Busy) as refused:
                gate.acquire(self.root, "beta", os.getpid(), None)
        self.assertIn("exceeds 1.5 x 8 logical cores with CPU idle 30% below 35%", str(refused.exception))
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))

    def test_a_lease_already_in_the_second_file_still_counts_with_no_migration(self):
        gate.acquire(self.root, "alpha", os.getpid(), None)
        lease = gate.read_state(self.root)
        gate.write_state(self.root, lease, gate.SECOND_SLOT)
        gate.write_state(self.root, None)
        self.assertEqual((self.root / "priority-lease.json").read_text().count(lease["token"]), 1)
        beta = gate.acquire(self.root, "beta", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root)["token"], beta)
        gamma = gate.acquire(self.root, "gamma", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["token"], gamma)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "delta", os.getpid(), None)

    def test_each_simulator_is_owned_by_one_lease(self):
        gate.acquire(self.root, "alpha", os.getpid(), SIM)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "beta", os.getpid(), SIM)
            gate.acquire(self.root, "beta", os.getpid(), None)  # non-simulator heavy work runs beside it
        with mock.patch.object(gate, "observe_booted", return_value=[SIM, "99999999-2222-3333-4444-555555555555"]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "gamma", os.getpid(), None)

    def test_simulator_cap_is_one_named_constant(self):
        self.assertEqual(gate.MAX_BOOTED_SIMULATORS, 1)

    def test_second_simulator_refused_while_one_is_booted_naming_the_holder(self):
        gate.acquire(self.root, "alpha", os.getpid(), SIM)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy) as refused:
                gate.acquire(self.root, "beta", os.getpid(), SIM2)
            with self.assertRaises(gate.Busy):
                gate.claim_sim(self.root, SIM2, "beta")
        self.assertIn("holder=alpha", str(refused.exception))
        self.assertIn("1 of 1 machine-wide simulator", str(refused.exception))
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))
        self.assertEqual(gate.read_claims(self.root), {})

    def test_unleased_booted_simulator_blocks_a_new_simulator(self):
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy) as refused:
                gate.acquire(self.root, "beta", os.getpid(), SIM2)
        self.assertIn("booted with no claim or lease", str(refused.exception))

    def test_a_claim_holds_the_cap_even_for_its_own_owner(self):
        gate.claim_sim(self.root, SIM, "alpha")
        for owner in ("alpha", "beta"):
            with self.assertRaises(gate.Busy) as refused:
                gate.acquire(self.root, owner, os.getpid(), SIM2)
            self.assertIn("claimed by alpha", str(refused.exception))
            with self.assertRaises(gate.Busy):
                gate.claim_sim(self.root, SIM2, owner)
        token = gate.acquire(self.root, "alpha", os.getpid(), SIM)
        gate.release(self.root, token)
        gate.release_sim(self.root, SIM, "alpha")
        gate.claim_sim(self.root, SIM2, "beta")

    def test_memory_guard_defers_on_warning_and_critical(self):
        for level, name in ((2, "warning"), (4, "critical")):
            with mock.patch.object(gate, "memory_pressure_level", return_value=(level, "sysctl")):
                with self.assertRaises(gate.Busy) as refused:
                    gate.acquire(self.root, "build", os.getpid(), None)
            self.assertIn("memory pressure is %s (level %d, via sysctl)" % (name, level), str(refused.exception))
            self.assertIsNone(gate.read_state(self.root))

    def sysctl_run(self, level, vm_stat=None, memsize="25769803776\n"):
        """Fake subprocess.run: the pressure sysctl answers `level` (None = unavailable); vm_stat and hw.memsize feed the fallback."""
        real = subprocess.run

        def run(cmd, **kwargs):
            if cmd[0] not in ("/usr/sbin/sysctl", "/usr/bin/vm_stat"):
                return real(cmd, **kwargs)  # ps, simctl and the rest stay real
            if cmd[-1] == "kern.memorystatus_vm_pressure_level":
                if level is None:
                    return mock.Mock(returncode=1, stdout="")
                return mock.Mock(returncode=0, stdout="%s\n" % level)
            if cmd[-1] == "hw.memsize":
                return mock.Mock(returncode=0, stdout=memsize)
            return mock.Mock(returncode=0, stdout=vm_stat or "")
        return mock.patch.object(gate.subprocess, "run", side_effect=run)

    def test_pressure_level_is_read_from_the_os_sysctl(self):
        self.memory.stop()
        try:
            for level in (1, 2, 4):
                with self.sysctl_run(level):
                    self.assertEqual(gate.memory_pressure_level(), (level, "sysctl"))
        finally:
            self.memory.start()

    def test_eight_gib_compressed_with_normal_pressure_is_go(self):
        self.memory.stop()
        try:
            vm_stat = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                       "Pages occupied by compressor:           524288.\n")  # 8 GiB of 24 GiB RAM
            with self.sysctl_run(1, vm_stat):
                token = gate.acquire(self.root, "build", os.getpid(), None)
                self.assertTrue(gate.host_reading()[0].startswith("GO "))
            gate.release(self.root, token)
        finally:
            self.memory.start()

    def test_unavailable_sysctl_falls_back_to_the_compressed_share_of_ram(self):
        self.memory.stop()
        try:
            page = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages occupied by compressor:           %d.\n"
            with self.sysctl_run(None, page % 524288):  # 8 GiB of 24 GiB = 33%
                self.assertEqual(gate.memory_pressure_level(), (1, "compressed-share"))
            with self.sysctl_run(None, page % 655360):  # 10 GiB of 24 GiB = 42%
                self.assertEqual(gate.memory_pressure_level(), (2, "compressed-share"))
            with self.sysctl_run(None, "changed"):
                with self.assertRaises(gate.GateError):
                    gate.memory_pressure_level()
        finally:
            self.memory.start()

    def test_cpu_idle_is_read_from_the_second_top_sample(self):
        self.idle.stop()
        try:
            output = ("Processes: 700 total\nCPU usage: 2.0% user, 1.0% sys, 97.0% idle \n"
                      "Processes: 700 total\nCPU usage: 70.1% user, 19.9% sys, 10.0% idle \n")
            with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=output)) as top:
                self.assertEqual(gate.cpu_idle_percent(), 10.0)
            self.assertEqual(top.call_args.args[0], ["/usr/bin/top", "-l", "2", "-n", "0", "-s", "1"])
            with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="CPU usage: 1% idle")):
                with self.assertRaises(gate.GateError):
                    gate.cpu_idle_percent()
        finally:
            self.idle.start()

    def test_choked_cpu_defers_acquire_and_claim_with_the_reading(self):
        with mock.patch.object(gate, "cpu_idle_percent", return_value=12):
            for call in (lambda: gate.acquire(self.root, "build", os.getpid(), None),
                         lambda: gate.claim_sim(self.root, SIM, "build")):
                with self.assertRaises(gate.Busy) as refused:
                    call()
                self.assertIn("CPU idle 12% is below 20%", str(refused.exception))
        self.assertIsNone(gate.read_state(self.root))
        self.assertEqual(gate.read_claims(self.root), {})

    def test_load_guard_is_one_and_a_half_per_core(self):
        self.assertEqual(gate.LOAD_PER_CORE, 1.5)
        with mock.patch.object(gate, "cpu_idle_percent", return_value=30):
            with mock.patch.object(gate, "simulator_pressure", return_value=(12, 8)):
                gate.release(self.root, gate.acquire(self.root, "at-limit", os.getpid(), None))
            with mock.patch.object(gate, "simulator_pressure", return_value=(12.5, 8)):
                with self.assertRaises(gate.Busy):
                    gate.acquire(self.root, "over", os.getpid(), None)

    def test_high_load_with_idle_cpu_is_go_and_with_a_busy_cpu_is_defer(self):
        """Load 200 on 8 cores at 57% idle and normal memory is I/O-wait load, not saturation: GO."""
        self.assertEqual(gate.LOAD_CONFIRM_IDLE_PERCENT, 35)
        with mock.patch.object(gate, "simulator_pressure", return_value=(200, 8)):
            with mock.patch.object(gate, "cpu_idle_percent", return_value=57):
                line, reason = gate.host_reading()
                self.assertIsNone(reason)
                self.assertTrue(line.startswith("GO idle=57%"), line)
                gate.release(self.root, gate.acquire(self.root, "io-wait", os.getpid(), None))
            for idle in (10, 30):  # 10 trips the idle floor; 30 only the confirmed load reason
                with mock.patch.object(gate, "cpu_idle_percent", return_value=idle):
                    line, reason = gate.host_reading()
                    self.assertTrue(line.startswith("DEFER"), line)
                    self.assertIn("1-minute load 200.0 exceeds" if idle == 30 else "CPU idle 10% is below 20%", reason)
                    with self.assertRaises(gate.Busy):
                        gate.acquire(self.root, "saturated", os.getpid(), None)
            with mock.patch.object(gate, "cpu_idle_percent", return_value=35):
                self.assertIsNone(gate.host_reading()[1])  # the confirming threshold is strict
        self.assertIsNone(gate.read_state(self.root))

    def test_explicit_migration_preserves_old_live_receipt(self):
        token = gate.acquire(self.root, "mine", os.getpid(), None)
        old = gate.read_state(self.root)
        del old["stages"]
        gate.write_state(self.root, old)
        with self.assertRaises(gate.GateError):
            gate.read_state(self.root)
        self.assertIn("migrated", gate.migrate(self.root))
        migrated = gate.read_state(self.root)
        self.assertEqual(migrated["token"], token)
        self.assertEqual(migrated["pid_start"], old["pid_start"])
        self.assertEqual(migrated["stages"], [])

    def test_release_needs_shutdown(self):
        token = gate.acquire(self.root, "mine", os.getpid(), SIM)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.release(self.root, token)
        self.assertEqual(gate.read_state(self.root)["token"], token)
        gate.release(self.root, token)
        self.assertIsNone(gate.read_state(self.root))

    def test_metadata_contains_no_command_or_environment(self):
        token = gate.acquire(self.root, "mine", os.getpid(), None)
        data = (self.root / "lease.json").read_text()
        self.assertIn(token, data)
        self.assertEqual(set(json.loads(data)), {"owner", "pid", "pid_start", "simulator", "token", "created", "child", "stages"})
        self.assertNotIn("PATH", data)
        self.assertNotIn("argv", data)

    def test_corrupt_state_and_symlink_fail_closed(self):
        gate.secure_root(self.root)
        (self.root / "lease.json").write_text("{broken")
        with self.assertRaises(gate.GateError):
            gate.acquire(self.root, "mine", os.getpid(), None)
        (self.root / "lease.json").unlink()
        (self.root / "lease.json").symlink_to(self.root / "target")
        with self.assertRaises(gate.GateError):
            gate.acquire(self.root, "mine", os.getpid(), None)

    def test_symlinked_parent_and_dotdot_root_fail_closed(self):
        target = Path(self.tmp.name).resolve() / "real"
        target.mkdir()
        link = Path(self.tmp.name).resolve() / "linked"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(gate.GateError):
            gate.secure_root(link / "capacity")
        with self.assertRaises(gate.GateError):
            gate.secure_root(target / ".." / "capacity")

    def test_bad_metadata_types_fail_closed(self):
        gate.acquire(self.root, "mine", os.getpid(), None)
        for key, bad in (("owner", 42), ("pid", True), ("simulator", 1),
                         ("token", 3), ("created", True), ("child", {"pid": True})):
            lease = gate.read_state(self.root)
            original = lease[key]
            lease[key] = bad
            gate.write_state(self.root, lease)
            with self.assertRaises(gate.GateError):
                gate.read_state(self.root)
            lease[key] = original
            gate.write_state(self.root, lease)

    def test_run_success_and_failure_clear_only_when_safe(self):
        self.assertEqual(gate.run_command(self.root, "mine", None, [sys.executable, "-c", "pass"]), 0)
        self.assertIsNone(gate.read_state(self.root))
        self.assertEqual(gate.run_command(self.root, "mine", None, [sys.executable, "-c", "raise SystemExit(7)"]), 7)
        self.assertIsNone(gate.read_state(self.root))

    def test_run_retains_lease_on_simulator_or_child_group(self):
        with mock.patch.object(gate, "observe_booted", side_effect=[[], [SIM]]), \
             mock.patch.object(gate, "shutdown_owned", side_effect=gate.GateError("still active")):
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), gate.BUSY)
        self.assertIsNotNone(gate.read_state(self.root))

    def test_stage_has_its_own_deadline_inside_run(self):
        code = gate.run_command(self.root, "mine", None,
                                [sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "0.2", "--", "sleep", "5"])
        self.assertEqual(code, gate.TIMEOUT)
        self.assertIsNone(gate.read_state(self.root))

    def test_whole_run_timeout_with_stage_cleans_or_retains_stage_receipt(self):
        code = gate.run_command(self.root, "mine", None,
                                [sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "30", "--", "sleep", "30"],
                                max_seconds=0.6)
        self.assertIn(code, (gate.TIMEOUT, gate.BUSY))
        lease = gate.read_state(self.root)
        if lease is not None:
            for stage in lease["stages"]:
                if gate.group_alive(stage["pgid"]):
                    with self.assertRaises(gate.Busy):
                        gate.release(self.root, lease["token"])

    def test_stage_receipt_limit_rejects_before_writing(self):
        gate.acquire(self.root, "mine", os.getpid(), None, child_pending=True)
        lease = gate.read_state(self.root)
        pgid = os.getpgrp()
        lease["child"] = {"pid": pgid, "pgid": pgid, "pid_start": "known"}
        lease["stages"] = [{"pid": 1000 + index, "pgid": 1000 + index, "pid_start": "known"}
                           for index in range(64)]
        gate.write_state(self.root, lease)
        with self.assertRaises(gate.GateError):
            gate.record_stage(self.root, 2000, "known")
        self.assertEqual(gate.read_state(self.root), lease)

    def test_python_wrapper_preserves_bridge_or_fails_before_payload(self):
        # Exercise the real run -> Python -> stage boundary, with no live state or simctl.
        self.root.mkdir(mode=0o700)
        lock_path = Path(self.tmp.name).resolve() / "legacy.lock"
        (self.root / "bridge.json").write_text(json.dumps({"lockPaths": [str(lock_path)]}))
        sim_fixture = self.root / "booted.json"
        sim_fixture.write_text('{"devices":{}}')
        pressure_fixture = self.root / "pressure.json"
        pressure_fixture.write_text('{"load":0,"cores":8}')
        env = dict(os.environ, LOCAL_CAPACITY_SIMCTL_JSON=str(sim_fixture),
                   LOCAL_CAPACITY_PRESSURE_JSON=str(pressure_fixture))
        marker = self.root / "payload-ran"
        # This independent process opens the lock afresh; inherited bridge FDs cannot
        # turn its flock into a same-open-description success.
        competitor = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(75)
finally:
    os.close(fd)
"""
        payload = """
import subprocess, sys
from pathlib import Path
result = subprocess.run([sys.executable, '-c', sys.argv[1], sys.argv[2]],
                        capture_output=True, timeout=5)
assert result.returncode == 75, result.stderr
Path(sys.argv[3]).write_text('competitor excluded')
"""
        wrapper = """
import os, subprocess, sys
fds = tuple(int(value) for value in
            os.environ.get('LOCAL_CAPACITY_LEGACY_FDS', '').split(',') if value)
assert fds and all(fd > 0 for fd in fds)
options = {'pass_fds': fds} if sys.argv[1] == 'preserve' else {}
result = subprocess.run(sys.argv[2:], env=os.environ.copy(), timeout=10, **options)
sys.exit(result.returncode)
"""
        for mode in ("preserve", "omit"):
            with self.subTest(mode=mode):
                marker.unlink(missing_ok=True)
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--root", str(self.root),
                     "run", "--owner", "wrapper-test", "--", sys.executable, "-c", wrapper,
                     mode, sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "5",
                     "--", sys.executable, "-c", payload, competitor, str(lock_path), str(marker)],
                    env=env, capture_output=True, text=True, timeout=20)
                if mode == "preserve":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(marker.read_text(), "competitor excluded")
                else:
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("stage legacy lock descriptors are unavailable", result.stderr)
                    self.assertFalse(marker.exists(), "stage executed after losing its bridge FDs")
                self.assertIsNone(gate.read_state(self.root))
                # Normal exit relinquishes the bridge as well as the capacity receipt.
                fd = os.open(lock_path, os.O_RDONLY)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)

    def test_legacy_flock_survives_supervisor_death_while_child_runs(self):
        lock_path = Path(self.tmp.name).resolve() / "old.lock"
        self.root.mkdir()
        (self.root / "bridge.json").write_text(json.dumps({"lockPaths": [str(lock_path)]}))
        sim_fixture = self.root / "booted.json"
        sim_fixture.write_text('{"devices":{}}')
        pressure_fixture = self.root / "pressure.json"
        pressure_fixture.write_text('{"load":0,"cores":8}')
        env = dict(os.environ, LOCAL_CAPACITY_SIMCTL_JSON=str(sim_fixture),
                   LOCAL_CAPACITY_PRESSURE_JSON=str(pressure_fixture))
        runner = subprocess.Popen([sys.executable, str(SCRIPT), "--root", str(self.root),
                                   "run", "--owner", "runner", "--", "sleep", "30"],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        group = None
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                lease = gate.read_state(self.root)
                if lease and lease["child"] and "pgid" in lease["child"]:
                    group = lease["child"]["pgid"]
                    break
                time.sleep(0.05)
            self.assertIsNotNone(group)
            runner.kill()
            runner.wait(timeout=5)
            fd = os.open(lock_path, os.O_RDONLY)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        finally:
            if group is not None:
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if runner.poll() is None:
                runner.kill()
                runner.wait()
            runner.stderr.close()

    def test_manual_release_rejects_live_recorded_group(self):
        token = gate.acquire(self.root, "mine", os.getpid(), None, child_pending=True)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            gate.record_child(self.root, token, child.pid, gate.pid_start(child.pid))
            with self.assertRaises(gate.Busy):
                gate.release(self.root, token)
        finally:
            gate.terminate_group(child)
        gate.release(self.root, token)

    def test_simulator_cleanup_targets_exact_device_and_verifies_shutdown(self):
        states = [{SIM: "Booted", "11111111-2222-3333-4444-555555555555": "Booted"},
                  {SIM: "Shutdown", "11111111-2222-3333-4444-555555555555": "Booted"}]
        with mock.patch.object(gate, "probe_devices", side_effect=states), \
             mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0)) as called:
            gate.shutdown_owned(SIM)
        self.assertEqual(called.call_args.args[0], ["/usr/bin/xcrun", "simctl", "shutdown", SIM])
        self.assertEqual(called.call_count, 1)

    def test_simulator_cleanup_failure_retains_lease(self):
        with mock.patch.object(gate, "shutdown_owned", side_effect=gate.GateError("still Booting")):
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), gate.BUSY)
        self.assertIsNotNone(gate.read_state(self.root))

    def test_successful_run_shuts_exact_simulator_before_release(self):
        with mock.patch.object(gate, "shutdown_owned") as shutdown:
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), 0)
        shutdown.assert_called_once_with(SIM)
        self.assertIsNone(gate.read_state(self.root))

    def test_running_child_group_defers_simulator_shutdown(self):
        with mock.patch.object(gate, "group_alive", return_value=True), \
             mock.patch.object(gate, "shutdown_owned") as shutdown:
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), gate.BUSY)
        shutdown.assert_not_called()
        self.assertIsNotNone(gate.read_state(self.root))

    def test_booting_device_blocks_release(self):
        token = gate.acquire(self.root, "mine", os.getpid(), SIM)
        self.probe.stop()
        try:
            with mock.patch.object(gate, "probe_devices", return_value={SIM: "Booting"}):
                with self.assertRaises(gate.Busy):
                    gate.release(self.root, token)
        finally:
            self.probe.start()

    def test_failed_receipt_never_grants_command_and_pending_needs_inspection(self):
        marker = Path(self.tmp.name) / "started"
        with mock.patch.object(gate, "record_child", side_effect=gate.GateError("receipt failed")):
            self.assertEqual(gate.run_command(self.root, "mine", None,
                             [sys.executable, "-c", "from pathlib import Path; Path(%r).touch()" % str(marker)]), gate.BUSY)
        self.assertFalse(marker.exists())
        lease = gate.read_state(self.root)
        self.assertEqual(lease["child"], {"state": "pending"})
        with self.assertRaises(gate.Busy):
            gate.release(self.root, lease["token"])
        with self.assertRaises(gate.Busy):
            gate.release(self.root, lease["token"], orphan_inspected=True)
        lease["pid"] = 999999
        gate.write_state(self.root, lease)
        gate.release(self.root, lease["token"], orphan_inspected=True)

    def test_parent_death_before_grant_cannot_start_command(self):
        marker = Path(self.tmp.name) / "started-after-death"
        code = ("import importlib.util,os,subprocess,sys; from pathlib import Path; from unittest import mock; "
                "s=importlib.util.spec_from_file_location('g',sys.argv[1]); "
                "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); "
                "p=mock.patch.object(g,'observe_booted',return_value=[]); p.start(); "
                "q=mock.patch.object(g,'simulator_pressure',return_value=(0,8)); q.start(); "
                "m=mock.patch.object(g,'memory_pressure_level',return_value=(1,'sysctl')); m.start(); "
                "c=mock.patch.object(g,'cpu_idle_percent',return_value=90); c.start(); "
                "g.acquire(Path(sys.argv[2]),'crashed',os.getpid(),None,child_pending=True); "
                "r,w=os.pipe(); "
                "subprocess.Popen(['/bin/sh','-c',"
                "'IFS= read -r ready <&%d && [ \"$ready\" = go ] && exec \"$@\"'%r,"
                "'gate',sys.executable,'-c','from pathlib import Path; Path(sys.argv[1]).touch()',sys.argv[3]],"
                "pass_fds=(r,),start_new_session=True); os._exit(0)")
        parent = subprocess.run([sys.executable, "-c", code, str(SCRIPT), str(self.root), str(marker)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(parent.returncode, 0, parent.stderr)
        time.sleep(0.3)
        self.assertFalse(marker.exists())
        lease = gate.read_state(self.root)
        self.assertEqual(lease["child"], {"state": "pending"})
        gate.release(self.root, lease["token"], orphan_inspected=True)

    def test_real_run_signal_stops_group_before_releasing(self):
        code = ("import importlib.util,sys; from pathlib import Path; from unittest import mock; "
                "s=importlib.util.spec_from_file_location('g',sys.argv[1]); "
                "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); "
                "p=mock.patch.object(g,'observe_booted',return_value=[]); p.start(); "
                "q=mock.patch.object(g,'simulator_pressure',return_value=(0,8)); q.start(); "
                "m=mock.patch.object(g,'memory_pressure_level',return_value=(1,'sysctl')); m.start(); "
                "c=mock.patch.object(g,'cpu_idle_percent',return_value=90); c.start(); "
                "sys.exit(g.run_command(Path(sys.argv[2]),'runner',None,"
                "[sys.executable,'-c','import time; time.sleep(30)']))")
        runner = subprocess.Popen([sys.executable, "-c", code, str(SCRIPT), str(self.root)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if (self.root / "lease.json").exists():
                    try:
                        lease = gate.read_state(self.root)
                        if lease and lease["child"] and "pgid" in lease["child"]:
                            break
                    except gate.GateError:
                        pass
                time.sleep(0.03)
            else:
                self.fail("runner did not record child")
            runner.send_signal(signal.SIGINT)
            _, stderr = runner.communicate(timeout=10)
            self.assertEqual(runner.returncode, 130, stderr)
            self.assertFalse(gate.group_alive(lease["child"]["pgid"]))
            current = gate.read_state(self.root)
            if current is not None:
                self.assertEqual(current["child"], lease["child"])
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.wait()


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        for name, value in (("observe_booted", []), ("simulator_pressure", (0, 8)), ("memory_pressure_level", (1, "sysctl")), ("cpu_idle_percent", 90)):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def cli(self, *args, load=0, host=None):
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "booted.json").write_text('{"devices":{}}')
        (self.root / "pressure.json").write_text(json.dumps({"load": load, "cores": 8}))
        (self.root / "host.json").write_text(json.dumps(host or {}))
        env = dict(os.environ, LOCAL_CAPACITY_SIMCTL_JSON=str(self.root / "booted.json"),
                   LOCAL_CAPACITY_PRESSURE_JSON=str(self.root / "pressure.json"),
                   LOCAL_CAPACITY_HOST_JSON=str(self.root / "host.json"))
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              env=env, capture_output=True, text=True, timeout=20)

    def hold_bridge(self):
        lock_path = Path(self.tmp.name).resolve() / "old.lock"
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "bridge.json").write_text(json.dumps({"lockPaths": [str(lock_path)]}))
        fd = os.open(lock_path, os.O_RDONLY | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(os.close, fd)

    def test_priority_owner_runs_beside_the_holder_and_nothing_is_stopped(self):
        holder = gate.acquire(self.root, "holder", os.getpid(), None)
        before = gate.read_state(self.root)
        gate.prioritize(self.root, "vip", 30, False)
        token = gate.acquire(self.root, "vip", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root), before)
        self.assertEqual(gate.read_state(self.root, slot=gate.SECOND_SLOT)["token"], token)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "vip", os.getpid(), None)
        gate.release(self.root, holder)
        self.assertEqual(gate.read_state(self.root, slot=gate.SECOND_SLOT)["token"], token)
        gate.release(self.root, token)
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))

    def test_priority_owner_keeps_the_saturation_guards_but_load_alone_does_not_block_it(self):
        gate.prioritize(self.root, "vip", 30, False)
        saturated = (
            (("simulator_pressure", (52.5, 8)), ("cpu_idle_percent", 30)),  # load confirmed by a busy CPU
            (("memory_pressure_level", (4, "sysctl")),),
            (("cpu_idle_percent", 5),),
        )
        for probes in saturated:
            with contextlib.ExitStack() as stack:
                for probe, value in probes:
                    stack.enter_context(mock.patch.object(gate, probe, return_value=value))
                for simulator in (None, SIM):
                    with self.assertRaises(gate.Busy):
                        gate.acquire(self.root, "vip", os.getpid(), simulator)
        self.assertIsNone(gate.read_state(self.root))
        with mock.patch.object(gate, "simulator_pressure", return_value=(200, 8)), \
             mock.patch.object(gate, "cpu_idle_percent", return_value=57):
            gate.release(self.root, gate.acquire(self.root, "vip", os.getpid(), None))

    def test_prioritize_does_not_bypass_the_simulator_cap(self):
        gate.acquire(self.root, "harbor", os.getpid(), SIM)
        gate.prioritize(self.root, "vip", 30, False)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy) as refused:
                gate.acquire(self.root, "vip", os.getpid(), SIM2)
        self.assertIn("holder=harbor", str(refused.exception))
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))

    def test_other_owner_is_deferred_with_the_priority_message_even_when_free(self):
        self.assertEqual(self.cli("prioritize", "--owner", "vip", "--minutes", "30").returncode, 0)
        deferred = self.cli("run", "--owner", "other", "--", sys.executable, "-c", "pass")
        self.assertEqual(deferred.returncode, gate.BUSY)
        self.assertIn("priority owner is vip until", deferred.stderr)
        self.assertIsNone(gate.read_state(self.root))
        self.assertEqual(self.cli("run", "--owner", "vip", "--", sys.executable, "-c", "pass").returncode, 0)

    def test_priority_owner_is_next_in_line_when_two_ordinary_owners_hold_both_slots(self):
        first = gate.acquire(self.root, "one", os.getpid(), None)
        gate.acquire(self.root, "two", os.getpid(), None)
        gate.acquire(self.root, "three", os.getpid(), None)
        gate.prioritize(self.root, "vip", 30, False)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "vip", os.getpid(), None)
        self.assertIn("all 3 heavy slots busy", str(refused.exception))
        gate.release(self.root, first)
        with self.assertRaises(gate.Busy) as deferred:
            gate.acquire(self.root, "other", os.getpid(), None)
        self.assertIn("priority owner is vip until", str(deferred.exception))
        token = gate.acquire(self.root, "vip", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root)["token"], token)

    def test_every_slot_busy_defers_even_the_priority_owner(self):
        gate.acquire(self.root, "holder", os.getpid(), None)
        gate.acquire(self.root, "middle", os.getpid(), None)
        gate.prioritize(self.root, "first", 30, False)
        gate.acquire(self.root, "first", os.getpid(), None)
        gate.prioritize(self.root, "second", 30, False)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "second", os.getpid(), None)

    def test_expired_record_is_ignored_and_cleaned(self):
        gate.secure_root(self.root)
        (self.root / "priority.json").write_text(json.dumps({"owner": "vip", "expires": time.time() - 5}))
        token = gate.acquire(self.root, "other", os.getpid(), None)
        self.assertEqual((self.root / "priority.json").read_text(), "")
        gate.release(self.root, token)

    def test_replace_and_clear(self):
        gate.prioritize(self.root, "first", 30, False)
        gate.prioritize(self.root, "second", 30, False)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "first", os.getpid(), None)
        self.assertEqual(self.cli("prioritize", "--clear").returncode, 0)
        gate.release(self.root, gate.acquire(self.root, "first", os.getpid(), None))

    def test_minutes_above_the_maximum_or_not_positive_is_rejected(self):
        for minutes in ("181", "0", "-5", "nan"):
            result = self.cli("prioritize", "--owner", "vip", "--minutes", minutes)
            self.assertEqual(result.returncode, 1, minutes)
        self.assertEqual(self.cli("prioritize", "--owner", "vip", "--minutes", "180").returncode, 0)
        self.assertEqual(self.cli("prioritize", "--owner", "bad/owner").returncode, 1)
        self.assertEqual(self.cli("prioritize").returncode, 1)

    def test_cpu_check_prints_one_go_or_defer_line(self):
        go = self.cli("cpu")
        self.assertEqual(go.returncode, 0, go.stderr)
        self.assertEqual(len(go.stdout.splitlines()), 1)
        self.assertTrue(go.stdout.startswith("GO idle=100%"), go.stdout)
        (self.root / "pressure.json").write_text(json.dumps({"load": 200, "cores": 8, "idle": 57, "memory_level": 1}))
        env = dict(os.environ, LOCAL_CAPACITY_PRESSURE_JSON=str(self.root / "pressure.json"),
                   LOCAL_CAPACITY_SIMCTL_JSON=str(self.root / "booted.json"))
        io_wait = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "cpu"],
                                 env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(io_wait.returncode, 0, io_wait.stdout)
        self.assertTrue(io_wait.stdout.startswith("GO idle=57% (min 20) load=200.0"), io_wait.stdout)
        (self.root / "pressure.json").write_text(json.dumps({"load": 1, "cores": 8, "idle": 8.5, "memory_level": 2}))
        env = dict(os.environ, LOCAL_CAPACITY_PRESSURE_JSON=str(self.root / "pressure.json"),
                   LOCAL_CAPACITY_SIMCTL_JSON=str(self.root / "booted.json"))
        defer = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "cpu"],
                               env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(defer.returncode, gate.BUSY)
        self.assertTrue(defer.stdout.startswith("DEFER idle=8%"), defer.stdout)
        self.assertIn("CPU idle 8% is below 20%", defer.stdout)
        self.assertIn("memory pressure is warning (level 2, via sysctl)", defer.stdout)
        self.assertIn("memory-pressure=warning (level 2, defer at 2)", defer.stdout)

    def test_status_prints_every_slot_free_and_held(self):
        free = self.cli("status").stdout.splitlines()
        self.assertEqual(free[:3], ["heavy slot %d of 3: free" % number for number in (1, 2, 3)])
        gate.acquire(self.root, "alpha", os.getpid(), None)
        lines = self.cli("status").stdout.splitlines()
        self.assertTrue(lines[0].startswith("heavy slot 1 of 3: holder=alpha "), lines)
        self.assertEqual(lines[1], "heavy slot 2 of 3: free")
        gate.acquire(self.root, "beta", os.getpid(), None)
        gate.acquire(self.root, "gamma", os.getpid(), None)
        lines = self.cli("status").stdout.splitlines()
        self.assertTrue(lines[1].startswith("heavy slot 2 of 3: holder=beta "), lines)
        self.assertTrue(lines[2].startswith("heavy slot 3 of 3: holder=gamma "), lines)

    def test_status_prints_the_record_only_while_it_is_live(self):
        self.assertNotIn("priority", self.cli("status").stdout)
        self.cli("prioritize", "--owner", "vip", "--minutes", "30")
        lines = [line for line in self.cli("status").stdout.splitlines() if line.startswith("priority: ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("vip until", lines[0])
        self.cli("prioritize", "--clear")
        self.assertNotIn("priority", self.cli("status").stdout)

    def test_priority_owner_cannot_take_the_holders_simulator(self):
        gate.acquire(self.root, "harbor", os.getpid(), SIM)
        gate.prioritize(self.root, "vip", 30, False)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "vip", os.getpid(), SIM)
            token = gate.acquire(self.root, "vip", os.getpid(), None)
            gate.release(self.root, token)

    def test_any_run_passes_a_legacy_lock_held_by_another_run_and_stages_work(self):
        self.hold_bridge()
        holder = gate.acquire(self.root, "holder", os.getpid(), None, allow_bridge=True)
        staged = [sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "5", "--", sys.executable, "-c", "pass"]
        self.assertEqual(gate.run_command(self.root, "other", None, staged), 0)
        self.assertIsNone(gate.read_state(self.root, slot=gate.SECOND_SLOT))
        self.assertEqual(gate.read_state(self.root)["token"], holder)

    def test_a_bridged_run_takes_the_third_file_when_the_second_is_held(self):
        self.hold_bridge()
        gate.acquire(self.root, "holder", os.getpid(), None, allow_bridge=True)
        middle = gate.acquire(self.root, "middle", os.getpid(), None, allow_bridge=True)
        self.assertEqual(gate.read_state(self.root, slot=gate.SECOND_SLOT)["token"], middle)
        token = gate.acquire(self.root, "other", os.getpid(), None, allow_bridge=True, second_slot_only=True)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["token"], token)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "late", os.getpid(), None, allow_bridge=True, second_slot_only=True)

    def test_legacy_lock_without_a_capacity_holder_still_blocks_every_owner(self):
        self.hold_bridge()
        for owner in ("vip", "other"):
            if owner == "vip":
                gate.prioritize(self.root, "vip", 30, False)
            else:
                gate.prioritize(self.root, None, 0, True)
            with self.assertRaises(gate.Busy):
                gate.run_command(self.root, owner, None, [sys.executable, "-c", "pass"])
            self.assertIsNone(gate.read_state(self.root))

    def test_the_holders_own_second_run_never_passes_the_legacy_lock(self):
        self.hold_bridge()
        gate.acquire(self.root, "holder", os.getpid(), None, allow_bridge=True)
        with self.assertRaises(gate.Busy):
            gate.run_command(self.root, "holder", None, [sys.executable, "-c", "pass"])


LAUNCHD = "launchd_sim /Users/x/Library/Developer/CoreSimulator/Devices/%s/data/var/run/launchd_bootstrap.plist"
RUNTIME = ("/Library/Developer/CoreSimulator/Volumes/iOS_X/Library/Developer/CoreSimulator/Profiles/Runtimes/"
           "iOS 27.0.simruntime/Contents/Resources/RuntimeRoot/System/Library/CoreServices/SpringBoard.app/SpringBoard")
BROWSER = "/Users/x/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing --remote-debugging-port=%d"
HELPER = ("/Users/x/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Google Chrome for Testing.app/Contents/Frameworks/"
          "Google Chrome for Testing Framework.framework/Helpers/Google Chrome for Testing Helper (Renderer).app/Contents/MacOS/"
          "Google Chrome for Testing Helper (Renderer) --type=renderer")


def ps_text(*rows):
    return "\n".join("%d %d %s %s %s" % row for row in rows) + "\n"


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        gate.secure_root(self.root)
        for name, value in (("observe_booted", []), ("simulator_pressure", (0, 8)), ("memory_pressure_level", (1, "sysctl")),
                            ("cpu_idle_percent", 90), ("live_session_cwds", ["/w/alpha", "/w/beta"])):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def lines(self, text):
        with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: text if key == "ps" else default):
            return gate.watchdog_lines(self.root)

    def test_hot_simulator_process_is_flagged_with_its_owner(self):
        gate.claim_sim(self.root, SIM, "alpha")
        text = ps_text((500, 1, "3.7", "05:00", LAUNCHD % SIM),
                       (501, 500, "312.0", "04:58", RUNTIME),
                       (502, 500, "20.0", "04:58", "/x/RuntimeRoot/usr/libexec/backboardd"))
        hot = [line for line in self.lines(text) if "HOT" in line]
        self.assertEqual(len(hot), 1, hot)
        self.assertIn("pid=501 SpringBoard cpu=312%", hot[0])
        self.assertIn("simulator=%s owner=alpha" % SIM, hot[0])
        self.assertIn("xcrun simctl shutdown %s" % SIM, hot[0])

    def test_young_or_cool_processes_are_not_flagged(self):
        text = ps_text((600, 1, "3.0", "00:30", LAUNCHD % SIM2),
                       (601, 600, "480.0", "00:29", RUNTIME),
                       (700, 1, "199.0", "01-02:00:00", "/usr/bin/some-daemon"))
        self.assertFalse([line for line in self.lines(text) if "HOT" in line])

    def test_any_hot_process_is_flagged_not_only_simulators(self):
        text = ps_text((800, 1, "250.0", "10:00", "/usr/local/bin/node vitest"))
        hot = [line for line in self.lines(text) if "HOT" in line]
        self.assertEqual(len(hot), 1)
        self.assertIn("pid=800 node", hot[0])
        self.assertNotIn("simulator=", hot[0])

    def test_booted_simulator_without_a_lease_and_an_idle_claim_are_flagged(self):
        gate.claim_sim(self.root, SIM2, "beta")
        lines = self.lines(ps_text((900, 1, "1.0", "10:00", LAUNCHD % SIM)))
        self.assertTrue(any("simulator %s is booted with no lease" % SIM in line for line in lines), lines)
        self.assertTrue(any("simulator claim %s owner=beta is idle" % SIM2 in line for line in lines), lines)

    def test_a_leased_booted_simulator_is_not_flagged_as_unleased(self):
        gate.acquire(self.root, "alpha", os.getpid(), SIM)
        lines = self.lines(ps_text((900, 1, "1.0", "10:00", LAUNCHD % SIM)))
        self.assertEqual(lines, ["watchdog: clear"])

    def test_more_than_one_test_browser_is_flagged_and_helpers_do_not_count(self):
        one = ps_text((1000, 1, "5.0", "10:00", BROWSER % 9222), (1001, 1000, "5.0", "10:00", HELPER))
        self.assertEqual(self.lines(one), ["watchdog: clear"])
        two = ps_text((1000, 1, "5.0", "10:00", BROWSER % 9222), (1002, 1, "5.0", "10:00", BROWSER % 9223))
        self.assertTrue(any("2 Chrome for Testing instances (pids 1000,1002)" in line for line in self.lines(two)))

    def test_status_and_watchdog_cli_print_the_flag(self):
        env_host = {"ps": ps_text((500, 1, "3.7", "05:00", LAUNCHD % SIM), (501, 500, "400.0", "03:00", RUNTIME))}
        runner = PriorityTests("cli")
        runner.tmp, runner.root = self.tmp, self.root
        status = runner.cli("status", host=env_host)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("watchdog: HOT pid=501 SpringBoard", status.stdout)
        self.assertIn("simulators in use: 0 of 1", status.stdout)
        watchdog = runner.cli("watchdog", host=env_host)
        self.assertIn("watchdog: HOT pid=501", watchdog.stdout)
        self.assertNotIn("heavy slot", watchdog.stdout)

    def test_elapsed_parses_every_ps_shape(self):
        self.assertEqual(gate.parse_elapsed("01:05"), 65)
        self.assertEqual(gate.parse_elapsed("02:00:01"), 7201)
        self.assertEqual(gate.parse_elapsed("3-00:00:00"), 3 * 86400)


class ReclaimTests(unittest.TestCase):
    """reclaim-sim acts only on an unleased simulator whose claim owner has no live session."""

    RECLAIM = "reclaim-sim --udid %s"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        gate.secure_root(self.root)
        self.sessions = ["/w/alpha/apps/ios"]
        self.devices = {SIM: "Booted"}
        for name, value in (("simulator_pressure", (0, 8)), ("memory_pressure_level", (1, "sysctl")), ("cpu_idle_percent", 90)):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(gate, "live_session_cwds", side_effect=lambda: list(self.sessions))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(gate, "probe_devices", side_effect=lambda: dict(self.devices))
        patch.start()
        self.addCleanup(patch.stop)
        self.real_run = subprocess.run
        self.xcrun = mock.patch.object(gate.subprocess, "run", side_effect=self.fake_xcrun)
        self.calls = self.xcrun.start()
        self.addCleanup(self.xcrun.stop)
        self.claim(SIM, "harbor")

    def fake_xcrun(self, command, **kwargs):
        if command[0] != "/usr/bin/xcrun":
            return self.real_run(command, **kwargs)  # only xcrun is stubbed; no real simulator is touched
        self.assertEqual(command[:3], ["/usr/bin/xcrun", "simctl", "shutdown"], command)
        self.devices[command[3]] = "Shutdown"
        return mock.Mock(returncode=0)

    def assert_no_xcrun(self):
        self.assertEqual([call for call in self.calls.call_args_list if call.args[0][0] == "/usr/bin/xcrun"], [])

    def claim(self, udid, owner):
        gate.write_claims(self.root, dict(gate.read_claims(self.root), **{udid: owner}))

    def test_refuses_while_the_claim_owner_has_a_live_session(self):
        self.sessions = ["/w/harbor/apps/ios"]
        with self.assertRaises(gate.GateError) as refused:
            gate.reclaim_sim(self.root, SIM)
        self.assertIn("claimed by harbor, which has a live session", str(refused.exception))
        self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})
        self.assert_no_xcrun()

    def test_refuses_while_a_lease_holds_the_simulator(self):
        token = None
        with mock.patch.object(gate, "observe_booted", return_value=[]):
            token = gate.acquire(self.root, "harbor", os.getpid(), SIM)
        with self.assertRaises(gate.GateError) as refused:
            gate.reclaim_sim(self.root, SIM)
        self.assertIn("holds a lease", str(refused.exception))
        self.assertIn("holder=harbor", str(refused.exception))
        self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})
        self.assertEqual(gate.read_state(self.root)["token"], token)
        self.assert_no_xcrun()

    def test_refuses_an_unclaimed_or_legacy_claimed_simulator(self):
        with self.assertRaises(gate.GateError) as refused:
            gate.reclaim_sim(self.root, SIM2)
        self.assertIn("has no claim", str(refused.exception))
        with mock.patch.object(gate, "legacy_claims", return_value={SIM: "old"}):
            with self.assertRaises(gate.GateError) as refused:
                gate.reclaim_sim(self.root, SIM)
        self.assertIn("legacy claim", str(refused.exception))
        self.assert_no_xcrun()

    def test_a_failed_session_probe_is_never_read_as_an_ended_owner(self):
        with mock.patch.object(gate, "live_session_cwds", side_effect=gate.GateError("live-session probe failed")):
            with self.assertRaises(gate.GateError):
                gate.reclaim_sim(self.root, SIM)
            self.assertEqual(gate.reclaim_hint(self.root, [None] * gate.HEAVY_SLOTS, SIM), "")
        self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})
        self.assert_no_xcrun()

    def test_succeeds_for_an_ended_owner_without_a_lease_and_never_deletes(self):
        message = gate.reclaim_sim(self.root, SIM.lower())
        self.assertEqual([call.args[0] for call in self.calls.call_args_list if call.args[0][0] == "/usr/bin/xcrun"],
                         [["/usr/bin/xcrun", "simctl", "shutdown", SIM]])
        self.assertEqual(self.devices, {SIM: "Shutdown"})  # shut down, still present: never deleted or erased
        self.assertEqual(gate.read_claims(self.root), {})
        self.assertIn("claim by harbor dropped", message)
        record = json.loads((self.root / "telemetry.jsonl").read_text().splitlines()[-1])
        self.assertEqual((record["event"], record["udid"], record["owner"]), ("reclaim-sim", SIM, "harbor"))

    def test_an_ended_owner_with_an_already_shut_down_simulator_only_drops_the_claim(self):
        self.devices = {SIM: "Shutdown"}
        gate.reclaim_sim(self.root, SIM)
        self.assert_no_xcrun()
        self.assertEqual(gate.read_claims(self.root), {})

    def test_a_shutdown_that_does_not_confirm_keeps_the_claim(self):
        self.calls.side_effect = lambda command, **kw: (mock.Mock(returncode=1) if command[0] == "/usr/bin/xcrun"
                                                        else self.real_run(command, **kw))
        with self.assertRaises(gate.GateError):
            gate.reclaim_sim(self.root, SIM)
        self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})

    def test_run_refusal_and_watchdog_print_the_command_only_for_an_ended_owner(self):
        command = self.RECLAIM % SIM
        ps = ps_text((900, 1, "1.0", "10:00", LAUNCHD % SIM))
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy) as ended:
                gate.acquire(self.root, "beta", os.getpid(), None)
            self.assertIn("booted simulators %s" % SIM, str(ended.exception))
            self.assertIn("claim owner harbor has no live session; reclaim it: python3 ~/.claude/bin/local-capacity.py " + command,
                          str(ended.exception))
            with self.assertRaises(gate.Busy) as capped:
                gate.claim_sim(self.root, SIM2, "beta")
            self.assertIn(command, str(capped.exception))
            with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: ps if key == "ps" else default):
                lines = gate.watchdog_lines(self.root)
        self.assertTrue(any("booted with no lease (claim owner=harbor); claim owner harbor has no live session; reclaim it:" in line
                            and command in line for line in lines), lines)
        self.sessions = ["/w/harbor"]
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy) as live:
                gate.acquire(self.root, "beta", os.getpid(), None)
            with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: ps if key == "ps" else default):
                lines = gate.watchdog_lines(self.root)
        self.assertNotIn("reclaim-sim", str(live.exception))
        self.assertTrue(any("that owner runs xcrun simctl shutdown %s then release-sim" % SIM in line for line in lines), lines)
        self.assertFalse(any("reclaim-sim" in line for line in lines), lines)

    def test_hot_process_and_idle_claim_lines_print_the_command_for_an_ended_owner_only(self):
        command = self.RECLAIM % SIM
        hot = ps_text((500, 1, "3.7", "05:00", LAUNCHD % SIM), (501, 500, "312.0", "04:58", RUNTIME))
        idle = ps_text()
        with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: hot if key == "ps" else default):
            lines = gate.watchdog_lines(self.root)
        self.assertTrue(any("HOT pid=501" in line and command in line for line in lines), lines)
        with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: idle if key == "ps" else default):
            lines = gate.watchdog_lines(self.root)
        self.assertTrue(any("simulator claim %s owner=harbor is idle" % SIM in line and command in line for line in lines), lines)
        self.sessions = ["/w/harbor"]
        with mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: idle if key == "ps" else default):
            lines = gate.watchdog_lines(self.root)
        self.assertTrue(any("release it: local-capacity.py release-sim" in line for line in lines), lines)
        self.assertFalse(any("reclaim-sim" in line for line in lines), lines)

    def test_cli_refuses_a_live_owner_and_reclaims_an_ended_one(self):
        runner = PriorityTests("cli")
        runner.tmp, runner.root = self.tmp, self.root
        shutdown = {"devices": {"iOS": [{"udid": SIM, "state": "Shutdown"}]}}

        def cli(host):
            (self.root / "booted.json").write_text(json.dumps(shutdown))
            return runner.cli("reclaim-sim", "--udid", SIM, host=host)
        self.xcrun.stop()
        try:
            refused = cli({"sessions": ["/w/harbor"]})
            self.assertEqual(refused.returncode, 1, refused.stderr)
            self.assertIn("live session", refused.stderr)
            self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})
            done = cli({"sessions": []})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("claim by harbor dropped", done.stdout)
            self.assertEqual(gate.read_claims(self.root), {})
        finally:
            self.xcrun.start()


class StackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        self.host = {"stacks": [], "vm_gib": 7.75, "sessions": [], "activity": {}}
        for name, value in (("simulator_pressure", (0, 8)), ("memory_pressure_level", (1, "sysctl")), ("cpu_idle_percent", 90)):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(gate, "host_fixture", side_effect=lambda key, default: self.host.get(key, default))
        patch.start()
        self.addCleanup(patch.stop)
        self.docker = mock.patch.object(gate, "docker_json_lines", return_value="")
        self.calls = self.docker.start()
        self.addCleanup(self.docker.stop)

    def running(self, *workspaces, supabase=True):
        self.host["stacks"] = [{"project": Path(ws).name, "workdir": ws, "supabase": supabase} for ws in workspaces]

    def test_cap_derives_from_the_docker_vm(self):
        self.assertEqual(gate.max_stacks(7.75), 2)
        self.assertEqual(gate.max_stacks(4), 1)
        self.assertEqual(gate.max_stacks(64), gate.STACK_CEILING)
        self.assertEqual(gate.max_stacks(None), 1)

    def test_third_stack_is_refused_naming_the_two_and_a_running_one_is_readmitted(self):
        now = time.time()
        self.host["activity"] = {"/w/a": now, "/w/b": now}
        self.running("/w/a", "/w/b")
        with self.assertRaises(gate.Busy) as refused:
            gate.stack_acquire(self.root, "gamma", "/w/c")
        self.assertIn("2 of 2 local dev stacks in use", str(refused.exception))
        self.assertIn("/w/a", str(refused.exception))
        gate.stack_acquire(self.root, "alpha", "/w/a")

    def test_fresh_leases_count_before_containers_appear(self):
        gate.stack_acquire(self.root, "alpha", "/w/a")
        gate.stack_acquire(self.root, "beta", "/w/b")
        with self.assertRaises(gate.Busy):
            gate.stack_acquire(self.root, "gamma", "/w/c")
        leases = gate.read_stack_leases(self.root)
        for workspace in leases:
            leases[workspace]["created"] -= (gate.STACK_START_GRACE_MIN + 1) * 60
        gate.write_stack_leases(self.root, leases)
        gate.stack_acquire(self.root, "gamma", "/w/c")
        self.assertEqual(set(gate.read_stack_leases(self.root)), {"/w/c"})

    def test_prioritize_and_memory_do_not_bypass_the_stack_cap(self):
        gate.prioritize(self.root, "vip", 30, False)
        now = time.time()
        self.host["activity"] = {"/w/a": now, "/w/b": now}
        self.running("/w/a", "/w/b")
        with self.assertRaises(gate.Busy):
            gate.stack_acquire(self.root, "vip", "/w/c")
        self.running()
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")):
            with self.assertRaises(gate.Busy):
                gate.stack_acquire(self.root, "vip", "/w/c")

    def test_sweep_stops_only_idle_supabase_stacks_and_keeps_volumes(self):
        old = time.time() - (gate.STACK_IDLE_MIN + 1) * 60
        self.running("/w/idle", "/w/live", "/w/busy", "/w/mine")
        self.host["sessions"] = ["/w/live/apps/api"]
        self.host["activity"] = {"/w/idle": old, "/w/live": old, "/w/busy": time.time(), "/w/mine": old}
        self.calls.return_value = "abc123\n"
        lines = gate.stack_sweep(True, exclude="/w/mine")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("stopped idle stack idle", lines[0])
        commands = [call.args[0] for call in self.calls.call_args_list]
        label = "label=com.supabase.cli.project=idle"
        self.assertEqual(commands, [["ps", "-q", "--filter", label], ["stop", "abc123"],
                                    ["container", "prune", "-f", "--filter", label],
                                    ["network", "prune", "-f", "--filter", label]])
        self.assertFalse(any("volume" in command for command in commands))

    def test_sweep_without_apply_only_reports_and_compose_stacks_are_never_stopped(self):
        old = time.time() - (gate.STACK_IDLE_MIN + 1) * 60
        self.running("/w/idle")
        self.host["activity"] = {"/w/idle": old}
        self.assertIn("stack-sweep --apply", gate.stack_sweep(False)[0])
        self.running("/w/compose", supabase=False)
        self.host["activity"] = {"/w/compose": old}
        self.assertEqual(gate.stack_sweep(True), [])
        self.calls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
