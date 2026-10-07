#!/usr/bin/env python3
"""Focused tests for the local report store."""

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid


SCRIPT = Path(__file__).with_name("session-performance.py")


class ReportStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.batch = "incident"

    def run_cli(self, *arguments, ok=True, env=None):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--batch", self.batch, *arguments],
            capture_output=True, text=True, timeout=8, env=env,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return json.loads(result.stderr)

    def register(self, session_id=None):
        return self.run_cli("register", "--id", session_id or str(uuid.uuid4()),
                            "--workspace", "/tmp/workspace", "--branch", "main", "--task", "task")

    def test_registration_and_partial_files(self):
        registered = self.register()
        session_id = registered["id"]
        again = self.register(session_id)
        self.assertTrue(again["existing"])
        folder = self.root / self.batch / session_id
        (folder / "report.md.tmp").write_text("unfinished")
        state = self.run_cli("status", "--expected", "6")
        self.assertEqual(state["registered"], 1)
        self.assertEqual(state["complete"], 0)
        self.assertEqual(state["missingRegistrations"], 5)
        self.assertEqual(state["missingReports"], 6)
        self.assertFalse(state["allComplete"])
        self.run_cli("register", "--id", session_id, "--workspace", "/tmp/other",
                     "--branch", "main", "--task", "task", ok=False)

    def test_concurrent_publish_keeps_first_report_and_addendum_is_pending(self):
        session_id = self.register()["id"]
        first = self.root / "first.md"
        second = self.root / "second.md"
        first.write_text("first evidence\n")
        second.write_text("second evidence\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda path: subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(self.root), "--batch", self.batch,
                 "publish", "--id", session_id, "--file", str(path)],
                capture_output=True, text=True, timeout=8), (first, second)))
        self.assertEqual(sorted(result.returncode for result in results), [0, 1])
        report = self.root / self.batch / session_id / "report.md"
        self.assertIn(report.read_text(), ("first evidence\n", "second evidence\n"))
        digest = self.run_cli("status", "--expected", "1")["sessions"][0]["reports"][0]["sha256"]
        self.run_cli("reviewed", "--id", session_id, "--sha256", digest)
        self.assertEqual(self.run_cli("status", "--expected", "1")["pendingReviewSessions"], 0)
        addendum = self.run_cli("publish", "--id", session_id, "--file", str(second), "--addendum")
        self.assertTrue(Path(addendum["path"]).name.startswith("addendum-"))
        state = self.run_cli("status", "--expected", "1")
        self.assertEqual(state["complete"], 1)
        self.assertEqual(state["pendingReviewSessions"], 1)
        self.assertFalse(state["allComplete"])
        self.run_cli("reviewed", "--id", session_id, "--report", Path(addendum["path"]).name,
                     "--sha256", addendum["sha256"])
        self.assertTrue(self.run_cli("status", "--expected", "1")["allComplete"])

    def test_external_registration_and_changed_content_need_review(self):
        session_id = str(uuid.uuid4())
        folder = self.root / self.batch / session_id
        folder.mkdir(parents=True)
        (folder / "registration.json").write_text('{"workspace":"/tmp/other"}')
        report = folder / "report.md"
        report.write_text("outside participant report")
        self.assertEqual(self.run_cli("status", "--expected", "1")["complete"], 1)
        digest = self.run_cli("status", "--expected", "1")["sessions"][0]["reports"][0]["sha256"]
        self.run_cli("reviewed", "--id", session_id, "--sha256", digest)
        report.write_text("late correction")
        state = self.run_cli("status", "--expected", "1")
        self.assertEqual(state["pendingReviewSessions"], 1)

    def test_rejects_ids_symlinks_and_does_not_fabricate_snapshot(self):
        self.run_cli("register", "--id", "../outside", "--workspace", "/tmp/workspace",
                     "--branch", "main", "--task", "task", ok=False)
        self.register()
        outside = self.root / "outside"
        outside.mkdir()
        link_id = str(uuid.uuid4())
        (self.root / self.batch / link_id).symlink_to(outside, target_is_directory=True)
        self.run_cli("snapshot", "--id", link_id, ok=False)
        session_id = next(path.name for path in (self.root / self.batch).iterdir() if path.is_dir() and not path.is_symlink())
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        for name, output in (("ps", "1 0 1.5 0.1 01:02 launchd\n2 1 91.2 4.0 00:05 build\n"),
                             ("xcrun", '{"devices":{}}\n'), ("sysctl", "8\n")):
            command = fake_bin / name
            command.write_text("#!/bin/sh\nprintf '%s' '" + output + "'\n")
            command.chmod(0o700)
        fake_env = {**os.environ, "PATH": str(fake_bin)}
        result = self.run_cli("snapshot", "--id", session_id, env=fake_env)
        data = json.loads(Path(result["path"]).read_text())
        self.assertIn("observedAt", data)
        self.assertIn("loadAverage", data)
        self.assertIn("available", data["bootedSimulators"])
        processes = data["processes"]["processes"]
        self.assertEqual([process["pid"] for process in processes], [2, 1])
        self.assertEqual(processes[0]["cpuPercent"], 91.2)
        self.assertEqual(processes[0]["ppid"], 1)
        self.assertEqual(processes[0]["elapsed"], "00:05")
        self.assertEqual(data["hardware"]["hw.ncpu"], 8)
        self.assertNotIn("args", json.dumps(data))
        (fake_bin / "xcrun").write_text("#!/bin/sh\nprintf '[]'\n")
        invalid = self.run_cli("snapshot", "--id", session_id, env=fake_env)
        invalid_data = json.loads(Path(invalid["path"]).read_text())
        self.assertFalse(invalid_data["bootedSimulators"]["available"])

    def test_review_requires_observed_hash_and_corrupt_participant_isolated(self):
        good = self.register()["id"]
        report = self.root / "sample.md"
        report.write_text("observed")
        published = self.run_cli("publish", "--id", good, "--file", str(report))
        self.run_cli("reviewed", "--id", good, "--sha256", "0" * 64, ok=False)
        self.run_cli("reviewed", "--id", good, "--sha256", published["sha256"])
        bad = self.root / self.batch / str(uuid.uuid4())
        bad.mkdir()
        (bad / "registration.json").write_text("[]")
        (bad / "report.md").write_text("untrusted")
        state = self.run_cli("status", "--expected", "2")
        self.assertEqual(state["complete"], 1)
        self.assertTrue(any("error" in session for session in state["sessions"]))
        self.assertFalse(state["allComplete"])

    def test_symlinked_ancestor_and_invalid_addenda_are_ignored(self):
        session_id = self.register()["id"]
        folder = self.root / self.batch / session_id
        (folder / "bad addendum.md").write_text("invalid name")
        (folder / "report.md").symlink_to(self.root / "outside.md")
        state = self.run_cli("status", "--expected", "1")
        self.assertFalse(state["allComplete"])
        self.assertTrue(state["sessions"][0]["warnings"])
        link = self.root / "root-link"
        link.symlink_to(self.root / self.batch, target_is_directory=True)
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(link / ".."),
                                 "--batch", self.batch, "status"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(link),
                                 "--batch", self.batch, "status"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
