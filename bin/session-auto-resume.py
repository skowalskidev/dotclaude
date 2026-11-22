#!/usr/bin/env python3
"""Hourly auto-resume watchdog for Claude Code sessions that stopped with unfinished work.

Why it exists: a session that stops on a usage limit, an API or network error, or a crash stays
stopped. Claude Code's own wait (autoContinueAtUsageLimit) lives inside the open interactive
process, so a Conductor/Agent SDK session, a closed process or a crash is never picked up again, and
in-session scheduled resumes die with the session. This runs OUTSIDE Claude from launchd, reads local
files only, makes zero model calls for the check, and resumes a qualifying session in place with
`claude -p --resume`. Method, sources and the rejected alternatives: references/session-auto-resume.md.

Usage:
  session-auto-resume.py run [--dry-run] [--session SID] [--max-age-hours 48] [--min-idle-minutes 15]
  session-auto-resume.py status
  session-auto-resume.py install | uninstall
  session-auto-resume.py ignore SID | unignore SID
  session-auto-resume.py record-stop        StopFailure hook: stdin payload -> stop marker

Privacy: logs and markers hold session ids, causes, counts and outcomes only, never transcript text,
prompts, titles or secret values. Python standard library only (macOS /usr/bin/python3 3.9).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import glob
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get('SESSION_AUTO_RESUME_CONFIG') or HOME / '.claude')
PROJECTS = Path(os.environ.get('SESSION_AUTO_RESUME_PROJECTS') or CONFIG / 'projects')
LIVE_SESSIONS = Path(os.environ.get('SESSION_AUTO_RESUME_LIVE') or CONFIG / 'sessions')
SESSION_ROOTS = Path(os.environ.get('SESSION_AUTO_RESUME_ROOTS') or CONFIG / '.session-root')
STATE_DIR = Path(os.environ.get('SESSION_AUTO_RESUME_STATE') or CONFIG / 'state' / 'session-auto-resume')
LOG_PATH = Path(os.environ.get('SESSION_AUTO_RESUME_LOG') or HOME / 'Library/Logs/session-auto-resume.log')
CLAUDE_JSON = Path(os.environ.get('SESSION_AUTO_RESUME_CLAUDE_JSON') or HOME / '.claude.json')
CONDUCTOR_DB = Path(os.environ.get('SESSION_AUTO_RESUME_CONDUCTOR_DB') or
                    HOME / 'Library/Application Support/com.conductor.app/conductor.db')
LAUNCHER = os.environ.get('SESSION_AUTO_RESUME_LAUNCHER') or str(CONFIG / 'bin' / 'claude-launch.py')
LEDGER_TOOL = str(CONFIG / 'hooks' / 'intent-ledger.sh')
LABEL = 'com.dotclaude.session-auto-resume'
PLIST_TEMPLATE = Path(__file__).resolve().parent.parent / 'dotfiles' / 'session-auto-resume.plist'
PLIST_TARGET = HOME / 'Library/LaunchAgents' / (LABEL + '.plist')

ATTEMPT_CAP = 24                 # resumes per session inside CAP_WINDOW before it stops and notifies
CAP_WINDOW = 48 * 3600
MIN_GAP = 55 * 60                # one attempt per session per hourly run (55 min absorbs timer jitter)
RESET_GRACE = 120                # seconds after a stated usage-limit reset before resuming
TAIL_START = 1 << 20             # first tail read; doubles until a conversational record is found
KNOWN_MODES = {'default', 'acceptEdits', 'plan', 'auto', 'dontAsk', 'bypassPermissions'}
WAITING_TOOLS = re.compile(r'(^|__)(AskUserQuestion|ExitPlanMode)$')
INTERRUPT = '[Request interrupted by user'
NOT_RESUMABLE = 'not auto-resumable: '
EXTRA_USAGE = 'extra usage is on, so a resume could bill (rules/spend-approval.md)'
CAP_REACHED = 'attempt cap reached'
PROMPT = ('Resumed by the hourly auto-resume watchdog after {cause}. Re-read your living plan and '
          'intent ledger, then continue the unfinished work. If nothing is left, say so and stop.')

# Stop causes a resume can clear by waiting. The rest (credits, billing, an invalid request) repeat
# identically on every retry, so they are reported once to Simon instead.
RETRYABLE = {'usage-limit', 'rate-limit', 'overloaded', 'server-error', 'network', 'api-error',
             'crash', 'auth'}

log = logging.getLogger('session-auto-resume')


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=512 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    launchd_log = LOG_PATH.with_name(LOG_PATH.stem + '.launchd.log')
    if launchd_log.is_file() and launchd_log.stat().st_size > 1024 * 1024:
        os.replace(launchd_log, launchd_log.with_name(launchd_log.name + '.1'))


def now() -> float:
    return float(os.environ.get('SESSION_AUTO_RESUME_NOW') or time.time())


def parse_ts(value) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def short(sid: str) -> str:
    return sid[:8]


# ---------------------------------------------------------------- transcript reading

def read_records(path: Path, from_end: bool):
    """Parsed JSONL records: the head (first 64 KB) or a tail window that grows until a
    conversational record is found. Unparseable lines are skipped."""
    size = path.stat().st_size
    with path.open('rb') as fh:
        if not from_end:
            chunk = fh.read(64 * 1024)
            lines = chunk.splitlines()
            return [r for r in (_load(x) for x in lines) if r is not None]
        window = TAIL_START
        while True:
            start = max(0, size - window)
            fh.seek(start)
            data = fh.read()
            lines = data.splitlines()
            if start > 0 and lines:
                lines = lines[1:]
            records = [r for r in (_load(x) for x in lines) if r is not None]
            if start == 0 or any(is_conversational(r) for r in records):
                return records
            window *= 2


def _load(line: bytes):
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def is_conversational(record: dict) -> bool:
    return (record.get('type') in ('user', 'assistant') and not record.get('isSidechain')
            and not record.get('isMeta'))


def content_blocks(record: dict) -> list:
    content = (record.get('message') or {}).get('content')
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    return [c for c in content or [] if isinstance(c, dict)]


def first_text(record: dict) -> str:
    for block in content_blocks(record):
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            return block['text']
    return ''


def classify_error(record: dict) -> tuple:
    """(cause, reset_epoch or 0) for an API-error assistant record (field names observed in
    Claude Code 2.1.3xx transcripts: error, apiError, apiErrorStatus, quotaLimits.resetsAt)."""
    error = record.get('error')
    api_error = record.get('apiError')
    status = record.get('apiErrorStatus')
    reset = 0
    quota = record.get('quotaLimits') or {}
    params = (record.get('apiErrorParams') or {}).get('rate_limit_info') or {}
    for source in (quota, params):
        if isinstance(source.get('resetsAt'), (int, float)):
            reset = max(reset, int(source['resetsAt']))
    if error == 'rate_limit':
        if api_error == 'model_requires_usage_credits':
            return 'usage-credits-required', 0
        return ('usage-limit' if reset or api_error == 'usage_limit_reached' else 'rate-limit'), reset
    return classify_error_type(error, api_error, status), 0


def classify_error_type(error, api_error=None, status=None) -> str:
    if error == 'rate_limit':
        return 'rate-limit'
    if error == 'server_error':
        if api_error in ('connection_failed', 'tls_untrusted_ca'):
            return 'network'
        return 'overloaded' if status == 529 else 'server-error'
    if error in ('authentication_failed', 'oauth_org_not_allowed'):
        return 'auth'
    if error in ('billing_error', 'account_on_hold'):
        return 'billing'
    if error in ('invalid_request', 'max_output_tokens', 'model_not_found', 'cloud_credential_error'):
        return 'invalid-request' if error == 'invalid_request' else 'not-retryable'
    return 'api-error'


def inspect_transcript(path: Path) -> dict:
    """Everything the decision needs from one main-session transcript."""
    head = read_records(path, from_end=False)
    tail = read_records(path, from_end=True)
    info = {'sid': path.stem, 'path': path, 'mtime': path.stat().st_mtime, 'origin': None,
            'cwd': None, 'mode': None, 'account': None, 'title': None, 'last_ts': 0.0,
            'stop': None, 'cause': None, 'reset': 0, 'mid_tool_loop': False, 'waiting_on_simon': False}
    for record in head:
        if info['origin'] is None and record.get('entrypoint'):
            info['origin'] = record['entrypoint']
        if info['cwd'] is None and isinstance(record.get('cwd'), str):
            info['cwd'] = record['cwd']
    for record in head + tail:
        if record.get('type') == 'session-owner' and record.get('accountUuid'):
            info['account'] = record['accountUuid']
        if record.get('type') == 'ai-title' and record.get('aiTitle'):
            info['title'] = record['aiTitle']
        mode = record.get('permissionMode')
        if record.get('type') in ('user', 'permission-mode') and mode in KNOWN_MODES:
            info['mode'] = mode
    convo = [r for r in tail if is_conversational(r)]
    if not convo:
        return info
    last = convo[-1]
    info['last_ts'] = parse_ts(last.get('timestamp'))
    blocks = content_blocks(last)
    if last.get('type') == 'assistant' and last.get('isApiErrorMessage'):
        info['stop'] = 'api-error'
        info['cause'], info['reset'] = classify_error(last)
        before = convo[-2] if len(convo) > 1 else None
        info['mid_tool_loop'] = bool(before and _tool_step(before))
    elif last.get('type') == 'user':
        if any(INTERRUPT in (b.get('text') or '') for b in blocks if b.get('type') == 'text'):
            info['stop'] = 'interrupted'
        else:
            info['stop'] = 'died-mid-turn'
            info['cause'] = 'crash'
            info['mid_tool_loop'] = any(b.get('type') == 'tool_result' for b in blocks)
    elif last.get('type') == 'assistant':
        uses = [b for b in blocks if b.get('type') == 'tool_use']
        if uses:
            info['mid_tool_loop'] = True
            if any(WAITING_TOOLS.search(str(b.get('name') or '')) for b in uses):
                info['stop'] = 'waiting-on-simon'
                info['waiting_on_simon'] = True
            else:
                info['stop'] = 'died-mid-turn'
                info['cause'] = 'crash'
        else:
            info['stop'] = 'ended-normally'
    return info


def _tool_step(record: dict) -> bool:
    kinds = {b.get('type') for b in content_blocks(record)}
    return 'tool_result' in kinds or 'tool_use' in kinds


# ---------------------------------------------------------------- unfinished work

def session_root(sid: str, cwd) -> Path:
    marker = SESSION_ROOTS / sid
    if marker.is_file():
        text = marker.read_text(errors='replace').strip()
        if text and Path(text).is_dir():
            return Path(text)
    if cwd and Path(cwd).is_dir():
        top = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True)
        if top.returncode == 0 and top.stdout.strip():
            return Path(top.stdout.strip())
        return Path(cwd)
    return Path(cwd or '/nonexistent')


PLAN_BLOCK = re.compile(r'```dashboard-state\s*\n(.*?)\n```', re.S)


def open_plan_sections(root: Path, sid: str) -> int:
    """Open sections in this session's active living plan (workflow-dashboard.py's format)."""
    active = []
    for plan in sorted((root / '.context').glob('*-plan.md')):
        try:
            match = PLAN_BLOCK.search(plan.read_text(errors='replace'))
            state = json.loads(match.group(1)) if match else None
        except (OSError, ValueError):
            state = None
        if not isinstance(state, dict) or state.get('phase') == 'complete':
            continue
        sections = [s for s in state.get('sections') or [] if isinstance(s, dict)]
        active.append((plan.name, sum(1 for s in sections if s.get('status') != 'done')))
    mine = [n for name, n in active if sid in name]
    if mine:
        return max(mine)
    return active[0][1] if len(active) == 1 else 0


def open_ledger_ask(root: Path, sid: str) -> bool:
    """True when this session's newest recorded ask has no reconcile heading after it."""
    ledger = root / '.context' / 'intent-ledger.md'
    try:
        lines = ledger.read_text(errors='replace').splitlines()
    except OSError:
        return False
    last_ask = None
    for index, line in enumerate(lines):
        if line.startswith('## ') and ' · ask · session ' + sid in line:
            last_ask = index
    if last_ask is None:
        return False
    return not any(line.startswith('## ') and line.rstrip().endswith('· reconcile')
                   for line in lines[last_ask + 1:])


