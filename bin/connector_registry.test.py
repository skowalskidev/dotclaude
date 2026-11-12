#!/usr/bin/env python3
"""Offline contracts for bin/connector_registry.py: loader, resolver order, health and migration.

Every root, identity overlay and repo here is temporary; nothing reads the real registry.
"""
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('connector_registry.py')
SPEC = importlib.util.spec_from_file_location('connector_registry_under_test', SOURCE)
reg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reg)

WORK_REMOTE = 'git@github.com:WorkOrg/alpha.git'
NOW = datetime.datetime(2026, 11, 6, 12, 0, tzinfo=datetime.timezone.utc)


def stamp(hours_ago):
    return (NOW - datetime.timedelta(hours=hours_ago)).isoformat().replace('+00:00', 'Z')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='connector-registry-test-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.cwd = self.base / 'alpha'
        self.cwd.mkdir()
        self.roots = {'work': self.base / 'work', 'personal': self.base / 'personal'}
        self.identity = {'workOrgMatch': 'WorkOrg/', 'workEmail': 'a@work.test',
                         'connectorRoots': {k: str(v) for k, v in self.roots.items()}}
        patch.dict(os.environ, {}, clear=False).start()
        os.environ.pop('CLAUDE_CONNECTOR_ROOTS', None)
        self.addCleanup(patch.stopall)
        self.root('work', match=['WorkOrg/'], projects={'alpha': ['WorkOrg/alpha'], 'beta': ['WorkOrg/beta']})
        self.root('personal', match=['PersonalOrg/'], projects={})

    def root(self, boundary, match, projects):
        path = self.roots[boundary]
        (path / 'projects').mkdir(parents=True, exist_ok=True)
        (path / 'index.json').write_text(json.dumps({'boundary': boundary, 'match': match}))
        for name, values in projects.items():
            (path / 'projects' / (name + '.json')).write_text(json.dumps({'match': values}))

    def provider(self, boundary, provider, routes, scope='shared-account', capabilities=None):
        record = {'provider': provider, 'scope': scope, 'routes': routes,
                  'capabilities': capabilities or [provider + '.send']}
        (self.roots[boundary] / (provider + '.json')).write_text(json.dumps(record))

    def health(self, boundary, value):
        (self.roots[boundary] / 'health.json').write_text(json.dumps(value))

    def resolve(self, capability, account='', remote=WORK_REMOTE):
        routes, boundary, project = reg.resolve(capability, self.cwd, remote=remote, identity=self.identity,
                                                claude_account=account, at=NOW)
        return [item['route'] for item in routes], routes, boundary, project

    # ---------------------------------------------------------------- resolver order

    def test_proven_route_ranks_above_untested_and_open_circuit_ranks_last(self):
        self.provider('work', 'chat', [{'id': 'first', 'name': 'chat'},
                                       {'id': 'second', 'name': 'chat-b'},
                                       {'id': 'third', 'name': 'chat-c'}])
        self.health('work', {'chat/first': {'lastFailure': {'at': stamp(1), 'reason': 'not loaded'}},
                             'chat/third': {'lastSuccess': {'at': stamp(30)}}})
        order, routes, _, _ = self.resolve('chat.send')
        self.assertEqual(order, ['third', 'second', 'first'])
        self.assertEqual([item['state'] for item in routes], ['ok', 'untested', 'open'])

    def test_failed_route_reopens_after_the_cooldown(self):
        self.provider('work', 'chat', [{'id': 'first', 'name': 'chat'}, {'id': 'second', 'name': 'chat-b'}])
        self.health('work', {'chat/first': {'lastFailure': {'at': stamp(reg.COOLDOWN_HOURS + 1)}}})
        order, routes, _, _ = self.resolve('chat')
        self.assertEqual(order, ['first', 'second'])
        self.assertEqual(routes[0]['state'], 'half-open')

    def test_success_after_a_failure_closes_the_circuit(self):
        self.provider('work', 'chat', [{'id': 'first', 'name': 'chat'}, {'id': 'second', 'name': 'chat-b'}])
        self.health('work', {'chat/first': {'lastFailure': {'at': stamp(5)}, 'lastSuccess': {'at': stamp(1)}}})
        self.assertEqual(self.resolve('chat.send')[0], ['first', 'second'])

    def test_declared_preference_orders_proven_routes(self):
        self.provider('work', 'chat', [{'id': 'native', 'name': 'chat'}, {'id': 'fallback', 'name': 'chat-b'}])
        self.health('work', {'chat/native': {'lastSuccess': {'at': stamp(48)}},
                             'chat/fallback': {'lastSuccess': {'at': stamp(1)}}})
        self.assertEqual(self.resolve('chat.send')[0], ['native', 'fallback'])

    def test_account_bound_route_is_blocked_on_another_login_and_the_fallback_runs(self):
        # The fix for a Slack send that asked Simon to reconnect while a proven app route existed.
        self.provider('work', 'chat', [
            {'id': 'claude-ai', 'name': 'chat', 'kind': 'claude-connector', 'requires': {'claudeAccount': 'workEmail'}},
            {'id': 'claude-ai-second', 'name': 'chat', 'kind': 'claude-connector',
             'requires': {'claudeAccount': 'b@work.test'}},
            {'id': 'codex-app', 'name': 'chat-codex', 'kind': 'codex-app'}])
        self.health('work', {'chat/claude-ai': {'lastSuccess': {'at': stamp(400)}},
                             'chat/claude-ai-second': {'lastFailure': {'at': stamp(2), 'reason': 'not loaded'}},
                             'chat/codex-app': {'lastSuccess': {'at': stamp(20)}}})
        order, routes, _, _ = self.resolve('chat.send', account='b@work.test')
        self.assertEqual(order, ['codex-app', 'claude-ai-second', 'claude-ai'])
        self.assertIn('a@work.test', routes[-1]['blocker'])
        self.assertEqual(self.resolve('chat.send', account='a@work.test')[0][0], 'claude-ai')

    def test_on_demand_route_is_listed_with_its_gate_after_the_rest(self):
        self.provider('work', 'db', [{'id': 'write', 'name': 'db-write', 'enabledOnDemand': True},
                                     {'id': 'read', 'name': 'db-read'}], capabilities=['db.read'])
        order, routes, _, _ = self.resolve('db.read')
        self.assertEqual(order, ['read', 'write'])
        self.assertIn('per-write yes', routes[1]['blocker'])

    def test_resolve_prints_each_routes_key_location_and_never_a_value(self):
        # The fix for a resolve that listed a Linear api route but not the file and variable holding its key.
        key_file = self.base / 'keys.env'
        key_file.write_text('TRACKER_KEY_ALPHA=value-that-must-not-print\n')
        self.provider('work', 'tracker', [
            {'id': 'api', 'name': 'tracker', 'kind': 'api',
             'secret': {'path': str(key_file), 'var': 'TRACKER_KEY_ALPHA'}},
            {'id': 'pair', 'name': 'tracker-b', 'kind': 'api',
             'secret': {'path': '~/keys/pair.env', 'var': ['PAIR_SID', 'PAIR_SECRET']}},
            {'id': 'oauth', 'name': 'tracker-mcp', 'kind': 'mcp-http'}])
        _, routes, _, _ = self.resolve('tracker')
        self.assertEqual([item['secret'] for item in routes],
                         [{'store': 'local', 'path': str(key_file), 'var': ['TRACKER_KEY_ALPHA']},
                          {'store': 'local', 'path': '~/keys/pair.env', 'var': ['PAIR_SID', 'PAIR_SECRET']},
                          None])
        identity = self.base / 'identity.json'
        identity.write_text(json.dumps(self.identity))
        outputs = {}
        with patch.dict(os.environ, {'CLAUDE_IDENTITY_FILE': str(identity)}), \
                patch.object(reg, 'origin', return_value=WORK_REMOTE), \
                patch.object(reg, 'current_claude_account', return_value=''):
            for flag in ([], ['--json']):
                with patch('sys.stdout', new_callable=io.StringIO) as out:
                    self.assertEqual(reg.main(['resolve', 'tracker', '--cwd', str(self.cwd)] + flag), 0)
                outputs[tuple(flag)] = out.getvalue()
        self.assertIn('key in ' + str(key_file) + ' as TRACKER_KEY_ALPHA', outputs[()])
        self.assertIn('key in ~/keys/pair.env as PAIR_SID, PAIR_SECRET', outputs[()])
        self.assertEqual(json.loads(outputs[('--json',)])['routes'][0]['secret']['var'], ['TRACKER_KEY_ALPHA'])
        for text in outputs.values():
            self.assertNotIn('value-that-must-not-print', text)

    def test_secret_var_must_be_a_variable_name_not_a_value(self):
        self.provider('work', 'tracker', [{'id': 'api', 'name': 'tracker', 'kind': 'api',
                                           'secret': {'path': '~/k.env', 'var': 'lin_api-abc.123'}}])
        self.assertIn('secret.var must be variable names', ' '.join(reg.load_all(self.identity)[0]['errors']))

    # ---------------------------------------------------------------- hybrid keys: local files + vault pointers

    def vault_setup(self, store_order=None, via='vaultdb/vault'):
        key_file = self.base / 'shared.env'
        key_file.write_text('MGMT_TOKEN=mgmt-token-must-not-print\nBILLING_KEY="local-value-must-not-print"\n')
        self.provider('work', 'vaultdb', [{'id': 'vault', 'name': 'vaultdb-vault', 'kind': 'api',
                                           'secret': {'path': str(key_file), 'var': 'MGMT_TOKEN'}}],
                      capabilities=['vaultdb.read'])
        record = {'provider': 'billing', 'scope': 'shared-account', 'capabilities': ['billing.read'],
                  'routes': [{'id': 'billing-vault', 'name': 'billing-vault', 'kind': 'api',
                              'secret': {'store': 'vault', 'via': via, 'project': 'proj-ref',
                                         'name': "Billing key ", 'env': 'BILLING_KEY'}},
                             {'id': 'billing-local', 'name': 'billing', 'kind': 'api',
                              'secret': {'path': str(key_file), 'var': 'BILLING_KEY'}}]}
        if store_order:
            record['storeOrder'] = store_order
        (self.roots['work'] / 'billing.json').write_text(json.dumps(record))
        return key_file

    def test_vault_pointer_holds_names_only_and_rejects_a_mixed_or_incomplete_record(self):
        bad = [({'store': 'vault', 'project': 'p', 'name': 'n', 'env': 'N'}, 'needs "via"'),
               ({'store': 'vault', 'via': 'db/vault', 'name': 'n', 'env': 'N'}, 'vault "project"'),
               ({'store': 'vault', 'via': 'db/vault', 'project': 'p', 'name': 'n', 'env': 'sk-live 1'},
                'needs "env"'),
               ({'store': 'vault', 'via': 'db/vault', 'project': 'p', 'name': 'n', 'env': 'N',
                 'path': '~/k.env'}, 'vault pointer'),
               ({'store': 'cloud', 'path': '~/k.env'}, 'store must be one of')]
        for secret, message in bad:
            self.provider('work', 'tracker', [{'id': 'api', 'name': 'tracker', 'kind': 'api', 'secret': secret}])
            self.assertIn(message, ' '.join(reg.load_all(self.identity)[0]['errors']), secret)
        self.provider('work', 'tracker', [{'id': 'api', 'name': 'tracker'}])
        (self.roots['work'] / 'tracker.json').write_text(json.dumps(
            {'provider': 'tracker', 'scope': 'shared-account', 'storeOrder': ['vault'], 'routes': []}))
        self.assertIn('storeOrder must list', ' '.join(reg.load_all(self.identity)[0]['errors']))

    def test_resolve_lists_the_local_key_before_the_vault_pointer_unless_the_provider_flips_it(self):
        self.vault_setup()
        order, routes, _, _ = self.resolve('billing')
        self.assertEqual(order, ['billing-local', 'billing-vault'])
        self.assertEqual(routes[1]['secret'], {'store': 'vault', 'via': 'vaultdb/vault', 'project': 'proj-ref',
                                               'name': 'Billing key ', 'env': 'BILLING_KEY'})
        self.assertEqual(routes[1]['blocker'], '')
        self.vault_setup(store_order=['vault', 'local'])
        self.assertEqual(self.resolve('billing')[0], ['billing-vault', 'billing-local'])

    def test_a_failed_local_key_falls_back_to_the_vault_pointer(self):
        self.vault_setup()
        self.health('work', {'billing/billing-local': {'lastFailure': {'at': stamp(1), 'reason': 'revoked'}}})
        self.assertEqual(self.resolve('billing')[0], ['billing-vault', 'billing-local'])

    def test_vault_pointer_through_an_undeclared_route_is_blocked(self):
        self.vault_setup(via='vaultdb/missing')
        order, routes, _, _ = self.resolve('billing')
        self.assertEqual(order, ['billing-local', 'billing-vault'])
        self.assertIn('names no local-key route', routes[1]['blocker'])

    def test_resolve_prints_the_vault_name_and_its_run_command_never_a_value(self):
        self.vault_setup()
        identity = self.base / 'identity.json'
        identity.write_text(json.dumps(self.identity))
        with patch.dict(os.environ, {'CLAUDE_IDENTITY_FILE': str(identity)}), \
                patch.object(reg, 'origin', return_value=WORK_REMOTE), \
                patch.object(reg, 'current_claude_account', return_value=''), \
                patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(reg.main(['resolve', 'billing', '--cwd', str(self.cwd)]), 0)
        text = out.getvalue()
        self.assertIn('key in Supabase Vault proj-ref as "Billing key " via vaultdb/vault', text)
        self.assertIn('connector_registry.py run billing billing-vault -- <cmd reading $BILLING_KEY>', text)
        self.assertNotIn('must-not-print', text)

    def run_child(self, route, expected, opener=None):
        """The real child process exits 0 only when it received the expected key in its environment."""
        identity = self.base / 'identity.json'
        identity.write_text(json.dumps(self.identity))
        child = [os.sys.executable, '-c', 'import os, sys; sys.exit(0 if os.environ.get("BILLING_KEY") == '
                 + repr(expected) + ' else 3)']
        with patch.dict(os.environ, {'CLAUDE_IDENTITY_FILE': str(identity)}), \
                patch.object(reg, 'origin', return_value=WORK_REMOTE):
            return reg.run_with_key('billing', route, child, self.cwd, opener=opener)

    def test_run_loads_a_local_key_into_the_child_only(self):
        self.vault_setup()
        self.assertEqual(self.run_child('billing-local', 'local-value-must-not-print'), 0)
        self.assertNotIn('BILLING_KEY', os.environ)

    def test_run_reads_a_vault_pointer_through_its_route_and_quotes_the_name(self):
        self.vault_setup()
        (self.roots['work'] / 'billing.json').write_text((self.roots['work'] / 'billing.json').read_text()
                                                         .replace('Billing key ', "Bob's key "))
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout):
            seen['url'] = request.full_url
            seen['auth'] = request.headers['Authorization']
            seen['query'] = json.loads(request.data)['query']
            return Response(json.dumps([{'name': "Bob's key ", 'decrypted_secret': 'vault-value-must-not-print'}]).encode())

        self.assertEqual(self.run_child('billing-vault', 'vault-value-must-not-print', opener=opener), 0)
        self.assertEqual(seen['url'], reg.VAULT_API + 'proj-ref/database/query')
        self.assertEqual(seen['auth'], 'Bearer mgmt-token-must-not-print')
        self.assertIn("where name in ('Bob''s key ')", seen['query'])

    def test_vault_read_errors_carry_neither_token_nor_value(self):
        def missing(request, timeout):
            raise reg.urllib.error.HTTPError(request.full_url, 401, 'Unauthorized', {}, None)
        secret = {'store': 'vault', 'via': 'a/b', 'project': 'p', 'name': 'n', 'env': 'N'}
        with self.assertRaises(reg.RegistryError) as caught:
            reg.read_vault(secret, 'mgmt-token-must-not-print', opener=missing)
        self.assertEqual(str(caught.exception), 'vault read for "n" failed: HTTP 401')

    def test_a_multi_key_vault_pointer_returns_every_variable_or_names_the_missing_one(self):
        secret = {'store': 'vault', 'via': 'a/b', 'project': 'p', 'name': ['Sid', 'Token'],
                  'env': ['ACCOUNT_SID', 'AUTH_TOKEN']}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        rows = [{'name': 'Sid', 'decrypted_secret': 'sid-value'}, {'name': 'Token', 'decrypted_secret': 'tok-value'}]
        got = reg.read_vault(secret, 't', opener=lambda request, timeout: Response(json.dumps(rows).encode()))
        self.assertEqual(got, {'ACCOUNT_SID': 'sid-value', 'AUTH_TOKEN': 'tok-value'})
        with self.assertRaises(reg.RegistryError) as caught:
            reg.read_vault(secret, 't', opener=lambda request, timeout: Response(json.dumps(rows[:1]).encode()))
        self.assertEqual(str(caught.exception), 'no Vault secret named "Token" in project p')
        self.assertNotIn('sid-value', str(caught.exception))
        self.provider('work', 'tracker', [{'id': 'api', 'name': 'tracker', 'kind': 'api',
                                           'secret': {**secret, 'env': ['ACCOUNT_SID']}}])
        self.assertIn('one variable name the consumer reads per vault name',
                      ' '.join(reg.load_all(self.identity)[0]['errors']))

    def test_validate_gates_a_staged_root_before_it_replaces_the_live_one(self):
        # The fix for vault pointers written to the live root before the engine that reads them was
        # active: every launch then failed on "secret needs a path string". Reader before data.
        self.vault_setup()
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(reg.main(['validate', str(self.roots['work'])]), 0)
        self.assertIn('PASS', out.getvalue())
        record = json.loads((self.roots['work'] / 'billing.json').read_text())
        record['routes'][0]['secret']['store'] = 'cloud-kms'  # a kind this engine cannot read
        (self.roots['work'] / 'billing.json').write_text(json.dumps(record))
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(reg.main(['validate', str(self.roots['work'])]), 1)
        self.assertIn('store must be one of', out.getvalue())
        self.vault_setup(via='vaultdb/missing')
        self.assertTrue(any('names no local-key route' in e for e in reg.validate_root(self.roots['work'])))

    # ---------------------------------------------------------------- scope and boundary

    def test_another_projects_key_is_ranked_after_but_never_excluded(self):
        self.provider('work', 'db', [
            {'id': 'beta-key', 'name': 'db-beta', 'serves': ['beta']},
            {'id': 'alpha-key', 'name': 'db-alpha', 'serves': ['alpha']}], scope='per-project',
            capabilities=['db.read'])
        self.health('work', {'db/beta-key': {'lastSuccess': {'at': stamp(1), 'project': 'beta'}}})
        order, routes, _, project = self.resolve('db.read')
        self.assertEqual(project, 'alpha')
        self.assertEqual(order, ['alpha-key', 'beta-key'])
        self.assertFalse(routes[1]['servesHere'])

    def test_a_recorded_success_for_this_project_counts_as_scope(self):
        self.provider('work', 'db', [
            {'id': 'beta-key', 'name': 'db-beta', 'serves': ['beta']},
            {'id': 'gamma-key', 'name': 'db-gamma', 'serves': ['gamma']}], scope='per-project',
            capabilities=['db.read'])
        self.health('work', {'db/gamma-key': {'lastSuccess': {'at': stamp(1), 'project': 'alpha'}}})
        order, routes, _, _ = self.resolve('db.read')
        self.assertEqual(order, ['gamma-key', 'beta-key'])
        self.assertTrue(routes[0]['servesHere'])

    def test_routes_of_the_other_boundary_are_never_returned(self):
        self.provider('work', 'chat', [{'id': 'work-route', 'name': 'chat'}])
        self.provider('personal', 'chat', [{'id': 'personal-route', 'name': 'chat-p'}])
        self.assertEqual(self.resolve('chat.send')[0], ['work-route'])
        order, _, boundary, _ = self.resolve('chat.send', remote='git@github.com:PersonalOrg/x.git')
        self.assertEqual((order, boundary), (['personal-route'], 'personal'))

    def test_capability_query_matches_provider_family_and_exact_names_only(self):
        self.provider('work', 'chat', [{'id': 'r', 'name': 'chat', 'capabilities': ['chat.send', 'chat.read']}])
        self.assertEqual(self.resolve('chat')[0], ['r'])
        self.assertEqual(self.resolve('chat.read')[0], ['r'])
        self.assertEqual(self.resolve('chat.upload')[0], [])
        self.assertEqual(self.resolve('cha')[0], [])

    # ---------------------------------------------------------------- health records

    def test_record_writes_outcomes_privately_and_keeps_both_sides(self):
        self.provider('work', 'chat', [{'id': 'r', 'name': 'chat'}])
        reg.record('chat', 'r', 'fail', self.cwd, reason='timeout', by='t', remote=WORK_REMOTE,
                   identity=self.identity, at=NOW)
        reg.record('chat', 'r', 'ok', self.cwd, by='t', remote=WORK_REMOTE, identity=self.identity,
                   at=NOW + datetime.timedelta(minutes=5))
        path = self.roots['work'] / 'health.json'
        entry = json.loads(path.read_text())['chat/r']
        self.assertEqual(entry['lastFailure']['reason'], 'timeout')
        self.assertEqual(entry['lastFailure']['project'], 'alpha')
        self.assertTrue(entry['lastSuccess']['at'] > entry['lastFailure']['at'])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.resolve('chat')[1][0]['state'], 'ok')

    def test_record_refuses_a_route_outside_the_session_boundary_or_unknown(self):
        self.provider('personal', 'chat', [{'id': 'p', 'name': 'chat'}])
        with self.assertRaisesRegex(ValueError, 'no work provider'):
            reg.record('chat', 'p', 'ok', self.cwd, remote=WORK_REMOTE, identity=self.identity)
        self.provider('work', 'chat', [{'id': 'w', 'name': 'chat'}])
        with self.assertRaisesRegex(ValueError, 'no route'):
            reg.record('chat', 'missing', 'ok', self.cwd, remote=WORK_REMOTE, identity=self.identity)

    # ---------------------------------------------------------------- loader and selection

    def test_selection_layers_shared_routes_and_respects_serves_lists(self):
        self.provider('work', 'chat', [{'id': 'everywhere', 'name': 'chat'},
                                       {'id': 'listed', 'name': 'chat-listed', 'serves': ['beta']}])
        self.provider('work', 'db', [{'id': 'alpha', 'name': 'db', 'serves': ['alpha']}], scope='per-project')
        path, manifest, boundary = reg.select(self.cwd, remote=WORK_REMOTE, identity=self.identity)
        self.assertEqual(path, self.roots['work'] / 'projects/alpha.json')
        self.assertEqual(boundary, 'work')
        self.assertEqual([item['name'] for item in manifest['connectors']], ['db', 'chat'])
        self.assertEqual(manifest['connectors'][0]['boundary'], 'work')
        self.assertEqual(manifest['sharedFrom'], [str(self.roots['work'])])

    def test_route_boundary_must_equal_its_root(self):
        self.provider('work', 'chat', [{'id': 'r', 'name': 'chat', 'boundary': 'personal'}])
        roots = reg.load_all(self.identity)
        self.assertIn('boundary differs', ' '.join(roots[0]['errors']))
        with self.assertRaisesRegex(ValueError, 'Unreadable'):
            reg.select(self.cwd, remote=WORK_REMOTE, identity=self.identity)

    def test_per_project_route_without_serves_is_rejected(self):
        self.provider('work', 'db', [{'id': 'r', 'name': 'db'}], scope='per-project')
        self.assertIn('must list the projects', ' '.join(reg.load_all(self.identity)[0]['errors']))

    def test_guard_facts_report_every_boundary_of_a_name(self):
        self.provider('work', 'store', [{'id': 'w', 'name': 'store', 'readOnly': True}])
        self.provider('personal', 'store', [{'id': 'p', 'name': 'store'}])
        roots = reg.load_all(self.identity)
        facts = reg.guard_facts('store', self.cwd, remote=WORK_REMOTE, roots=roots, identity=self.identity)
        self.assertEqual(facts['boundaries'], ['personal', 'work'])
        self.assertTrue(facts['readOnly'])

    # ---------------------------------------------------------------- migration

    def legacy(self):
        same = {'name': 'sms-api', 'kind': 'api', 'secret': {'path': '~/keys/shared.env'}, 'readOnly': True}
        return {
            'alpha': {'project': 'alpha', 'boundary': 'work', 'match': ['WorkOrg/alpha'],
                      'ignoreProjectInstructions': True, 'monitor': {'probe': 1},
                      'connectors': [dict(same, auth={'how': 'alpha notes'}),
                                     {'name': 'db', 'kind': 'api', 'secret': {'path': '~/keys/alpha.env'}}]},
            'beta': {'project': 'beta', 'boundary': 'work', 'match': ['WorkOrg/beta'],
                     'connectors': [dict(same, auth={'how': 'beta notes'}),
                                    {'name': 'db', 'kind': 'api', 'secret': {'path': '~/keys/beta.env'}}]},
            'work-shared': {'shared': True, 'boundary': 'work', 'match': ['WorkOrg/'],
                            'connectors': [{'name': 'chat', 'kind': 'claude-connector', 'boundary': 'work'}]},
        }

    def migrate(self, legacy):
        for path in self.roots.values():
            for file in sorted(path.rglob('*'), reverse=True):
                file.unlink() if file.is_file() else file.rmdir()
        tree = reg.build_registry(legacy)
        reg.write_registry(tree, list(self.roots.items()), force=True)
        return reg.load_all(self.identity)

    def test_migration_keeps_every_field_reachable_and_merges_one_shared_account(self):
        legacy = self.legacy()
        roots = self.migrate(legacy)
        self.assertEqual(reg.check_migration(legacy, roots), [])
        routes = {route['route']: route for route in reg.flat_routes(roots[0])}
        self.assertEqual(routes['sms-api']['scope'], 'shared-account')
        self.assertEqual(routes['sms-api']['serves'], ['alpha', 'beta'])
        self.assertEqual(sorted(name for name in routes if name.startswith('db')), ['db', 'db@beta'])
        _, beta, _ = reg.select(self.cwd, remote='git@github.com:WorkOrg/beta.git', identity=self.identity)
        sms = next(item for item in beta['connectors'] if item['name'] == 'sms-api')
        self.assertEqual(sms['auth'], {'how': 'beta notes'})
        _, alpha, _ = reg.select(self.cwd, remote=WORK_REMOTE, identity=self.identity)
        self.assertTrue(alpha['ignoreProjectInstructions'])
        self.assertEqual(alpha['monitor'], {'probe': 1})
        self.assertEqual(reg.project_manifest('beta', roots)['project'], 'beta')

    def test_migration_check_catches_a_dropped_field(self):
        legacy = self.legacy()
        roots = self.migrate(legacy)
        provider = self.roots['work'] / 'db.json'
        record = json.loads(provider.read_text())
        del record['routes'][0]['secret']
        provider.write_text(json.dumps(record))
        problems = reg.check_migration(legacy, reg.load_all(self.identity))
        self.assertTrue(any('connector db not reachable' in problem for problem in problems))

    def test_migration_refuses_a_record_of_the_other_boundary(self):
        legacy = {'alpha': {'project': 'alpha', 'boundary': 'work', 'match': ['x'],
                            'connectors': [{'name': 'p', 'boundary': 'personal'}]}}
        with self.assertRaisesRegex(ValueError, 'boundary differs'):
            reg.build_registry(legacy)

    def test_roots_come_from_the_environment_override_first(self):
        with patch.dict(os.environ, {'CLAUDE_CONNECTOR_ROOTS': 'work=' + str(self.roots['work'])}):
            self.assertEqual(reg.configured_roots(self.identity), [('work', self.roots['work'])])
        self.assertEqual(len(reg.configured_roots(self.identity)), 2)


if __name__ == '__main__':
    unittest.main()
