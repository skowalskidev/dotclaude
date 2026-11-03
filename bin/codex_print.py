#!/usr/bin/env python3
"""Run codex -p through native Codex exec without changing authentication."""
import argparse
from contextlib import nullcontext
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from agent_setup import (
    matches_implementation_model,
    matches_model,
    resolve_tier,
    require_provider,
    tier_of,
)


def collect(events, event_log=None, model=None, setup="full-openai"):
    result = {'provider': 'codex', 'model': model, 'agent_setup': setup,
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


def completion_reason(final, events, done, accept, commits="", dirty=""):
    """Judge completion independently of the native worker's exit code."""
    worked = bool(commits)
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed":
            worked |= item.get("type") == "file_change" and bool(item.get("changes"))
            worked |= (item.get("type") == "command_execution" and item.get("exit_code") == 0
                       and bool(re.search(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b", item.get("command", ""))))
    if worked and re.search(r"no (?:files? (?:were )?changed|work (?:was )?done|changes (?:were )?made)", final, re.I):
        return "context-loss: final reports no work after recorded edits or commits"
    if not done or accept not in done or not re.search(r"\|.*(?:verdict|status|result).*\|", done, re.I):
        return "incomplete: missing acceptance table for the dispatched task"
    if not re.search(r"acceptance", final, re.I):
        return "incomplete: final report omits task acceptance"
    if commits and not all(sha in final + done for sha in re.findall(r"^[0-9a-f]{7,40}", commits, re.M)):
        return "incomplete: commits since dispatch are unreported"
    return None


def dispatcher_completion(repo, directory, spec, index, base):
    """Write recovery evidence for the existing superspeed supervisor; never launch a model."""
    directory = Path(directory)
    task = json.loads(Path(spec).read_text())["slices"][int(index)]
    owns = task.get("owns", [])
    def git(*args):
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError("completion Git probe failed")
        return result.stdout
    commits = git("log", "--format=%h %s", base + "..HEAD", "--", *owns) if base and owns else ""
    dirty = git("status", "--short", "--", *owns) if base and owns else ""
    result = json.loads((directory / "result.json").read_text())
    if result.get("is_error") or (directory / "BLOCKED.md").exists():
        return 0  # Ordinary errors and explicit blocks are not context-loss retries.
    done = (directory / "DONE.md").read_text() if (directory / "DONE.md").exists() else ""
    events = (directory / "events.jsonl").read_text() if (directory / "events.jsonl").exists() else ""
    reason = completion_reason(result.get("result", ""), events, done,
                               task.get("accept", "the files you own are complete and self-consistent"), commits, dirty)
    (directory / "completion.json").write_text(json.dumps({"reason": reason, "commits": commits, "uncommitted": dirty}) + "\n")
    if not reason:
        return 0
    checkpoint = directory / "CHECKPOINT.md"
    remaining = checkpoint.read_text() if checkpoint.exists() else "No worker checkpoint. Reconcile each acceptance item against the owned files and checks."
    continuation = ((directory / "prompt.txt").read_text() +
                    "\n\nCONTINUATION: recover the original task. Preserve existing work.\nStop reason: " + reason +
                    "\nCommits since dispatch:\n" + commits + "\nUncommitted owned files:\n" + dirty +
                    "\nRemaining items and checkpoint:\n" + remaining +
                    "\nInspect the preserved attempt-0 events and report before changing files. Finish remaining items; report all commits and the acceptance table.\n")
    (directory / "continuation.txt").write_text(continuation)
    return 1


def execute(prompt, cwd, sandbox, events_file=None, model=None, setup="full-openai"):
    require_provider("openai")
    model = model or resolve_tier('openai', 'mid')
    launcher = Path(__file__).with_name('codex-launch.py')
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError('Native Codex launcher is unavailable; no Claude fallback is allowed.')
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='codex-print-result-') as temporary:
        final_message = Path(temporary) / 'message.txt'
        command = [str(launcher), '--cd', str(cwd), '-a', 'never',
                   '-c', 'agents.enabled=false', 'exec', '--model', model,
                   '--sandbox', sandbox, '--json', '--output-last-message', str(final_message), '-']
        environment = dict(os.environ, AGENT_SETUP=setup, AGENT_MODEL_PROVIDER='openai',
                           AGENT_DELEGATED_WORKER='1')
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
                result = collect(process.stdout, event_log, model, setup)
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
    parser.add_argument('--model', default=None)
    args = parser.parse_args()
    if not args.model:
        try:
            args.model = resolve_tier('openai', 'mid')
        except ValueError as error:
            print('codex -p: ' + str(error), file=sys.stderr)
            return 2
    setup = os.environ.get('AGENT_SETUP', 'full-astra' if tier_of(args.model) == 'top' else 'full-openai')
    model_matches_role = (matches_model(setup, args.model) if args.sandbox == 'read-only'
                          else matches_implementation_model(setup, args.model))
    if setup not in ('full-astra', 'full-openai') or not model_matches_role:
        parser.error('Model conflicts with the inherited setup or role; Astra requires read-only review.')
    if args.prompt == '-' and sys.stdin.isatty():
        parser.error('Supply prompt text after -p or pipe it on stdin.')
    prompt = sys.stdin.read() if args.prompt == '-' else args.prompt
    if not prompt.strip():
        parser.error('The prompt must not be empty.')
    try:
        result, returncode = execute(prompt, args.cd.expanduser().resolve(), args.sandbox, args.events_file, args.model, setup)
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