# ---------------------------------------------------------------- liveness and ownership

def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    out = subprocess.run(['ps', '-p', str(pid), '-o', 'comm='], capture_output=True, text=True)
    return out.returncode == 0 and 'claude' in out.stdout.lower()


def live_session_ids() -> set:
    """Session ids held by a running Claude Code process, from its own ~/.claude/sessions/<pid>.json."""
    ids = set()
    for path in LIVE_SESSIONS.glob('*.json'):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and pid_alive(data.get('pid')) and data.get('sessionId'):
            ids.add(data['sessionId'])
    return ids


def conductor_rows() -> dict:
    """claude_session_id -> Conductor status/title/archive facts, read-only; {} when unavailable."""
    if not CONDUCTOR_DB.is_file():
        return {}
    try:
        db = sqlite3.connect('file:' + str(CONDUCTOR_DB) + '?mode=ro', uri=True, timeout=2)
        rows = db.execute(
            'SELECT s.claude_session_id, s.status, s.title, s.closed_at, s.is_hidden, w.state '
            'FROM sessions s LEFT JOIN workspaces w ON w.id = s.workspace_id OR w.local_id = s.workspace_id '
            'WHERE s.claude_session_id IS NOT NULL').fetchall()
        db.close()
    except sqlite3.Error:
        return {}
    return {r[0]: {'status': r[1], 'title': r[2], 'closed': bool(r[3]) or bool(r[4]),
                   'workspace_state': r[5]} for r in rows}


