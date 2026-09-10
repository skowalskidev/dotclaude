#!/usr/bin/env python3
"""Offline setup, headless Astra and dual-dispatch tests; all CLIs are fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import agent_setup

SOURCE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location('codex_print_under_test', SOURCE / 'codex_print.py')
astra = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(astra)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        self.spec = {'agent_setup': 'full-claude', 'orchestrator_model': 'claude-opus-4-8',
                     'slices': [{'name': 'alpha'}]}

    def test_claude_default_preserves_existing_worker_model(self):
        self.assertEqual(agent_setup.resolve(self.spec)['model'], 'claude-sonnet-4-6')

    def test_astra_defaults_to_astra_for_workers(self):
        self.spec.update(agent_setup='full-astra', orchestrator_model='gpt-6-astra')
        self.assertEqual(agent_setup.resolve(self.spec)['model'], 'gpt-6-astra')

    def test_missing_setup_inherits_current_model(self):
        del self.spec['agent_setup']
        self.assertEqual(agent_setup.resolve(self.spec)['agent_setup'], 'full-claude')

    def test_mixed_models_are_rejected(self):
        for field in ('orchestrator_model', 'model', 'reviewer_model'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                agent_setup.resolve(dict(self.spec, **{field: 'gpt-6-astra'}))

    def test_astra_rejects_other_gpt_models(self):
        self.spec.update(agent_setup='full-astra', orchestrator_model='gpt-6-astra')
        with self.assertRaisesRegex(ValueError, 'Worker model'):
            agent_setup.resolve(dict(self.spec, model='gpt-5.6-sol'))

    def test_unknown_orchestrator_is_not_assumed(self):
        del self.spec['orchestrator_model']
        with self.assertRaisesRegex(ValueError, 'actual orchestrator_model'):
            agent_setup.resolve(self.spec)

    def test_nested_setup_cannot_change(self):
        with patch.dict(os.environ, {'AGENT_SETUP': 'full-astra'}), self.assertRaises(ValueError):
            agent_setup.resolve(self.spec)

    def test_saved_spec_is_idempotent(self):
        resolved = agent_setup.resolve(self.spec)
        self.assertEqual(agent_setup.resolve(resolved), resolved)
        self.assertNotIn('model', self.spec)

    def test_slice_guards(self):
        for slices in ([], [{'name': '../escape'}], [{'name': 'alpha'}, {'name': 'alpha'}],
                       [{'name': 'alpha', 'model': 'gpt-6-astra'}]):
            with self.subTest(slices=slices), self.assertRaises(ValueError):
                agent_setup.resolve(dict(self.spec, slices=slices))

    def test_openai_chat_rejects_stale_claude_plan_and_declaration(self):
        for signal in ('CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'AGENT_MODEL_PROVIDER'):
            value = 'openai' if signal == 'AGENT_MODEL_PROVIDER' else 'native-fixture'
            with self.subTest(signal=signal), patch.dict(os.environ, {signal: value}):
                with self.assertRaisesRegex(ValueError, 'Current chat provider is openai'):
                    agent_setup.resolve(self.spec)

    def test_claude_chat_rejects_openai_plan(self):
        with patch.dict(os.environ, {'CLAUDECODE': '1'}):
            with self.assertRaisesRegex(ValueError, 'Current chat provider is anthropic'):
                agent_setup.resolve(dict(self.spec, agent_setup='full-astra', orchestrator_model='gpt-6-astra'))

    def test_explicit_override_allows_cross_provider(self):
        with patch.dict(os.environ, {'CLAUDECODE': '1', 'AGENT_ALLOW_CROSS_PROVIDER': '1'}):
            resolved = agent_setup.resolve(
                dict(self.spec, agent_setup='full-astra', orchestrator_model='gpt-6-astra'))
        self.assertEqual(resolved['model_provider'], 'openai')
        self.assertEqual(resolved['agent_setup'], 'full-astra')

    def test_general_openai_session_inherits_model_without_astra_switch(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'native-fixture'}):
            resolved = agent_setup.resolve(dict(self.spec, agent_setup=None, orchestrator_model='gpt-5.6-sol'))
        self.assertEqual(resolved['agent_setup'], 'full-openai')
        self.assertEqual(resolved['model'], 'gpt-5.6-sol')
        self.assertEqual(resolved['model_provider'], 'openai')

    def test_openai_setup_accepts_same_provider_models_and_rejects_other_reviewers(self):
        spec = dict(self.spec, agent_setup='full-openai', orchestrator_model='gpt-5.6-sol', model='gpt-6-astra')
        self.assertEqual(agent_setup.resolve(spec)['model'], 'gpt-6-astra')
        for other in ('claude-sonnet-4-6', 'gemini-3-pro', 'unknown'):
            with self.subTest(model=other), self.assertRaises(ValueError):
                agent_setup.resolve(dict(spec, reviewer_model=other))

    def test_conflicting_native_signals_fail_closed(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'native-fixture', 'CLAUDECODE': '1'}):
            with self.assertRaisesRegex(ValueError, 'Conflicting native provider signals'):
                agent_setup.resolve(self.spec)

    def test_override_resolves_conflict_via_inherited_provider(self):
        env = {'CLAUDECODE': '1', 'AGENT_MODEL_PROVIDER': 'openai', 'AGENT_ALLOW_CROSS_PROVIDER': '1'}
        with patch.dict(os.environ, env):
            self.assertEqual(agent_setup.current_provider(), 'openai')
        # without the flag the same two signals still fail closed
        with patch.dict(os.environ, {'CLAUDECODE': '1', 'AGENT_MODEL_PROVIDER': 'openai'}):
            with self.assertRaisesRegex(ValueError, 'Conflicting native provider signals'):
                agent_setup.current_provider()


class EventTests(unittest.TestCase):
    def result(self, events):
        return astra.collect(json.dumps(event) + '\n' for event in events)

    def test_usage_and_unknown_measurements(self):
        result = self.result([
            {'type': 'thread.started', 'thread_id': 'fixture'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Ready'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 6,
                                                'output_tokens': 4}},
        ])
        self.assertFalse(result['is_error'])
        self.assertEqual(result['usage']['cache_read_input_tokens'], 6)
        self.assertEqual(result['result'], 'Ready')
        self.assertIsNone(result['total_cost_usd'])
        self.assertIsNone(result['duration_api_ms'])
        self.assertNotIn('cache_creation_input_tokens', result['usage'])

    def test_empty_failed_and_malformed_streams_are_errors(self):
        self.assertTrue(self.result([])['is_error'])
        self.assertTrue(self.result([{'type': 'turn.failed'}])['is_error'])
        self.assertTrue(astra.collect(['not-json\n', '{"type":"turn.completed"}\n'])['is_error'])

    def test_transient_error_does_not_hide_a_completed_turn(self):
        result = self.result([{'type': 'error'}, {'type': 'turn.completed'}])
        self.assertFalse(result['is_error'])


class CommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='agent-setups-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = self.root / 'workspace with spaces'
        self.repo.mkdir()
        for name in ('agent_setup.py', 'codex_print.py', 'codex-launch.py', 'superspeed-dispatch.sh'):
            shutil.copy2(SOURCE / name, self.bin / name)
        (self.bin / 'agent_runtime.py').write_text('''import os, sys
from pathlib import Path
def launch():
    binary = str(Path(__file__).with_name('codex-native'))
    os.execv(binary, [binary, *sys.argv[1:]])
''')
        subscription = self.home / '.codex'
        subscription.mkdir()
        (subscription / 'auth.json').write_text(json.dumps({
            'auth_mode': 'chatgpt', 'tokens': {'access_token': 'fixture-only'}}))
        self.calls = self.root / 'calls.jsonl'
        self.env = {'HOME': str(self.home), 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'AGENT_CODEX_BIN': str(self.bin / 'codex-native'),
                    'FIXTURE_CALLS': str(self.calls)}
        stub = '''#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
args = sys.argv[1:]
if '--version' in args:
    print('codex-cli fixture')
    sys.exit(0)
kind = 'claude' if Path(sys.argv[0]).name == 'claude' else 'codex'
prompt = args[args.index('-p') + 1] if kind == 'claude' else sys.stdin.read()
with open(os.environ['FIXTURE_CALLS'], 'a') as output:
    output.write(json.dumps({'kind': kind, 'args': args, 'prompt': prompt,
                            'setup': os.environ.get('AGENT_SETUP'), 'pid': os.getpid(),
                            'home': os.environ.get('CODEX_HOME'),
                            'api_env_present': bool(os.environ.get('CODEX_API_KEY') or os.environ.get('OPENAI_API_KEY')),
                            'intake': os.environ.get('CLAUDE_INTAKE_GATE'),
                            'ledger': os.environ.get('CLAUDE_INTENT_LEDGER')}) + '\\n')
if os.environ.get('FIXTURE_SLEEP'):
    time.sleep(60)
match = re.search(r'When done, write (.+?)/DONE.md', prompt)
if match and not os.environ.get('FIXTURE_NO_DONE'):
    Path(match.group(1), 'DONE.md').write_text('src/fixture.py\\n')
if kind == 'claude':
    print(json.dumps({'is_error': False, 'result': 'Ready', 'usage': {}}))
else:
    print(json.dumps({'type': 'thread.started', 'thread_id': 'fixture'}))
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Ready'}}))
    if os.environ.get('FIXTURE_FAIL'):
        print(json.dumps({'type': 'turn.failed'}))
        sys.exit(7)
    if not os.environ.get('FIXTURE_INCOMPLETE'):
        print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 20, 'output_tokens': 5}}))
    Path(args[args.index('--output-last-message') + 1]).write_text('Ready')
'''
        for name in ('codex-native', 'claude'):
            path = self.bin / name
            path.write_text(stub)
            path.chmod(0o700)

    def astra_command(self, *args, **kwargs):
        return subprocess.run([sys.executable, str(self.bin / 'codex-launch.py'), *args], cwd=self.repo,
                              env=self.env, capture_output=True, text=True, timeout=15, **kwargs)

    def test_print_text_and_literal_prompt(self):
        prompt = 'Explain $(touch NEVER) and "quotes"'
        result = self.astra_command('-p', prompt)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'Ready')
        call = json.loads(self.calls.read_text())
        self.assertEqual(call['prompt'], prompt)
        self.assertIn('gpt-6-astra', call['args'])
        self.assertIn('agents.enabled=false', call['args'])
        self.assertEqual(call['intake'], 'off')
        self.assertEqual(call['ledger'], 'off')
        self.assertIn('workspace-write', call['args'])
        self.assertNotIn('--dangerously-bypass-hook-trust', call['args'])
        self.assertNotIn('--ignore-user-config', call['args'])
        self.assertFalse((self.repo / 'NEVER').exists())

    def test_stdin_and_json_with_events(self):
        events = self.root / 'events.jsonl'
        result = self.astra_command('-p', '--output-format', 'json', '--events-file', str(events),
                                    '--sandbox', 'read-only', input='Read only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['model'], 'gpt-6-astra')
        self.assertIn('turn.completed', events.read_text())

    def test_long_print_and_equals_forms(self):
        for flag in ('--print', '--print=work', '-p=work'):
            with self.subTest(flag=flag):
                args = [flag, 'work'] if flag == '--print' else [flag]
                result = self.astra_command(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'Ready')

    def test_native_commands_are_not_print_mode(self):
        (self.bin / 'codex-native').write_text('''#!/usr/bin/env python3
import json, sys
print(json.dumps(sys.argv[1:]))
''')
        commands = ((), ('--profile', 'work'), ('--profile', '-p'),
                    ('exec', '--profile', 'work', 'a prompt with -p inside'),
                    ('exec', '-p', 'work', 'native short profile'),
                    ('review', '--base', 'master'), ('exec', 'review', '--uncommitted'),
                    ('mcp', 'list', '--json'), ('app-server', '--listen', 'stdio://'),
                    ('--help',), ('--version',), ('--', '-p'), ('explain -p',))
        for args in commands:
            with self.subTest(args=args):
                result = self.astra_command(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), list(args))

    def test_work_worker_uses_subscription_despite_old_api_home_and_environment(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, env=self.env)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
                        'https://example.invalid/WorkOrg/project.git'], check=True, env=self.env)
        (self.root / 'identity.local.json').write_text(json.dumps({'workOrgMatch': 'WorkOrg/'}))
        old_home = self.home / '.codex-work'
        old_home.mkdir()
        old_auth = old_home / 'auth.json'
        old_auth.write_text(json.dumps({'auth_mode': 'apikey', 'OPENAI_API_KEY': 'fixture-only'}))
        before = old_auth.read_bytes()
        self.env.update(CODEX_HOME=str(old_home), CODEX_API_KEY='fixture-only', OPENAI_API_KEY='fixture-only')
        result = self.astra_command('-p', 'work')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads(self.calls.read_text())
        self.assertEqual(call['home'], str(self.home / '.codex'))
        self.assertFalse(call['api_env_present'])
        self.assertIn('forced_login_method="chatgpt"', call['args'])
        self.assertIn('openai_base_url="https://chatgpt.com/backend-api/codex"', call['args'])
        self.assertEqual(old_auth.read_bytes(), before)

    def test_worker_with_api_auth_never_starts_native_inference(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        (self.home / '.codex/auth.json').write_text(json.dumps({
            'auth_mode': 'apikey', 'OPENAI_API_KEY': 'fixture-only'}))
        result = self.astra_command('-p', 'work')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Subscription-only', result.stderr)
        self.assertFalse(self.calls.exists())

    def test_review_uses_real_subscription_launcher_without_api_exception(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        (self.bin / 'codex-native').write_text('''#!/usr/bin/env python3
import json, os, sys
print(json.dumps({'args': sys.argv[1:], 'home': os.environ['CODEX_HOME'],
                  'api_env_present': bool(os.environ.get('CODEX_API_KEY'))}))
''')
        self.env.update(CODEX_API_KEY='fixture-only', CODEX_HOME=str(self.home / '.codex-work'))
        result = self.astra_command('review', '--base', 'master')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads(result.stdout)
        self.assertEqual(call['home'], str(self.home / '.codex'))
        self.assertFalse(call['api_env_present'])
        self.assertIn('forced_login_method="chatgpt"', call['args'])
        self.assertEqual(call['args'][-3:], ['review', '--base', 'master'])

    def test_shell_codex_function_uses_print_launcher(self):
        shared = self.home / '.claude'
        shared.mkdir()
        (shared / 'bin').symlink_to(self.bin, target_is_directory=True)
        result = subprocess.run(['zsh', '-f', '-c',
                                 'source "$1"; codex -p "from shell"', 'fixture',
                                 str(SOURCE.parent / 'dotfiles/zsh-work-codex.zsh')],
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'Ready')
        self.assertEqual(json.loads(self.calls.read_text())['prompt'], 'from shell')

    def test_native_failure_is_propagated_without_fallback(self):
        self.env['FIXTURE_FAIL'] = '1'
        result = self.astra_command('-p', 'work', '--output-format', 'json')
        self.assertEqual(result.returncode, 7)
        self.assertTrue(json.loads(result.stdout)['is_error'])
        self.assertEqual(json.loads(self.calls.read_text())['kind'], 'codex')

    def test_zero_exit_without_completed_turn_is_failure(self):
        self.env['FIXTURE_INCOMPLETE'] = '1'
        result = self.astra_command('-p', 'work', '--output-format', 'json')
        self.assertEqual(result.returncode, 1)

    def test_empty_prompt_and_claude_workflow_do_not_launch(self):
        self.assertNotEqual(self.astra_command('-p', '').returncode, 0)
        self.env['AGENT_SETUP'] = 'full-claude'
        self.assertNotEqual(self.astra_command('-p', 'work').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_cross_provider_model_override_is_rejected(self):
        self.assertNotEqual(self.astra_command('-p', 'work', '--model', 'claude-sonnet-4-6').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_cancellation_reaps_native_worker(self):
        self.env['FIXTURE_SLEEP'] = '1'
        with subprocess.Popen([sys.executable, str(self.bin / 'codex-launch.py'), '-p', 'work'],
                              cwd=self.repo, env=self.env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as process:
            try:
                deadline = time.monotonic() + 5
                while not self.calls.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(self.calls.exists(), 'Native fixture never started')
                worker_pid = json.loads(self.calls.read_text())['pid']
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130)
                with self.assertRaises(ProcessLookupError):
                    os.kill(worker_pid, 0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)

    def test_unavailable_launcher_does_not_fall_back(self):
        (self.bin / 'codex-launch.py').unlink()
        result = subprocess.run([sys.executable, str(self.bin / 'codex_print.py'), '-p', 'work'],
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no Claude fallback', result.stderr)
        self.assertFalse(self.calls.exists())

    def dispatch(self, agent_mode, **changes):
        spec = {'task': 'fixture', 'repo': str(self.repo), 'setup': 'none', 'agent_setup': agent_mode,
                'orchestrator_model': 'gpt-6-astra' if agent_mode == 'full-astra' else 'claude-opus-4-8',
                'slices': [{'name': name, 'owns': ['src/' + name + '.py'], 'verify': 'none',
                            'prompt': 'fixture'} for name in ('alpha', 'beta')]}
        spec.update(changes)
        source = self.root / 'spec.json'
        source.write_text(json.dumps(spec))
        output = self.repo / '.context/run'
        result = subprocess.run(['bash', str(self.bin / 'superspeed-dispatch.sh'), str(source), str(output)],
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=20)
        return result, output

    def test_full_claude_launches_only_claude(self):
        result, output = self.dispatch('full-claude')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([call['kind'] for call in calls], ['claude', 'claude'])
        self.assertEqual(json.loads((output / 'spec.json').read_text())['model'], 'claude-sonnet-4-6')

    def test_full_astra_launches_only_astra_and_records_mode(self):
        result, output = self.dispatch('full-astra')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([call['kind'] for call in calls], ['codex', 'codex'])
        self.assertTrue(all(call['setup'] == 'full-astra' for call in calls))
        self.assertEqual(json.loads((output / 'run.json').read_text())['agent_setup'], 'full-astra')
        for name in ('alpha', 'beta'):
            self.assertEqual((output / 'slices' / name / 'status').read_text().strip(), 'ok')
            self.assertTrue((output / 'slices' / name / 'events.jsonl').is_file())

    def test_dispatch_workers_use_real_subscription_launcher(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, env=self.env)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
                        'https://example.invalid/WorkOrg/project.git'], check=True, env=self.env)
        (self.root / 'identity.local.json').write_text(json.dumps({'workOrgMatch': 'WorkOrg/'}))
        self.env.update(CODEX_HOME=str(self.home / '.codex-work'),
                        CODEX_API_KEY='fixture-only', OPENAI_API_KEY='fixture-only')
        result, output = self.dispatch('full-astra', reviewer_model='gpt-6-astra')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call['kind'], 'codex')
            self.assertEqual(call['home'], str(self.home / '.codex'))
            self.assertFalse(call['api_env_present'])
            self.assertIn('gpt-6-astra', call['args'])
            self.assertIn('forced_login_method="chatgpt"', call['args'])
            self.assertIn('openai_base_url="https://chatgpt.com/backend-api/codex"', call['args'])
        for name in ('alpha', 'beta'):
            self.assertEqual((output / 'slices' / name / 'status').read_text().strip(), 'ok')

    def test_stale_claude_plan_from_openai_chat_never_runs_setup_or_worker(self):
        self.env['CODEX_THREAD_ID'] = 'native-fixture'
        marker = self.root / 'setup-ran'
        result, output = self.dispatch('full-claude', setup='touch ' + str(marker))
        self.assertEqual(result.returncode, 2)
        self.assertIn('Current chat provider is openai', result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(output.exists())
        self.assertFalse(self.calls.exists())

    def test_openai_dispatch_passes_selected_model_and_provider(self):
        self.env['CODEX_THREAD_ID'] = 'native-fixture'
        result, _ = self.dispatch('full-openai', orchestrator_model='gpt-5.6-sol', model='gpt-5.6-sol')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call['kind'] == 'codex' and 'gpt-5.6-sol' in call['args'] for call in calls))

    def test_claude_chat_cannot_launch_codex_print_or_native_review(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        self.env['CLAUDECODE'] = '1'
        for args in (('-p', 'review'), ('review', '--base', 'master')):
            with self.subTest(args=args):
                result = self.astra_command(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Current chat provider is anthropic', result.stderr)
        self.assertFalse(self.calls.exists())

    def test_claude_chat_can_use_codex_metadata_without_inference(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        self.env['CLAUDECODE'] = '1'
        result = self.astra_command('--version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls.exists())

    def test_missing_choice_stops_before_setup_or_spend(self):
        marker = self.root / 'setup-ran'
        result, output = self.dispatch(None, orchestrator_model=None, setup='touch ' + str(marker))
        self.assertEqual(result.returncode, 2)
        self.assertIn('actual orchestrator_model', result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(output.exists())
        self.assertFalse(self.calls.exists())

    def test_mismatched_orchestrator_stops_before_spend(self):
        result, _ = self.dispatch('full-astra', orchestrator_model='claude-opus-4-8')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls.exists())

    def test_failed_worker_is_not_a_successful_dispatch(self):
        self.env['FIXTURE_FAIL'] = '1'
        result, output = self.dispatch('full-astra')
        self.assertEqual(result.returncode, 1)
        self.assertEqual((output / 'slices/alpha/status').read_text().strip(), 'nonzero-exit')

    def test_missing_done_is_not_success(self):
        self.env['FIXTURE_NO_DONE'] = '1'
        result, _ = self.dispatch('full-astra')
        self.assertEqual(result.returncode, 1)

    def analyse(self, output):
        result = subprocess.run([sys.executable, str(SOURCE / 'superspeed-analyse.py'), str(output)],
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((output / 'analysis.json').read_text()), result.stdout

    def test_astra_analysis_preserves_unknown_measurements(self):
        result, output = self.dispatch('full-astra')
        self.assertEqual(result.returncode, 0, result.stderr)
        analysis, report = self.analyse(output)
        self.assertIsNone(analysis['total_cost'])
        self.assertIsNone(analysis['achieved_concurrency'])
        self.assertIsNone(analysis['cache_read_write_ratio'])
        for item in analysis['slices']:
            self.assertIsNone(item['cost'])
            self.assertIsNone(item['api_s'])
            self.assertIsNone(item['cache_write'])
        self.assertIn('not reported', report)
        self.assertNotIn('no transcript found', report)

    def test_claude_analysis_retains_reported_measurements(self):
        result, output = self.dispatch('full-claude')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('alpha', 'beta'):
            path = output / 'slices' / name / 'result.json'
            payload = json.loads(path.read_text())
            payload.update(total_cost_usd=0.5, duration_api_ms=1000)
            payload['usage'] = {'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 20}
            path.write_text(json.dumps(payload))
        analysis, _ = self.analyse(output)
        self.assertEqual(analysis['total_cost'], 1)
        self.assertEqual(analysis['cache_read_write_ratio'], 2)
        self.assertTrue(all(item['api_s'] == 1 for item in analysis['slices']))


if __name__ == '__main__':
    unittest.main()
