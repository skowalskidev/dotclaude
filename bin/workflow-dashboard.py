#!/usr/bin/env python3
"""One plan, one reusable dashboard. Standard library only; no model or cloud calls."""
import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BLOCK = re.compile(r'^```dashboard-state\n(.*?)\n```\s*$', re.M | re.S)
TEMPLATE = Path(__file__).with_name('workflow-dashboard.html')
STATES = {'todo', 'doing', 'blocked', 'review', 'done'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def require(condition, message):
    if not condition:
        raise ValueError(message)


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
    if s.get('phase') in ('running', 'complete'):
        require(selected is not None, 'Select run options before starting work')
    require(s.get('phase') in ('planning', 'running', 'paused', 'blocked', 'complete'), 'Unknown phase')
    require(type(s.get('revision')) is int and s['revision'] >= 1, 'Invalid revision')
    require(type(s.get('iteration')) is int and s['iteration'] >= 0, 'Invalid iteration')
    require(type(s.get('maxIterations')) is int and s['maxIterations'] > 0, 'Invalid maxIterations')
    require(isinstance(s.get('updatedAt'), str), 'Missing updatedAt')
    require(dt.datetime.fromisoformat(s['updatedAt']).tzinfo is not None, 'Timestamp needs timezone')
    sections = s.get('sections')
    require(isinstance(sections, list) and len(sections) > 0, 'At least one section required')
    ids = set()
    for section in sections:
        require(isinstance(section.get('id'), str) and section['id'] not in ids, 'Duplicate/missing section id')
        ids.add(section['id'])
        require(isinstance(section.get('title'), str), 'Missing section title')
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


def update(path, replacement, expected):
    path = Path(path).resolve()
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        content, match, old = read_plan(path)
        require(old['revision'] == expected, 'Revision conflict; re-read plan before updating')
        new = copy.deepcopy(replacement)
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
    if state is None:
        _, _, state = read_plan(plan)
    s = copy.deepcopy(state)
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


def serve(plan, output, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = self.headers.get('Host', '')
            if host != '127.0.0.1:' + str(self.server.server_port):
                self.send_error(403)
                return
            route = urlsplit(self.path).path
            try:
                if route in ('/', '/dashboard.html'):
                    body, mime = render(plan).encode(), 'text/html; charset=utf-8'
                    atomic_write(output, body.decode())
                elif route == '/state':
                    body, mime = json.dumps(public_spec(plan)).encode(), 'application/json'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.send_error(422, 'Invalid plan or missing evidence')

        def log_message(self, *args):
            pass

    atomic_write(output, render(plan))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print('DASHBOARD_URL=http://127.0.0.1:' + str(server.server_port), flush=True)
    print('PID=' + str(os.getpid()), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        atomic_write(output, render(plan))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'export', 'serve', 'state', 'update'))
    parser.add_argument('plan', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--expect-revision', type=int)
    args = parser.parse_args()
    output = args.output or args.plan.with_name(args.plan.stem.removesuffix('-plan') + '-dashboard.html')
    try:
        if args.command == 'update':
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
            atomic_write(output, render(args.plan))
            print(output)
        else:
            serve(args.plan, output, args.port)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
