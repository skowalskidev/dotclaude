"""Offline shell fixtures: no package install, live dotfile edit or service access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SELECTOR = Path(__file__).with_name('node-runtime.zsh')


class NodeRuntimeTests(unittest.TestCase):
    def test_shell_modes_and_directory_independence(self):
        with tempfile.TemporaryDirectory(prefix='node-runtime-') as tmp:
            root = Path(tmp)
            old = root / 'old'
            old.mkdir()
            (old / 'node').write_text('#!/bin/sh\necho v21.1.0\n')
            (old / 'node').chmod(0o755)
            for version in ('v24.9.0', 'v24.21.0', 'v24.22.0-rc.1', 'v24.30.0', 'v26.0.0'):
                directory = root / 'nvm/versions/node' / version / 'bin'
                directory.mkdir(parents=True)
                for name in ('node', 'npm', 'npx'):
                    if version == 'v24.30.0' and name == 'npx':
                        continue
                    binary = directory / name
                    binary.write_text('#!/bin/sh\necho ' + version + '\n')
                    binary.chmod(0o755)
            expected = root / 'nvm/versions/node/v24.21.0/bin'
            source = 'source "' + str(SELECTOR) + '"\n'
            (root / '.zshenv').write_text(source)
            (root / '.zprofile').write_text('path=("' + str(old) + '" $path)\n' + source)
            (root / '.zshrc').write_text(source)
            env = {**os.environ, 'ZDOTDIR': str(root), 'NVM_DIR': str(root / 'nvm'),
                   'PATH': str(old) + ':/usr/bin:/bin', 'NVM_BIN': str(old)}
            directories = [root, root / 'workspace', root / 'workspace/subdirectory']
            for directory in directories:
                directory.mkdir(exist_ok=True)
                for mode in ('-c', '-lc', '-ic', '-lic'):
                    with self.subTest(directory=directory.name, mode=mode):
                        result = subprocess.run(['/bin/zsh', mode, source +
                            'node --version; command -v node npm npx; print -r -- $NVM_BIN; '
                            'print -l -- $path'], cwd=directory, env=env, text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        lines = result.stdout.splitlines()
                        self.assertEqual(lines[:5], ['v24.21.0', *[str(expected / n) for n in ('node', 'npm', 'npx')], str(expected)])
                        self.assertEqual(lines[5:].count(str(expected)), 1)
                        self.assertIn(str(old), lines[5:])

    def test_missing_runtime_fails_explicitly(self):
        with tempfile.TemporaryDirectory(prefix='node-runtime-missing-') as tmp:
            result = subprocess.run(['/bin/zsh', '-fc', 'source "' + str(SELECTOR) + '"'],
                env={**os.environ, 'NVM_DIR': tmp}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Node 24 is missing', result.stderr)


if __name__ == '__main__':
    unittest.main()
