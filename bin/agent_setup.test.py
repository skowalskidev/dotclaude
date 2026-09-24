#!/usr/bin/env python3
"""Offline setup, headless Astra and dual-dispatch tests; all CLIs are fixtures."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
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


class IsolatedCachesMixin:
    """A temp CODEX_HOME and a temp Claude model-catalog dir, so a test never reads Simon's real
    caches. Both start empty: openai_ranked_models() raises and claude_catalog() returns None until
    a test writes a fixture into them."""

    def isolate_caches(self):
        self.codex_home = Path(tempfile.mkdtemp(prefix='agent-setup-codex-home-'))
        self.addCleanup(shutil.rmtree, self.codex_home, ignore_errors=True)
        self.claude_catalog_dir = Path(tempfile.mkdtemp(prefix='agent-setup-claude-catalog-'))
        self.addCleanup(shutil.rmtree, self.claude_catalog_dir, ignore_errors=True)
        patch.dict(os.environ, {'CODEX_HOME': str(self.codex_home),
                                'CLAUDE_MODEL_CATALOG_DIR': str(self.claude_catalog_dir)}).start()

    def write_openai_cache(self, entries, fetched_at='2026-09-24T08:16:41.342528Z'):
        """entries: a list of dicts, each at least {'slug', 'priority'}. visibility defaults to
        'list' and upgrade to None unless a dict overrides them (for a hidden/retiring fixture)."""
        models = []
        for entry in entries:
            row = {'visibility': 'list', 'upgrade': None}
            row.update(entry)
            models.append(row)
        (self.codex_home / 'models_cache.json').write_text(
            json.dumps({'fetched_at': fetched_at, 'models': models}))

    def write_claude_catalog(self, models, fetched_at_ms=None, name='fixture-cc.json'):
        payload = {'fetchedAt': fetched_at_ms if fetched_at_ms is not None else int(time.time() * 1000),
                  'catalog': {'config': {'models': models}}}
        (self.claude_catalog_dir / name).write_text(json.dumps(payload))

    def default_claude_catalog(self):
        self.write_claude_catalog([
            {'id': 'claude-opus-5-5', 'short_name': 'Opus', 'section': 'main'},
            {'id': 'claude-fable-5-1', 'short_name': 'Fable', 'section': 'main'},
            {'id': 'claude-sonnet-5', 'short_name': 'Sonnet', 'section': 'main'},
            {'id': 'claude-haiku-4-5-20251001', 'short_name': 'Haiku', 'section': 'main'},
        ])


class SetupTests(IsolatedCachesMixin, unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        self.isolate_caches()
        self.spec = {'agent_setup': 'full-claude', 'orchestrator_model': 'claude-opus-5-5',
                     'slices': [{'name': 'alpha'}]}

    def test_claude_default_preserves_existing_worker_model(self):
        self.assertEqual(agent_setup.resolve(self.spec)['model'], 'sonnet')

    def test_claude_implementation_rejects_top_tier_and_accepts_worker_tiers(self):
        for model in ('opus', 'claude-opus-4-8', 'claude-opus-5-5', 'fable', 'claude-fable-5-1'):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, 'smaller Claude'):
                agent_setup.resolve(dict(self.spec, model=model))
        for model in ('sonnet', 'haiku', 'claude-sonnet-5'):
            with self.subTest(model=model):
                self.assertEqual(agent_setup.resolve(dict(self.spec, model=model))['model'], model)

    def test_openai_top_tier_orchestrator_detected_by_rank_not_name(self):
        # "Astra" is only ever a name Simon might see; the guard is by RANK, so a differently
        # named model at priority 1 is recognized identically, and the old name at priority 2
        # is not, proving the check is not a substring match on "astra".
        for slug in ('gpt-6-astra', 'gpt-9-nova'):
            with self.subTest(slug=slug):
                self.write_openai_cache([{'slug': slug, 'priority': 1},
                                         {'slug': 'gpt-worker-mid', 'priority': 2},
                                         {'slug': 'gpt-worker-small', 'priority': 3}])
                self.assertTrue(agent_setup.matches_orchestrator('full-astra', slug))
                spec = dict(self.spec, agent_setup='full-astra', orchestrator_model=slug)
                with self.assertRaisesRegex(ValueError, 'smaller OpenAI'):
                    agent_setup.resolve(dict(spec, model=slug))

    def test_openai_worker_defaults_to_the_mid_tier_from_the_live_cache(self):
        self.spec.update(agent_setup='full-astra', orchestrator_model='gpt-6-astra')
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-worker-mid', 'priority': 2},
                                 {'slug': 'gpt-worker-small', 'priority': 3}])
        self.assertEqual(agent_setup.resolve(self.spec)['model'], 'gpt-worker-mid')

    def test_missing_openai_cache_raises_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'launch Codex once to refresh it'):
            agent_setup.resolve_tier('openai', 'mid')

    def test_missing_setup_inherits_current_model(self):
        del self.spec['agent_setup']
        self.assertEqual(agent_setup.resolve(self.spec)['agent_setup'], 'full-claude')

    def test_mixed_models_are_rejected(self):
        for field in ('orchestrator_model', 'model', 'reviewer_model'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                agent_setup.resolve(dict(self.spec, **{field: 'gpt-6-astra'}))

    def test_astra_accepts_sol_and_rejects_astra_as_implementation(self):
        self.spec.update(agent_setup='full-astra', orchestrator_model='gpt-6-astra')
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-5.6-sol', 'priority': 2},
                                 {'slug': 'gpt-5.6-luna', 'priority': 3}])
        self.assertEqual(agent_setup.resolve(dict(self.spec, model='gpt-5.6-sol'))['model'],
                         'gpt-5.6-sol')
        with self.assertRaisesRegex(ValueError, 'smaller OpenAI'):
            agent_setup.resolve(dict(self.spec, model='gpt-6-astra'))

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
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-5.6-sol', 'priority': 2},
                                 {'slug': 'gpt-5.6-luna', 'priority': 3}])
        with patch.dict(os.environ, {'CLAUDECODE': '1', 'AGENT_ALLOW_CROSS_PROVIDER': '1'}):
            resolved = agent_setup.resolve(
                dict(self.spec, agent_setup='full-astra', orchestrator_model='gpt-6-astra',
                     model='gpt-5.6-sol'))
        self.assertEqual(resolved['model_provider'], 'openai')
        self.assertEqual(resolved['agent_setup'], 'full-astra')

    def test_general_openai_session_inherits_model_without_astra_switch(self):
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-5.6-sol', 'priority': 2},
                                 {'slug': 'gpt-5.6-luna', 'priority': 3}])
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'native-fixture'}):
            resolved = agent_setup.resolve(dict(self.spec, agent_setup=None, orchestrator_model='gpt-5.6-sol'))
        self.assertEqual(resolved['agent_setup'], 'full-openai')
        self.assertEqual(resolved['model'], 'gpt-5.6-sol')
        self.assertEqual(resolved['model_provider'], 'openai')

    def test_openai_setup_accepts_same_provider_models_and_rejects_other_reviewers(self):
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-5.6-sol', 'priority': 2},
                                 {'slug': 'gpt-5.6-luna', 'priority': 3}])
        spec = dict(self.spec, agent_setup='full-openai', orchestrator_model='gpt-5.6-sol',
                    model='gpt-5.6-luna')
        self.assertEqual(agent_setup.resolve(spec)['model'], 'gpt-5.6-luna')
        for other in ('sonnet', 'gemini-3-pro', 'unknown'):
            with self.subTest(model=other), self.assertRaises(ValueError):
                agent_setup.resolve(dict(spec, reviewer_model=other))
        with self.assertRaisesRegex(ValueError, 'smaller OpenAI'):
            agent_setup.resolve(dict(spec, model='gpt-6-astra'))

    def test_openai_design_route_pins_fable_and_preserves_general_workers(self):
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-5.6-sol', 'priority': 2},
                                 {'slug': 'gpt-5.6-luna', 'priority': 3}])
        spec = {
            'agent_setup': 'full-openai',
            'orchestrator_model': 'gpt-5.6-sol',
            'model': 'gpt-5.6-sol',
            'slices': [{'name': 'screen', 'model_route': 'design'}, {'name': 'api'}],
        }
        resolved = agent_setup.resolve(spec)
        self.assertEqual(resolved['model'], 'gpt-5.6-sol')
        self.assertEqual(resolved['design_model'], agent_setup.resolve_tier('anthropic', 'design'))
        for design_model in ('fable', 'claude-fable-5-1'):
            with self.subTest(design_model=design_model):
                self.assertEqual(agent_setup.resolve(dict(spec, design_model=design_model))['design_model'],
                                 design_model)
        with self.assertRaisesRegex(ValueError, 'Fable'):
            agent_setup.resolve(dict(spec, design_model='sonnet'))

    def test_design_route_is_openai_only_and_rejects_unknown_routes(self):
        with self.assertRaisesRegex(ValueError, 'GPT-orchestrated'):
            agent_setup.resolve(dict(self.spec, slices=[{'name': 'screen', 'model_route': 'design'}]))
        with self.assertRaisesRegex(ValueError, 'general or design'):
            agent_setup.resolve(dict(self.spec, slices=[{'name': 'screen', 'model_route': 'visual'}]))

    def test_astra_design_uses_fable_and_general_work_uses_worker_model(self):
        spec = {
            'agent_setup': 'full-astra',
            'orchestrator_model': 'gpt-6-astra',
            'slices': [{'name': 'screen', 'model_route': 'design'},
                       {'name': 'approved-ui', 'model_route': 'general'}],
        }
        self.write_openai_cache([{'slug': 'gpt-6-astra', 'priority': 1},
                                 {'slug': 'gpt-worker-mid', 'priority': 2},
                                 {'slug': 'gpt-worker-small', 'priority': 3}])
        resolved = agent_setup.resolve(spec)
        self.assertEqual(resolved['model'], 'gpt-worker-mid')
        self.assertEqual(resolved['design_model'], agent_setup.resolve_tier('anthropic', 'design'))
        with self.assertRaisesRegex(ValueError, 'Fable'):
            agent_setup.resolve(dict(spec, design_model='sonnet'))

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


class ModelResolutionTests(IsolatedCachesMixin, unittest.TestCase):
    """resolve_tier / tier_of / openai_ranked_models against fixture caches only."""

    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        self.isolate_caches()

    def test_new_top_priority_model_becomes_top_and_ranks_shift(self):
        self.write_openai_cache([{'slug': 'gpt-old-top', 'priority': 1},
                                 {'slug': 'gpt-old-mid', 'priority': 2},
                                 {'slug': 'gpt-old-small', 'priority': 3}])
        self.assertEqual(agent_setup.resolve_tier('openai', 'top'), 'gpt-old-top')
        self.write_openai_cache([{'slug': 'gpt-new-flagship', 'priority': 0},
                                 {'slug': 'gpt-old-top', 'priority': 1},
                                 {'slug': 'gpt-old-mid', 'priority': 2},
                                 {'slug': 'gpt-old-small', 'priority': 3}])
        self.assertEqual(agent_setup.resolve_tier('openai', 'top'), 'gpt-new-flagship')
        self.assertEqual(agent_setup.resolve_tier('openai', 'mid'), 'gpt-old-top')
        self.assertEqual(agent_setup.resolve_tier('openai', 'small'), 'gpt-old-mid')

    def test_retiring_and_hidden_models_are_never_picked(self):
        self.write_openai_cache([
            {'slug': 'gpt-retiring', 'priority': 1, 'upgrade': {'model': 'gpt-next'}},
            {'slug': 'gpt-hidden', 'priority': 2, 'visibility': 'hide'},
            {'slug': 'gpt-visible', 'priority': 3},
        ])
        ranked = agent_setup.openai_ranked_models()
        self.assertEqual(ranked, ['gpt-visible'])
        self.assertNotIn('gpt-retiring', ranked)
        self.assertNotIn('gpt-hidden', ranked)
        self.assertEqual(agent_setup.resolve_tier('openai', 'top'), 'gpt-visible')

    def test_missing_cache_raises_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'launch Codex once to refresh it'):
            agent_setup.resolve_tier('openai', 'mid')

    def test_rank_clamps_to_the_last_available_rank(self):
        self.write_openai_cache([{'slug': 'only-model', 'priority': 1}])
        self.assertEqual(agent_setup.resolve_tier('openai', 'top'), 'only-model')
        self.assertEqual(agent_setup.resolve_tier('openai', 'mid'), 'only-model')
        self.assertEqual(agent_setup.resolve_tier('openai', 'small'), 'only-model')

    def test_openai_has_no_design_tier(self):
        self.write_openai_cache([{'slug': 'gpt-top', 'priority': 1}])
        with self.assertRaisesRegex(ValueError, 'no design tier'):
            agent_setup.resolve_tier('openai', 'design')

    def test_implementation_guard_rejects_top_tier_models(self):
        self.write_openai_cache([{'slug': 'gpt-top', 'priority': 1},
                                 {'slug': 'gpt-mid', 'priority': 2},
                                 {'slug': 'gpt-small', 'priority': 3}])
        self.assertFalse(agent_setup.matches_implementation_model('full-openai', 'gpt-top'))
        for model in ('opus', 'fable', 'claude-opus-5-5', 'claude-fable-5-1'):
            with self.subTest(model=model):
                self.assertFalse(agent_setup.matches_implementation_model('full-claude', model))

    def test_implementation_guard_accepts_worker_tiers(self):
        self.write_openai_cache([{'slug': 'gpt-top', 'priority': 1},
                                 {'slug': 'gpt-mid', 'priority': 2},
                                 {'slug': 'gpt-small', 'priority': 3}])
        for model in ('sonnet', 'haiku', 'claude-sonnet-5'):
            with self.subTest(model=model):
                self.assertTrue(agent_setup.matches_implementation_model('full-claude', model))
        for model in ('gpt-mid', 'gpt-small'):
            with self.subTest(model=model):
                self.assertTrue(agent_setup.matches_implementation_model('full-openai', model))

    def test_tier_of_full_claude_id_via_catalog_short_name(self):
        self.write_claude_catalog([{'id': 'claude-opus-5-5', 'short_name': 'Opus', 'section': 'main'},
                                   {'id': 'claude-fable-5-1', 'short_name': 'Fable', 'section': 'main'}])
        self.assertEqual(agent_setup.tier_of('claude-opus-5-5'), 'top')
        self.assertEqual(agent_setup.tier_of('claude-fable-5-1'), 'design')

    def test_tier_of_unknown_openai_model_is_none(self):
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}])
        self.assertIsNone(agent_setup.tier_of('gpt-unlisted'))


class CheckModelsTests(IsolatedCachesMixin, unittest.TestCase):
    """check_models(): warnings and the config.toml auto-update. It must never raise."""

    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        self.isolate_caches()

    def test_never_raises_with_nothing_on_disk(self):
        self.assertIsInstance(agent_setup.check_models(), list)

    def test_stale_openai_cache_warns(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat().replace('+00:00', 'Z')
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}], fetched_at=stale)
        self.default_claude_catalog()
        lines = agent_setup.check_models()
        self.assertTrue(any('OpenAI model cache is' in l and 'days old' in l for l in lines), lines)

    def test_stale_claude_catalog_warns(self):
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}])
        stale_ms = int((datetime.now(timezone.utc) - timedelta(days=9)).timestamp() * 1000)
        self.write_claude_catalog([{'id': 'claude-sonnet-5', 'short_name': 'Sonnet', 'section': 'main'}],
                                  fetched_at_ms=stale_ms)
        lines = agent_setup.check_models()
        self.assertTrue(any('Claude model catalog cache is' in l and 'days old' in l for l in lines), lines)

    def test_env_pin_warns(self):
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}])
        self.default_claude_catalog()
        with patch.dict(os.environ, {'ANTHROPIC_DEFAULT_SONNET_MODEL': 'claude-sonnet-4-9'}):
            lines = agent_setup.check_models()
        self.assertTrue(any('ANTHROPIC_DEFAULT_SONNET_MODEL' in l for l in lines), lines)

    def test_new_tier_and_vanished_tier_warn(self):
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}])
        self.write_claude_catalog([
            {'id': 'claude-opus-5-5', 'short_name': 'Opus', 'section': 'main'},
            {'id': 'claude-nova-1', 'short_name': 'Nova', 'section': 'main'},
        ])
        lines = agent_setup.check_models()
        self.assertTrue(any('nova' in l.lower() for l in lines), lines)
        self.assertTrue(any('fable' in l.lower() and 'retired' in l.lower() for l in lines), lines)

    def test_config_auto_update_rewrites_only_the_unlisted_top_level_model_line(self):
        self.write_openai_cache([{'slug': 'gpt-top', 'priority': 1},
                                 {'slug': 'gpt-mid', 'priority': 2},
                                 {'slug': 'gpt-small', 'priority': 3}])
        self.default_claude_catalog()
        config = self.codex_home / 'config.toml'
        config.write_text(
            'model = "gpt-retired"  # comment kept\n'
            'forced_login_method = "chatgpt"\n'
            '\n[marketplaces.openai-bundled]\n'
            'model = "left-alone"\n')
        config.chmod(0o600)
        lines = agent_setup.check_models()
        text = config.read_text()
        self.assertIn('model = "gpt-mid"  # comment kept', text)
        self.assertIn('forced_login_method = "chatgpt"', text)
        self.assertIn('[marketplaces.openai-bundled]\nmodel = "left-alone"', text)
        self.assertTrue(any('gpt-retired -> gpt-mid' in l for l in lines), lines)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)

    def test_config_left_alone_when_the_current_model_is_still_listed(self):
        self.write_openai_cache([{'slug': 'gpt-top', 'priority': 1}, {'slug': 'gpt-mid', 'priority': 2}])
        self.default_claude_catalog()
        config = self.codex_home / 'config.toml'
        config.write_text('model = "gpt-mid"\n')
        before = config.read_text()
        agent_setup.check_models()
        self.assertEqual(config.read_text(), before)

    def test_config_left_alone_without_a_top_level_model_line(self):
        self.write_openai_cache([{'slug': 'gpt-mid', 'priority': 1}])
        self.default_claude_catalog()
        config = self.codex_home / 'config.toml'
        config.write_text('forced_login_method = "chatgpt"\n')
        before = config.read_text()
        agent_setup.check_models()
        self.assertEqual(config.read_text(), before)

    def test_config_left_alone_without_a_readable_cache(self):
        config = self.codex_home / 'config.toml'
        config.write_text('model = "gpt-anything"\n')
        before = config.read_text()
        agent_setup.check_models()
        self.assertEqual(config.read_text(), before)


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
    def write_openai_cache(self, directory, entries, fetched_at='2026-09-24T08:16:41.342528Z'):
        models = []
        for entry in entries:
            row = {'visibility': 'list', 'upgrade': None}
            row.update(entry)
            models.append(row)
        Path(directory, 'models_cache.json').write_text(
            json.dumps({'fetched_at': fetched_at, 'models': models}))

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
        (subscription / 'config.toml').write_text('model = "gpt-5.6-sol"\n')
        # OpenAI workers have no tier alias; the fixture mid-tier worker model comes from this
        # ranked cache, exactly as Simon's own ~/.codex/models_cache.json would supply it.
        self.write_openai_cache(subscription, [{'slug': 'gpt-6-astra', 'priority': 1},
                                               {'slug': 'gpt-5.6-sol', 'priority': 2},
                                               {'slug': 'gpt-5.6-luna', 'priority': 3}])
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
        self.assertIn('gpt-5.6-sol', call['args'])
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
        self.assertEqual(json.loads(result.stdout)['model'], 'gpt-5.6-sol')
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
        (old_home / 'config.toml').write_text('model = "gpt-5.6-sol"\n')
        self.write_openai_cache(old_home, [{'slug': 'gpt-6-astra', 'priority': 1},
                                           {'slug': 'gpt-5.6-sol', 'priority': 2},
                                           {'slug': 'gpt-5.6-luna', 'priority': 3}])
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
        self.assertNotEqual(self.astra_command('-p', 'work', '--model', 'sonnet').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_astra_implementation_override_is_rejected(self):
        self.assertNotEqual(self.astra_command('-p', 'work', '--model', 'gpt-6-astra').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_astra_read_only_review_is_allowed(self):
        result = self.astra_command('-p', 'review', '--model', 'gpt-6-astra',
                                    '--sandbox', 'read-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads(self.calls.read_text())
        self.assertIn('gpt-6-astra', call['args'])
        self.assertIn('read-only', call['args'])

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
                'orchestrator_model': 'gpt-6-astra' if agent_mode == 'full-astra' else 'claude-opus-5-5',
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
        self.assertEqual(json.loads((output / 'spec.json').read_text())['model'], 'sonnet')

    def test_full_astra_launches_sol_workers_and_records_mode(self):
        result, output = self.dispatch('full-astra')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([call['kind'] for call in calls], ['codex', 'codex'])
        self.assertTrue(all(call['setup'] == 'full-astra' for call in calls))
        self.assertEqual(json.loads((output / 'run.json').read_text())['agent_setup'], 'full-astra')
        self.assertEqual(json.loads((output / 'spec.json').read_text())['model'], 'gpt-5.6-sol')
        for name in ('alpha', 'beta'):
            self.assertEqual((output / 'slices' / name / 'status').read_text().strip(), 'ok')
            self.assertTrue((output / 'slices' / name / 'events.jsonl').is_file())

    def test_dispatch_workers_use_real_subscription_launcher(self):
        shutil.copy2(SOURCE / 'agent_runtime.py', self.bin / 'agent_runtime.py')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, env=self.env)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
                        'https://example.invalid/WorkOrg/project.git'], check=True, env=self.env)
        (self.root / 'identity.local.json').write_text(json.dumps({'workOrgMatch': 'WorkOrg/'}))
        old_home = self.home / '.codex-work'
        old_home.mkdir(parents=True, exist_ok=True)
        (old_home / 'config.toml').write_text('model = "gpt-5.6-sol"\n')
        self.write_openai_cache(old_home, [{'slug': 'gpt-6-astra', 'priority': 1},
                                           {'slug': 'gpt-5.6-sol', 'priority': 2},
                                           {'slug': 'gpt-5.6-luna', 'priority': 3}])
        self.env.update(CODEX_HOME=str(old_home),
                        CODEX_API_KEY='fixture-only', OPENAI_API_KEY='fixture-only')
        result, output = self.dispatch('full-astra', reviewer_model='gpt-6-astra')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call['kind'], 'codex')
            self.assertEqual(call['home'], str(self.home / '.codex'))
            self.assertFalse(call['api_env_present'])
            self.assertIn('gpt-5.6-sol', call['args'])
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
        result, _ = self.dispatch('full-astra', orchestrator_model='claude-opus-5-5')
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
