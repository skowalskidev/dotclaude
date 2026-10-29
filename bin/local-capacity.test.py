#!/usr/bin/env python3
"""Offline tests for the cooperative capacity lease."""

import contextlib
import importlib.util
import io
import fcntl
import json
import multiprocessing
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
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


def setUpModule():
    # These offline fixtures own temporary leases, not the enclosing test runner's real lease.
    environment = mock.patch.dict(os.environ, {
        key: value for key, value in os.environ.items() if not key.startswith("LOCAL_CAPACITY_")
    }, clear=True)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


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

    def test_nested_run_is_refused_without_a_retryable_exit(self):
        """A child of a leased run retrying for its owner's lease would wait out its whole budget."""
        self.root.mkdir(mode=0o700, exist_ok=True)
        for action in (["run", "--owner", "alpha", "--wait-min", "0", "--", "true"],
                       ["acquire", "--owner", "alpha", "--pid", str(os.getpid())]):
            with mock.patch.dict(os.environ, LOCAL_CAPACITY_RUN_ROOT=str(self.root)):
                with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                    code = gate.main(["--root", str(self.root), *action])
            self.assertEqual(code, 1, action)
            self.assertIn("nested lease refused", err.getvalue())
            self.assertIn("stage", err.getvalue())
        self.assertIsNone(gate.read_state(self.root))

    def test_a_run_on_another_capacity_root_is_not_nested(self):
        other = self.root.parent / "other-root"
        with mock.patch.dict(os.environ, LOCAL_CAPACITY_RUN_ROOT=str(other)):
            gate.refuse_nested_lease(self.root)

    def test_one_owner_holds_at_most_one_lease(self):
        gate.acquire(self.root, "alpha", os.getpid(), None)
        with self.assertRaises(gate.Busy) as refused:
            gate.acquire(self.root, "alpha", os.getpid(), None)
        self.assertIn("one owner holds at most one lease", str(refused.exception))
        self.assertIn("stage", str(refused.exception))
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

    def test_cpu_idle_is_read_from_the_second_iostat_sample(self):
        self.idle.stop()
        try:
            output = "      cpu\n us sy id\n  2  1 97\n 70 20 10\n"
            with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=output)) as probe:
                self.assertEqual(gate.cpu_idle_percent(), 10.0)
            self.assertEqual(probe.call_args.args[0], ["/usr/sbin/iostat", "-d", "-C", "-n", "0", "-c", "2", "-w", "1"])
            with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="cpu\nus sy id\n2 1 97")):
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

    def test_admission_samples_cpu_load_and_memory_once_even_when_deferred(self):
        for idle, level in ((90, 1), (2, 1), (90, 4)):
            with self.subTest(idle=idle, level=level), \
                 mock.patch.object(gate, "cpu_idle_percent", return_value=idle) as cpu, \
                 mock.patch.object(gate, "simulator_pressure", return_value=(0, 8)) as load, \
                 mock.patch.object(gate, "memory_pressure_level", return_value=(level, "sysctl")) as memory:
                if idle == 90 and level == 1:
                    gate.release(self.root, gate.acquire(self.root, "sample", os.getpid(), None))
                else:
                    with self.assertRaises(gate.Busy):
                        gate.acquire(self.root, "sample", os.getpid(), None)
                cpu.assert_called_once_with()
                load.assert_called_once_with()
                memory.assert_called_once_with()

    def test_cpu_probe_failure_classifies_without_exposing_output(self):
        self.idle.stop()
        try:
            cases = ((subprocess.TimeoutExpired("iostat", 5, output="private-output"), "timed out after 5 seconds"),
                     (OSError("private-path"), "iostat unavailable"),
                     (mock.Mock(returncode=3, stdout="private-output"), "iostat exited 3"),
                     (mock.Mock(returncode=0, stdout="private-output"), "header or two-sample output changed"),
                     (mock.Mock(returncode=0, stdout="cpu\nus sy id\n2 1 97\n0 0 101"), "invalid CPU sample"))
            for result, reason in cases:
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with self.subTest(reason=reason), mock.patch.object(gate.subprocess, "run", **kwargs):
                    with self.assertRaises(gate.ProbeFailed) as failed:
                        gate.cpu_idle_percent()
                    self.assertIn(reason, str(failed.exception))
                    self.assertNotIn("private-", str(failed.exception))
        finally:
            self.idle.start()

    def test_cpu_probe_requires_two_valid_rows_and_exact_cpu_header(self):
        self.idle.stop()
        try:
            outputs = ("cpu\nus sy id\n2 1 97", "cpu\nus id sy\n2 1 97\n70 20 10",
                       "disk0 cpu\nKB/t tps MB/s us sy id\n0 0 0 2 1 97\n0 0 0 70 20 10",
                       "cpu\nus sy id\n2 1 97\n70 nan 10", "cpu\nus sy id\n2 1 97\n70 20 50",
                       "cpu\nus sy id\n2 1 97\n70 20 -10", "cpu\nus sy id\n2 1 97\n70 20",
                       "cpu\nus sy id\n2 1 97\n70 20 10\n0 0 100")
            for output in outputs:
                with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=output)):
                    with self.assertRaises(gate.ProbeFailed):
                        gate.cpu_idle_percent()
        finally:
            self.idle.start()

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

    def test_completed_payload_retries_only_release_lock_without_relaunch(self):
        original = gate.release
        calls = []
        marker = Path(self.tmp.name) / "runs"

        def release(root, token):
            calls.append(token)
            if len(calls) == 1:
                raise gate.StateLockBusy("contended")
            return original(root, token)

        with mock.patch.object(gate, "release", side_effect=release), \
             mock.patch.object(gate.time, "sleep"):
            code = gate.run_command(self.root, "mine", None,
                                    [sys.executable, "-c", "open(%r, 'a').write('once\\n')" % str(marker)])
        self.assertEqual(code, 0)
        self.assertEqual(marker.read_text(), "once\n")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertIsNone(gate.read_state(self.root))

    def test_cleanup_contention_has_a_deadline_and_keeps_the_receipt(self):
        token = gate.acquire(self.root, "mine", os.getpid(), None)
        now = [0]
        with mock.patch.object(gate.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(gate.time, "sleep", side_effect=lambda n: now.__setitem__(0, now[0] + n)), \
             mock.patch.object(gate, "release", side_effect=gate.StateLockBusy("contended")):
            with self.assertRaises(gate.StateLockBusy):
                gate.cleanup_run(self.root, token, None)
        self.assertEqual(now[0], gate.CLEANUP_WAIT_SECONDS)
        self.assertEqual(gate.read_state(self.root)["token"], token)

    def test_cleanup_retry_revalidates_replacement_token(self):
        token = gate.acquire(self.root, "mine", os.getpid(), None)
        replacement = gate.read_state(self.root)
        replacement["token"] = "f" * 64
        original = gate.release
        calls = []

        def release(root, candidate):
            calls.append(candidate)
            if len(calls) == 1:
                gate.write_state(root, replacement)
                raise gate.StateLockBusy("contended")
            return original(root, candidate)

        with mock.patch.object(gate, "release", side_effect=release), mock.patch.object(gate.time, "sleep"):
            with self.assertRaisesRegex(gate.GateError, "does not match"):
                gate.cleanup_run(self.root, token, None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(gate.read_state(self.root), replacement)

    def test_cleanup_does_not_retry_resource_or_identity_refusals(self):
        for refusal in (gate.Busy("group still alive"), gate.GateError("identity changed")):
            with mock.patch.object(gate, "release", side_effect=refusal) as release, \
                 mock.patch.object(gate.time, "sleep") as sleep:
                with self.assertRaises(type(refusal)):
                    gate.cleanup_run(self.root, "0" * 64, None)
                release.assert_called_once()
                sleep.assert_not_called()

    def test_status_external_probes_do_not_hold_the_state_lock(self):
        gate.acquire(self.root, "mine", os.getpid(), None)
        checked = []

        def probe(label, result):
            def run(*args):
                with gate.locked(self.root):
                    checked.append(label)
                return result
            return run

        with mock.patch.object(gate, "observe_booted", side_effect=probe("simctl", [])), \
             mock.patch.object(gate, "holder_text", side_effect=probe("holder", "mine")), \
             mock.patch.object(gate, "process_table", side_effect=probe("processes", [])), \
             mock.patch.object(gate, "print_stacks", side_effect=probe("stacks", None)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(["--root", str(self.root), "status"]), 0)
        self.assertEqual(checked, ["simctl", "holder", "processes", "stacks"])

    def test_stale_report_cannot_reclaim_a_replaced_live_owner(self):
        gate.secure_root(self.root)
        gate.write_claims(self.root, {SIM: "ended"})
        snapshot = gate.report_snapshot(self.root)
        gate.write_claims(self.root, {SIM: "current"})
        with mock.patch.object(gate, "owner_session_live", side_effect=lambda owner, workspace: owner == "current"), \
             mock.patch.object(gate, "shutdown_owned") as shutdown:
            self.assertIn("reclaim it", gate.reclaim_hint(self.root, snapshot["states"], SIM, snapshot))
            with self.assertRaisesRegex(gate.GateError, "current.*live session"):
                gate.reclaim_sim(self.root, SIM)
            shutdown.assert_not_called()
        self.assertEqual(gate.read_claims(self.root), {SIM: "current"})

    def test_running_child_group_defers_simulator_shutdown(self):
        with mock.patch.object(gate, "group_alive", return_value=True), \
             mock.patch.object(gate, "shutdown_owned") as shutdown:
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), gate.BUSY)
        shutdown.assert_not_called()
        self.assertIsNotNone(gate.read_state(self.root))

    def test_reaped_child_never_authorizes_another_group_signal(self):
        child = mock.Mock(pid=43210, returncode=0)
        with mock.patch.object(gate.os, "killpg") as signal_group:
            gate.terminate_group(child)
        signal_group.assert_not_called()
        child.wait.assert_not_called()

    def test_ordinary_teardown_accepts_only_proven_zombie_only_eperm(self):
        child = mock.Mock(pid=43210, returncode=None)
        child.wait.side_effect = lambda **kwargs: setattr(child, "returncode", 0)
        with mock.patch.object(gate, "pid_start", return_value="child-start"), \
             mock.patch.object(gate.OwnedGroup, "child_identity", return_value=(43210, os.getpid(), 43210, ["child-start"], "Z")), \
             mock.patch.object(gate.OwnedGroup, "group_running", return_value=False), \
             mock.patch.object(gate.os, "killpg", side_effect=PermissionError("denied")) as signal_group:
            gate.terminate_group(child)
            gate.terminate_group(child)
        signal_group.assert_called_once_with(43210, signal.SIGTERM)
        child.wait.assert_called_once()

    def test_live_group_eperm_retains_evidence_and_never_retries_signal(self):
        child = mock.Mock(pid=43210, returncode=None)
        with mock.patch.object(gate, "pid_start", return_value="child-start"), \
             mock.patch.object(gate.OwnedGroup, "child_identity", return_value=(43210, os.getpid(), 43210, ["child-start"], "S")), \
             mock.patch.object(gate.os, "killpg", side_effect=PermissionError("denied")) as signal_group:
            for _ in range(2):
                with self.assertRaises(gate.GateError):
                    gate.terminate_group(child)
        signal_group.assert_called_once_with(43210, signal.SIGTERM)
        child.wait.assert_not_called()

    def test_teardown_keeps_leader_unreaped_until_descendants_stop(self):
        child = mock.Mock(pid=43210, returncode=None)
        events, alive, now = [], [True], [0]

        def send(pid, sig):
            events.append(sig)
            if sig == signal.SIGKILL:
                alive[0] = False

        def reap(**kwargs):
            events.append("reap")
            child.returncode = 0

        child.wait.side_effect = reap
        with mock.patch.object(gate, "pid_start", return_value="child-start"), \
             mock.patch.object(gate.OwnedGroup, "child_identity", return_value=(43210, os.getpid(), 43210, ["child-start"], "Z")), \
             mock.patch.object(gate.OwnedGroup, "group_running", side_effect=lambda: alive[0]), \
             mock.patch.object(gate.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(gate.time, "sleep", side_effect=lambda n: now.__setitem__(0, now[0] + n)), \
             mock.patch.object(gate.os, "killpg", side_effect=send):
            gate.terminate_group(child)
        self.assertEqual(events, [signal.SIGTERM, signal.SIGKILL, "reap"])

    def test_teardown_rejects_foreign_parent_or_changed_group_before_signalling(self):
        for parent, group in ((os.getpid() + 1, 43210), (os.getpid(), 999)):
            child = mock.Mock(pid=43210, returncode=None)
            with mock.patch.object(gate, "pid_start", return_value="child-start"), \
                 mock.patch.object(gate.OwnedGroup, "child_identity", return_value=(43210, parent, group, ["child-start"], "S")), \
                 mock.patch.object(gate.os, "killpg") as signal_group:
                with self.assertRaises(gate.GateError):
                    gate.terminate_group(child)
                signal_group.assert_not_called()

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


class AutoReleaseTests(unittest.TestCase):
    """A provably dead lease frees its slot on admission; anything live, simulator-bound or unknown stays."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "capacity"
        for name, value in (("observe_booted", []), ("simulator_pressure", (0, 8)),
                            ("memory_pressure_level", (1, "sysctl")), ("cpu_idle_percent", 90),
                            ("live_session_cwds", ["/w/alpha"])):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        gate.secure_root(self.root)

    def exited_group(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        child.wait()
        return child.pid

    def live_group(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        return child.pid

    def hold(self, slot, owner, pid, pid_start, pgid, simulator=None):
        lease = {"owner": owner, "pid": pid, "pid_start": pid_start, "simulator": simulator,
                 "token": os.urandom(32).hex(), "created": time.time(),
                 "child": {"pid": pgid, "pgid": pgid, "pid_start": "child start"}, "stages": []}
        gate.write_state(self.root, lease, slot)
        return lease

    def fill_other_slots(self):
        for slot in gate.SLOTS[:2]:
            self.hold(slot, "live-" + slot, os.getpid(), gate.pid_start(os.getpid()), self.live_group())

    def telemetry(self):
        path = self.root / "telemetry.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_dead_owner_with_exited_group_and_no_simulator_is_released_on_admission(self):
        self.fill_other_slots()
        dead = self.exited_group()
        self.hold(gate.THIRD_SLOT, "pending-prod-replay", dead, "old start", dead)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            token = gate.acquire(self.root, "newcomer", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["token"], token)
        self.assertIn("auto-released heavy slot 3 of 3: holder=pending-prod-replay (owner pid %d not running" % dead,
                      stderr.getvalue())
        event = self.telemetry()[-1]
        self.assertEqual((event["event"], event["owner"], event["slot"], event["pgid"]),
                         ("auto-release", "pending-prod-replay", 3, dead))
        self.assertIn("not running", event["reason"])

    def test_reused_owner_pid_with_exited_group_is_released(self):
        self.fill_other_slots()
        dead = self.exited_group()
        self.hold(gate.THIRD_SLOT, "reused", os.getpid(), "old process start", dead)
        with contextlib.redirect_stderr(io.StringIO()):
            gate.acquire(self.root, "newcomer", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["owner"], "newcomer")
        self.assertIn("reused", self.telemetry()[-1]["reason"])

    def test_live_process_in_the_recorded_group_keeps_the_lease(self):
        self.fill_other_slots()
        dead = self.exited_group()
        lease = self.hold(gate.THIRD_SLOT, "still-building", dead, "old start", self.live_group())
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "newcomer", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT), lease)
        self.assertEqual(self.telemetry(), [])

    def test_live_stage_group_keeps_the_lease(self):
        dead = self.exited_group()
        lease = self.hold(gate.THIRD_SLOT, "staged", dead, "old start", dead)
        stage = self.live_group()
        lease["stages"] = [{"pid": stage, "pgid": stage, "pid_start": "stage start"}]
        gate.write_state(self.root, lease, gate.THIRD_SLOT)
        self.assertEqual(gate.reap_dead_leases(self.root), [])
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT), lease)

    def test_simulator_lease_is_kept_for_reclaim(self):
        dead = self.exited_group()
        lease = self.hold(gate.THIRD_SLOT, "sim-holder", dead, "old start", dead, simulator=SIM)
        self.assertEqual(gate.reap_dead_leases(self.root), [])
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT), lease)

    def test_unrecorded_or_pending_group_and_unknown_owner_are_kept(self):
        dead = self.exited_group()
        pending = self.hold(gate.LEASE_SLOT, "pending", dead, "old start", dead)
        pending["child"] = {"state": "pending"}
        gate.write_state(self.root, pending, gate.LEASE_SLOT)
        bare = self.hold(gate.SECOND_SLOT, "acquire-only", dead, "old start", dead)
        bare["child"] = None
        gate.write_state(self.root, bare, gate.SECOND_SLOT)
        unknown = self.hold(gate.THIRD_SLOT, "unknown", os.getpid(), "old start", dead)
        with mock.patch.object(gate, "pid_start", return_value=None):
            self.assertEqual(gate.reap_dead_leases(self.root), [])
        self.assertEqual([gate.read_state(self.root, slot=name) for name in gate.SLOTS], [pending, bare, unknown])

    def test_live_priority_session_lease_is_kept(self):
        gate.prioritize(self.root, "vip", 30, False, workspace=None)
        dead = self.exited_group()
        lease = self.hold(gate.THIRD_SLOT, "vip", dead, "old start", dead)
        with mock.patch.object(gate, "owner_session_live", return_value=True):
            self.assertEqual(gate.reap_dead_leases(self.root), [])
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT), lease)
        with mock.patch.object(gate, "owner_session_live", return_value=False), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(len(gate.reap_dead_leases(self.root)), 1)
        self.assertIsNone(gate.read_state(self.root, slot=gate.THIRD_SLOT))

    def test_a_lease_replaced_after_the_probe_is_not_released(self):
        dead = self.exited_group()
        self.hold(gate.THIRD_SLOT, "gone", dead, "old start", dead)
        original = gate.provably_dead

        def replace_then_judge(lease, priority):
            verdict = original(lease, priority)
            self.hold(gate.THIRD_SLOT, "replacement", dead, "old start", dead)
            return verdict

        with mock.patch.object(gate, "provably_dead", side_effect=replace_then_judge):
            self.assertEqual(gate.reap_dead_leases(self.root), [])
        self.assertEqual(gate.read_state(self.root, slot=gate.THIRD_SLOT)["owner"], "replacement")

    def test_status_and_watchdog_release_and_print_the_owner_and_slot(self):
        for action in ("status", "watchdog"):
            dead = self.exited_group()
            self.hold(gate.THIRD_SLOT, "ended-" + action, dead, "old start", dead)
            stderr = io.StringIO()
            with mock.patch.object(gate, "process_table", return_value=[]), \
                 mock.patch.object(gate, "stack_sweep", return_value=[]), \
                 mock.patch.object(gate, "print_stacks"), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(gate.main(["--root", str(self.root), action]), 0)
            self.assertIn("auto-released heavy slot 3 of 3: holder=ended-" + action, stderr.getvalue())
            self.assertIsNone(gate.read_state(self.root, slot=gate.THIRD_SLOT))


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

    def test_other_owner_runs_in_spare_capacity_with_primary_reserved(self):
        self.assertEqual(self.cli("prioritize", "--owner", "vip", "--minutes", "30").returncode, 0)
        deferred = self.cli("run", "--owner", "other", "--", sys.executable, "-c", "pass")
        self.assertEqual(deferred.returncode, 0, deferred.stderr)
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
        gate.write_priority(self.root, {"owner": "vip", "expires": time.time() - 5, "workspace": None})
        token = gate.acquire(self.root, "other", os.getpid(), None)
        self.assertEqual((self.root / "priority.json").read_text(), "")
        gate.release(self.root, token)

    def test_replace_and_clear(self):
        gate.prioritize(self.root, "first", 30, False)
        gate.prioritize(self.root, "second", 30, False)
        gate.release(self.root, gate.acquire(self.root, "first", os.getpid(), None))
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

    def test_a_failed_host_probe_defers_with_exit_75_not_a_hard_failure(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "booted.json").write_text('{"devices":{}}')
        env = dict(os.environ, LOCAL_CAPACITY_PRESSURE_JSON=str(self.root / "pressure.json"),
                   LOCAL_CAPACITY_SIMCTL_JSON=str(self.root / "booted.json"))
        broken = (({"load": 0, "cores": 8, "idle": "unreadable"}, "CPU probe failed (invalid idle percent); defer heavy work"),
                  ({"load": 0, "idle": 90}, "host load probe failed; defer simulator work"),
                  ({"load": 0, "cores": 8, "idle": 90, "memory_level": 3}, "memory probe failed; defer heavy work"))
        for fixture, message in broken:
            (self.root / "pressure.json").write_text(json.dumps(fixture))
            for args in (("run", "--owner", "prober", "--wait-min", "0", "--", sys.executable, "-c", "pass"), ("cpu",),
                         ("claim-sim", "--udid", SIM, "--owner", "prober")):
                result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                                        env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, gate.BUSY, (args, result.stderr))
                self.assertIn(message, result.stderr)
        self.assertIsNone(gate.read_state(self.root))
        self.assertEqual(gate.read_claims(self.root), {})

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
                gate.run_command(self.root, owner, None, [sys.executable, "-c", "pass"], wait_seconds=0)
            self.assertIsNone(gate.read_state(self.root))

    def test_a_waiter_never_holds_the_legacy_lock_while_probing_the_host(self):
        lock_path = str(Path(self.tmp.name).resolve() / "old.lock")
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "bridge.json").write_text(json.dumps({"lockPaths": [lock_path]}))
        os.close(os.open(lock_path, os.O_RDONLY | os.O_CREAT, 0o600))
        held_during_probe = []

        def probe():
            fd = os.open(lock_path, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held_during_probe.append(False)
            except BlockingIOError:
                held_during_probe.append(True)
            finally:
                os.close(fd)
            return 90, 0, 8, 2, "sysctl"

        with mock.patch.object(gate, "sample_host", side_effect=probe):
            with self.assertRaisesRegex(gate.Busy, "no session is prioritised"):
                gate.run_command(self.root, "other", None, ["unused"], wait_seconds=0)
        self.assertEqual(held_during_probe, [False])

    def test_a_briefly_held_legacy_lock_is_waited_out_and_a_lasting_one_names_its_holder(self):
        lock_path = Path(self.tmp.name).resolve() / "old.lock"
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "bridge.json").write_text(json.dumps({"lockPaths": [str(lock_path)]}))
        holder = subprocess.Popen([sys.executable, "-c",
                                   "import fcntl,os,sys,time; fd=os.open(sys.argv[1],os.O_RDONLY|os.O_CREAT,0o600); "
                                   "fcntl.flock(fd,fcntl.LOCK_EX); print('held',flush=True); time.sleep(float(sys.argv[2]))",
                                   str(lock_path), "0.5"], stdout=subprocess.PIPE, text=True)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.assertEqual(gate.run_command(self.root, "other", None, [sys.executable, "-c", "pass"], wait_seconds=0), 0)
        holder.wait(5)
        holder.stdout.close()
        lasting = subprocess.Popen([sys.executable, "-c",
                                    "import fcntl,os,sys,time; fd=os.open(sys.argv[1],os.O_RDONLY|os.O_CREAT,0o600); "
                                    "fcntl.flock(fd,fcntl.LOCK_EX); print('held',flush=True); time.sleep(30)",
                                    str(lock_path)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (lasting.kill(), lasting.wait(5), lasting.stdout.close()))
        self.assertEqual(lasting.stdout.readline().strip(), "held")
        with mock.patch.object(gate, "LEGACY_LOCK_GRACE_SECONDS", 0.2):
            with self.assertRaisesRegex(gate.Busy, r"held for over 0.2s by pid %d \(" % lasting.pid):
                gate.run_command(self.root, "other", None, ["unused"], wait_seconds=0)
        self.assertIsNone(gate.read_state(self.root))

    def test_the_holders_own_second_run_never_passes_the_legacy_lock(self):
        self.hold_bridge()
        gate.acquire(self.root, "holder", os.getpid(), None, allow_bridge=True)
        with self.assertRaises(gate.Busy):
            gate.run_command(self.root, "holder", None, [sys.executable, "-c", "pass"], wait_seconds=0)


LAUNCHD = "launchd_sim /Users/x/Library/Developer/CoreSimulator/Devices/%s/data/var/run/launchd_bootstrap.plist"
RUNTIME = ("/Library/Developer/CoreSimulator/Volumes/iOS_X/Library/Developer/CoreSimulator/Profiles/Runtimes/"
           "iOS 27.0.simruntime/Contents/Resources/RuntimeRoot/System/Library/CoreServices/SpringBoard.app/SpringBoard")
BROWSER = "/Users/x/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing --remote-debugging-port=%d"
HELPER = ("/Users/x/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Google Chrome for Testing.app/Contents/Frameworks/"
          "Google Chrome for Testing Framework.framework/Helpers/Google Chrome for Testing Helper (Renderer).app/Contents/MacOS/"
          "Google Chrome for Testing Helper (Renderer) --type=renderer")


def ps_text(*rows):
    return "\n".join("%d %d %s %s %s" % row for row in rows) + "\n"


class CooperativeTests(unittest.TestCase):
    setUp = PriorityTests.setUp

    def controller(self):
        token = gate.acquire(self.root, "secondary", os.getpid(), None, child_pending=True)
        gate.record_child(self.root, token, 43210, "child-start")
        parent_start = gate.pid_start(os.getpid())
        self.child = mock.Mock(pid=43210)
        self.child.returncode = None
        self.child.poll.return_value = None
        self.child.wait.return_value = 0
        self.now = 0
        patches = (
            mock.patch.object(gate.time, "monotonic", side_effect=lambda: self.now),
            mock.patch.object(gate, "pid_start", side_effect=lambda pid: parent_start if pid == os.getpid() else "child-start"),
            mock.patch.object(gate.CooperativeRun, "child_identity",
                              return_value=(43210, os.getpid(), 43210, ["child-start"], "T")),
            mock.patch.object(gate.CooperativeRun, "group_running", return_value=False),
            mock.patch.object(gate.os, "killpg"),
        )
        results = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)
        self.signals = results[-1]
        return gate.CooperativeRun(self.root, "secondary", token, self.child, "child-start")

    def tick(self, controller):
        self.now += gate.RETRY_SECONDS
        controller.tick()

    def test_two_secondaries_leave_one_slot_and_primary_uses_it(self):
        gate.prioritize(self.root, "primary", 30, False)
        for owner in ("one", "two"):
            gate.acquire(self.root, owner, os.getpid(), None)
        with self.assertRaisesRegex(gate.Busy, "last heavy slot reserved"):
            gate.acquire(self.root, "three", os.getpid(), None)
        gate.acquire(self.root, "primary", os.getpid(), None)
        self.assertEqual(sum(bool(gate.read_state(self.root, slot=s)) for s in gate.SLOTS), gate.HEAVY_SLOTS)

    def test_primary_already_holds_a_slot_so_all_spare_slots_are_available(self):
        gate.prioritize(self.root, "primary", 30, False)
        for owner in ("primary", "one", "two"):
            gate.acquire(self.root, owner, os.getpid(), None)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "three", os.getpid(), None)

    def test_pause_and_stable_resume_retain_lease_and_memory(self):
        c = self.controller()
        before = gate.read_state(self.root)
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "host_reading", side_effect=[("DEFER", "memory warning"), ("GO", None),
                                                                ("DEFER", "CPU busy"), ("GO", None), ("GO", None)]):
            for _ in range(4):
                self.tick(c)
                self.assertTrue(c.paused)
            self.tick(c)
        self.assertFalse(c.paused)
        self.assertEqual(gate.read_state(self.root), before)
        self.assertEqual(self.signals.call_args_list, [mock.call(43210, signal.SIGSTOP), mock.call(43210, signal.SIGCONT)])

    def test_no_primary_does_not_pause_a_busy_cpu(self):
        c = self.controller()
        with mock.patch.object(gate, "host_reading", side_effect=AssertionError("unneeded probe")):
            self.tick(c)
        self.signals.assert_not_called()

    def test_failed_probe_pauses_and_never_counts_as_recovery(self):
        c = self.controller()
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "host_reading", side_effect=gate.ProbeFailed("unknown")):
            self.tick(c)
            self.tick(c)
        self.assertTrue(c.paused)
        self.assertEqual(c.healthy, 0)
        self.signals.assert_called_once_with(43210, signal.SIGSTOP)

    def test_pause_deadline_bounds_memory_retention(self):
        c = self.controller()
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "host_reading", return_value=("DEFER", "memory warning")):
            self.tick(c)
            self.now += gate.PAUSE_MAX_SECONDS
            with self.assertRaisesRegex(gate.Busy, "pause exceeded"):
                c.tick()
        self.assertIsNotNone(gate.read_state(self.root))

    def test_cleanup_of_paused_child_continues_pending_term(self):
        c = self.controller()
        c.paused = True
        c.terminate()
        self.assertEqual(self.signals.call_args_list, [mock.call(43210, signal.SIGTERM), mock.call(43210, signal.SIGCONT)])

    def test_each_signal_rechecks_identity_including_cleanup(self):
        c = self.controller()
        for sig in (signal.SIGSTOP, signal.SIGCONT, signal.SIGTERM, signal.SIGKILL):
            with mock.patch.object(gate, "pid_start", return_value="reused"):
                with self.assertRaises(gate.GateError):
                    c.signal(sig)
        with mock.patch.object(c, "child_identity", return_value=(43210, os.getpid(), 999, ["child-start"], "T")):
            with self.assertRaises(gate.GateError):
                c.signal(signal.SIGSTOP)
        self.signals.assert_not_called()

    def test_reaped_leader_cannot_authorize_a_signal(self):
        c = self.controller()
        with mock.patch.object(c, "child_identity", side_effect=gate.GateError("identity unavailable")):
            with self.assertRaisesRegex(gate.GateError, "identity unavailable"):
                c.signal(signal.SIGCONT)
        self.signals.assert_not_called()

    def test_unreaped_exited_leader_keeps_descendant_group_identity(self):
        c = self.controller()
        with mock.patch.object(c, "child_identity", return_value=(43210, os.getpid(), 43210, ["child-start"], "Z")):
            self.assertTrue(c.signal(signal.SIGCONT))
        self.child.poll.assert_not_called()
        self.signals.assert_called_once_with(43210, signal.SIGCONT)

    def test_foreign_receipt_or_stage_cannot_be_paused(self):
        c = self.controller()
        lease = gate.read_state(self.root)
        lease["stages"] = [{"pid": 999, "pgid": 999, "pid_start": "other"}]
        gate.write_state(self.root, lease)
        with self.assertRaises(gate.GateError):
            c.signal(signal.SIGSTOP)
        self.signals.assert_not_called()

    def test_default_admission_retries_then_runs_without_manual_resume(self):
        now = [0]
        with mock.patch.object(gate.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(gate.time, "sleep", side_effect=lambda n: now.__setitem__(0, now[0] + n)) as sleep, \
             mock.patch.object(gate, "_run_command", side_effect=[gate.Busy("full"), gate.ProbeFailed("unknown"), 0]) as run:
            self.assertEqual(gate.run_command(self.root, "secondary", None, ["unused"]), 0)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [mock.call(10), mock.call(10)])

    def test_admission_wait_is_bounded_and_never_restarts_a_started_job(self):
        now = [0]
        with mock.patch.object(gate.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(gate.time, "sleep", side_effect=lambda n: now.__setitem__(0, now[0] + n)), \
             mock.patch.object(gate, "_run_command", side_effect=gate.Busy("full")) as run:
            with self.assertRaises(gate.Busy):
                gate.run_command(self.root, "secondary", None, ["unused"], wait_seconds=25)
        self.assertEqual(now[0], 25)
        self.assertEqual(run.call_count, 4)

    def test_pause_safe_rejects_simulator_bridge_and_separate_stages(self):
        with self.assertRaises(gate.GateError):
            gate.run_command(self.root, "secondary", SIM, ["unused"], pause_safe=True)
        with mock.patch.object(gate, "bridge_paths", return_value=["/some/lock"]):
            with self.assertRaises(gate.GateError):
                gate.run_command(self.root, "secondary", None, ["unused"], pause_safe=True)
        with mock.patch.dict(os.environ, LOCAL_CAPACITY_PAUSE_SAFE="1", LOCAL_CAPACITY_RUN_ROOT=str(self.root)):
            with self.assertRaisesRegex(gate.GateError, "separate stage groups"):
                gate.stage_command(self.root, 5, ["unused"])

    def test_real_paused_command_timeout_cleans_owned_group_and_lease(self):
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "RETRY_SECONDS", 0.01), \
             mock.patch.object(gate, "host_reading", side_effect=[("GO", None)] + [("DEFER", "CPU busy")] * 10), \
             mock.patch.object(gate.os, "killpg", wraps=os.killpg) as signals:
            result = gate.run_command(self.root, "secondary", None, [sys.executable, "-c", "import time; time.sleep(30)"],
                                      max_seconds=0.6, pause_safe=True)
        self.assertEqual(result, gate.TIMEOUT)
        self.assertIsNone(gate.read_state(self.root))
        sent = [c.args[1] for c in signals.call_args_list]
        self.assertIn(signal.SIGSTOP, sent)
        # macOS may deliver TERM to a stopped process immediately; otherwise CONT drains it.
        self.assertIn(signal.SIGTERM, sent)

    def test_real_paused_descendant_gets_cont_after_leader_dies(self):
        gate.prioritize(self.root, "primary", 30, False)
        marker = Path(self.tmp.name) / "descendant-cleaned"
        ready = Path(self.tmp.name) / "descendant-ready"
        code = ("import os,signal,time\nfrom pathlib import Path\n"
                "if os.fork() == 0:\n"
                " def stop(sig, frame):\n"
                "  Path(%r).touch()\n  os._exit(0)\n"
                " signal.signal(signal.SIGTERM,stop)\n"
                " Path(%r).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n" % (str(marker), str(ready)))
        # Pause only after the descendant exists; a fixed poll count races interpreter startup.
        def pressure_after_ready(**_kwargs):
            return ("DEFER", "CPU busy") if ready.exists() else ("GO", None)

        with mock.patch.object(gate, "RETRY_SECONDS", 0.01), \
             mock.patch.object(gate, "host_reading", side_effect=pressure_after_ready), \
             mock.patch.object(gate.os, "killpg", wraps=os.killpg) as signals:
            result = gate.run_command(self.root, "secondary", None, [sys.executable, "-c", code],
                                      max_seconds=0.8, pause_safe=True)
        self.assertEqual(result, gate.TIMEOUT)
        self.assertTrue(ready.exists(), "descendant never started")
        self.assertIn(signal.SIGSTOP, [call.args[1] for call in signals.call_args_list])
        self.assertTrue(marker.exists(), "stopped descendant never handled TERM")
        self.assertIsNone(gate.pid_start(int(ready.read_text())))
        self.assertIsNone(gate.read_state(self.root))

    def test_compute_runs_beside_unknown_legacy_holder_reserving_native_lane(self):
        PriorityTests.hold_bridge(self)
        with mock.patch.object(gate, "legacy_bridge", side_effect=AssertionError("compute must not touch mutex")):
            self.assertEqual(gate.run_command(self.root, "compute", None, [sys.executable, "-c", "pass"],
                                             resource="compute", pause_safe=True), 0)
        for owner in ("one", "two"):
            gate.acquire(self.root, owner, os.getpid(), None, allow_bridge=True, compute_only=True)
        self.assertIsNone(gate.read_state(self.root))
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "three", os.getpid(), None, allow_bridge=True, compute_only=True)
        with self.assertRaises(gate.Busy):
            gate.run_command(self.root, "native", None, ["unused"], wait_seconds=0)

    def test_registered_native_counts_once_and_compute_primary_can_enter(self):
        PriorityTests.hold_bridge(self)
        gate.acquire(self.root, "native", os.getpid(), None, allow_bridge=True)
        gate.prioritize(self.root, "primary", 30, False)
        gate.acquire(self.root, "secondary", os.getpid(), None, allow_bridge=True, compute_only=True)
        gate.acquire(self.root, "primary", os.getpid(), None, allow_bridge=True, compute_only=True)
        self.assertEqual(sum(bool(gate.read_state(self.root, slot=s)) for s in gate.SLOTS), 3)

    def test_compute_keeps_pressure_and_simulator_guards(self):
        PriorityTests.hold_bridge(self)
        for probe, value in (("cpu_idle_percent", 1), ("memory_pressure_level", (2, "sysctl")),
                             ("observe_booted", [SIM])):
            with mock.patch.object(gate, probe, return_value=value):
                with self.assertRaises(gate.Busy):
                    gate.run_command(self.root, "compute", None, ["unused"], resource="compute", wait_seconds=0)
        with self.assertRaises(gate.GateError):
            gate.run_command(self.root, "compute", SIM, ["unused"], resource="compute")

    def test_legacy_directory_reserves_a_lane_without_bridge_and_ambiguity_defers(self):
        legacy = Path(self.tmp.name) / "legacy"
        (legacy / "slot.d").mkdir(parents=True)
        with mock.patch.object(gate, "legacy_slot_dir", return_value=legacy):
            for owner in ("one", "two"):
                gate.acquire(self.root, owner, os.getpid(), None, compute_only=True)
            self.assertIsNone(gate.read_state(self.root))
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "three", os.getpid(), None, compute_only=True)
            with mock.patch.object(gate, "bridge_paths", return_value=["/one"]):
                with self.assertRaisesRegex(gate.Busy, "multiple legacy lanes"):
                    gate.acquire(self.root, "three", os.getpid(), None, compute_only=True, allow_bridge=True)
        with mock.patch.object(gate, "bridge_paths", return_value=["/one", "/two"]):
            with self.assertRaisesRegex(gate.Busy, "multiple legacy lanes"):
                gate.acquire(self.root, "three", os.getpid(), None, compute_only=True, allow_bridge=True)


class PriorityAllowanceTests(unittest.TestCase):
    setUp = PriorityTests.setUp

    def run_payload(self, code="pass", **kwargs):
        return gate.run_command(self.root, "primary", None, [sys.executable, "-c", code],
                                wait_seconds=0, **kwargs)

    def test_priority_progresses_under_warning_or_cpu_contention(self):
        gate.prioritize(self.root, "primary", 30, False)
        for level, idle, load in ((2, 90, 0), (1, 2, 300), (2, 2, 300)):
            marker = Path(self.tmp.name) / "completed"
            with mock.patch.object(gate, "memory_pressure_level", return_value=(level, "sysctl")), \
                 mock.patch.object(gate, "cpu_idle_percent", return_value=idle), \
                 mock.patch.object(gate, "simulator_pressure", return_value=(load, 8)):
                self.assertEqual(self.run_payload("from pathlib import Path; Path(%r).touch()" % str(marker)), 0)
            self.assertTrue(marker.exists())
            marker.unlink()
            self.assertFalse(any(gate.read_state(self.root, slot=s) for s in gate.SLOTS))

    def test_allowed_live_payload_survives_transient_priority_state_lock(self):
        gate.prioritize(self.root, "primary", 30, False)
        marker = Path(self.tmp.name) / "completed"
        original = gate.check_priority_allowance
        ready = threading.Event()
        workers = []
        checks = []

        def hold():
            with gate.locked(self.root):
                ready.set()
                time.sleep(0.08)

        def check(root, owner, binding):
            checks.append(owner)
            if len(checks) == 1:
                worker = threading.Thread(target=hold)
                workers.append(worker)
                worker.start()
                self.assertTrue(ready.wait(1))
            return original(root, owner, binding)

        try:
            with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
                 mock.patch.object(gate, "RETRY_SECONDS", 1), \
                 mock.patch.object(gate, "CLEANUP_RETRY_SECONDS", 0.01), \
                 mock.patch.object(gate, "check_priority_allowance", side_effect=check):
                code = "from pathlib import Path; import time; time.sleep(0.3); Path(%r).touch()" % str(marker)
                self.assertEqual(self.run_payload(code), 0)
        finally:
            for worker in workers:
                worker.join(1)
        self.assertGreater(len(checks), 1)
        self.assertTrue(marker.exists())
        self.assertIsNone(gate.read_state(self.root))

    def test_memory_failure_during_lock_retry_stops_started_payload(self):
        for failure in ((4, "sysctl"), gate.ProbeFailed("unknown memory")):
            gate.prioritize(self.root, "primary", 30, False)
            marker = Path(self.tmp.name) / "started"
            checks = []
            original = gate.check_priority_allowance

            def check(root, owner, binding):
                checks.append(owner)
                if len(checks) == 1:
                    until = time.monotonic() + 2
                    while not marker.exists() and time.monotonic() < until:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists())
                    raise gate.StateLockBusy("contended")
                with mock.patch.object(gate, "memory_pressure_level", **(
                        {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure})):
                    return original(root, owner, binding)

            with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
                 mock.patch.object(gate, "check_priority_allowance", side_effect=check), \
                 mock.patch.object(gate, "CLEANUP_RETRY_SECONDS", 0.01):
                code = "from pathlib import Path; import time; Path(%r).touch(); time.sleep(30)" % str(marker)
                self.assertEqual(self.run_payload(code), gate.BUSY)
            self.assertEqual(len(checks), 2)
            self.assertIsNone(gate.read_state(self.root))
            marker.unlink()

    def test_allowance_uses_admission_proof_without_repeating_ownership_probe(self):
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
             mock.patch.object(gate, "RETRY_SECONDS", 0.05), \
             mock.patch.object(gate, "priority_matches", side_effect=[True, gate.GateError("ownership timeout")]) as match:
            self.assertEqual(self.run_payload("import time; time.sleep(0.25)"), 0)
        match.assert_called_once()

    def test_binding_allows_renewal_but_rejects_changed_or_unknown_scope(self):
        record = {"owner": "primary", "workspace": "/workspace", "expires": time.time() + 60}
        binding = gate.priority_binding(record)
        self.assertTrue(gate.bound_priority_matches(dict(record, expires=time.time() + 3600), binding))
        for replacement in (None, dict(record, owner="other"), dict(record, workspace="/other")):
            self.assertFalse(gate.bound_priority_matches(replacement, binding))
        with mock.patch.object(gate.Path, "cwd", side_effect=OSError("inaccessible")):
            with self.assertRaises(gate.GateError):
                gate.bound_priority_matches(record, binding)

    def test_warning_requires_supervision_and_one_machine_wide_allowance(self):
        gate.prioritize(self.root, "primary", 30, False)
        holder = gate.acquire(self.root, "secondary", os.getpid(), None)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")):
            self.assertEqual(self.run_payload(), 0)
            self.assertEqual(gate.read_state(self.root)["token"], holder)
            gate.release(self.root, holder)
            for owner, pending, says in (("primary", False, "needs a supervised foreground run"),
                                         ("secondary", True, "only the priority session")):
                with self.assertRaisesRegex(gate.Busy, says):
                    gate.acquire(self.root, owner, os.getpid(), None, child_pending=pending)
            first = gate.acquire(self.root, "primary", os.getpid(), None, child_pending=True)
            gate.prioritize(self.root, "replacement", 30, False)
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "replacement", os.getpid(), None, child_pending=True)
            self.assertEqual(gate.read_state(self.root)["token"], first)
            self.assertEqual(gate.allowance_token(self.root), first)
            gate.prioritize(self.root, "primary", 30, False)
            with self.assertRaisesRegex(gate.Busy, "priority allowance is held by holder=primary"):
                gate.acquire(self.root, "primary", os.getpid(), None, child_pending=True)

    def test_prioritized_simulator_run_with_stages_is_admitted_at_warning(self):
        gate.prioritize(self.root, "primary", 30, False)
        staged = [sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "5", "--", sys.executable, "-c", "pass"]
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
             mock.patch.object(gate, "shutdown_owned") as shutdown:
            self.assertEqual(gate.run_command(self.root, "primary", SIM, staged, wait_seconds=0), 0)
        shutdown.assert_called_once_with(SIM)
        self.assertIsNone(gate.read_state(self.root))
        self.assertIsNone(gate.allowance_token(self.root))

    def test_prioritized_simulator_run_is_refused_at_critical(self):
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(4, "sysctl")), \
             mock.patch.object(gate, "launch_granted") as launch:
            with self.assertRaisesRegex(gate.Busy, "waits until memory leaves critical"):
                gate.run_command(self.root, "primary", SIM, ["unused"], wait_seconds=0)
            launch.assert_not_called()
        self.assertIsNone(gate.read_state(self.root))

    def test_non_priority_simulator_run_still_defers_at_warning(self):
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
             mock.patch.object(gate, "launch_granted") as launch:
            with self.assertRaisesRegex(gate.Busy, "only the priority session"):
                gate.run_command(self.root, "secondary", SIM, ["unused"], wait_seconds=0)
            launch.assert_not_called()
        self.assertIsNone(gate.read_state(self.root))

    def test_compute_allowance_runs_beside_native_simulator_and_releases_only_itself(self):
        PriorityTests.hold_bridge(self)
        native = gate.acquire(self.root, "native", os.getpid(), SIM, allow_bridge=True)
        before = gate.read_state(self.root)
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]), \
             mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
             mock.patch.object(gate, "cpu_idle_percent", return_value=2):
            self.assertEqual(self.run_payload(resource="compute"), 0)
            self.assertEqual(gate.read_state(self.root), before)
            self.assertEqual(gate.read_state(self.root)["token"], native)
            self.assertIsNone(gate.allowance_token(self.root))

    def test_warning_never_exceeds_slot_cap(self):
        for owner in ("one", "two", "three"):
            gate.acquire(self.root, owner, os.getpid(), None)
        gate.prioritize(self.root, "primary", 30, False)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")):
            with self.assertRaisesRegex(gate.Busy, "all 3 heavy slots busy"):
                self.run_payload()
        self.assertIsNone(gate.allowance_token(self.root))

    def test_critical_fallback_and_unknown_never_launch_payload(self):
        gate.prioritize(self.root, "primary", 30, False)
        for value in ((4, "sysctl"), (2, "compressed-share")):
            with mock.patch.object(gate, "memory_pressure_level", return_value=value), \
                 mock.patch.object(gate, "launch_granted") as launch:
                with self.assertRaises(gate.Busy):
                    self.run_payload()
                launch.assert_not_called()
        for probe in ("memory_pressure_level", "cpu_idle_percent", "simulator_pressure"):
            with mock.patch.object(gate, probe, side_effect=gate.ProbeFailed("unknown")), \
                 mock.patch.object(gate, "launch_granted") as launch:
                with self.assertRaises(gate.Busy):
                    self.run_payload()
                launch.assert_not_called()

    def test_allowance_honours_max_min_and_releases_owned_group_at_it(self):
        gate.prioritize(self.root, "primary", 30, False)
        for resource in ("native", "compute"):
            err = io.StringIO()
            with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
                 contextlib.redirect_stderr(err):
                self.assertEqual(self.run_payload(max_seconds=7200, resource=resource), 0)
            self.assertIn("runs up to --max-min (7200 seconds)", err.getvalue())
            err = io.StringIO()
            with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
                 contextlib.redirect_stderr(err):
                self.assertEqual(self.run_payload("import time; time.sleep(30)", max_seconds=1, resource=resource),
                                 gate.TIMEOUT)
            self.assertIn("exceeded its --max-min limit of 1 seconds", err.getvalue())
            self.assertIsNone(gate.read_state(self.root))

    def test_critical_escalation_stops_only_the_started_owned_command(self):
        gate.prioritize(self.root, "primary", 30, False)
        marker = Path(self.tmp.name) / "started"
        readings = [(2, "sysctl")] * 3 + [(4, "sysctl")] * 10
        with mock.patch.object(gate, "memory_pressure_level", side_effect=readings), \
             mock.patch.object(gate, "RETRY_SECONDS", 0.05):
            code = "from pathlib import Path; import time; Path(%r).touch(); time.sleep(30)" % str(marker)
            self.assertEqual(self.run_payload(code), gate.BUSY)
        self.assertTrue(marker.exists())
        self.assertIsNone(gate.read_state(self.root))

    def test_expiry_during_allowance_stops_and_cleans_record(self):
        gate.prioritize(self.root, "primary", 0.002, False)
        with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")), \
             mock.patch.object(gate, "RETRY_SECONDS", 0.05):
            self.assertEqual(self.run_payload("import time; time.sleep(30)"), gate.BUSY)
        self.assertIsNone(gate.read_priority(self.root))
        self.assertIsNone(gate.read_state(self.root))

    def test_expired_or_cleared_priority_has_no_allowance(self):
        for clear in (False, True):
            gate.prioritize(self.root, "primary", 30, False)
            if clear:
                gate.prioritize(self.root, None, 30, True)
            else:
                record = gate.read_priority(self.root)
                record["expires"] = time.time() - 1
                gate.write_priority(self.root, record)
            with mock.patch.object(gate, "memory_pressure_level", return_value=(2, "sysctl")):
                with self.assertRaises(gate.Busy):
                    self.run_payload()
            self.assertIsNone(gate.read_priority(self.root))

    def test_wait_limit_error_names_minutes(self):
        with self.assertRaisesRegex(gate.GateError, r"--wait-min must be 0..60 minutes \(got 90\)"):
            gate.run_command(self.root, "primary", None, ["unused"], wait_seconds=90 * 60)

    def test_explicit_migration_preserves_priority_owner_and_expiry(self):
        gate.secure_root(self.root)
        old = {"owner": "primary", "expires": time.time() + 120}
        (self.root / "priority.json").write_text(json.dumps(old))
        self.assertIsNone(gate.read_priority(self.root)["workspace"])
        gate.migrate(self.root, self.tmp.name)
        self.assertEqual(gate.read_priority(self.root), dict(old, workspace=str(Path(self.tmp.name).resolve())))
        self.assertEqual(json.loads((self.root / "priority.json").read_text()), old)

    def test_old_supervisor_replacement_cannot_transfer_session_scope(self):
        gate.prioritize(self.root, "primary", 30, False, self.tmp.name)
        self.assertEqual(set(json.loads((self.root / "priority.json").read_text())), {"owner", "expires"})
        replacement = {"owner": "other", "expires": time.time() + 60}
        (self.root / "priority.json").write_text(json.dumps(replacement))
        self.assertIsNone(gate.read_priority(self.root)["workspace"])
        self.assertEqual((self.root / "priority-session.json").read_text(), "")

    def test_clear_and_expiry_remove_session_scope(self):
        for clear in (False, True):
            gate.prioritize(self.root, "primary", 30, False, self.tmp.name)
            if clear:
                gate.prioritize(self.root, None, 30, True)
            else:
                record = gate.read_priority(self.root)
                record["expires"] = time.time() - 1
                gate.write_priority(self.root, record)
            self.assertIsNone(gate.read_priority(self.root))
            self.assertEqual((self.root / "priority-session.json").read_text(), "")


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
        gate.write_claims(self.root, dict(gate.read_claims(self.root), **{udid: owner}),
                          {udid: "/w/" + owner})

    def test_old_label_only_claim_is_unknown_with_live_sessions_and_reclaimable_without_them(self):
        (self.root / "claims.json").write_text(json.dumps({SIM: "harbor"}))
        with self.assertRaisesRegex(gate.GateError, "workspace is unknown"):
            gate.reclaim_sim(self.root, SIM)
        self.assertEqual(gate.reclaim_hint(self.root, [None] * gate.HEAVY_SLOTS, SIM), "")
        self.assert_no_xcrun()
        self.assertEqual(gate.read_claims(self.root), {SIM: "harbor"})
        self.sessions = []
        gate.reclaim_sim(self.root, SIM)
        self.assertEqual(gate.read_claims(self.root), {})

    def test_claim_workspace_receipt_survives_other_claim_writes_and_cannot_be_rehomed(self):
        gate.write_claims(self.root, {SIM: "harbor"})
        self.assertEqual(gate.claim_workspace(self.root, SIM), "/w/harbor")
        with mock.patch.object(gate, "observe_booted", return_value=[]):
            gate.claim_sim(self.root, SIM, "harbor")
        self.assertEqual(gate.claim_workspace(self.root, SIM), "/w/harbor")
        gate.write_claims(self.root, {})
        self.assertIsNone(gate.claim_workspace(self.root, SIM))

    def test_new_claim_records_workspace_without_changing_owner_label_api(self):
        gate.write_claims(self.root, {})
        with mock.patch.object(gate, "observe_booted", return_value=[]):
            gate.claim_sim(self.root, SIM, "custom-owner")
        self.assertEqual(gate.read_claims(self.root), {SIM: "custom-owner"})
        workspace = gate.claim_workspace(self.root, SIM)
        self.assertTrue(Path(workspace).is_absolute())
        self.sessions = [workspace]
        with self.assertRaisesRegex(gate.GateError, "live session"):
            gate.reclaim_sim(self.root, SIM)
        self.assert_no_xcrun()

    def test_malformed_workspace_receipts_block_reclamation(self):
        for workspace in ("relative", "/w/../other", "/w/one\n/w/two", None):
            with self.subTest(workspace=workspace):
                (self.root / "claims.json").write_text(json.dumps({SIM: {"owner": "harbor", "workspace": workspace}}))
                with self.assertRaisesRegex(gate.GateError, "claims are corrupt"):
                    gate.reclaim_sim(self.root, SIM)
                self.assert_no_xcrun()

    def test_claim_without_git_workspace_keeps_unknown_provenance(self):
        gate.write_claims(self.root, {})
        with mock.patch.object(gate, "observe_booted", return_value=[]), \
             mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=128)):
            gate.claim_sim(self.root, SIM, "harbor")
        self.assertIsNone(gate.claim_workspace(self.root, SIM))
        with self.assertRaisesRegex(gate.GateError, "workspace is unknown"):
            gate.reclaim_sim(self.root, SIM)
        self.assert_no_xcrun()

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


class SessionOwnershipTests(unittest.TestCase):
    """Real Git topology, fake host processes and Docker: never touch a live stack."""

    def setUp(self):
        StackTests.setUp(self)
        self.base = Path(self.tmp.name).resolve()
        self.checkout = self.base / "parent checkout"
        self.nested = self.checkout / ".context/wt/child"
        self.sibling = self.base / "sibling"
        self.unrelated = self.checkout / ".context/wt/unrelated"
        self.git("init", "-q", str(self.checkout))
        message = self.base / "commit-message"
        message.write_text("fixture\n")
        self.git("-C", str(self.checkout), "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit", "-q", "--allow-empty", "-F", str(message))
        for target in (self.nested, self.sibling):
            self.git("-C", str(self.checkout), "worktree", "add", "-q", "--detach", str(target))
        self.git("init", "-q", str(self.unrelated))
        (self.checkout / "apps/api").mkdir(parents=True)

    running = StackTests.running

    def git(self, *args):
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args],
                              capture_output=True, text=True, check=True, timeout=10)

    def test_parent_protects_nested_stack_but_not_sibling_or_unrelated_repository(self):
        workspaces = [str(path) for path in (self.nested, self.sibling, self.unrelated)]
        self.running(*workspaces)
        self.host["activity"] = dict.fromkeys(workspaces, 0)
        self.host["sessions"] = [str(self.checkout / "apps/api")]
        lines = gate.stack_sweep(True)
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all("stopped idle stack " in line for line in lines))
        self.assertFalse(any(str(self.nested) in line for line in lines))
        commands = [call.args[0] for call in self.calls.call_args_list]
        self.assertFalse(any("label=com.supabase.cli.project=child" in command for command in commands))
        self.host["sessions"] = []
        self.assertEqual(len(gate.stack_sweep(False)), 3)

    def test_priority_covers_worker_labels_and_nested_worktrees_not_siblings(self):
        probe = mock.patch.object(gate, "observe_booted", return_value=[])
        probe.start()
        self.addCleanup(probe.stop)
        gate.prioritize(self.root, "session", 30, False, str(self.checkout))
        record = gate.read_priority(self.root)
        for workspace in (self.checkout, self.checkout / "apps/api", self.nested):
            with mock.patch.object(gate.Path, "cwd", return_value=workspace):
                self.assertTrue(gate.priority_matches(record, "different-worker-label"))
                token = gate.acquire(self.root, "different-worker-label", os.getpid(), None)
                self.assertEqual(gate.read_state(self.root)["owner"], "session")
                with self.assertRaisesRegex(gate.Busy, "one owner"):
                    gate.acquire(self.root, "second-worker", os.getpid(), None)
                gate.release(self.root, token)
        for workspace in (self.sibling, self.unrelated):
            with mock.patch.object(gate.Path, "cwd", return_value=workspace):
                self.assertFalse(gate.priority_matches(record, "session"), "a copied label cannot grant session priority")

    def test_parent_session_protects_nested_simulator_and_independent_owner_can_be_reclaimed(self):
        gate.secure_root(self.root)
        self.host["sessions"] = [str(self.checkout / "apps/api")]
        for workspace, retained in ((self.nested, True), (self.sibling, False), (self.unrelated, False)):
            with self.subTest(workspace=workspace):
                gate.write_claims(self.root, {SIM: workspace.name}, {SIM: str(workspace)})
                with mock.patch.object(gate, "probe_devices", return_value={SIM: "Booted"}), \
                     mock.patch.object(gate, "shutdown_owned") as shutdown:
                    if retained:
                        with self.assertRaisesRegex(gate.GateError, "live session"):
                            gate.reclaim_sim(self.root, SIM)
                        shutdown.assert_not_called()
                        self.assertEqual(gate.reclaim_hint(self.root, [None] * gate.HEAVY_SLOTS, SIM), "")
                    else:
                        gate.reclaim_sim(self.root, SIM)
                        shutdown.assert_called_once_with(SIM)

    def test_missing_nested_workspace_keeps_simulator_and_port_ownership_unknown(self):
        gate.secure_root(self.root)
        gate.write_claims(self.root, {SIM: "child"}, {SIM: str(self.nested)})
        self.host["sessions"] = [str(self.checkout)]
        self.git("-C", str(self.checkout), "worktree", "remove", str(self.nested))
        with mock.patch.object(gate, "shutdown_owned") as shutdown:
            with self.assertRaisesRegex(gate.GateError, "ownership probe failed"):
                gate.reclaim_sim(self.root, SIM)
            shutdown.assert_not_called()
        env = self.fake_host()
        retained = subprocess.run(["bash", str(gate.PORT_REGISTRY), "can-reap-workspace", str(self.nested)],
                                  env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(retained.returncode, 2, retained.stderr)

    def test_reap_requires_confirmed_absence_and_known_session_snapshot(self):
        env = self.fake_host()
        missing = self.base / "ended"
        broken = self.base / "broken"
        broken.symlink_to(self.base / "absent-target")
        for path, expected in ((missing, 0), (self.nested, 1), (broken, 2)):
            result = subprocess.run(["bash", str(gate.PORT_REGISTRY), "can-reap-workspace", str(path)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected, (path, result.stderr))
        (self.base / "fake-bin/ps").write_text("#!/bin/sh\nexit 1\n")
        result = subprocess.run(["bash", str(gate.PORT_REGISTRY), "can-reap-workspace", str(missing)],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    @unittest.skipIf(os.getuid() == 0, "root bypasses directory permissions")
    def test_reap_retains_an_inaccessible_workspace(self):
        env = self.fake_host()
        self.checkout.chmod(0)
        try:
            result = subprocess.run(["bash", str(gate.PORT_REGISTRY), "can-reap-workspace", str(self.nested)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
        finally:
            self.checkout.chmod(0o755)

    def test_port_sweep_rechecks_every_row_and_never_signals_live_or_unknown_owners(self):
        env = self.fake_host()
        missing = self.base / "ended"
        broken = self.base / "broken"
        broken.symlink_to(self.base / "absent-target")
        self.git("-C", str(self.checkout), "worktree", "remove", str(self.nested))
        signals = self.base / "signals"
        env.update({"SIGNALS": str(signals), "TMP": str(self.base), "REGISTRY_SH": str(gate.PORT_REGISTRY)})
        (self.base / "fake-bin/lsof").write_text("""#!/bin/sh
case "$*" in
  *-iTCP:*)
    case "$*" in
      *-iTCP:39001*) [ ! -f "$SIGNALS" ] || exit 1; printf '990001\\n' ;;
      *) printf '990002\\n' ;;
    esac ;;
  *) cat "$FIXTURE_CWDS" ;;
