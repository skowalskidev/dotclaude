#!/usr/bin/env python3
"""Offline tests for the landing lock in bin/config-land-check.py.

Standard library only. Each case builds a throwaway ~/.claude repo (HOME points at a temp dir) with
a bare origin, a stub contract suite and a stub secret scan, so nothing touches the real config, its
lock or the network. Covers: two landers serialize and both land; a waiter names the holder; the
bounded wait ends non-zero; a killed holder releases the lock.
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "config-land-check.py"
spec = importlib.util.spec_from_file_location("config_land_check", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAILS = []
STUB_SUITE = """import os, sys, time
log = os.environ.get("STUB_SUITE_LOG")
if log:
    with open(log, "a") as f:
        f.write(f"start {os.getcwd()} {time.time()}\\n")
time.sleep(float(os.environ.get("STUB_SUITE_SLEEP", "0")))
if log:
    with open(log, "a") as f:
        f.write(f"end {os.getcwd()} {time.time()}\\n")
"""


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


class Repo:
    """A temp HOME whose ~/.claude is a git repo with a bare origin and stub checks."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.home = self.tmp / "home"
        self.config = self.home / ".claude"
        self.origin = self.tmp / "origin.git"
        self.config.mkdir(parents=True)
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.config, "init", "-q", "-b", "main")
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"),
                           ("commit.gpgsign", "false")):
            git(self.config, "config", key, value)
        (self.config / "hooks").mkdir()
        (self.config / "hooks" / "config-contract.test.py").write_text(STUB_SUITE)
        (self.config / "dotfiles").mkdir()
        (self.config / "dotfiles" / "secret-scan.sh").write_text("exit 0\n")
        git(self.config, "add", "-A")
        git(self.config, "commit", "-q", "-m", "chore: seed")
        git(self.config, "remote", "add", "origin", str(self.origin))
        git(self.config, "push", "-q", "origin", "main")
        self.lock = Path(git(self.config, "rev-parse", "--path-format=absolute", "--git-common-dir")) / mod.LOCK

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(HOME=str(self.home), **extra)
        return env

    def worktree(self, name, filename):
        path = self.tmp / name
        git(self.config, "fetch", "-q", "origin")
        git(self.config, "worktree", "add", "-q", "-b", f"config-update/{name}", str(path), "origin/main")
        (path / filename).write_text(f"{name}\n")
        git(path, "add", filename)
        git(path, "commit", "-q", "-m", f"fix({name}): add {filename}")
        return path

    def run(self, root, *extra, **env):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *extra],
                              capture_output=True, text=True, env=self.env(**env))

    def popen(self, root, *extra, **env):
        return subprocess.Popen([sys.executable, str(SCRIPT), "--root", str(root), *extra],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env(**env))

    def digest(self, root):
        shown = self.run(root, "--diff")
        line = [ln for ln in shown.stdout.splitlines() if ln.startswith("diff-sha256: ")]
        if shown.returncode or not line:
            raise RuntimeError(f"--diff failed: {shown.stderr}")
        return line[-1].split()[-1]

    def origin_main(self):
        return git(self.origin, "rev-parse", "main")

    def hold(self, seconds):
        """A separate process holding the lock through the module's own writer, as a lander would."""
        code = ("import importlib.util, sys, time\n"
                "spec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "with m.landing_lock(sys.argv[2], 5, {'root': '/held/root', 'branch': 'config-update/holder'}):\n"
                "    print('held', flush=True); time.sleep(float(sys.argv[3]))\n")
        p = subprocess.Popen([sys.executable, "-c", code, str(SCRIPT), str(self.lock), str(seconds)],
                             stdout=subprocess.PIPE, text=True)
        if p.stdout.readline().strip() != "held":
            raise RuntimeError("holder never took the lock")
        return p


