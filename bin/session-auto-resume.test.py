#!/usr/bin/env python3
"""Offline checks for bin/session-auto-resume.py, driven through its real CLI with fixture
transcripts, a fixture Conductor DB and a fake launcher. Zero model calls, no launchd, no network."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name('session-auto-resume.py')
ACCOUNT = 'acct-1'
HOUR = 3600


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(epoch))


class Fixture:
    def __init__(self, base: Path):
        self.base = base
        self.projects = base / 'projects'
        self.live = base / 'sessions'
        self.state = base / 'state'
        self.roots = base / 'roots'
        self.work = base / 'work'
        for d in (self.projects, self.live, self.state, self.roots, self.work):
            d.mkdir(parents=True)
        self.claude_json = base / 'claude.json'
        self.account()
        self.calls = base / 'calls.jsonl'
        self.launcher = base / 'fake-claude'
        self.launcher.write_text('#!/bin/sh\n/usr/bin/python3 -c \'import json,os,sys; '
                                 'open(sys.argv[1],"a").write(json.dumps({"argv":sys.argv[2:],'
                                 '"cwd":os.getcwd(),"resumed":os.environ.get("AGENT_SESSION_RESUMED")})+"\\n")\' '
                                 '"%s" "$@"\n' % self.calls)
        self.launcher.chmod(0o755)
        self.db = base / 'conductor.db'

    def account(self, uuid=ACCOUNT, extra=False):
        self.claude_json.write_text(json.dumps({'oauthAccount': {'accountUuid': uuid,
                                                                 'hasExtraUsageEnabled': extra}}))

    def transcript(self, sid, records, origin='sdk-ts', account=ACCOUNT, age=2 * HOUR, mode='bypassPermissions'):
        """Write a main-session transcript whose last record is `age` seconds old."""
        stamp = time.time() - age
        head = [{'type': 'user', 'entrypoint': origin, 'cwd': str(self.work), 'sessionId': sid,
                 'permissionMode': mode, 'timestamp': iso(stamp - 60),
                 'message': {'role': 'user', 'content': 'build the thing'}}]
        if account:
            head.append({'type': 'session-owner', 'accountUuid': account, 'sessionId': sid})
        for record in records:
            record.setdefault('timestamp', iso(stamp))
            record.setdefault('sessionId', sid)
        path = self.projects / '-fixture' / (sid + '.jsonl')
        path.parent.mkdir(exist_ok=True)
        path.write_text('\n'.join(json.dumps(r) for r in head + records) + '\n')
        os.utime(path, (stamp, stamp))
        return path

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('SESSION_AUTO_RESUME_', 'AGENT_'))}
        env.update({
            'SESSION_AUTO_RESUME_CONFIG': str(self.base), 'SESSION_AUTO_RESUME_PROJECTS': str(self.projects),
            'SESSION_AUTO_RESUME_LIVE': str(self.live), 'SESSION_AUTO_RESUME_ROOTS': str(self.roots),
            'SESSION_AUTO_RESUME_STATE': str(self.state), 'SESSION_AUTO_RESUME_LOG': str(self.base / 'log'),
            'SESSION_AUTO_RESUME_CLAUDE_JSON': str(self.claude_json),
            'SESSION_AUTO_RESUME_CONDUCTOR_DB': str(self.db),
            'SESSION_AUTO_RESUME_LAUNCHER': str(self.launcher), 'SESSION_AUTO_RESUME_DIRECT': '1',
            'SESSION_AUTO_RESUME_NO_NOTIFY': '1'})
        env.update(extra)
        return env

    def run(self, *args, **extra):
        out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                             env=self.env(**extra), timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stdout + out.stderr)
        return out.stdout

    def resumes(self, wait=5.0):
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.calls.exists():
                return [json.loads(x) for x in self.calls.read_text().splitlines()]
            time.sleep(0.05)
        return []

    def conductor(self, sid, status='error', workspace_state='ready', closed=None):
        db = sqlite3.connect(self.db)
        db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT, status TEXT, claude_session_id TEXT, '
                   'title TEXT, closed_at TEXT, is_hidden INTEGER, workspace_id TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS workspaces (local_id TEXT, id TEXT, state TEXT)')
        db.execute('INSERT INTO workspaces VALUES (?, ?, ?)', ('w-' + sid, 'w-' + sid, workspace_state))
        db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?, 0, ?)',
                   ('c-' + sid, status, sid, 'Fixture task', closed, 'w-' + sid))
        db.commit()
        db.close()

    def plan(self, statuses, phase='execute', name='session-task-plan.md'):
        context = self.work / '.context'
        context.mkdir(exist_ok=True)
        state = {'phase': phase, 'sections': [{'id': str(i), 'status': s} for i, s in enumerate(statuses)]}
        (context / name).write_text('# Plan\n\n## Dashboard state\n\n```dashboard-state\n' +
                                    json.dumps(state, indent=2) + '\n```\n')


def usage_limit(reset):
    return {'type': 'assistant', 'isApiErrorMessage': True, 'error': 'rate_limit',
            'apiError': 'usage_limit_reached', 'apiErrorStatus': 429,
            'quotaLimits': {'status': 'rejected', 'resetsAt': int(reset)},
            'message': {'role': 'assistant', 'model': '<synthetic>',
                        'content': [{'type': 'text', 'text': "You've hit your 5-hour limit"}]}}


def api_error(error, status=None, api=None):
    return {'type': 'assistant', 'isApiErrorMessage': True, 'error': error, 'apiError': api,
            'apiErrorStatus': status,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'API Error'}]}}


def tool_use(name='Bash'):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': 't1', 'name': name, 'input': {}}]}}


def tool_result():
    return {'type': 'user', 'message': {'role': 'user',
            'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}]}}


def answer():
    return {'type': 'assistant', 'message': {'role': 'assistant', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': 'Done.'}]}}


class AutoResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_usage_limit_waits_for_the_stated_reset_then_resumes_in_place(self):
        self.f.plan(['done', 'todo'])
        self.f.transcript('s-quota', [tool_result(), usage_limit(time.time() + HOUR)])
        self.assertIn('waiting for usage reset', self.f.run('run'))
        self.assertEqual(self.f.resumes(wait=0.3), [])
        self.f.transcript('s-quota', [tool_result(), usage_limit(time.time() - 10 * 60)])
        self.assertIn('RESUME', self.f.run('run'))
        call = self.f.resumes()[0]
        self.assertEqual(call['cwd'], str(self.f.work.resolve()))
        self.assertEqual(call['resumed'], '1')
        argv = call['argv']
        self.assertEqual(argv[:3], ['-p', '--resume', 's-quota'])
        self.assertEqual(argv[argv.index('--permission-mode') + 1], 'bypassPermissions')
        self.assertTrue(argv[-1].startswith('Resumed by the hourly auto-resume watchdog after usage-limit.'))

    def test_one_session_quota_reset_holds_every_session_of_that_account(self):
        self.f.plan(['todo'])
        self.f.transcript('s-old', [tool_use()], age=3 * HOUR)
        self.f.transcript('s-new', [usage_limit(time.time() + HOUR)], age=HOUR)
        out = self.f.run('run')
        rows = [l for l in out.splitlines() if l.startswith('s-')]
        self.assertEqual(sum('waiting for usage reset' in l for l in rows), 2, out)

    def test_crash_mid_tool_loop_resumes_and_normal_or_human_stops_never_do(self):
        self.f.transcript('s-crash', [tool_use()])
        self.f.transcript('s-done', [answer()])
        self.f.transcript('s-int', [{'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'text', 'text': '[Request interrupted by user]'}]}}])
        self.f.transcript('s-ask', [tool_use('mcp__conductor__AskUserQuestion')])
        out = self.f.run('run', '--max-age-hours', '48')
        self.assertIn('RESUME', next(l for l in out.splitlines() if l.startswith('s-crash ')))
        self.assertNotIn('s-done', out.split('scanned')[0])
        self.assertIn('waiting on Simon', out)
        self.assertEqual([c['argv'][2] for c in self.f.resumes()], ['s-crash'])

    def test_no_resume_without_recorded_unfinished_work(self):
        self.f.transcript('s-idle', [answer(), api_error('server_error', 529)])
        self.assertIn('no unfinished work recorded', self.f.run('run'))
        self.f.plan(['done', 'todo'])
        self.assertIn('RESUME', self.f.run('run'))

    def test_a_complete_plan_or_reconciled_ask_is_not_unfinished_work(self):
        self.f.plan(['todo'], phase='complete')
        ledger = self.f.work / '.context' / 'intent-ledger.md'
        ledger.write_text('# Intent ledger\n\n## 2026-11-22T01:00:00Z · ask · session s-led\n\nx\n\n'
                          '## 2026-11-22T01:05:00Z · reconcile\n\ndone\n')
        self.f.transcript('s-led', [answer(), api_error('server_error', 500)])
        self.assertIn('no unfinished work recorded', self.f.run('run'))
        ledger.write_text(ledger.read_text() + '\n## 2026-11-22T02:00:00Z · ask · session s-led\n\nmore\n')
        self.assertIn('RESUME', self.f.run('run'))

    def test_running_recent_archived_or_other_account_sessions_are_left_alone(self):
        self.f.plan(['todo'])
        fake = self.f.base / 'claude'
        fake.symlink_to('/bin/sleep')  # a live process whose command name says claude
        holder = subprocess.Popen([str(fake), '30'])
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.f.transcript('s-live', [tool_use()])
        (self.f.live / ('%d.json' % holder.pid)).write_text(json.dumps({'pid': holder.pid, 'sessionId': 's-live'}))
        self.f.transcript('s-fresh', [tool_use()], age=60)
        self.f.transcript('s-arch', [tool_use()])
        self.f.conductor('s-arch', workspace_state='archived')
        self.f.transcript('s-busy', [tool_use()])
        self.f.conductor('s-busy', status='working')
        self.f.transcript('s-other', [tool_use()], account='acct-2')
        self.f.transcript('s-stale', [tool_use()], age=50 * HOUR)
        out = self.f.run('run')
        self.assertFalse(any(l.startswith('s-stale') for l in out.splitlines()), out)
        for sid, reason in (('s-live', 'running'), ('s-fresh', 'written to recently'),
                            ('s-arch', 'archived or closed in Conductor'),
                            ('s-busy', 'Conductor shows it working'), ('s-other', 'other Claude account')):
            line = next(l for l in out.splitlines() if l.startswith(sid))
            self.assertIn('skip: ' + reason, line)
        self.assertEqual(self.f.resumes(wait=0.3), [])

    def test_one_attempt_per_hour_and_a_cap_of_24_in_48_hours(self):
        self.f.plan(['todo'])
        self.f.transcript('s-cap', [api_error('server_error', None, 'connection_failed')])
        self.assertIn('network', self.f.run('run'))
        self.assertIn('attempted this hour', self.f.run('run'))
        state_path = self.f.state / 'state.json'
        state = json.loads(state_path.read_text())
        state['sessions']['s-cap']['attempts'] = [time.time() - (i + 1) * HOUR for i in range(24)]
        state['sessions']['s-cap']['pid'] = 0
        state_path.write_text(json.dumps(state))
        self.assertIn('attempt cap reached', self.f.run('run'))
        self.assertIn('attempt cap reached:network', json.loads(state_path.read_text())['sessions']['s-cap']['notified'])
        self.assertEqual(len(self.f.resumes()), 1)

    def test_errors_a_retry_cannot_clear_are_reported_not_resumed(self):
        self.f.plan(['todo'])
        self.f.transcript('s-long', [api_error('invalid_request', 400)])
        self.f.transcript('s-cred', [api_error('rate_limit', 429, 'model_requires_usage_credits')])
        out = self.f.run('run')
        self.assertIn('not auto-resumable: invalid-request', out)
        self.assertIn('not auto-resumable: usage-credits-required', out)
        self.assertEqual(self.f.resumes(wait=0.3), [])

    def test_extra_usage_on_pauses_every_resume_under_the_spend_rule(self):
        self.f.plan(['todo'])
        self.f.account(extra=True)
        self.f.transcript('s-x', [tool_use()])
        self.assertIn('extra usage is on', self.f.run('run'))
        self.assertEqual(self.f.resumes(wait=0.3), [])

    def test_dry_run_resumes_nothing_and_writes_no_state(self):
        self.f.plan(['todo'])
        self.f.transcript('s-dry', [tool_use()])
        self.assertIn('WOULD RESUME', self.f.run('run', '--dry-run'))
        self.assertEqual(self.f.resumes(wait=0.3), [])
        self.assertFalse((self.f.state / 'state.json').exists())

    def test_a_held_lock_skips_the_run(self):
        import fcntl
        self.f.plan(['todo'])
        self.f.transcript('s-lock', [tool_use()])
        with open(self.f.state / 'run.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertNotIn('RESUME', self.f.run('run'))
        self.assertEqual(self.f.resumes(wait=0.3), [])

    def test_headless_workers_resume_only_when_named(self):
        self.f.transcript('s-worker', [tool_use()], origin='sdk-cli')
        self.assertIn('headless -p worker', self.f.run('run'))
        self.assertIn('RESUME', self.f.run('run', '--session', 's-worker'))

    def test_ignored_sessions_stay_stopped(self):
        self.f.transcript('s-ign', [tool_use()])
        self.f.run('ignore', 's-ign')
        self.assertIn('ignored by Simon', self.f.run('run'))

    def test_session_mode_is_kept_and_never_added(self):
        self.f.transcript('s-plain', [tool_use()], mode=None)
        self.f.run('run')
        self.assertNotIn('--permission-mode', self.f.resumes()[0]['argv'])

    def test_stop_failure_hook_records_only_the_error_type(self):
        payload = {'session_id': 's-hook', 'hook_event_name': 'StopFailure', 'error': 'server_error',
                   'last_assistant_message': 'API Error: secret-looking text', 'cwd': str(self.f.work)}
        out = subprocess.run([sys.executable, str(SCRIPT), 'record-stop'], input=json.dumps(payload),
                             capture_output=True, text=True, env=self.f.env())
        self.assertEqual((out.returncode, out.stdout), (0, ''))
        marker = json.loads((self.f.state / 'stops' / 's-hook.json').read_text())
        self.assertEqual(sorted(marker), ['at', 'error'])
        self.assertEqual(marker['error'], 'server_error')
        bad = subprocess.run([sys.executable, str(SCRIPT), 'record-stop'], input='not json',
                             capture_output=True, text=True, env=self.f.env())
        self.assertEqual(bad.returncode, 0)

    def test_a_stop_marker_alone_marks_an_error_stop(self):
        self.f.plan(['todo'])
        self.f.transcript('s-mark', [answer()])
        (self.f.state / 'stops').mkdir(parents=True, exist_ok=True)
        (self.f.state / 'stops' / 's-mark.json').write_text(json.dumps({'error': 'server_error', 'at': iso(time.time() - HOUR)}))
        self.assertIn('server-error', self.f.run('run'))

    def test_logs_hold_ids_and_causes_never_transcript_text(self):
        self.f.plan(['todo'])
        self.f.transcript('s-log', [tool_use()])
        self.f.run('run')
        text = (self.f.base / 'log').read_text()
        self.assertIn('sid=s-log cause=crash', text)
        self.assertNotIn('build the thing', text)


if __name__ == '__main__':
    unittest.main()
