#!/usr/bin/env python3
"""One plan, one reusable dashboard engine, bridged to the gauntlet Next.js app for viewing."""
import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, url2pathname, urlopen

BLOCK = re.compile(r'^```dashboard-state\n(.*?)\n```\s*$', re.M | re.S)
TEMPLATE = Path(__file__).with_name('workflow-dashboard.html')
STATES = {'todo', 'doing', 'blocked', 'review', 'done'}
APP_DIR = Path.home() / '.claude' / 'apps' / 'gauntlet'
APP_PORT = 4747
APP_RECEIPT = Path.home() / '.claude' / 'state' / 'gauntlet-server.json'
RECORD_HEADINGS = (
    ('goal & user journey', 'User journey'),
    ('system journey', 'System journey'),
    ('tasks', 'Tasks'),
    ('decisions & rationale', 'Decisions'),
    ('risks & assumptions', 'Risks'),
    ('sources', 'Sources'),
    ('execution notes', 'Execution notes'),
    ('out of scope', 'Out of scope'),
    ('changelog', 'Changelog'),
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_preview_url(value):
    if not isinstance(value, str) or not re.match(r'^https?://', value, re.I):
        return False
    if re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.hostname and parsed.port != 0 and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def validate(s):
    require(s.get('schemaVersion') == 1, 'Unsupported schemaVersion')
    require(isinstance(s.get('title'), str) and s['title'].strip(), 'Missing title')
    require(s.get('engine') in ('current', 'ralph'), 'Unknown engine')
    require(type(s.get('gauntlet')) is bool, 'gauntlet must be boolean')
    require(s.get('referenceMode') in ('images', 'names', 'none'), 'Unknown reference mode')
    require(isinstance(s.get('inspiration'), str), 'inspiration must be text')
    selected = s.get('optionsConfirmedAt')
    if selected is not None:
        require(isinstance(selected, str) and dt.datetime.fromisoformat(selected).tzinfo is not None,
                'Run options need a timezone-aware confirmation timestamp')
        require(s['referenceMode'] != 'names' or s['inspiration'].strip(), 'Name the selected platforms')
    if s.get('phase') in ('running', 'complete') and (s['gauntlet'] or s['engine'] == 'ralph'):
        require(selected is not None, 'Select run options before starting work')
    require(s.get('phase') in ('planning', 'running', 'paused', 'blocked', 'complete'), 'Unknown phase')
    require(type(s.get('revision')) is int and s['revision'] >= 1, 'Invalid revision')
    require(type(s.get('iteration')) is int and s['iteration'] >= 0, 'Invalid iteration')
    require(type(s.get('maxIterations')) is int and s['maxIterations'] > 0, 'Invalid maxIterations')
    require(isinstance(s.get('updatedAt'), str), 'Missing updatedAt')
    require(dt.datetime.fromisoformat(s['updatedAt']).tzinfo is not None, 'Timestamp needs timezone')
    handoff = s.get('handoff')
    if handoff is not None:
        require(isinstance(handoff, dict), 'handoff must be an object')
        require(isinstance(handoff.get('plan'), str) and handoff['plan'].strip(), 'handoff needs a plan path')
        require(type(handoff.get('hop')) is int and handoff['hop'] >= 1, 'handoff needs a positive hop count')
    sections = s.get('sections')
    require(isinstance(sections, list) and len(sections) > 0, 'At least one section required')
    ids = set()
    for section in sections:
        require(isinstance(section.get('id'), str) and section['id'] not in ids, 'Duplicate/missing section id')
        ids.add(section['id'])
        require(isinstance(section.get('title'), str), 'Missing section title')
        if section.get('previewUrl') is not None:
            require(valid_preview_url(section['previewUrl']),
                    'previewUrl must be an absolute HTTP(S) URL without credentials or whitespace')
        require(section.get('status') in STATES, 'Unknown section status')
        require(type(section.get('artifactRevision')) is int and section['artifactRevision'] > 0, 'Invalid artifact revision')
        checks = section.get('criteria')
        require(isinstance(checks, list) and checks, 'Each section needs criteria')
        check_ids = set()
        for c in checks:
            require(isinstance(c.get('id'), str) and c['id'] not in check_ids, 'Duplicate/missing criterion id')
            check_ids.add(c['id'])
            require(isinstance(c.get('text'), str) and c['text'].strip(), 'Missing criterion text')
            require(type(c.get('passed')) is bool, 'passed must be boolean')
            require(not c['passed'] or (isinstance(c.get('evidence'), str) and c['evidence'].strip()), 'Passed criterion needs evidence')
        judge = section.get('judge', {})
        require(judge.get('verdict', 'pending') in ('pending', 'pass', 'fail', 'blocked'), 'Invalid judge verdict')
        if judge.get('verdict') == 'pass':
            require(judge.get('agentId') and judge.get('builderId') and judge['agentId'] != judge['builderId'], 'Judge must be independent')
            require(judge.get('artifactRevision') == section['artifactRevision'], 'Judge evidence is stale')
            require(judge.get('evidence') and judge.get('reference'), 'Judge pass needs evidence and named reference')
            target = section.get('target') or {}
            if target.get('origin') == 'generated':
                approval = target.get('approval') or {}
                require(approval.get('by') == 'user' and approval.get('evidence') and
                        type(target.get('targetRevision')) is int and
                        approval.get('targetRevision') == target['targetRevision'],
                        'Generated target needs explicit approval of its current revision')
        if section['status'] == 'done':
            require(all(c['passed'] for c in checks), 'Done requires every criterion')
            require(not s['gauntlet'] or judge.get('verdict') == 'pass', 'Done requires judge pass')
        if section['status'] == 'blocked':
            require(section.get('next'), 'Blocked needs next action')
        for key in ('before', 'target', 'current'):
            asset = section.get(key)
            if asset:
                require(asset.get('kind') in ('text', 'image', 'html'), 'Unknown asset kind')
                require(asset.get('label'), 'Asset needs a name')
                if asset['kind'] != 'text':
                    require(asset.get('path') and asset.get('source'), 'Captured asset needs path and provenance')
        if section['status'] == 'review':
            require((section.get('target') or {}).get('kind') in ('html', 'image'),
                    'A review section needs its proposal embedded as the target asset (kind html or image)')
    if s['phase'] == 'complete':
        require(all(x['status'] == 'done' for x in sections), 'Complete requires every section done')
    return s


def read_plan(path):
    content = Path(path).read_text()
    matches = list(BLOCK.finditer(content))
    require(len(matches) == 1, 'Plan needs exactly one dashboard-state fenced block')
    return content, matches[0], validate(json.loads(matches[0].group(1)))


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def canonical_dashboard_path(plan):
    plan = Path(plan)
    return plan.with_name(plan.stem.removesuffix('-plan') + '-dashboard.html')


def runtime_receipt_path(plan):
    plan = Path(plan)
    return plan.with_name(plan.stem.removesuffix('-plan') + '-dashboard.runtime.json')


def workspace_root(root):
    root = Path(root).resolve()
    return next((candidate for candidate in (root, *root.parents) if (candidate / '.git').exists()), root)


def plan_candidates(context):
    candidates = []
    for path in sorted(Path(context).glob('*-plan.md')):
        try:
            state = read_plan(path)[2]
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
        candidates.append((path.resolve(), state))
    return candidates


def slugify(value):
    value = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')[:48]
    return value or 'session-task'


def initial_plan(title, plan, root):
    title = re.sub(r'\s+', ' ', title).strip()[:120] or 'Session task'
    try:
        plan_path = str(plan.relative_to(root))
    except ValueError:
        plan_path = str(plan)
    state = {
        'schemaVersion': 1,
        'title': title,
        'planPath': plan_path,
        'revision': 1,
        'updatedAt': now(),
        'phase': 'planning',
        'engine': 'current',
        'gauntlet': False,
        'referenceMode': 'none',
        'inspiration': '',
        'optionsConfirmedAt': None,
        'iteration': 0,
        'maxIterations': 1,
        'sections': [{
            'id': 'task-intake',
            'title': 'Task intake',
            'summary': 'The task record exists; replace this intake section with the approved work.',
            'status': 'todo',
            'artifactRevision': 1,
            'next': 'Record the approved task, sources and acceptance criteria.',
            'criteria': [{
                'id': 'task-intake-1',
                'text': 'The approved task and its acceptance criteria are recorded.',
                'passed': False,
                'evidence': '',
            }],
            'judge': {'verdict': 'pending'},
        }],
    }
    return (
        f'# {title}\n\n'
        '## Status\n\nPLANNING (intake pending)\n\n'
        '## Goal & user journey (current trajectory)\n\nPending task intake.\n\n'
        '## System journey (current trajectory)\n\nThe session will replace this skeleton with the approved task flow.\n\n'
        '## Tasks\n\n- Record the approved scope and acceptance criteria.\n\n'
        '## Decisions & rationale\n\n- Ordinary task tracking starts with the independent judge off.\n\n'
        '## Risks & assumptions\n\n- This skeleton is not an approved implementation plan.\n\n'
        '## Sources\n\n- Task intake; replace with the real prompt, tickets and references.\n\n'
        '## Execution notes\n\n- Dashboard initialized before task routing.\n\n'
        '## Out of scope\n\n- Implementation before task approval.\n\n'
        '## Changelog\n\n### rev 1 · automatic intake\n\nCreated the session record skeleton.\n\n'
        '## Dashboard state\n\n```dashboard-state\n' + json.dumps(state, indent=2) + '\n```\n'
    )


def initialize(root, title='Session task', slug='session-task'):
    root = workspace_root(root)
    context = root / '.context'
    context.mkdir(parents=True, exist_ok=True)
    lock_path = context / '.workflow-dashboard.init.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = [(path, state) for path, state in plan_candidates(context)
                  if state['phase'] != 'complete']
        require(len(active) <= 1, 'Multiple active dashboard plans; reconcile one before initializing:\n' +
                '\n'.join(str(path) for path, _ in active))
        if active:
            plan = active[0][0]
            created = False
        else:
            stem = slugify(slug)
            plan = context / (stem + '-plan.md')
            suffix = 2
            while plan.exists():
                plan = context / (stem + '-' + str(suffix) + '-plan.md')
                suffix += 1
            atomic_write(plan, initial_plan(title, plan, root))
            created = True
        output = export_dashboard(plan)
    return plan.resolve(), output.resolve(), created


