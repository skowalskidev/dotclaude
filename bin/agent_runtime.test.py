#!/usr/bin/env python3
"""Offline native-adapter contracts; all homes, manifests, and hooks are temporary."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('agent_runtime.py')
SPEC = importlib.util.spec_from_file_location('agent_runtime_under_test', SOURCE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agent-runtime-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'shared'
        self.home = self.base / 'home'
        self.cwd = self.base / 'workspace'
        for directory in (self.root / 'connectors', self.root / 'rules',
                          self.root / 'bin', self.root / 'dotfiles', self.home, self.cwd):
            directory.mkdir(parents=True, exist_ok=True)
        self.write('identity.local.json', {'workOrgMatch': 'WorkOrg/'})
        self.write('settings.json', {'hooks': {}})
        (self.root / 'CLAUDE.md').write_text('Canonical instructions v1')
        (self.root / 'rules/example.md').write_text('Canonical rule v1')
        (self.root / 'dotfiles/codex-AGENTS.md').write_text('Shared native entrypoint')
        self.remote = 'https://github.com/PersonalOrg/project.git'
        self.addCleanup(patch.stopall)
        patch.object(runtime, 'ROOT', self.root).start()
        patch.object(Path, 'home', return_value=self.home).start()
        patch.object(runtime, 'origin', side_effect=lambda cwd: self.remote).start()
        patch.dict(os.environ, {'HOME': str(self.home),
                                'PATH': os.defpath,
                                'CODEX_HOME': str(self.home / '.codex')}, clear=True).start()

    def write(self, name, value):
        file = self.root / name
        file.write_text(json.dumps(value))
        return file

    def manifest(self, name='personal', match=None, boundary='personal', connectors=None):
        return self.write('connectors/' + name + '.json', {
            'match': match or ['PersonalOrg/'], 'boundary': boundary,
            'connectors': connectors or [],
        })

    def connector(self, name='linear', url='https://example.invalid/mcp', **extra):
        return {'name': name, 'kind': 'mcp-http', 'mcp': {'type': 'http', 'url': url}, **extra}

    def parsed_overrides(self):
        args, home = runtime.overrides(self.cwd)
        self.assertTrue(all(value == '-c' for value in args[::2]))
        return [tomllib.loads(value) for value in args[1::2]], home

    def stub_hook(self, output=None, exit_code=0, marker=None):
        file = self.root / 'bin' / ('stub-' + str(len(list((self.root / 'bin').iterdir()))) + '.py')
        file.write_text('import json,sys\nfrom pathlib import Path\n'
                        'payload=json.load(sys.stdin)\n'
                        + ('Path(' + repr(str(marker)) + ').write_text(json.dumps(payload))\n' if marker else '')
                        + 'print(' + repr(json.dumps(output or {})) + ')\n'
                        + 'sys.exit(' + str(exit_code) + ')\n')
        return {'type': 'command', 'command': shlex.join([sys.executable, str(file)])}

    def configure_hook(self, event, handler, matcher='*'):
        self.write('settings.json', {'hooks': {event: [{'matcher': matcher, 'hooks': [handler]}]}})

    def test_remote_takes_precedence_over_directory_match(self):
        self.manifest('remote')
        self.manifest('path', match=[str(self.cwd)])
        path, _, boundary = runtime.project(self.cwd)
        self.assertEqual(path.name, 'remote.json')
        self.assertEqual(boundary, 'personal')

    def test_path_fallback_only_without_remote(self):
        self.remote = ''
        self.manifest(match=[str(self.cwd)])
        self.assertIsNotNone(runtime.project(self.cwd)[0])
        self.remote = 'https://github.com/Elsewhere/other.git'
        self.assertIsNone(runtime.project(self.cwd)[0])

    def test_ambiguous_manifests_fail(self):
        self.manifest('one')
        self.manifest('two')
        with self.assertRaisesRegex(ValueError, 'Multiple connector manifests'):
            runtime.project(self.cwd)

    def test_work_boundary_comes_from_identity_and_remote(self):
        self.remote = 'git@github.com:WorkOrg/project.git'
        self.manifest(match=['WorkOrg/'], boundary='work')
        self.assertEqual(runtime.project(self.cwd)[2], 'work')
        self.assertEqual(runtime.overrides(self.cwd)[1], self.home / '.codex')

    def test_manifest_boundary_disagreement_fails(self):
        self.manifest(boundary='work')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            runtime.project(self.cwd)

    def test_model_subscription_is_shared_not_selected_by_project_billing(self):
        self.assertEqual(runtime.subscription_home(), self.home / '.codex')
        self.remote = 'git@github.com:WorkOrg/project.git'
        self.assertEqual(runtime.overrides(self.cwd)[1], self.home / '.codex')

    def save_auth(self, value):
        path = runtime.subscription_home() / 'auth.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def test_cached_api_auth_is_rejected_without_mutation(self):
        for auth in ({'auth_mode': 'apikey', 'OPENAI_API_KEY': 'fixture-only'},
                     {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': 'fixture-only', 'tokens': {}},
                     {'OPENAI_API_KEY': 'fixture-only'}, [], {'auth_mode': 'workload_identity'}):
            with self.subTest(auth=auth):
                path = self.save_auth(auth)
                before = (path.read_bytes(), path.stat().st_mtime_ns)
                for args in (['exec', 'task'], ['review'], ['app-server'], ['login', 'status']):
                    with self.assertRaisesRegex(ValueError, 'saved login is not ChatGPT'):
                        runtime.check_subscription_auth(args)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_absent_or_malformed_subscription_auth_fails_before_inference(self):
        for args in (['exec', 'task'], ['review'], ['exec', 'review']):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'sign in'):
                runtime.check_subscription_auth(args)
        path = self.save_auth({})
        path.write_text('invalid-json')
        with self.assertRaisesRegex(ValueError, 'cannot read saved login'):
            runtime.check_subscription_auth(['exec', 'task'])

    def test_existing_chatgpt_subscription_is_accepted_for_every_role(self):
        self.save_auth({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'fixture-only'}})
        for args in ([], ['exec', 'task'], ['review'], ['exec', 'review'], ['app-server']):
            with self.subTest(args=args):
                runtime.check_subscription_auth(args)
                config = {}
                for value in runtime.subscription_policy(args)[1::2]:
                    config.update(tomllib.loads(value))
                self.assertEqual(config['forced_login_method'], 'chatgpt')
                self.assertEqual(config['model_provider'], 'openai')
                self.assertEqual(config['model_providers'], {})
                self.assertEqual(config['openai_base_url'], 'https://chatgpt.com/backend-api/codex')

    def test_signin_and_help_remain_available_without_credentials(self):
        for args in (['login'], ['login', 'status'], ['app-server'], ['--help'], ['--version']):
            runtime.check_subscription_auth(args)

    def test_api_env_and_work_home_never_reach_native_children(self):
        names = ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_API_BASE',
                 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT', 'CODEX_BEARER_TOKEN')
        with patch.dict(os.environ, dict.fromkeys(names, 'fixture-only') | {
                'CODEX_HOME': str(self.home / '.codex-work'), 'UNRELATED': 'preserved'}):
            environment = runtime.subscription_environment()
            self.assertTrue(all(name not in environment for name in names))
            self.assertEqual(environment['CODEX_HOME'], str(self.home / '.codex'))
            self.assertEqual(environment['UNRELATED'], 'preserved')
            self.assertEqual(os.environ['CODEX_API_KEY'], 'fixture-only')

    def test_billing_overrides_cannot_bypass_policy_including_reviews(self):
        overrides = ('forced_login_method="api"', 'model_provider="proxy"',
                     'model_providers.proxy.env_key="SECRET"',
                     'openai_base_url="https://example.invalid"',
                     'chatgpt_base_url="https://example.invalid"',
                     'cli_auth_credentials_store="keyring"', 'preferred_auth_method="apikey"',
                     '"forced_login_method"="api"')
        for value in overrides:
            for form in (['-c', value], ['--config', value], ['--config=' + value], ['-c' + value]):
                for command in ('exec', 'review', 'app-server'):
                    with self.subTest(form=form, command=command), self.assertRaises(ValueError):
                        runtime.subscription_policy([command, *form])
        for flag in ('--with-api-key', '--oss', '--local-provider=ollama', '--remote=ws://example.invalid'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                runtime.subscription_policy(['login', flag])

    def test_native_nonbilling_flags_profiles_and_literal_prompts_remain_supported(self):
        runtime.subscription_policy(['--profile', 'review', '-c', 'model="fixture"', 'exec',
                                     '--', '--with-api-key'])

    def test_subscription_home_still_rejects_work_personal_boundary_switch(self):
        marker = self.base / 'must-not-run'
        self.configure_hook('PreToolUse', self.stub_hook(marker=marker))
        with patch.dict(os.environ, {'AGENT_CODEX_BOUNDARY': 'work'}):
            output, _ = runtime.hook('PreToolUse', {'cwd': str(self.cwd)})
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertFalse(marker.exists())

    def test_conductor_workspace_and_explicit_cd(self):
        with patch.dict(os.environ, {'CONDUCTOR_WORKSPACE_PATH': str(self.cwd)}):
            self.assertEqual(runtime.launch_cwd(['app-server']), self.cwd.resolve())
            self.assertEqual(runtime.launch_cwd(['-C', str(self.home), 'exec']), self.home.resolve())
            self.assertEqual(runtime.launch_cwd(['--cd=' + str(self.home)]), self.home.resolve())
            self.assertEqual(runtime.launch_cwd(['--', '--cd', str(self.home)]), self.cwd.resolve())

    def test_toml_round_trip_special_characters(self):
        value = {'quoted.key': 'line\n"quoted" \\ path $HOME `literal` café',
                 'nested': {'yes': True, 'no': False}, 'list': [1, 2.5, 'x', []]}
        self.assertEqual(tomllib.loads('value=' + runtime.toml(value))['value'], value)

    def test_toml_rejects_null(self):
        with self.assertRaises(ValueError):
            runtime.toml(None)

    def test_server_key_uses_native_unquoted_override_segments(self):
        self.assertEqual(runtime.server_key('linear-server'), 'mcp_servers.linear-server')
        self.assertEqual(runtime.server_key('fixture_123'), 'mcp_servers.fixture_123')
        self.manifest(connectors=[self.connector('linear-server')])
        args, _ = runtime.overrides(self.cwd)
        self.assertTrue(any(value.startswith('mcp_servers.linear-server=') for value in args))
        self.assertFalse(any('mcp_servers."' in value for value in args))

    def test_server_key_rejects_names_requiring_quoted_segments(self):
        for name in ('linear.server', '"linear"', "linear's", 'linear server', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runtime.server_key(name)

    def test_overrides_follow_add_change_remove_without_projection_files(self):
        before = set(self.home.rglob('*'))
        self.manifest(connectors=[self.connector()])
        first, _ = self.parsed_overrides()
        self.assertEqual(first[1]['mcp_servers']['linear']['url'], 'https://example.invalid/mcp')
        self.manifest(connectors=[self.connector(url='https://changed.invalid/mcp'), self.connector('second')])
        second, _ = self.parsed_overrides()
        self.assertEqual(second[1]['mcp_servers']['linear']['url'], 'https://changed.invalid/mcp')
        self.assertIn('second', second[2]['mcp_servers'])
        self.manifest(connectors=[])
        final, _ = self.parsed_overrides()
        self.assertFalse(any('mcp_servers' in item for item in final))
        self.assertEqual(set(self.home.rglob('*')), before)

    def test_cli_connectors_are_not_mcp_servers(self):
        self.manifest(connectors=[{'name': 'gh', 'kind': 'cli'}])
        values, _ = self.parsed_overrides()
        self.assertEqual(len(values), 1)

    def test_on_demand_and_wrong_boundary_connectors_disabled(self):
        self.assertFalse(runtime.codex_server(self.connector(enabledOnDemand=True), 'personal')['enabled'])
        self.assertFalse(runtime.codex_server(self.connector(boundary='work'), 'personal')['enabled'])

    def test_stdio_expansion_and_input_not_mutated(self):
        connector = {'name': 'local', 'mcp': {'type': 'stdio', 'command': '~/bin/tool',
                     'args': ['~/config', 'literal'], 'env': {'MODE': 'work'}}}
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            result = runtime.codex_server(connector, 'personal')
        self.assertEqual(result['command'], str(self.home / 'bin/tool'))
        self.assertEqual(result['args'][0], str(self.home / 'config'))
        self.assertEqual(connector['mcp']['type'], 'stdio')

    def test_unsupported_or_sensitive_mcp_shape_fails(self):
        for source in ({'type': 'sse', 'url': 'https://example.invalid'},
                       {'type': 'http', 'url': 'https://example.invalid', 'headers': {'Authorization': 'fixture'}},
                       {'type': 'http'}, {'type': 'stdio', 'command': 'x', 'unexpected': True}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                runtime.codex_server({'name': 'test', 'mcp': source}, 'personal')

    def test_native_hooks_follow_settings_events(self):
        self.assertEqual(set(runtime.native_hooks()), {'SessionStart', 'PreToolUse'})
        self.write('settings.json', {'hooks': {'Stop': [], 'UserPromptSubmit': []}})
        self.assertEqual(set(runtime.native_hooks()), {'SessionStart', 'PreToolUse', 'Stop', 'UserPromptSubmit'})
        self.write('settings.json', {'hooks': {'InventedEvent': []}})
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            runtime.native_hooks()

    def test_exit_and_interrupt_native_timeouts_are_at_most_three_seconds(self):
        self.write('settings.json', {'hooks': {'SessionEnd': [], 'Interrupt': []}})
        for event in ('SessionEnd', 'Interrupt'):
            for group in runtime.native_hooks()[event]:
                for handler in group['hooks']:
                    self.assertLessEqual(handler['timeout'], 3)

    def test_stdio_transport_inferred_from_manifest_kind(self):
        connector = {'name': 'fixture', 'kind': 'mcp-stdio',
                     'mcp': {'command': 'python3', 'args': ['fixture.py']}}
        self.assertEqual(runtime.codex_server(connector, 'personal'),
                         {'command': 'python3', 'args': ['fixture.py'], 'enabled': True})

    def test_retired_receipt_stores_names_without_connector_settings(self):
        self.manifest(connectors=[self.connector('one'), self.connector('two'),
                                  {'name': 'cli', 'kind': 'cli'}])
        home = self.home / '.codex'
        self.assertEqual(runtime.retired_overrides(self.cwd, home), [])
        receipt = home / '.agent-runtime/managed-mcp-names.json'
        self.assertEqual(json.loads(receipt.read_text()), ['one', 'two'])
        self.assertNotIn('example.invalid', receipt.read_text())
        self.assertFalse((home / '.agent-runtime/managed-mcp-names.tmp').exists())

    def test_retired_connectors_receive_disabled_tombstones_after_deletion(self):
        self.manifest(connectors=[self.connector('retired'), self.connector('kept')])
        home = self.home / '.codex'
        runtime.retired_overrides(self.cwd, home)
        self.manifest(connectors=[self.connector('kept')])
        args = runtime.retired_overrides(self.cwd, home)
        self.assertEqual(args[::2], ['-c'])
        config = tomllib.loads(args[1])['mcp_servers']
        self.assertEqual(config, {'retired': {'command': 'false', 'enabled': False}})
        self.assertEqual(runtime.retired_overrides(self.cwd, home), args)
        self.manifest(connectors=[self.connector('kept'), self.connector('retired')])
        self.assertEqual(runtime.retired_overrides(self.cwd, home), [])

    def test_switching_projects_masks_previous_managed_names_without_editing_config_or_auth(self):
        self.manifest('first', match=['PersonalOrg/first'], connectors=[self.connector('first-server')])
        self.manifest('second', match=['PersonalOrg/second'], connectors=[self.connector('second-server')])
        home = self.home / '.codex'
        home.mkdir()
        native = home / 'config.toml'
        auth = home / 'auth.json'
        native.write_text('model = "fixture"\n')
        auth.write_text('fixture-auth')
        originals = {file: (file.read_bytes(), file.stat().st_mtime_ns)
                     for file in [native, auth, *sorted((self.root / 'connectors').glob('*.json'))]}
        self.remote = 'https://github.com/PersonalOrg/first.git'
        runtime.retired_overrides(self.cwd, home)
        self.remote = 'https://github.com/PersonalOrg/second.git'
        args = runtime.retired_overrides(self.cwd, home)
        self.assertEqual(tomllib.loads(args[1])['mcp_servers']['first-server']['enabled'], False)
        self.assertEqual(json.loads((home / '.agent-runtime/managed-mcp-names.json').read_text()),
                         ['first-server', 'second-server'])
        for file, original in originals.items():
            self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), original)

    def test_conductor_root_key_preserves_preferences_and_original_backup(self):
        path = self.home / '.conductor/settings.toml'
        path.parent.mkdir()
        original = ('"$schema" = "https://example.invalid/schema"\n'
                    'codex_provider = "default"\n\n[models]\ndefault = "codex:fixture"\n'
                    '[models.codex]\ndefault_thinking_level = "high"\n')
        path.write_text(original)
        runtime.configure_conductor()
        parsed = tomllib.loads(path.read_text())
        self.assertEqual(parsed['codex_executable_path'], str(self.root / 'bin/codex-launch.py'))
        self.assertEqual(parsed['models']['default'], 'codex:fixture')
        self.assertEqual(parsed['models']['codex']['default_thinking_level'], 'high')
        self.assertEqual(parsed['codex_provider'], 'default')
        backup = path.with_name('settings.toml.before-shared-config')
        self.assertEqual(backup.read_text(), original)
        modified = path.stat().st_mtime_ns
        runtime.configure_conductor()
        self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertEqual(backup.read_text(), original)

    def test_conductor_updates_existing_root_key_once(self):
        path = self.home / '.conductor/settings.toml'
        path.parent.mkdir()
        path.write_text('codex_executable_path = "/old/path"\n[models]\ndefault = "fixture"\n')
        runtime.configure_conductor()
        self.assertEqual(path.read_text().count('codex_executable_path'), 1)
        self.assertEqual(tomllib.loads(path.read_text())['codex_executable_path'],
                         str(self.root / 'bin/codex-launch.py'))

    def test_conductor_replaces_indented_root_key_without_invalid_duplicate(self):
        path = self.home / '.conductor/settings.toml'
        path.parent.mkdir()
        path.write_text('  codex_executable_path = "/old/path"\n[models]\ndefault = "fixture"\n')
        runtime.configure_conductor()
        parsed = tomllib.loads(path.read_text())
        self.assertEqual(parsed['codex_executable_path'], str(self.root / 'bin/codex-launch.py'))

    def test_conductor_creates_new_settings_without_spurious_backup(self):
        runtime.configure_conductor()
        path = self.home / '.conductor/settings.toml'
        self.assertEqual(tomllib.loads(path.read_text())['codex_executable_path'],
                         str(self.root / 'bin/codex-launch.py'))
        self.assertFalse(path.with_name('settings.toml.before-shared-config').exists())

    def test_session_start_matcher_checks_source(self):
        marker = self.base / 'resume-hook-ran'
        self.configure_hook('SessionStart', self.stub_hook(marker=marker), '^resume$')
        runtime.hook('SessionStart', {'cwd': str(self.cwd), 'source': 'startup'})
        self.assertFalse(marker.exists())
        runtime.hook('SessionStart', {'cwd': str(self.cwd), 'source': 'resume'})
        self.assertEqual(json.loads(marker.read_text())['source'], 'resume')

    def test_apply_patch_routes_source_destination_and_other_targets(self):
        payload = {'tool_name': 'apply_patch', 'cwd': str(self.cwd), 'tool_input': {'command':
                   '*** Begin Patch\n*** Update File: old.py\n*** Move to: new.py\n'
                   '*** Add File: added.py\n*** Delete File: gone.py\n*** End Patch'}}
        values = runtime.adapted_payloads(payload)
        self.assertEqual([Path(item['tool_input']['file_path']).name for item in values],
                         ['old.py', 'new.py', 'added.py', 'gone.py'])
        self.assertTrue(all(item['tool_name'] == 'Edit' for item in values))

    def test_unparseable_patch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'identify'):
            runtime.adapted_payloads({'tool_name': 'apply_patch', 'tool_input': {'command': 'invalid'}})

    def test_shell_and_agent_aliases(self):
        result = runtime.adapted_payloads({'tool_name': 'exec_command', 'tool_input': {'cmd': 'true'}})[0]
        self.assertEqual(result['tool_name'], 'Bash')
        self.assertEqual(result['tool_input']['command'], 'true')
        self.assertEqual(runtime.adapted_payloads({'tool_name': 'spawn_agent'})[0]['tool_name'], 'Agent')

    def test_hook_routing_reads_settings_live(self):
        marker = self.base / 'hook-ran.json'
        handler = self.stub_hook({'hookSpecificOutput': {'additionalContext': 'first'}}, marker=marker)
        self.configure_hook('PreToolUse', handler, '^Bash$')
        payload = {'cwd': str(self.cwd), 'tool_name': 'Bash', 'tool_input': {'command': 'true'}}
        output, code = runtime.hook('PreToolUse', payload)
        self.assertEqual(code, 0)
        self.assertEqual(output['hookSpecificOutput']['additionalContext'], 'first')
        self.assertEqual(json.loads(marker.read_text())['tool_name'], 'Bash')
        second = self.stub_hook({'hookSpecificOutput': {'additionalContext': 'second'}})
        self.configure_hook('PreToolUse', second, '^Bash$')
        self.assertEqual(runtime.hook('PreToolUse', payload)[0]['hookSpecificOutput']['additionalContext'], 'second')
        self.write('settings.json', {'hooks': {}})
        self.assertEqual(runtime.hook('PreToolUse', payload), ({}, 0))

    def test_unmatched_hooks_do_not_execute(self):
        marker = self.base / 'must-not-exist'
        self.configure_hook('PreToolUse', self.stub_hook(marker=marker), '^Edit$')
        self.assertEqual(runtime.hook('PreToolUse', {'cwd': str(self.cwd), 'tool_name': 'Bash'}), ({}, 0))
        self.assertFalse(marker.exists())

    def test_hook_decisions_propagate(self):
        for decision in ({'continue': False, 'stopReason': 'hold'},
                         {'decision': 'block', 'reason': 'hold'},
                         {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': 'hold'}},
                         {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'ask'}}):
            with self.subTest(decision=decision):
                self.configure_hook('PreToolUse', self.stub_hook(decision))
                self.assertEqual(runtime.hook('PreToolUse', {'cwd': str(self.cwd)}), (decision, 0))

    def test_failed_hook_stops_dispatch(self):
        self.configure_hook('PreToolUse', self.stub_hook(exit_code=2))
        output, code = runtime.hook('PreToolUse', {'cwd': str(self.cwd)})
        self.assertEqual(code, 2)
        self.assertFalse(output['continue'])

    def test_profile_mismatch_denies_before_running_hook(self):
        marker = self.base / 'must-not-exist'
        self.configure_hook('PreToolUse', self.stub_hook(marker=marker))
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex-work')}):
            output, _ = runtime.hook('PreToolUse', {'cwd': str(self.cwd)})
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertFalse(marker.exists())

    def test_same_boundary_different_manifest_denied_before_shared_hook(self):
        first = self.manifest('first', match=['PersonalOrg/first'])
        self.manifest('second', match=['PersonalOrg/second'])
        marker = self.base / 'must-not-exist'
        self.configure_hook('PreToolUse', self.stub_hook(marker=marker))
        self.remote = 'https://github.com/PersonalOrg/second.git'
        with patch.dict(os.environ, {'AGENT_CODEX_MANIFEST': str(first)}):
            output, code = runtime.hook('PreToolUse', {'cwd': str(self.cwd)})
            start_output, _ = runtime.hook('SessionStart', {'cwd': str(self.cwd)})
        self.assertEqual(code, 0)
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertFalse(start_output['continue'])
        self.assertFalse(marker.exists())

    def test_same_manifest_different_cwd_remains_allowed(self):
        manifest = self.manifest()
        other = self.base / 'another-worktree'
        other.mkdir()
        marker = self.base / 'same-manifest-hook-ran'
        self.configure_hook('PreToolUse', self.stub_hook(marker=marker))
        with patch.dict(os.environ, {'AGENT_CODEX_MANIFEST': str(manifest),
                                    'AGENT_CODEX_LAUNCH_CWD': str(self.cwd)}):
            self.assertEqual(runtime.hook('PreToolUse', {'cwd': str(other)}), ({}, 0))
        self.assertEqual(json.loads(marker.read_text())['cwd'], str(other))

    def test_session_context_reads_canonical_rules_live(self):
        self.assertIn('Canonical rule v1', runtime.context(self.cwd))
        (self.root / 'rules/example.md').write_text('Canonical rule v2')
        output, code = runtime.hook('SessionStart', {'cwd': str(self.cwd)})
        self.assertEqual(code, 0)
        self.assertIn('Canonical rule v2', output['hookSpecificOutput']['additionalContext'])

    def test_install_is_idempotent_and_keeps_auth_files(self):
        home = self.home / '.codex'
        home.mkdir()
        auth = home / 'auth.json'
        auth.write_bytes(b'fixture-auth-do-not-touch')
        original = auth.stat().st_mtime_ns
        runtime.install(home)
        runtime.install(home)
        self.assertEqual((home / 'AGENTS.md').resolve(), (self.root / 'dotfiles/codex-AGENTS.md').resolve())
        self.assertEqual(auth.read_bytes(), b'fixture-auth-do-not-touch')
        self.assertEqual(auth.stat().st_mtime_ns, original)

    def test_install_requires_replace_and_archives_existing_instructions(self):
        home = self.home / '.codex'
        home.mkdir()
        (home / 'AGENTS.md').write_text('old instructions')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            runtime.install(home)
        runtime.install(home, replace=True)
        self.assertEqual((home / 'AGENTS.md.before-shared-config').read_text(), 'old instructions')
        self.assertTrue((home / 'AGENTS.md').is_symlink())

    def test_install_will_not_overwrite_previous_backup(self):
        home = self.home / '.codex'
        home.mkdir()
        (home / 'AGENTS.md').write_text('current')
        (home / 'AGENTS.md.before-shared-config').write_text('previous')
        with self.assertRaisesRegex(ValueError, 'Backup already exists'):
            runtime.install(home, replace=True)
        self.assertEqual((home / 'AGENTS.md').read_text(), 'current')

    def stub_binary(self, path, executable=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o700 if executable else 0o600)
        return path

    def test_launcher_selects_newest_stable_conductor_binary_before_path(self):
        directory = self.base / 'Conductor binaries'
        expected = self.stub_binary(directory / 'codex/0.153.2/codex')
        for version in ('0.99.0', '0.142.5', '0.154.0-alpha.1'):
            self.stub_binary(directory / 'codex' / version / 'codex')
        self.stub_binary(directory / 'codex/0.154.0/codex', executable=False)
        self.stub_binary(self.base / 'path/codex')
        with patch.dict(os.environ, {'CONDUCTOR_AGENT_BINARIES_DIR': str(directory),
                                     'PATH': str(self.base / 'path')}):
            self.assertEqual(runtime.executable(), str(expected.resolve()))

    def test_launcher_finds_conductor_binary_without_host_environment(self):
        directory = self.home / 'Library/Application Support/com.conductor.app/agent-binaries'
        expected = self.stub_binary(directory / 'codex/0.153.2/codex')
        self.assertEqual(runtime.executable(), str(expected.resolve()))

    def test_launcher_explicit_binary_wins_over_conductor(self):
        directory = self.base / 'conductor'
        self.stub_binary(directory / 'codex/0.153.2/codex')
        expected = self.stub_binary(self.base / 'explicit-codex')
        with patch.dict(os.environ, {'CONDUCTOR_AGENT_BINARIES_DIR': str(directory),
                                     'AGENT_CODEX_BIN': str(expected)}):
            self.assertEqual(runtime.executable(), str(expected.resolve()))

    def test_launcher_invalid_explicit_binary_does_not_fall_back(self):
        self.stub_binary(self.base / 'path/codex')
        with patch.dict(os.environ, {'AGENT_CODEX_BIN': str(self.base / 'missing'),
                                     'PATH': str(self.base / 'path')}):
            with self.assertRaisesRegex(ValueError, 'Codex executable not found'):
                runtime.executable()

    def test_launcher_falls_back_to_path_without_bundled_binary(self):
        expected = self.stub_binary(self.base / 'path/codex')
        with patch.dict(os.environ, {'CONDUCTOR_AGENT_BINARIES_DIR': str(self.base / 'missing'),
                                     'PATH': str(expected.parent)}):
            self.assertEqual(runtime.executable(), str(expected.resolve()))

    def test_launcher_skips_its_own_symlink_in_conductor_directory(self):
        directory = self.base / 'conductor'
        own = self.stub_binary(self.root / 'bin/codex-launch.py')
        link = directory / 'codex/0.153.2/codex'
        link.parent.mkdir(parents=True)
        link.symlink_to(own)
        expected = self.stub_binary(self.base / 'path/codex')
        with patch.dict(os.environ, {'CONDUCTOR_AGENT_BINARIES_DIR': str(directory),
                                     'PATH': str(expected.parent)}):
            self.assertEqual(runtime.executable(), str(expected.resolve()))

    def test_provider_guard_distinguishes_metadata_from_inference(self):
        for args in (['--version'], ['--cd', 'review', 'mcp', 'list'], ['login', 'status'],
                     ['--profile', 'review', 'features', 'list']):
            with self.subTest(args=args):
                self.assertFalse(runtime.codex_inference(args))
        for args in ([], ['review', '--base', 'mcp'], ['exec', 'mcp'], ['app-server'],
                     ['--', 'mcp'], ['--model', 'gpt-6-astra', 'review']):
            with self.subTest(args=args):
                self.assertTrue(runtime.codex_inference(args))

    def test_launcher_executes_only_explicit_fixture_binary(self):
        self.manifest(match=[str(self.cwd)], connectors=[self.connector()])
        binary = self.base / 'stub-codex'
        binary.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                          'print(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd(),'
                          '"home":os.environ.get("CODEX_HOME"),'
                          '"manifest":os.environ.get("AGENT_CODEX_MANIFEST"),'
                          '"provider":os.environ.get("AGENT_MODEL_PROVIDER"),"launch":os.environ.get("AGENT_CODEX_LAUNCH_CWD")}))\n')
        binary.chmod(0o700)
        runner = ('import importlib.util,sys\nfrom pathlib import Path\n'
                  'sys.path.insert(0,str(Path(sys.argv[1]).parent))\n'
                  's=importlib.util.spec_from_file_location("adapter",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                  'm.ROOT=Path(sys.argv[2]);m.origin=lambda cwd:""\n'
                  'sys.argv=["codex-launch.py","app-server","--stdio"];m.launch()\n')
        result = subprocess.run([sys.executable, '-c', runner, str(SOURCE), str(self.root)],
            env={'HOME': str(self.home), 'PATH': os.defpath, 'AGENT_CODEX_BIN': str(binary),
                 'CONDUCTOR_WORKSPACE_PATH': str(self.cwd), 'CODEX_HOME': str(self.home / 'wrong')},
            cwd=self.base, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['cwd'], str(self.cwd.resolve()))
        self.assertEqual(output['home'], str(self.home / '.codex'))
        self.assertEqual(output['provider'], 'openai')
        self.assertEqual(output['launch'], str(self.cwd.resolve()))
        self.assertEqual(output['manifest'], str(self.root / 'connectors/personal.json'))
        self.assertEqual(output['args'][-2:], ['app-server', '--stdio'])
        self.assertTrue(any(value.startswith('mcp_servers.') for value in output['args']))

    def test_launcher_relative_cd_is_not_applied_twice(self):
        self.save_auth({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'fixture-only'}})
        with patch.object(runtime.sys, 'argv', ['codex-launch.py', '-C', 'workspace', 'exec']), \
             patch.object(runtime.os, 'getcwd', return_value=str(self.base)), \
             patch.object(runtime.os, 'chdir') as change_directory, \
             patch.object(runtime.os, 'execve') as execute, \
             patch.object(runtime, 'executable', return_value='/fixture/codex'):
            runtime.launch()
        launch_directory = Path(change_directory.call_args.args[0])
        argv = execute.call_args.args[1]
        effective = launch_directory
        for index, arg in enumerate(argv):
            if arg in ('-C', '--cd'):
                effective = launch_directory / argv[index + 1]
            elif arg.startswith('--cd='):
                effective = launch_directory / arg.split('=', 1)[1]
        self.assertEqual(effective.resolve(), self.cwd.resolve())


if __name__ == '__main__':
    unittest.main()
