#!/usr/bin/env python3
"""Offline tests for the cooperative capacity lease."""

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
        self.assertEqual(set(json.loads(data)), {"owner", "pid", "pid_start", "simulator", "token", "created", "child"})
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
        with mock.patch.object(gate, "observe_booted", side_effect=[[], [SIM]]):
            self.assertEqual(gate.run_command(self.root, "mine", SIM, [sys.executable, "-c", "pass"]), gate.BUSY)
        self.assertIsNotNone(gate.read_state(self.root))

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

    def test_real_run_signal_retains_receipt_and_stops_group(self):
        code = ("import importlib.util,sys; from pathlib import Path; from unittest import mock; "
                "s=importlib.util.spec_from_file_location('g',sys.argv[1]); "
                "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); "
                "p=mock.patch.object(g,'observe_booted',return_value=[]); p.start(); "
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
            self.assertEqual(gate.read_state(self.root)["child"], lease["child"])
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.wait()


if __name__ == "__main__":
    unittest.main()