def narrative_sections(content):
    """Project selected plan prose into the viewer without creating another task store."""
    headings = list(re.finditer(r'^## ([^\n]+)\s*$', content, re.M))
    found = {}
    for index, match in enumerate(headings):
        name = match.group(1).strip().lower()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        body = content[match.end():end].strip()
        for prefix, label in RECORD_HEADINGS:
            if name.startswith(prefix):
                found[label] = body
                break
    return [{'label': label, 'text': found[label]} for _, label in RECORD_HEADINGS if found.get(label)]


def task_record(content, state):
    artifacts = []
    remaining = []
    for section in state['sections']:
        for key in ('before', 'target', 'current'):
            asset = section.get(key)
            if not asset:
                continue
            artifacts.append({
                'sectionId': section['id'],
                'section': section['title'],
                'role': key,
                **{field: asset[field] for field in ('kind', 'label', 'path', 'source', 'capturedAt') if field in asset},
            })
        if section['status'] != 'done':
            remaining.append({
                'sectionId': section['id'],
                'section': section['title'],
                'status': section['status'],
                'next': section.get('next', ''),
                'criteria': [criterion['text'] for criterion in section['criteria'] if not criterion['passed']],
            })
    return {'sections': narrative_sections(content), 'artifacts': artifacts, 'remaining': remaining}