esac
""")
        pgrep = self.base / "fake-bin/pgrep"
        pgrep.write_text("#!/bin/sh\nexit 1\n")
        pgrep.chmod(0o755)
        registry = Path(env["PORT_REGISTRY_FILE"])
        registry.write_text("## Held\n\n" + "".join(
            "| %s | %s | %s | fixture | 2000-01-01T00:00:00Z | - |\n" % (port, path.name, path)
            for port, path in ((39001, missing), (39002, self.nested), (39003, broken))) + "\n## Waiting\n")
        # Evaluate the real sweep functions only: all signals are intercepted, and unrelated
        # lane discovery and runtime logging cannot touch this machine's config.
        source = SCRIPT.with_name("port-slot.sh").read_text()
        sweep = source.split("# --- the sweep ", 1)[1].split("# --- logging ", 1)[0]
        sweep = sweep[sweep.index("\n") + 1:]
        program = """set -u
TAB="$(printf '\\t')"
QUIET=1
say() { :; }
kill() { printf '%s\\n' "$*" >> "$SIGNALS"; }
sleep() { :; }
""" + sweep + "\nsweep\n"
        result = subprocess.run(["bash"], input=program, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(signals.read_text().splitlines(), ["-TERM 990001"])
        self.assertIn(str(self.nested), registry.read_text())
        self.assertIn(str(broken), registry.read_text())

    def test_port_sweep_retains_a_claim_when_owner_probe_becomes_unknown_before_signalling(self):
        fake = self.base / "registry"
        fake.write_text("""#!/bin/sh
