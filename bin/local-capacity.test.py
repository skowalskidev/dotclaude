#!/usr/bin/env python3
"""Offline tests for the cooperative capacity lease."""

import importlib.util
import fcntl
import json
import multiprocessing
import os
import signal
import fcntl
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


def competing(root, queue, event):
    with mock.patch.object(gate, "observe_booted", return_value=[]):
        event.wait()
        try:
            queue.put(("ok", gate.acquire(Path(root), "competitor", os.getpid(), None)))
        except gate.Busy:
            queue.put(("busy", ""))


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

    def test_competing_processes_get_one_slot(self):
        ctx = multiprocessing.get_context("fork")
        queue, event = ctx.Queue(), ctx.Event()
        children = [ctx.Process(target=competing, args=(str(self.root), queue, event)) for _ in range(2)]
        for child in children:
            child.start()
        event.set()
        answers = [queue.get(timeout=10) for _ in children]
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sorted(item[0] for item in answers), ["busy", "ok"])
        self.assertEqual(gate.read_state(self.root)["token"], next(value for kind, value in answers if kind == "ok"))

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
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "another", os.getpid(), None)
        gate.release(self.root, token)

    def test_pid_reuse_is_visible(self):
        gate.acquire(self.root, "mine", os.getpid(), None)
        lease = gate.read_state(self.root)
        lease["pid_start"] = "old process start"
        gate.write_state(self.root, lease)
        self.assertIn("PID reused", gate.holder_text(lease))
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "other", os.getpid(), None)

    def test_foreign_booted_simulator_and_probe_failure_block(self):
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "mine", os.getpid(), SIM)
        with mock.patch.object(gate, "observe_booted", side_effect=gate.GateError("probe failed")):
            with self.assertRaises(gate.GateError):
                gate.acquire(self.root, "mine", os.getpid(), None)
        self.assertIsNone(gate.read_state(self.root))

    def test_load_preflight_blocks_every_heavy_command(self):
        with mock.patch.object(gate, "simulator_pressure", return_value=(17, 8)):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "build", os.getpid(), None)
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
        for name, value in (("observe_booted", []), ("simulator_pressure", (0, 8))):
            patch = mock.patch.object(gate, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def cli(self, *args, load=0):
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / "booted.json").write_text('{"devices":{}}')
        (self.root / "pressure.json").write_text(json.dumps({"load": load, "cores": 8}))
        env = dict(os.environ, LOCAL_CAPACITY_SIMCTL_JSON=str(self.root / "booted.json"),
                   LOCAL_CAPACITY_PRESSURE_JSON=str(self.root / "pressure.json"))
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
        self.assertEqual(gate.read_state(self.root, slot=gate.PRIORITY_SLOT)["token"], token)
        with self.assertRaises(gate.Busy):
            gate.acquire(self.root, "vip", os.getpid(), None)
        gate.release(self.root, holder)
        self.assertEqual(gate.read_state(self.root, slot=gate.PRIORITY_SLOT)["token"], token)
        gate.release(self.root, token)
        self.assertIsNone(gate.read_state(self.root, slot=gate.PRIORITY_SLOT))

    def test_priority_owner_skips_the_load_gate_and_others_keep_it(self):
        gate.prioritize(self.root, "vip", 30, False)
        with mock.patch.object(gate, "simulator_pressure", return_value=(52.5, 8)):
            token = gate.acquire(self.root, "vip", os.getpid(), None)
        self.assertEqual(gate.read_state(self.root)["token"], token)
        gate.release(self.root, token)
        gate.prioritize(self.root, None, 0, True)
        with mock.patch.object(gate, "simulator_pressure", return_value=(52.5, 8)):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "other", os.getpid(), None)

    def test_other_owner_is_deferred_with_the_priority_message_even_when_free(self):
        self.assertEqual(self.cli("prioritize", "--owner", "vip", "--minutes", "30").returncode, 0)
        deferred = self.cli("run", "--owner", "other", "--", sys.executable, "-c", "pass")
        self.assertEqual(deferred.returncode, gate.BUSY)
        self.assertIn("priority owner is vip until", deferred.stderr)
        self.assertIsNone(gate.read_state(self.root))
        self.assertEqual(self.cli("run", "--owner", "vip", "--", sys.executable, "-c", "pass").returncode, 0)

    def test_both_slots_busy_defers_even_the_priority_owner(self):
        gate.acquire(self.root, "holder", os.getpid(), None)
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

    def test_status_prints_the_record_only_while_it_is_live(self):
        self.assertNotIn("priority", self.cli("status").stdout)
        self.cli("prioritize", "--owner", "vip", "--minutes", "30")
        lines = [line for line in self.cli("status").stdout.splitlines() if line.startswith("priority: ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("vip until", lines[0])
        self.cli("prioritize", "--clear")
        self.assertNotIn("priority", self.cli("status").stdout)

    def test_priority_owner_cannot_take_the_holders_simulator(self):
        gate.acquire(self.root, "holder", os.getpid(), SIM)
        gate.prioritize(self.root, "vip", 30, False)
        with mock.patch.object(gate, "observe_booted", return_value=[SIM]):
            with self.assertRaises(gate.Busy):
                gate.acquire(self.root, "vip", os.getpid(), SIM)
            token = gate.acquire(self.root, "vip", os.getpid(), None)
            gate.release(self.root, token)

    def test_priority_run_passes_a_legacy_lock_held_by_another_run_and_stages_work(self):
        self.hold_bridge()
        holder = gate.acquire(self.root, "holder", os.getpid(), None, allow_bridge=True)
        with self.assertRaises(gate.Busy):
            gate.run_command(self.root, "other", None, [sys.executable, "-c", "pass"])
        gate.prioritize(self.root, "vip", 30, False)
        staged = [sys.executable, str(SCRIPT), "stage", "--timeout-seconds", "5", "--", sys.executable, "-c", "pass"]
        self.assertEqual(gate.run_command(self.root, "vip", None, staged), 0)
        self.assertIsNone(gate.read_state(self.root, slot=gate.PRIORITY_SLOT))
        self.assertEqual(gate.read_state(self.root)["token"], holder)

    def test_legacy_lock_without_a_capacity_holder_still_blocks_the_priority_owner(self):
        self.hold_bridge()
        gate.prioritize(self.root, "vip", 30, False)
        with self.assertRaises(gate.Busy):
            gate.run_command(self.root, "vip", None, [sys.executable, "-c", "pass"])
        self.assertIsNone(gate.read_state(self.root))


if __name__ == "__main__":
    unittest.main()