def update(path, replacement, expected):
    path = Path(path).resolve()
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        content, match, old = read_plan(path)
        require(old['revision'] == expected, 'Revision conflict; re-read plan before updating')
        new = copy.deepcopy(replacement)
        new.pop('record', None)
        new['revision'] = old['revision'] + 1
        new['updatedAt'] = now()
        # Artifact changes invalidate a passing judge even if an agent forgets to reset it.
        previous = {x['id']: x for x in old['sections']}
        for section in new['sections']:
            prior = previous.get(section['id'])
            if prior and section['artifactRevision'] != prior['artifactRevision']:
                section['judge'] = {'verdict': 'pending'}
                if section['status'] == 'done':
                    section['status'] = 'review'
        validate(new)
        # Validate and render every referenced file BEFORE advancing the canonical state.
        rendered = render_spec(public_spec(path, state=new))
        block = '```dashboard-state\n' + json.dumps(new, indent=2) + '\n```\n'
        atomic_write(path, content[:match.start()] + block + content[match.end():])
        return new, rendered


def public_spec(plan, state=None):
    content = Path(plan).read_text()
    if state is None:
        _, _, state = read_plan(plan)
    s = copy.deepcopy(state)
    s['record'] = task_record(content, s)
    base = Path(plan).resolve().parent
    import base64
    for section in s['sections']:
        for key in ('before', 'target', 'current'):
            asset = section.get(key)
            if not asset or asset['kind'] == 'text':
                continue
            path = (base / asset['path']).resolve()
            require(path.is_relative_to(base), 'Assets must stay inside the plan directory')
            require(path.is_file(), 'Missing asset: ' + str(path))
            raw = path.read_bytes()
            require(len(raw) <= 12_000_000, 'Compress asset below 12 MB')
            if asset['kind'] == 'html':
                asset['html'] = raw.decode('utf-8')
            else:
                mime = {'.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(path.suffix.lower())
                require(mime, 'Images must be PNG, JPEG or WebP')
                asset['data'] = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()
            asset['sha256'] = hashlib.sha256(raw).hexdigest()
    return s


def render_spec(spec):
    data = json.dumps(spec).replace('<', '\\u003c').replace('&', '\\u0026')
    return TEMPLATE.read_text().replace('__DASHBOARD_SPEC__', data)


def render(plan):
    return render_spec(public_spec(plan))


def discover_plan(root):
    root = Path(root).resolve()
    context = next((candidate / '.context' for candidate in (root, *root.parents)
                    if (candidate / '.context').is_dir()), None)
    require(context is not None, 'No .context directory found from ' + str(root))
    candidates = plan_candidates(context)
    require(candidates, 'No dashboard plan found under ' + str(context))
    active = [(path, state) for path, state in candidates if state['phase'] != 'complete']
    if len(active) == 1:
        return active[0][0]
    if not active and len(candidates) == 1:
        return candidates[0][0]
    choices = active or candidates
    raise ValueError('Multiple active dashboard plans; reconcile one before linking:\n' +
                     '\n'.join(str(path) for path, _ in choices))


def export_dashboard(plan, output=None):
    plan = Path(plan).resolve()
    output = Path(output).resolve() if output else canonical_dashboard_path(plan)
    base = plan.parent
    _, _, state = read_plan(plan)
    referenced = set()
    for section in state['sections']:
        for key in ('before', 'target', 'current'):
            asset = section.get(key)
            if asset and asset.get('path'):
                referenced.add((base / asset['path']).resolve())
    for sub in ('mockups', 'previews'):
        subdir = base / sub
        if not subdir.is_dir():
            continue
        for file in sorted(subdir.rglob('*.html')):
            require(file.resolve() in referenced,
                    'Unreferenced mockup/preview: ' + str(file.relative_to(base)) +
                    ' — embed it as a section asset (kind html) before exporting')
    atomic_write(output, render(plan))
    return output


def stamp_handoff(plan, note=None, by=None):
    """Stamp a same-machine resume manifest into the plan and re-render its dashboard.
    Repeatable: each call bumps the hop, so a chain A->B->C regenerates from the one living
    plan and never degrades. Returns (new_state, rendered_html, link_to_copy)."""
    plan = Path(plan).resolve()
    _, _, state = read_plan(plan)
    root = workspace_root(plan.parent)
    dashboard = canonical_dashboard_path(plan)
    try:
        runtime = live_runtime(plan)
    except (ValueError, OSError):
        runtime = None
    previous = state.get('handoff') or {}
    new = copy.deepcopy(state)
    new['handoff'] = {
        'preparedAt': now(),
        'hop': int(previous.get('hop', 0)) + 1,
        'plan': str(plan),
        'planPath': state.get('planPath', str(plan)),
        'worktree': str(root),
        'dashboard': str(dashboard),
        'dashboardUrl': runtime['url'] if runtime else None,
        'resumeSkill': '/sk:work-handoff-prepare-and-pickup',
    }
    if by:
        new['handoff']['by'] = str(by)[:120]
    if note:
        new['handoff']['note'] = str(note)[:2000]
    result, rendered = update(plan, new, state['revision'])
    link = runtime['url'] if runtime else dashboard.as_uri()
    return result, rendered, link


def resolve_handoff(target):
    """Map a pasted loopback dashboard URL, a dashboard .html, or a plan .md back to its plan
    on THIS machine. Same-machine only by design: a loopback URL and a worktree path do not
    cross machines. Returns (plan_path, state)."""
    target = target.strip()
    require(target, 'resolve needs a dashboard URL, a dashboard .html, or a plan .md')
    if re.match(r'^https?://', target, re.I):
        url = urlsplit(target)
        require(url.hostname in ('127.0.0.1', 'localhost', '::1') and url.port,
                'Only a loopback dashboard URL (http://127.0.0.1:PORT) resolves on this machine')
        with urlopen(target.rstrip('/') + '/state', timeout=2) as response:
            require(response.status == 200, 'Dashboard viewer is not responding')
            spec = json.loads(response.read())
        info = spec.get('handoff') or {}
        require(info.get('plan'),
                'That dashboard has no handoff manifest yet; prepare a handoff in the source session first')
        plan = Path(info['plan'])
    else:
        raw = url2pathname(urlsplit(target).path) if target.startswith('file://') else target
        path = Path(raw).expanduser()
        require(path.exists(), 'No dashboard or plan at ' + str(path) + ' (same machine only)')
        if path.suffix == '.md':
            plan = path
        elif path.suffix == '.html':
            plan = path.with_name(path.stem.removesuffix('-dashboard') + '-plan.md')
        else:
            raise ValueError('Give a loopback dashboard URL, a dashboard .html, or a plan .md')
    plan = plan.resolve()
    require(plan.is_file(), 'Resolved plan is missing: ' + str(plan) + ' (same machine only)')
    return plan, read_plan(plan)[2]


def pid_command_and_cwd(pid):
    command = subprocess.run(
        ['ps', '-ww', '-p', str(pid), '-o', 'command='], capture_output=True, text=True
    )
    require(command.returncode == 0 and command.stdout.strip(), 'Dashboard viewer PID is not running')
    cwd = subprocess.run(
        ['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], capture_output=True, text=True
    )
    require(cwd.returncode == 0, 'Cannot resolve dashboard viewer working directory')
    paths = [line[1:] for line in cwd.stdout.splitlines() if line.startswith('n')]
    require(len(paths) == 1, 'Cannot resolve one dashboard viewer working directory')
    return command.stdout.strip(), Path(paths[0]).resolve()


def app_health(port):
    """GET the gauntlet app's health endpoint; None if it is not up or not responding in time."""
    try:
        with urlopen('http://127.0.0.1:' + str(port) + '/api/health', timeout=1.5) as response:
            if response.status != 200:
                return None
            return json.loads(response.read())
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def app_projects(port):
    with urlopen('http://127.0.0.1:' + str(port) + '/api/projects', timeout=2) as response:
        return json.loads(response.read())


def served_plan(port, plan):
    """True if the gauntlet app on `port` currently has `plan` registered."""
    plan = Path(plan).resolve()
    try:
        projects = app_projects(port)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return any(Path(row['plan']).resolve() == plan for row in projects if row.get('plan'))


def _projects_request(port, method, plan):
    body = json.dumps({'plan': str(plan)}).encode()
    request = Request(
        'http://127.0.0.1:' + str(port) + '/api/projects',
        data=body, method=method, headers={'Content-Type': 'application/json'},
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read())


def register_plan(port, plan):
    return _projects_request(port, 'POST', plan)


def unregister_plan(port, plan):
    return _projects_request(port, 'DELETE', plan)


def resolve_nvm_bin():
    nvm_bin = os.environ.get('NVM_BIN')
    if nvm_bin and Path(nvm_bin).is_dir():
        return nvm_bin
    versions_dir = Path.home() / '.nvm' / 'versions' / 'node'

    def version_key(path):
        return tuple(int(part) if part.isdigit() else -1 for part in path.name.lstrip('v').split('.'))

    candidates = sorted((p for p in versions_dir.glob('v24.*') if (p / 'bin').is_dir()), key=version_key)
    require(candidates, 'No nvm-installed Node v24.x found under ' + str(versions_dir))
    return str(candidates[-1] / 'bin')


def start_app(port):
    """Spawn the gauntlet Next.js dev server on `port` and wait for it to become healthy."""
    node_bin = resolve_nvm_bin()
    env = dict(os.environ)
    env['PATH'] = node_bin + os.pathsep + env.get('PATH', '')
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_path = APP_DIR / '.gauntlet.log'
    with log_path.open('ab') as log:
        process = subprocess.Popen(
            ['npm', 'run', 'dev', '--', '-p', str(port)],
            cwd=APP_DIR, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    atomic_write(APP_RECEIPT, json.dumps({
        'pid': process.pid, 'port': port, 'startedAt': now(),
    }, indent=2) + '\n')
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        health = app_health(port)
        if health:
            return health
        time.sleep(.5)
    tail = ''
    try:
        tail = log_path.read_text()[-4000:]
    except OSError:
        pass
    raise ValueError('gauntlet app did not become healthy on port ' + str(port) + ' within 40s\n' + tail)


def validate_runtime_owner(plan, data):
    plan = Path(plan).resolve()
    require(plan.is_file(), 'Runtime plan is missing')
    root = workspace_root(plan.parent)
    require(plan.is_relative_to(root), 'Runtime plan is outside its worktree')
    require(Path(data['plan']).resolve() == plan, 'Runtime plan mismatch')
    port = int(data['port'])
    health = app_health(port)
    require(health and health.get('ok'), 'Gauntlet app is not healthy on port ' + str(port))
    require(int(data['pid']) == int(health.get('pid', -1)),
            'Runtime receipt PID does not match the running gauntlet app')
    require(served_plan(port, plan), 'Plan is not registered with the gauntlet app')
    return data


def live_runtime(plan):
    receipt = runtime_receipt_path(plan)
    try:
        data = json.loads(receipt.read_text())
    except (OSError, TypeError, json.JSONDecodeError):
        receipt.unlink(missing_ok=True)
        return None
    try:
        os.kill(int(data['pid']), 0)
    except (OSError, KeyError, TypeError, ValueError):
        receipt.unlink(missing_ok=True)
        return None
    return validate_runtime_owner(plan, data)


def pid_exited(pid):
    result = subprocess.run(
        ['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True
    )
    return result.returncode != 0 or not result.stdout.strip() or result.stdout.lstrip().startswith('Z')


def stop_runtime(plan, expected_pid):
    plan = Path(plan).resolve()
    receipt = runtime_receipt_path(plan)
    require(receipt.is_file(), 'Dashboard runtime receipt is missing')
    data = json.loads(receipt.read_text())
    require(int(data['pid']) == expected_pid, 'Dashboard viewer PID changed after confirmation')
    port = int(data['port'])
    try:
        unregister_plan(port, plan)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError('Could not unregister the plan from the gauntlet app: ' + str(exc)) from exc
    receipt.unlink(missing_ok=True)
    try:
        projects = app_projects(port)
    except (OSError, ValueError, json.JSONDecodeError):
        projects = []
    if not projects:
        require(APP_RECEIPT.is_file(), 'No plans remain, but the gauntlet app receipt is missing')
        app_data = json.loads(APP_RECEIPT.read_text())
        app_pid = int(app_data['pid'])
        require(app_pid == expected_pid, 'Gauntlet app PID does not match --expect-pid')
        command, _ = pid_command_and_cwd(app_pid)
        require('next' in command or 'gauntlet' in command,
                'PID does not look like the gauntlet app; refusing to kill it')
        os.kill(app_pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_exited(app_pid):
            time.sleep(.05)
        require(pid_exited(app_pid), 'Gauntlet app did not stop within 5 seconds')
        APP_RECEIPT.unlink(missing_ok=True)
    return data


def serve(plan, output, port=APP_PORT):
    plan = Path(plan).resolve()
    output = Path(output).resolve()
    export_dashboard(plan, output)
    print('DASHBOARD_PATH=' + str(output), flush=True)

    health = app_health(port) or start_app(port)
    register_plan(port, plan)

    url = 'http://127.0.0.1:' + str(port) + '/p?plan=' + quote(str(plan), safe='')
    atomic_write(runtime_receipt_path(plan), json.dumps({
        'pid': health['pid'],
        'port': port,
        'url': url,
        'plan': str(plan),
        'app': 'gauntlet',
        'startedAt': now(),
    }, indent=2) + '\n')
    print(url, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'export', 'serve', 'state', 'update', 'link', 'init', 'stop', 'handoff', 'resolve'))
    parser.add_argument('plan', type=Path, nargs='?')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--title', default='Session task')
    parser.add_argument('--slug', default='session-task')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--port', type=int, default=APP_PORT)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--target')
    parser.add_argument('--note')
    parser.add_argument('--by')
    parser.add_argument('--expect-revision', type=int)
    parser.add_argument('--expect-pid', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            require(args.plan is None and args.output is None,
                    'init chooses its plan and canonical dashboard paths')
            plan, output, created = initialize(args.root, args.title, args.slug)
            print('DASHBOARD_STATUS=' + ('created' if created else 'reused'))
            print('PLAN_PATH=' + str(plan))
            print('DASHBOARD_PATH=' + str(output))
        elif args.command == 'link':
            require(args.plan is None and args.output is None,
                    'link discovers the workspace plan and always uses its canonical dashboard path')
            plan = discover_plan(args.root)
            output = export_dashboard(plan)
            print('DASHBOARD_PATH=' + str(output))
            receipt = runtime_receipt_path(plan)
            if receipt.is_file():
                try:
                    data = json.loads(receipt.read_text())
                    port = int(data['port'])
                    health = app_health(port)
                    if health and health.get('ok') and served_plan(port, plan):
                        print('DASHBOARD_URL=' + data['url'])
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    pass
        elif args.command == 'resolve':
            require(args.target is not None,
                    'resolve needs --target <dashboard url | dashboard.html | plan.md>')
            plan, state = resolve_handoff(args.target)
            info = state.get('handoff') or {}
            print('PLAN_PATH=' + str(plan))
            print('WORKTREE=' + str(workspace_root(plan.parent)))
            print('DASHBOARD_PATH=' + str(canonical_dashboard_path(plan)))
            print('ENGINE=' + state['engine'])
            print('GAUNTLET=' + ('true' if state['gauntlet'] else 'false'))
            print('PHASE=' + state['phase'])
            print('ITERATION=' + str(state['iteration']))
            print('MAX_ITERATIONS=' + str(state['maxIterations']))
            print('REVISION=' + str(state['revision']))
            print('HANDOFF_HOP=' + str(info.get('hop', 0)))
            print('HANDOFF_AT=' + str(info.get('preparedAt', '')))
        else:
            require(args.plan is not None, args.command + ' needs a plan path')
            output = args.output or canonical_dashboard_path(args.plan)
        if args.command == 'handoff':
            result, rendered, link = stamp_handoff(args.plan, note=args.note, by=args.by)
            atomic_write(output, rendered)
            print('HANDOFF_HOP=' + str(result['handoff']['hop']))
            print('HANDOFF_LINK=' + link)
            print('PLAN_PATH=' + str(Path(args.plan).resolve()))
            print('DASHBOARD_PATH=' + str(output))
            print('Updated revision', result['revision'])
        elif args.command == 'stop':
            require(args.expect_pid is not None, 'stop needs --expect-pid from the confirmed receipt')
            stopped = stop_runtime(args.plan, args.expect_pid)
            print('STOPPED_PID=' + str(stopped['pid']))
        elif args.command == 'update':
            require(args.input is not None and args.expect_revision is not None, 'update needs --input and --expect-revision')
            result, rendered = update(args.plan, json.loads(args.input.read_text()), args.expect_revision)
            atomic_write(output, rendered)
            print('Updated revision', result['revision'])
        elif args.command == 'state':
            print(json.dumps(read_plan(args.plan)[2], indent=2))
        elif args.command == 'validate':
            public_spec(args.plan)
            print('Plan and assets valid')
        elif args.command == 'export':
            print(export_dashboard(args.plan, output))
        elif args.command == 'serve':
            serve(args.plan, output, args.port)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