case "$1" in
  reap) exit 5 ;;
  list) printf '39001\\tended\\t/absent/ended\\tfixture\\t2000-01-01T00:00:00Z\\t990001\\n' ;;
  can-reap-workspace) exit 2 ;;
  *) exit 91 ;;
esac
""")
        fake.chmod(0o755)
        source = SCRIPT.with_name("port-slot.sh").read_text()
        sweep = source.split("# --- the sweep ", 1)[1].split("# --- logging ", 1)[0]
        sweep = sweep[sweep.index("\n") + 1:]
        # A regression reaching kill_orphan_on_port is observed before any host probe or signal.
        program = "TAB=\"$(printf '\\t')\"\nQUIET=1\nsay() { :; }\n" + sweep
        program += '\nkill_orphan_on_port() { printf "UNSAFE\\n"; }\nsweep\n'
        result = subprocess.run(["bash"], input=program, env={**os.environ, "REGISTRY_SH": str(fake),
                                "TMP": str(self.base)}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("UNSAFE", result.stdout)

    def test_nested_session_does_not_protect_a_sibling_nested_worktree(self):
        other = self.checkout / ".context/wt/other"
        self.git("-C", str(self.checkout), "worktree", "add", "-q", "--detach", str(other))
        self.assertFalse(gate.session_owns_workspace(str(other), [str(self.nested)]))
        self.assertTrue(gate.session_owns_workspace(str(self.nested), [str(self.nested)]))

    def test_acquire_keeps_live_parent_stacks_and_still_enforces_the_cap(self):
        other = self.checkout / ".context/wt/other"
        self.git("-C", str(self.checkout), "worktree", "add", "-q", "--detach", str(other))
        self.running(str(self.nested), str(other))
        self.host["sessions"] = [str(self.checkout)]
        with self.assertRaisesRegex(gate.Busy, "2 of 2 local dev stacks in use"):
            gate.stack_acquire(self.root, "new-task", str(self.base / "new-task"))
        self.calls.assert_not_called()

    def test_parent_directory_and_prefix_neighbor_do_not_own_nested_worktree(self):
        neighbor = self.base / "parent checkout-extra"
        neighbor.mkdir()
        for cwd in (self.base, neighbor):
            self.assertFalse(gate.session_owns_workspace(str(self.nested), [str(cwd)]))

    def test_symlinked_parent_resolves_to_the_same_nested_ownership(self):
        alias = self.base / "alias"
        alias.symlink_to(self.checkout, target_is_directory=True)
        self.assertTrue(gate.session_owns_workspace(str(self.nested), [str(alias / "apps/api")]))

    @unittest.skipIf(os.getuid() == 0, "root bypasses directory permissions")
    def test_unreadable_workspace_is_unknown_instead_of_unowned(self):
        self.nested.chmod(0)
        try:
            with self.assertRaisesRegex(gate.GateError, "ownership probe failed"):
                gate.session_owns_workspace(str(self.nested), [str(self.checkout)])
        finally:
            self.nested.chmod(0o755)

    def fake_host(self):
        binaries = self.base / "fake-bin"
        binaries.mkdir()
        ps = binaries / "ps"
        ps.write_text("""#!/bin/sh