def wait_for_holder(lock, pid, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if json.loads(lock.read_text() or "{}").get("pid") == pid:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    return False


def test_two_landers_serialize_and_both_land():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        a, b = repo.worktree("alpha", "a.txt"), repo.worktree("beta", "b.txt")
        da, db = repo.digest(a), repo.digest(b)
        log = Path(tmp) / "suite.log"
        first = repo.popen(a, "--reviewed", da, STUB_SUITE_SLEEP="2", STUB_SUITE_LOG=str(log))
        check(wait_for_holder(repo.lock, first.pid), "serialize: the first lander never recorded itself as holder")
        second = repo.popen(b, "--reviewed", db, "--lock-wait", "60", STUB_SUITE_SLEEP="0", STUB_SUITE_LOG=str(log))
        out_a, err_a = first.communicate(timeout=60)
        out_b, err_b = second.communicate(timeout=60)
        check(first.returncode == 0, f"serialize: first lander failed: {err_a}")
        check(second.returncode == 0, f"serialize: second lander failed instead of queueing: {err_b}")
        check(f"held by pid {first.pid} (config-update/alpha at {a})" in err_b,
              f"serialize: the waiter did not name the holder, its branch and root: {err_b!r}")
        check(" since " in err_b, f"serialize: the waiter did not say since when: {err_b!r}")
        check(f"merged origin/main" in err_b, f"serialize: the second lander did not merge the first landing: {err_b!r}")
        head_b = git(b, "rev-parse", "HEAD")
        check(repo.origin_main() == head_b, "serialize: origin main is not the second lander's merged head")
        check(git(repo.origin, "merge-base", "--is-ancestor", git(a, "rev-parse", "HEAD"), "main") == "",
              "serialize: the first landing is missing from origin main")
        events = [ln.split()[0] for ln in log.read_text().splitlines()]
        check(events == ["start", "end", "start", "end"], f"serialize: the two suites overlapped: {events}")
        check(repo.lock.read_text() == "", "serialize: the released lock still names a holder")


def test_timeout_ends_non_zero_and_names_holder():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        wt = repo.worktree("gamma", "c.txt")
        digest, before = repo.digest(wt), repo.origin_main()
        holder = repo.hold(30)
        try:
            started = time.monotonic()
            result = repo.run(wt, "--reviewed", digest, "--lock-wait", "1.5")
            elapsed = time.monotonic() - started
        finally:
            holder.kill()
            holder.wait()
        check(result.returncode == mod.EXIT_LOCK_TIMEOUT,
              f"timeout: expected exit {mod.EXIT_LOCK_TIMEOUT}, got {result.returncode}: {result.stderr}")
        check(f"held by pid {holder.pid} (config-update/holder at /held/root)" in result.stderr
              and "TIMEOUT" in result.stderr, f"timeout: the message did not name the holder: {result.stderr!r}")
        check(f"waiting for the landing lock held by pid {holder.pid}" in result.stderr,
              f"timeout: no waiting line while queued: {result.stderr!r}")
        check(1.4 <= elapsed < 15, f"timeout: the bounded wait took {elapsed:.1f} s for a 1.5 s bound")
        check(repo.origin_main() == before, "timeout: a lander that never held the lock pushed")


def test_killed_holder_releases_the_lock():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        wt = repo.worktree("delta", "d.txt")
        digest = repo.digest(wt)
        holder = repo.hold(300)
        os.kill(holder.pid, signal.SIGKILL)
        holder.wait()
        started = time.monotonic()
        result = repo.run(wt, "--reviewed", digest, "--lock-wait", "30")
        elapsed = time.monotonic() - started
        check(result.returncode == 0, f"killed holder: the next lander failed: {result.stderr}")
        check("waiting for the landing lock" not in result.stderr,
              f"killed holder: the lock outlived its dead holder: {result.stderr!r}")
        check(elapsed < 15, f"killed holder: landing took {elapsed:.1f} s after the holder died")
        check(repo.origin_main() == git(wt, "rev-parse", "HEAD"), "killed holder: the head did not land")


def test_main_change_to_the_reviewed_lines_needs_a_new_review():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        a, b = repo.worktree("epsilon", "same.txt"), repo.worktree("zeta", "other.txt")
        (b / "same.txt").write_text("main side\n")
        git(b, "add", "same.txt")
        git(b, "commit", "-q", "-m", "fix(zeta): touch the same file")
        check(repo.run(b, "--reviewed", repo.digest(b)).returncode == 0, "overlap: setup landing failed")
        digest, before = repo.digest(a), repo.origin_main()
        result = repo.run(a, "--reviewed", digest)
        check(result.returncode == 1 and "conflicts" in result.stderr,
              f"overlap: a conflicting main did not stop the landing: {result.stderr!r}")
        check(git(a, "status", "--porcelain") == "", "overlap: the aborted merge left the tree dirty")
        check(repo.origin_main() == before, "overlap: a conflicting head was pushed")


def main():
    tests = [test_two_landers_serialize_and_both_land, test_timeout_ends_non_zero_and_names_holder,
             test_killed_holder_releases_the_lock, test_main_change_to_the_reviewed_lines_needs_a_new_review]
    for test in tests:
        try:
            test()
        except Exception as e:  # a crash in one case is a failure, not a skipped suite
            FAILS.append(f"{test.__name__} crashed: {e!r}")
    if FAILS:
        print("\n".join(f"FAIL: {f}" for f in FAILS))
        return 1
    print(f"config-land-check: {len(tests)} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