def current_account():
    try:
        data = json.loads(CLAUDE_JSON.read_text())
    except (OSError, ValueError):
        return None, False
    account = data.get('oauthAccount') or {}
    return account.get('accountUuid'), bool(account.get('hasExtraUsageEnabled'))


# ---------------------------------------------------------------- state

def load_state() -> dict:
    try:
        state = json.loads((STATE_DIR / 'state.json').read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault('sessions', {})
    state.setdefault('ignored', [])
    return state


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / 'state.json.tmp'
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, STATE_DIR / 'state.json')


def stop_marker(sid: str):
    try:
        return json.loads((STATE_DIR / 'stops' / (sid + '.json')).read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- decision

def decide(info: dict, ctx: dict, explicit: bool) -> tuple:
    """('resume', cause) or ('skip', reason) for one transcript; reasons are fixed strings."""
    sid, t = info['sid'], now()
    entry = ctx['state']['sessions'].get(sid, {})
    marker = stop_marker(sid)
    if info['stop'] not in ('api-error', 'died-mid-turn') and marker and \
            parse_ts(marker.get('at')) + 5 >= info['last_ts'] and info['stop'] != 'interrupted':
        info['stop'], info['cause'] = 'api-error', classify_error_type(marker.get('error'))
    if sid in ctx['state']['ignored']:
        return 'skip', 'ignored by Simon'
    if info['origin'] == 'sdk-cli' and not explicit:
        return 'skip', 'headless -p worker (its supervisor owns it)'
    if info['stop'] == 'interrupted':
        return 'skip', 'Simon interrupted it'
    if info['stop'] == 'waiting-on-simon':
        return 'skip', 'waiting on Simon'
    if info['stop'] in (None, 'ended-normally'):
        return 'skip', 'ended normally'
    if t - info['last_ts'] > ctx['max_age']:
        return 'skip', 'stopped too long ago'
    if t - info['mtime'] < ctx['min_idle']:
        return 'skip', 'written to recently'
    if sid in ctx['live'] or pid_alive(entry.get('pid')):
        return 'skip', 'running'
    row = ctx['conductor'].get(sid)
    if row:
        if row['closed'] or (row['workspace_state'] not in (None, 'active', 'ready')):
            return 'skip', 'archived or closed in Conductor'
        if row['status'] not in ('idle', 'error'):
            return 'skip', 'Conductor shows it ' + str(row['status'])
    if not info['cwd'] or not Path(info['cwd']).is_dir():
        return 'skip', 'working directory gone'
    if info['account'] and info['account'] != ctx['account']:
        return 'skip', 'other Claude account'
    root = session_root(sid, info['cwd'])
    plan_open = open_plan_sections(root, sid)
    ask_open = open_ledger_ask(root, sid)
    if not (plan_open or ask_open or info['mid_tool_loop']):
        return 'skip', 'no unfinished work recorded'
    info['work'] = {'plan_sections_open': plan_open, 'ask_open': ask_open,
                    'mid_tool_loop': info['mid_tool_loop'], 'root': str(root)}
    if info['cause'] not in RETRYABLE:
        return 'skip', NOT_RESUMABLE + str(info['cause'])
    if ctx['extra_usage']:
        return 'skip', EXTRA_USAGE
    reset = max(info['reset'], ctx['account_reset'])
    if info['cause'] in ('usage-limit', 'rate-limit') or ctx['account_reset'] > t:
        if reset and t < reset + RESET_GRACE:
            return 'skip', 'waiting for usage reset at ' + time.strftime('%H:%M', time.localtime(reset))
    attempts = [a for a in entry.get('attempts', []) if t - a < CAP_WINDOW]
    if attempts and t - attempts[-1] < MIN_GAP:
        return 'skip', 'attempted this hour'
    if len(attempts) >= ATTEMPT_CAP:
        return 'skip', CAP_REACHED
    return 'resume', info['cause']


def candidates(session: str | None, max_age: float) -> list:
    if session:
        return [Path(p) for p in glob.glob(str(PROJECTS / '*' / (session + '.jsonl')))]
    cutoff = now() - max_age
    return [p for p in PROJECTS.glob('*/*.jsonl') if p.stat().st_mtime >= cutoff]


def account_reset(infos: list, account) -> int:
    """The newest usage-limit reset this account reported, so no session spends an attempt
    before the shared limit resets."""
    newest = (0.0, 0)
    for info in infos:
        if info['cause'] == 'usage-limit' and info['reset'] and info['account'] in (None, account):
            newest = max(newest, (info['last_ts'], info['reset']))
    return newest[1]


# ---------------------------------------------------------------- actions

def notify(title: str, message: str):
    if os.environ.get('SESSION_AUTO_RESUME_NO_NOTIFY') == '1':
        return
    script = ['-e', 'on run argv', '-e', 'display notification (item 1 of argv) with title (item 2 of argv)',
              '-e', 'end run']
    subprocess.run(['osascript', *script, message[:200], title[:80]], capture_output=True)


def ledger_note(sid: str, root: str, cause: str, attempt: int):
    """One line in the session's intent ledger through its single writer; best effort."""
    if not os.access(LEDGER_TOOL, os.X_OK) or not Path(root).is_dir():
        return
    scratch = STATE_DIR / ('note-' + sid + '.md')
    scratch.write_text('Auto-resume watchdog: resumed this session after %s (attempt %d in 48 h). '
                       'The resume prompt is the watchdog\'s, not Simon\'s.\n' % (cause, attempt))
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=sid, CLAUDE_PROJECT_DIR=root,
               PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    env.pop('AGENT_DELEGATED_WORKER', None)
    subprocess.run([LEDGER_TOOL, 'note', 'plan', str(scratch)], cwd=root, env=env,
                   capture_output=True, timeout=20)
    scratch.unlink(missing_ok=True)


def resume(info: dict, cause: str) -> int:
    """Start `claude -p --resume` detached, in the session's own directory and permission mode."""
    args = [LAUNCHER, '-p', '--resume', info['sid'], '--output-format', 'json']
    if info['mode'] in KNOWN_MODES:
        args += ['--permission-mode', info['mode']]
    args.append(PROMPT.format(cause=cause))
    env = {'HOME': str(HOME), 'USER': os.environ.get('USER', ''), 'LANG': 'en_US.UTF-8',
           'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'AGENT_SESSION_RESUMED': '1'}
    # A login shell supplies Simon's PATH (Homebrew, nvm Node 24, ~/.local/bin) to the resumed
    # session's tools; the arguments pass as "$@", so nothing is re-parsed by the shell.
    command = ['/bin/zsh', '-l', '-c', 'exec "$@"', 'zsh', *args]
    if os.environ.get('SESSION_AUTO_RESUME_DIRECT') == '1':
        command = args
    child = subprocess.Popen(command, cwd=info['cwd'], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    return child.pid


def run(args) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_DIR / 'run.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('skip run: previous run still holds the lock')
        return 0
    state = load_state()
    account, extra_usage = current_account()
    max_age = args.max_age_hours * 3600
    infos = []
    for path in candidates(args.session, max_age):
        try:
            infos.append(inspect_transcript(path))
        except OSError:
            continue
    ctx = {'state': state, 'account': account, 'extra_usage': extra_usage, 'max_age': max_age,
           'min_idle': args.min_idle_minutes * 60, 'live': live_session_ids(),
           'conductor': conductor_rows(), 'account_reset': account_reset(infos, account)}
    if account is None:
        print('No Claude login found in ~/.claude.json; nothing resumed.')
        log.info('run: no account; nothing resumed')
        return 0
    tally, rows = {}, []
    for info in infos:
        verdict, why = decide(info, ctx, explicit=bool(args.session))
        if verdict == 'skip' and why in ('ended normally', 'Simon interrupted it') and not args.session:
            tally[why] = tally.get(why, 0) + 1
            continue
        rows.append((info, verdict, why))
        key = ('would resume: ' if args.dry_run else 'resume: ') + why if verdict == 'resume' else why
        tally[key] = tally.get(key, 0) + 1
    for info, verdict, why in rows:
        where = Path(info['cwd'] or '?').name
        line = '%s  %-9s %-14s %s' % (short(info['sid']), info['origin'] or '?', info['cause'] or '-',
                                      ('WOULD RESUME' if args.dry_run else 'RESUME') if verdict == 'resume'
                                      else 'skip: ' + why)
        print(line + '  [' + where + ']')
        if args.dry_run:
            continue
        label = (ctx['conductor'].get(info['sid']) or {}).get('title') or info['title'] or where
        entry = state['sessions'].setdefault(info['sid'], {})
        if verdict == 'resume':
            attempts = [a for a in entry.get('attempts', []) if now() - a < CAP_WINDOW] + [now()]
            previous = entry.get('cause')
            pid = resume(info, why)
            entry.update({'attempts': attempts, 'pid': pid, 'cause': why, 'startedAt': now()})
            log.info('resume sid=%s cause=%s attempt=%d pid=%d', info['sid'], why, len(attempts), pid)
            # One notification per cause streak; repeat hourly retries are logged, not announced.
            if len(attempts) == 1 or previous != why:
                hint = ' If it fails again, run /login.' if why == 'auth' else ''
                notify('Session resumed', '%s: resumed after %s. Let it finish before typing in it.%s'
                       % (label, why, hint))
            if info['work']['root']:
                ledger_note(info['sid'], info['work']['root'], why, len(attempts))
        elif why == CAP_REACHED or why == EXTRA_USAGE or why.startswith(NOT_RESUMABLE):
            # Each of these needs Simon (credits, a decision or a look); tell him once per reason.
            reason = why + ':' + str(info['cause'])
            if reason not in entry.get('notified', []):
                entry.setdefault('notified', []).append(reason)
                entry['notifiedAt'] = now()
                notify('Session needs you', '%s stopped on %s and was not resumed: %s.' % (
                    label, info['cause'], why))
                log.info('notify sid=%s reason=%s', info['sid'], reason)
        if not entry:
            del state['sessions'][info['sid']]
    summary = ', '.join('%s=%d' % (k, v) for k, v in sorted(tally.items())) or 'no recent sessions'
    print(('DRY RUN ' if args.dry_run else '') + 'scanned %d recent sessions: %s' % (len(infos), summary))
    if not args.dry_run:
        prune(state)
        save_state(state)
        log.info('run: scanned=%d %s', len(infos), summary)
    return 0


def prune(state: dict):
    t = now()
    for sid in list(state['sessions']):
        entry = state['sessions'][sid]
        entry['attempts'] = [a for a in entry.get('attempts', []) if t - a < CAP_WINDOW]
        last = max(entry.get('startedAt', 0), entry.get('notifiedAt', 0))
        if not entry['attempts'] and not pid_alive(entry.get('pid')) and t - last > CAP_WINDOW:
            del state['sessions'][sid]
    for marker in (STATE_DIR / 'stops').glob('*.json'):
        if t - marker.stat().st_mtime > 7 * 86400:
            marker.unlink(missing_ok=True)


def record_stop() -> int:
    """StopFailure hook: keep the documented error type as a second stop signal. Never fails."""
    try:
        payload = json.load(sys.stdin)
        sid = re.sub(r'[^A-Za-z0-9._-]', '', str(payload.get('session_id') or ''))
        if sid:
            (STATE_DIR / 'stops').mkdir(parents=True, exist_ok=True)
            marker = {'error': str(payload.get('error') or 'unknown')[:40],
                      'at': dt.datetime.now(dt.timezone.utc).isoformat()}
            (STATE_DIR / 'stops' / (sid + '.json')).write_text(json.dumps(marker))
    except Exception:  # noqa: BLE001 - a hook must never break the session
        pass
    return 0


# ---------------------------------------------------------------- install / status

def launchctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(['launchctl', *args], capture_output=True, text=True)


def install() -> int:
    script = CONFIG / 'bin' / 'session-auto-resume.py'
    text = PLIST_TEMPLATE.read_text()
    text = text.replace('__SCRIPT__', str(script)).replace('__LOG_DIR__', str(LOG_PATH.parent))
    PLIST_TARGET.parent.mkdir(parents=True, exist_ok=True)
    PLIST_TARGET.write_text(text)
    domain = 'gui/%d' % os.getuid()
    launchctl('bootout', domain + '/' + LABEL)
    result = launchctl('bootstrap', domain, str(PLIST_TARGET))
    if result.returncode != 0:
        print('launchctl bootstrap failed (exit %d): %s' % (result.returncode, result.stderr.strip()))
        return 1
    print('Installed %s -> %s (hourly at minute 17; runs on wake after a missed hour).' % (LABEL, PLIST_TARGET))
    return 0


def uninstall() -> int:
    launchctl('bootout', 'gui/%d/%s' % (os.getuid(), LABEL))
    PLIST_TARGET.unlink(missing_ok=True)
    gone = launchctl('print', 'gui/%d/%s' % (os.getuid(), LABEL)).returncode != 0
    print('Uninstalled %s: %s.' % (LABEL, 'service and plist removed' if gone else 'SERVICE STILL LOADED'))
    return 0 if gone else 1


def status() -> int:
    printed = launchctl('print', 'gui/%d/%s' % (os.getuid(), LABEL))
    if printed.returncode != 0:
        print('launchd: %s not loaded' % LABEL)
    else:
        fields = {}
        for line in printed.stdout.splitlines():
            m = re.match(r'\s*(state|runs|last exit code|path) = (.*)', line)
            if m and m.group(1) not in fields:
                fields[m.group(1)] = m.group(2).strip()
        print('launchd: ' + ', '.join('%s=%s' % kv for kv in fields.items()))
    state = load_state()
    live = [(sid, e) for sid, e in state['sessions'].items() if pid_alive(e.get('pid'))]
    print('tracked sessions: %d, resumes running now: %d, ignored: %d' % (
        len(state['sessions']), len(live), len(state['ignored'])))
    for sid, entry in sorted(state['sessions'].items()):
        print('  %s attempts=%d last-cause=%s %s' % (short(sid), len(entry.get('attempts', [])),
              entry.get('cause', '-'), 'RUNNING' if pid_alive(entry.get('pid')) else ''))
    print('log: %s' % LOG_PATH)
    return 0


def set_ignored(sid: str, ignored: bool) -> int:
    state = load_state()
    listed = set(state['ignored'])
    (listed.add if ignored else listed.discard)(sid)
    state['ignored'] = sorted(listed)
    save_state(state)
    print('%s %s' % (short(sid), 'ignored' if ignored else 'no longer ignored'))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    run_p = sub.add_parser('run')
    run_p.add_argument('--dry-run', action='store_true')
    run_p.add_argument('--session', help='consider only this session id (also admits a -p session)')
    run_p.add_argument('--max-age-hours', type=float, default=48)
    run_p.add_argument('--min-idle-minutes', type=float, default=15)
    for name in ('status', 'install', 'uninstall', 'record-stop'):
        sub.add_parser(name)
    for name in ('ignore', 'unignore'):
        sub.add_parser(name).add_argument('sid')
    args = parser.parse_args(argv)
    if args.command == 'record-stop':
        return record_stop()
    setup_logging()
    if args.command == 'run':
        return run(args)
    if args.command in ('ignore', 'unignore'):
        return set_ignored(args.sid, args.command == 'ignore')
    return {'status': status, 'install': install, 'uninstall': uninstall}[args.command]()


if __name__ == '__main__':
    sys.exit(main())