[ "$*" = '-axo pid=,comm=' ] || exit 91
cat <<'ROWS'
101 /Applications/Agent Host/bin/claude
102 claude
103 /Applications/Agent Host/bin/codex
104 codex
105 /Applications/Claude.app/Claude Helper
106 /bin/zsh
107 codex-helper
ROWS
""")
        lsof = binaries / "lsof"
        lsof.write_text("""#!/bin/sh
case "$*" in
  '-a -p 101,102,103,104 -d cwd -Fn') cat "$FIXTURE_CWDS" ;;
  *-iTCP:*) exit 0 ;;
  *) exit 92 ;;
esac
""")
        for binary in (ps, lsof):
            binary.chmod(0o755)
        cwds = self.base / "cwds"
        cwds.write_text("p101\nn%s\np102\nn%s\np103\nn%s\np104\nn%s\n" % (
            self.checkout, self.checkout, self.checkout / "apps/api", self.checkout / "apps/api"))
        return {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "FIXTURE_CWDS": str(cwds), "PORT_REGISTRY_FILE": str(self.base / "ports.md")}

    def test_detector_recognizes_native_hosts_without_arguments_and_reconcile_retains_child_lane(self):
        env = self.fake_host()
        sessions = subprocess.run(["bash", str(gate.PORT_REGISTRY), "sessions"],
                                  env=env, capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(set(sessions.stdout.splitlines()), {str(self.checkout), str(self.checkout / "apps/api")})
        # Use only the Codex cwd to prove that host alone protects the nested lane.
        (self.base / "fake-bin/ps").write_text("#!/bin/sh\nprintf '103 codex\\n'\n")
        (self.base / "fake-bin/lsof").write_text("#!/bin/sh\ncase \"$*\" in\n"
                                              "  *-iTCP:*) exit 0 ;;\n"
                                              "  *) cat \"$FIXTURE_CWDS\" ;;\nesac\n")
        Path(env["FIXTURE_CWDS"]).write_text("p103\nn%s\n" % self.checkout)
        registry = Path(env["PORT_REGISTRY_FILE"])
        registry.write_text("## Held\n\n" + "".join(
            "| %s | %s | %s | fixture | 2000-01-01T00:00:00Z | - |\n" % (port, path.name, path)
            for port, path in ((39001, self.nested), (39002, self.sibling), (39003, self.unrelated))) + "\n## Waiting\n")
        rows = subprocess.run(["bash", str(gate.PORT_REGISTRY), "list", "--tsv"],
                              env=env, capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(len(rows.stdout.splitlines()), 1, rows.stdout)
        self.assertIn(str(self.nested), rows.stdout)
        self.assertNotIn(str(self.sibling), registry.read_text())

    def test_failed_ownership_probe_prevents_reclamation(self):
        self.running(str(self.nested))
        self.host["sessions"] = [str(self.checkout)]
        with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=2)):
            with self.assertRaisesRegex(gate.GateError, "ownership probe failed"):
                gate.stack_sweep(True)
        self.calls.assert_not_called()

    def test_failed_process_probes_and_missing_cwds_are_unknown_and_keep_claims(self):
        env = self.fake_host()
        ps = self.base / "fake-bin/ps"
        lsof = self.base / "fake-bin/lsof"
        original_ps, original_lsof = ps.read_text(), lsof.read_text()
        cases = (("ps failure", "#!/bin/sh\nexit 1\n", original_lsof),
                 ("lsof failure", original_ps, "#!/bin/sh\nexit 1\n"),
                 ("empty lsof", original_ps, "#!/bin/sh\nexit 0\n"),
                 ("missing cwd", original_ps, "#!/bin/sh\nprintf 'p101\\nn/tmp\\np102\\n'\n"))
        for label, ps_text, lsof_text in cases:
            with self.subTest(label=label):
                ps.write_text(ps_text)
                lsof.write_text(lsof_text.replace("#!/bin/sh\n", "#!/bin/sh\ncase \"$*\" in *-iTCP:*) exit 0 ;; esac\n", 1))
                result = subprocess.run(["bash", str(gate.PORT_REGISTRY), "sessions"],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                registry = Path(env["PORT_REGISTRY_FILE"])
                registry.write_text("## Held\n| 39001 | child | %s | fixture | 2000-01-01T00:00:00Z | - |\n" % self.nested)
                rows = subprocess.run(["bash", str(gate.PORT_REGISTRY), "list", "--tsv"],
                                      env=env, capture_output=True, text=True, check=True, timeout=10)
                self.assertIn(str(self.nested), rows.stdout)
                self.assertIn("ownership unknown", rows.stderr)
        ps.write_text("#!/bin/sh\nprintf '101 codex-helper\\n102 /bin/zsh\\n'\n")
        result = subprocess.run(["bash", str(gate.PORT_REGISTRY), "sessions"],
                                env=env, capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(result.stdout, "")  # A successful empty snapshot is genuinely unowned.

    def test_failed_git_probe_for_nested_candidate_prevents_sweep_and_keeps_port(self):
        env = self.fake_host()
        real_git = shutil.which("git")
        fake_git = self.base / "fake-bin/git"
        fake_git.write_text("#!/usr/bin/env python3\nimport os, sys\n"
                            "if '--git-common-dir' in sys.argv: sys.exit(1)\n"
                            "os.execv(%r, [%r, *sys.argv[1:]])\n" % (real_git, real_git))
        fake_git.chmod(0o755)
        self.running(str(self.nested))
        self.host["sessions"] = [str(self.checkout)]
        with mock.patch.dict(os.environ, env):
            with self.assertRaisesRegex(gate.GateError, "ownership probe failed"):
                gate.stack_sweep(True)
        self.calls.assert_not_called()
        registry = Path(env["PORT_REGISTRY_FILE"])
        registry.write_text("## Held\n| 39001 | child | %s | fixture | 2000-01-01T00:00:00Z | - |\n" % self.nested)
        rows = subprocess.run(["bash", str(gate.PORT_REGISTRY), "list", "--tsv"],
                              env=env, capture_output=True, text=True, check=True, timeout=10)
        self.assertIn(str(self.nested), rows.stdout)
        self.assertIn("ownership unknown", rows.stderr)


if __name__ == "__main__":
    unittest.main()
