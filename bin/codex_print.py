#!/usr/bin/env python3
"""Run codex -p through native Codex exec without changing authentication."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from agent_setup import ASTRA_MODEL


def collect(events, event_log=None):
    result = {'provider': 'codex', 'model': ASTRA_MODEL, 'agent_setup': 'full-astra',
              'session_id': None, 'result': '', 'num_turns': 0, 'usage': {},
              'duration_api_ms': None, 'total_cost_usd': None, 'is_error': False}
    for line in events:
        if event_log:
            event_log.write(line)
            event_log.flush()
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            event_type = event.get('type')
            if event_type == 'thread.started':
                result['session_id'] = event.get('thread_id')
            elif event_type == 'item.completed':
                item = event.get('item', {})
                if item.get('type') == 'agent_message':
                    result['result'] = item.get('text', '')
            elif event_type == 'turn.completed':
                result['num_turns'] += 1
                usage = event.get('usage') or {}
                mapping = {'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens',
                           'cached_input_tokens': 'cache_read_input_tokens',
                           'reasoning_output_tokens': 'reasoning_output_tokens'}
                for native, common in mapping.items():
                    if native in usage:
                        result['usage'][common] = result['usage'].get(common, 0) + usage[native]
            elif event_type == 'turn.failed':
                result['is_error'] = True
        except (ValueError, TypeError, AttributeError):
            result['is_error'] = True
    result['is_error'] = result['is_error'] or result['num_turns'] == 0
    return result


def execute(prompt, cwd, sandbox, events_file=None):
    launcher = Path(__file__).with_name('codex-launch.py')
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError('Native Codex launcher is unavailable; no Claude fallback is allowed.')
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='codex-print-result-') as temporary:
        final_message = Path(temporary) / 'message.txt'
        command = [str(launcher), '--cd', str(cwd), '-a', 'never',
                   '-c', 'agents.enabled=false', 'exec', '--model', ASTRA_MODEL,
                   '--sandbox', sandbox, '--json', '--output-last-message', str(final_message), '-']
        environment = dict(os.environ, AGENT_SETUP='full-astra',
                           CLAUDE_INTAKE_GATE='off', CLAUDE_INTENT_LEDGER='off')
        log_context = events_file.open('w') if events_file else nullcontext()
        with log_context as event_log, subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                cwd=cwd, env=environment, start_new_session=True) as process:
            def interrupt(signum, frame):
                raise KeyboardInterrupt

            previous = {signum: signal.signal(signum, interrupt)
                        for signum in (signal.SIGINT, signal.SIGTERM)}
            try:
                try:
                    process.stdin.write(prompt)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                result = collect(process.stdout, event_log)
                returncode = process.wait()
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                raise
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
        if final_message.is_file():
            result['result'] = final_message.read_text()
    result['duration_ms'] = round((time.monotonic() - start) * 1000)
    result['is_error'] = result['is_error'] or returncode != 0
    return result, returncode if returncode else int(result['is_error'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, prog='codex')
    parser.add_argument('-p', '--print', dest='prompt', nargs='?', const='-', required=True,
                        help='Prompt text, or - to read the prompt from stdin')
    parser.add_argument('-C', '--cd', type=Path, default=Path.cwd())
    parser.add_argument('--output-format', choices=('text', 'json'), default='text')
    parser.add_argument('--sandbox', choices=('read-only', 'workspace-write'), default='workspace-write')
    parser.add_argument('--events-file', type=Path)
    args = parser.parse_args()
    if os.environ.get('AGENT_SETUP') not in (None, 'full-astra'):
        parser.error('This workflow selected Full Claude; return to its orchestrator instead of mixing setups.')
    if args.prompt == '-' and sys.stdin.isatty():
        parser.error('Supply prompt text after -p or pipe it on stdin.')
    prompt = sys.stdin.read() if args.prompt == '-' else args.prompt
    if not prompt.strip():
        parser.error('The prompt must not be empty.')
    try:
        result, returncode = execute(prompt, args.cd.expanduser().resolve(), args.sandbox, args.events_file)
        if args.output_format == 'json':
            print(json.dumps(result))
        else:
            print(result['result'])
        if result['is_error']:
            print('codex -p: Codex did not complete successfully; no fallback was launched.', file=sys.stderr)
        return returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print('codex -p: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
