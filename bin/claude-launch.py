#!/usr/bin/env python3
"""Launch Claude with the selected project's private instruction policy."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from agent_runtime import project

ROOT = Path(__file__).resolve().parent.parent
TERMINATION_GRACE_SECONDS = 10


def launch_cwd():
    return Path(os.environ.get('CONDUCTOR_WORKSPACE_PATH') or os.getcwd()).resolve()


def instruction_root(cwd):
    result = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                            capture_output=True, text=True)
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else cwd


def exclusion_patterns(cwd):
    """Cover native project memory at launch and on demand without hiding personal files."""
    root = instruction_root(cwd)
    patterns = []
    names = ('CLAUDE.md', 'CLAUDE.local.md', 'AGENTS.md')
    for directory in [root, *list(root.parents)]:
        if directory == Path.home() or directory == Path(directory.anchor):
            break
        for name in names:
            patterns.append(str(directory / name))
        patterns.extend((str(directory / '.claude/CLAUDE.md'),
                         str(directory / '.claude/AGENTS.md'),
                         str(directory / '.claude/rules/**')))
    for name in names:
        patterns.append(str(root / '**' / name))
    patterns.extend((str(root / '**/.claude/CLAUDE.md'),
                     str(root / '**/.claude/AGENTS.md'),
                     str(root / '**/.claude/rules/**')))
    return list(dict.fromkeys(patterns))


def merged_settings(args, cwd, excludes):
    """Keep caller settings intact while adding this launch's exclusion list."""
    merged = {}
    forwarded = []
    iterator = iter(args)
    for arg in iterator:
        if arg == '--':
            forwarded.extend([arg, *iterator])
            break
        if arg == '--settings':
            value = next(iterator, None)
            if value is None:
                raise ValueError('--settings requires a JSON file or object')
        elif arg.startswith('--settings='):
            value = arg.split('=', 1)[1]
        else:
            forwarded.append(arg)
            continue
        if value.lstrip().startswith('{'):
            settings = json.loads(value)
        else:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            settings = json.loads(path.read_text())
        if not isinstance(settings, dict):
            raise ValueError('--settings must contain a JSON object')
        merged.update(settings)
    existing = merged.get('claudeMdExcludes', [])
    if not isinstance(existing, list) or any(not isinstance(value, str) for value in existing):
        raise ValueError('claudeMdExcludes must be a list of strings')
    merged['claudeMdExcludes'] = list(dict.fromkeys([*existing, *excludes]))
    return merged, forwarded


def run_with_settings(binary, args, settings, cwd):
    """Keep caller settings out of argv; remove the private overlay after Claude exits."""
    with tempfile.TemporaryDirectory(prefix='agent-claude-settings-') as private_dir:
        path = Path(private_dir) / 'settings.json'
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(settings, output)
        child = subprocess.Popen([binary, '--settings', str(path), *args], cwd=cwd,
                                 env=dict(os.environ))
        previous = {}
        termination_deadline = None
        def forward(number, _frame):
            nonlocal termination_deadline
            if child.poll() is not None:
                return
            if number in (signal.SIGTERM, signal.SIGHUP) and termination_deadline is not None:
                return
            child.send_signal(number)
            if number in (signal.SIGTERM, signal.SIGHUP):
                termination_deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
        try:
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                previous[number] = signal.signal(number, forward)
            while True:
                try:
                    return child.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    if termination_deadline is not None and time.monotonic() >= termination_deadline:
                        child.kill()
                        return child.wait()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=TERMINATION_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def executable():
    own = Path(__file__).resolve()
    explicit = os.environ.get('AGENT_CLAUDE_BIN')
    candidates = [explicit] if explicit else []
    if not explicit:
        directory = Path(os.environ.get('CONDUCTOR_AGENT_BINARIES_DIR') or
                         Path.home() / 'Library/Application Support/com.conductor.app/agent-binaries')
        bundled = [path for path in (directory / 'claude').glob('*/claude')
                   if re.fullmatch(r'\d+\.\d+\.\d+', path.parent.name)]
        bundled.sort(key=lambda path: tuple(int(part) for part in path.parent.name.split('.')),
                     reverse=True)
        candidates = [str(path) for path in bundled]
        candidates.extend(str(Path(part) / 'claude') for part in os.get_exec_path())
    for name in candidates:
        if name and Path(name).is_file() and os.access(name, os.X_OK) and Path(name).resolve() != own:
            return str(Path(name).resolve())
    raise ValueError('Claude executable not found; install Claude or set AGENT_CLAUDE_BIN')


def launch():
    try:
        cwd = launch_cwd()
        _, manifest, _ = project(cwd)
        args = sys.argv[1:]
        binary = executable()
        if manifest.get('ignoreProjectInstructions', False):
            settings, args = merged_settings(args, cwd, exclusion_patterns(cwd))
            status = run_with_settings(binary, args, settings, cwd)
            raise SystemExit(128 - status if status < 0 else status)
        os.chdir(cwd)
        os.execve(binary, [binary, *args], dict(os.environ))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print('agent config: ' + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    launch()
