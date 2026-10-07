#!/usr/bin/env python3
"""Offline Claude launcher checks with temporary projects and fake binaries."""
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('claude-launch.py')
SPEC = importlib.util.spec_from_file_location('claude_launcher_under_test', SOURCE)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='claude-launch-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'repo'
        self.nested = self.project / 'src'
        self.nested.mkdir(parents=True)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(Path, 'home', return_value=self.home).start()
        patch.dict(os.environ, {'HOME': str(self.home), 'PATH': os.defpath}, clear=True).start()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)

    def test_excludes_project_and_ancestor_instructions_but_not_personal_sources(self):
        patterns = launcher.exclusion_patterns(self.nested)
        root = self.project.resolve()
        self.assertIn(str(root / 'AGENTS.md'), patterns)
        self.assertIn(str(root / 'CLAUDE.local.md'), patterns)
        self.assertIn(str(root / '**/.claude/rules/**'), patterns)
        self.assertIn(str(root / '**/AGENTS.md'), patterns)
        self.assertNotIn(str(self.home / '.claude/CLAUDE.md'), patterns)

    def test_settings_merge_preserves_caller_options_and_exclusions(self):
        settings_file = self.base / 'settings.json'
        settings_file.write_text(json.dumps({'env': {'FIXTURE': 'yes'},
                                             'claudeMdExcludes': ['/caller/rule.md']}))
        settings, args = launcher.merged_settings(
            ['--settings', str(settings_file), '--model', 'fixture'],
            self.nested, ['/repo/AGENTS.md'])
        self.assertEqual(settings['env'], {'FIXTURE': 'yes'})
        self.assertEqual(settings['claudeMdExcludes'], ['/caller/rule.md', '/repo/AGENTS.md'])
        self.assertEqual(args, ['--model', 'fixture'])

    def test_private_settings_are_not_in_argv_and_are_removed_on_exit(self):
        binary = self.base / 'stub-claude'
        output = self.base / 'observed.json'
        binary.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                          'Path(sys.argv[-1]).write_text(json.dumps({"argv":sys.argv[1:],'
                          '"settings":json.loads(Path(sys.argv[2]).read_text())}))\n')
        binary.chmod(0o700)
        status = launcher.run_with_settings(str(binary), [str(output)],
                                            {'env': {'SECRET_FIXTURE': 'private'}}, self.nested)
        self.assertEqual(status, 0)
        observed = json.loads(output.read_text())
        self.assertEqual(observed['settings']['env']['SECRET_FIXTURE'], 'private')
        self.assertNotIn('SECRET_FIXTURE', ' '.join(observed['argv']))
        self.assertFalse(Path(observed['argv'][1]).exists())

    def test_supervisor_forwards_signal_and_cleans_private_settings(self):
        binary = self.base / 'waiting-claude'
        marker = self.base / 'settings-path'
        binary.write_text('#!' + sys.executable + '\nimport signal,sys,time\nfrom pathlib import Path\n'
                          'Path(sys.argv[-1]).write_text(sys.argv[2])\n'
                          'signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n'
                          'print("ready", flush=True)\n'
                          'while True: time.sleep(0.05)\n')
        binary.chmod(0o700)
        runner = ('import importlib.util,sys\n'
                  'from pathlib import Path\n'
                  'sys.path.insert(0,str(Path(sys.argv[1]).parent))\n'
                  's=importlib.util.spec_from_file_location("launcher",sys.argv[1])\n'
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                  'sys.exit(m.run_with_settings(sys.argv[2],[sys.argv[3]],{"fixture":True},Path(sys.argv[4])))\n')
        parent = subprocess.Popen([sys.executable, '-c', runner, str(SOURCE), str(binary),
                                   str(marker), str(self.nested)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([parent.stdout], [], [], 5)[0], 'child did not become ready')
            self.assertEqual(parent.stdout.readline().strip(), 'ready')
            time.sleep(0.1)
            parent.send_signal(signal.SIGTERM)
            _, errors = parent.communicate(timeout=5)
            self.assertEqual(parent.returncode, 0, errors)
            self.assertFalse(Path(marker.read_text()).exists())
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()

    def test_supervisor_kills_only_stubborn_child_after_grace(self):
        binary = self.base / 'stubborn-claude'
        marker = self.base / 'stubborn-settings-path'
        binary.write_text('#!' + sys.executable + '\nimport os,signal,sys,time\nfrom pathlib import Path\n'
                          'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                          'Path(sys.argv[-1]).write_text(sys.argv[2])\n'
                          'print("ready", flush=True)\n'
                          'while True: time.sleep(0.05)\n')
        binary.chmod(0o700)
        runner = ('import importlib.util,sys\nfrom pathlib import Path\n'
                  'sys.path.insert(0,str(Path(sys.argv[1]).parent))\n'
                  's=importlib.util.spec_from_file_location("launcher",sys.argv[1])\n'
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                  'm.TERMINATION_GRACE_SECONDS=0.2\n'
                  'sys.exit(m.run_with_settings(sys.argv[2],[sys.argv[3]],{"fixture":True},Path(sys.argv[4])))\n')
        parent = subprocess.Popen([sys.executable, '-c', runner, str(SOURCE), str(binary),
                                   str(marker), str(self.nested)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([parent.stdout], [], [], 5)[0], 'child did not become ready')
            self.assertEqual(parent.stdout.readline().strip(), 'ready')
            time.sleep(0.1)
            parent.send_signal(signal.SIGTERM)
            parent.communicate(timeout=5)
            self.assertNotEqual(parent.returncode, 0)
            self.assertFalse(Path(marker.read_text()).exists())
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()

    def test_sigint_does_not_start_termination_deadline(self):
        binary = self.base / 'interactive-claude'
        marker = self.base / 'interactive-settings-path'
        binary.write_text('#!' + sys.executable + '\nimport signal,sys,time\nfrom pathlib import Path\n'
                          'signal.signal(signal.SIGINT, signal.SIG_IGN)\n'
                          'signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n'
                          'Path(sys.argv[-1]).write_text(sys.argv[2])\n'
                          'print("ready", flush=True)\n'
                          'while True: time.sleep(0.05)\n')
        binary.chmod(0o700)
        runner = ('import importlib.util,sys\nfrom pathlib import Path\n'
                  'sys.path.insert(0,str(Path(sys.argv[1]).parent))\n'
                  's=importlib.util.spec_from_file_location("launcher",sys.argv[1])\n'
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                  'm.TERMINATION_GRACE_SECONDS=0.2\n'
                  'sys.exit(m.run_with_settings(sys.argv[2],[sys.argv[3]],{"fixture":True},Path(sys.argv[4])))\n')
        parent = subprocess.Popen([sys.executable, '-c', runner, str(SOURCE), str(binary),
                                   str(marker), str(self.nested)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([parent.stdout], [], [], 5)[0], 'child did not become ready')
            self.assertEqual(parent.stdout.readline().strip(), 'ready')
            parent.send_signal(signal.SIGINT)
            time.sleep(0.5)
            self.assertIsNone(parent.poll())
            parent.send_signal(signal.SIGTERM)
            parent.communicate(timeout=5)
            self.assertEqual(parent.returncode, 0)
            self.assertFalse(Path(marker.read_text()).exists())
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()

    def test_disabled_policy_passes_arguments_through_and_enabled_adds_settings(self):
        binary = self.base / 'claude'
        binary.write_text('fixture')
        binary.chmod(0o700)
        with patch.object(launcher, 'project', return_value=(None, {}, 'personal')), \
             patch.object(launcher, 'executable', return_value=str(binary)), \
             patch.object(launcher.os, 'chdir'), patch.object(launcher.os, 'execve') as execute, \
             patch.object(launcher.sys, 'argv', ['claude-launch.py', '--version']):
            launcher.launch()
        self.assertEqual(execute.call_args.args[1], [str(binary), '--version'])
        with patch.object(launcher, 'project', return_value=(None, {'ignoreProjectInstructions': True}, 'personal')), \
             patch.object(launcher, 'executable', return_value=str(binary)), \
             patch.object(launcher, 'run_with_settings', return_value=0) as run, \
             patch.object(launcher.sys, 'argv', ['claude-launch.py', '--version']):
            with self.assertRaises(SystemExit) as caught:
                launcher.launch()
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(run.call_args.args[1], ['--version'])
        self.assertIn('claudeMdExcludes', run.call_args.args[2])

    def test_binary_selection_prefers_stable_conductor_and_skips_self(self):
        directory = self.base / 'conductor'
        for version in ('2.1.1', '2.2.0-alpha.1', '2.1.2'):
            path = directory / 'claude' / version / 'claude'
            path.parent.mkdir(parents=True)
            path.write_text('fixture')
            path.chmod(0o700)
        with patch.dict(os.environ, {'CONDUCTOR_AGENT_BINARIES_DIR': str(directory)}):
            self.assertEqual(launcher.executable(), str((directory / 'claude/2.1.2/claude').resolve()))
        with patch.dict(os.environ, {'AGENT_CLAUDE_BIN': str(SOURCE)}):
            with self.assertRaisesRegex(ValueError, 'not found'):
                launcher.executable()


if __name__ == '__main__':
    unittest.main()
