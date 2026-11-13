#!/usr/bin/env python3
"""connector_registry.py: the ONE loader for Simon's connector registry, plus the route resolver.

The registry is local data, never in ~/.claude. One root per boundary, declared in the identity
overlay (`connectorRoots` in identity.local.json), e.g. a work root under the work-projects folder
and a personal root under the personal-projects folder. Each root holds:

  index.json         {"boundary", "match": [...]}: the root itself and the repos its shared routes reach
  projects/<p>.json  {"match": [...], "ignoreProjectInstructions"?, "monitor"?}: one file per project
  <provider>.json    {"provider", "capabilities", "scope", "routes": [route, ...]}: one file per provider
  health.json        route outcomes, written only by `record` (state, kept apart from the records)

A route is a connector record (the fields references/connectors-setup.md documents) plus `id`,
optional `capabilities`, `scope` (shared-account | per-project), `serves` (projects it is known to
serve) and optional `requires` ({"claudeAccount": <email or identity-overlay key>}).

A route's `secret` is hybrid: `store: local` (the default) names a key file and variable names,
`store: vault` names a Supabase Vault secret, the local-key route that reads it (`via`), the
project and the variable the consumer expects. A provider's `storeOrder` ranks the two (local
first by default). The value is never in a record, and `run` hands it only to the child process.

Readers (connectors-provision.sh, work-resource-guard.sh, session-connectors.sh, agent_runtime.py,
health-pulse.py) all go through this module, so there is one parser and one boundary rule.

Usage:
  connector_registry.py roots                         list the configured roots and their state
  connector_registry.py manifest [--cwd DIR]          effective manifest for DIR (project + shared routes)
  connector_registry.py project NAME                  one project's manifest by name
  connector_registry.py guard-facts NAME [--cwd DIR]  boundaries, readOnly, gated for one connector name
  connector_registry.py cli-profile CLI [--cwd DIR]   the profile this project pins for a CLI
  connector_registry.py resolve CAPABILITY [--cwd DIR] [--claude-account EMAIL] [--json]
  connector_registry.py record PROVIDER ROUTE ok|fail [--reason TEXT] [--by WHO] [--cwd DIR]
  connector_registry.py run PROVIDER ROUTE [--cwd DIR] -- CMD...   CMD with the route's key in its env
  connector_registry.py list [--json]                 every provider, capability and route, per root
  connector_registry.py validate DIR                   exit 1 unless THIS engine reads every file in a candidate root
  connector_registry.py migrate --from DIR [--write] [--provider-map JSON]
  connector_registry.py check-migration --from DIR    every legacy manifest field is reachable here
"""
import argparse
import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get('CLAUDE_HOME', str(Path.home() / '.claude')))
BOUNDARIES = ('work', 'personal')
SCOPES = ('shared-account', 'per-project')
ROUTE_KEYS = ('id', 'capabilities', 'scope', 'serves', 'requires')  # registry-only route fields
INDEX = 'index.json'
HEALTH = 'health.json'
COOLDOWN_HOURS = 24  # a failed route is skipped for this long unless every other route fails
VAR_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')  # a secret.var entry is a variable NAME, never a value
STORES = ('local', 'vault')  # where a route's key lives: a local key file, or a Supabase Vault pointer
VIA = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.@-]+$')  # provider/route of the route that reads the vault
VAULT_API = os.environ.get('CLAUDE_VAULT_API', 'https://api.supabase.com/v1/projects/')


class RegistryError(ValueError):
    pass


# ---------------------------------------------------------------------------- loading

def identity_file():
    return Path(os.environ.get('CLAUDE_IDENTITY_FILE', str(CLAUDE_HOME / 'identity.local.json')))


def read_identity():
    path = identity_file()
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def expand(path):
    return Path(os.path.expanduser(str(path)))


def configured_roots(identity=None):
    """[(boundary, Path)] from CLAUDE_CONNECTOR_ROOTS ("work=/a,personal=/b") or the overlay."""
    raw = os.environ.get('CLAUDE_CONNECTOR_ROOTS')
    pairs = {}
    if raw is not None:
        for part in filter(None, raw.split(',')):
            key, _, value = part.partition('=')
            pairs[key.strip()] = value.strip()
    else:
        pairs = (identity if identity is not None else read_identity()).get('connectorRoots') or {}
    roots = []
    for boundary, value in pairs.items():
        if boundary not in BOUNDARIES or not value:
            continue
        roots.append((boundary, expand(value)))
    return roots


def load_root(boundary, path):
    """One root: its index, provider records and health. Unreadable files land in `errors`."""
    root = {'boundary': boundary, 'path': path, 'index': None, 'providers': {}, 'health': {},
            'projectPaths': {}, 'errors': []}
    index_path = path / INDEX
    try:
        index = json.loads(index_path.read_text())
    except FileNotFoundError:
        root['errors'].append(str(index_path) + ': missing')
        return root
    except (OSError, ValueError) as exc:
        root['errors'].append(str(index_path) + ': ' + str(exc))
        return root
    if index.get('boundary') != boundary:
        root['errors'].append(str(index_path) + ': boundary must be ' + boundary)
        return root
    if 'ignoreProjectInstructions' in index:
        raise RegistryError('ignoreProjectInstructions belongs only in a project connector manifest '
                            '(a project entry), not in ' + str(index_path))
    if 'projects' in index:
        root['errors'].append(str(index_path) + ': projects live in projects/<name>.json')
    index = {**index, 'projects': {}}
    root['index'] = index
    root['projectPaths'] = {}
    for file in sorted((path / 'projects').glob('*.json')):
        try:
            entry = json.loads(file.read_text())
            if not isinstance(entry, dict) or 'connectors' in entry or 'boundary' in entry:
                raise RegistryError('a project file holds match/ignoreProjectInstructions/monitor only')
        except (OSError, ValueError) as exc:
            root['errors'].append(str(file) + ': ' + str(exc))
            continue
        index['projects'][file.stem] = entry
        root['projectPaths'][file.stem] = file
    for file in sorted(path.glob('*.json')):
        if file.name in (INDEX, HEALTH):
            continue
        try:
            record = json.loads(file.read_text())
            validate_provider(record, boundary, file)
        except (OSError, ValueError) as exc:
            root['errors'].append(str(file) + ': ' + str(exc))
            continue
        root['providers'][record['provider']] = record
    try:
        root['health'] = json.loads((path / HEALTH).read_text())
    except (OSError, ValueError):
        root['health'] = {}
    return root


def validate_provider(record, boundary, file):
    if not isinstance(record, dict) or not record.get('provider'):
        raise RegistryError('needs a "provider" name')
    if record.get('boundary', boundary) != boundary:
        raise RegistryError('boundary differs from its root (' + boundary + ')')
    if record.get('scope', 'per-project') not in SCOPES:
        raise RegistryError('scope must be one of ' + ', '.join(SCOPES))
    seen = set()
    for route in record.get('routes', []):
        if not route.get('id') or not route.get('name'):
            raise RegistryError('every route needs an "id" and a connector "name"')
        if route['id'] in seen:
            raise RegistryError('duplicate route id ' + route['id'])
        seen.add(route['id'])
        if route.get('boundary', boundary) != boundary:
            raise RegistryError('route ' + route['id'] + ' boundary differs from its root')
        scope = route.get('scope', record.get('scope', 'per-project'))
        if scope not in SCOPES:
            raise RegistryError('route ' + route['id'] + ' has an unknown scope')
        if scope == 'per-project' and not route.get('serves'):
            raise RegistryError('per-project route ' + route['id'] + ' must list the projects it serves')
        validate_secret(route)
    order = record.get('storeOrder', list(STORES))
    if not isinstance(order, list) or sorted(order) != sorted(STORES):
        raise RegistryError('storeOrder must list ' + ' and '.join(STORES) + ' once each')


def validate_secret(route):
    """`secret` is local {path, var?} (the key file and the variable names in it) or a vault pointer
    {store: vault, via, project, name, env}. Both hold names and paths only, never a value."""
    if 'secret' not in route:
        return
    secret = route['secret']
    where = 'route ' + route['id'] + ' secret'
    if not isinstance(secret, dict) or secret.get('store', 'local') not in STORES:
        raise RegistryError(where + ' store must be one of ' + ', '.join(STORES))
    if secret.get('store') == 'vault':
        if not isinstance(secret.get('via'), str) or not VIA.match(secret['via']):
            raise RegistryError(where + ' needs "via": the provider/route that reads the vault')
        if not isinstance(secret.get('project'), str) or not secret['project'].strip():
            raise RegistryError(where + ' needs a vault "project" string')
        names, envs = as_list(secret.get('name')), as_list(secret.get('env'))
        if not names or not all(isinstance(n, str) and n.strip() for n in names):
            raise RegistryError(where + ' needs a vault "name" string (or a list of them)')
        if len(envs) != len(names) or not all(isinstance(e, str) and VAR_NAME.match(e) for e in envs):
            raise RegistryError(where + ' needs "env": one variable name the consumer reads per vault name')
        if 'path' in secret or 'var' in secret:
            raise RegistryError(where + ' is a vault pointer; a local path or var belongs on its own route')
        return
    if not isinstance(secret.get('path'), str) or not secret['path']:
        raise RegistryError(where + ' needs a "path" string')
    names = secret.get('var', [])
    names = [names] if isinstance(names, str) else names
    if not isinstance(names, list) or not all(isinstance(n, str) and VAR_NAME.match(n) for n in names):
        raise RegistryError(where + '.var must be variable names, never a value')


def as_list(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def vault_pairs(secret):
    """[(vault name, variable)] of a vault pointer; `name` and `env` are one string or equal lists."""
    return list(zip(as_list(secret['name']), as_list(secret['env'])))


def secret_location(route):
    """Where a route's key lives, or None. Never reads the file, the vault or a value.

    local: {store, path, var: [names]}; vault: {store, via, project, name, env}.
    """
    secret = route.get('secret')
    if not isinstance(secret, dict):
        return None
    if secret.get('store') == 'vault':
        return {key: secret[key] for key in ('store', 'via', 'project', 'name', 'env')}
    if not secret.get('path'):
        return None
    names = secret.get('var', [])
    return {'store': 'local', 'path': secret['path'], 'var': [names] if isinstance(names, str) else list(names)}


def store_rank(route, record):
    """0 for the provider's first store in `storeOrder` (local unless it says otherwise)."""
    store = (secret_location(route) or {}).get('store', 'local')
    return list(record.get('storeOrder', STORES)).index(store)


def validate_root(path):
    """Errors (empty = pass) this engine raises on a candidate root: staged copy before the live one."""
    path = expand(path)
    try:
        boundary = json.loads((path / INDEX).read_text()).get('boundary')
    except (OSError, ValueError) as exc:
        return [str(path / INDEX) + ': ' + str(exc)]
    if boundary not in BOUNDARIES:
        return [str(path / INDEX) + ': boundary must be one of ' + ', '.join(BOUNDARIES)]
    try:
        root = load_root(boundary, path)
    except RegistryError as exc:
        return [str(exc)]
    errors = list(root['errors'])
    for provider, record in root['providers'].items():
        for route in record.get('routes', []):
            secret = secret_location(route)
            if secret and secret['store'] == 'vault' and vault_reader(root, secret) is None:
                errors.append(provider + '/' + route['id'] + ': vault pointer via ' + secret['via'] +
                              ' names no local-key route in this root')
    return errors


def load_all(identity=None):
    return [load_root(boundary, path) for boundary, path in configured_roots(identity)]


def flat_routes(root):
    """Every route of a root as a connector record, with provider, boundary and scope filled in."""
    out = []
    for provider, record in root['providers'].items():
        for order, route in enumerate(record.get('routes', [])):
            item = {key: value for key, value in route.items() if key not in ('boundary',)}
            item['provider'] = provider
            item['route'] = route['id']
            item['boundary'] = root['boundary']
            item['scope'] = route.get('scope', record.get('scope', 'per-project'))
            item['capabilities'] = list(route.get('capabilities') or record.get('capabilities') or [provider])
            item['serves'] = list(route.get('serves', []))
            item['_order'] = order
            item['_store'] = store_rank(route, record)
            out.append(item)
    return out


def provisioned_for(route, project):
    """Whether a route is part of a project's provisioned set (registered, guarded, launched).

    A shared-account route with an empty `serves` reaches every repo of its root; one that lists
    projects is provisioned only there, so a migration never registers a server somewhere new.
    The resolver still ranks every shared-account route as serving any project of the boundary.
    """
    if route['scope'] == 'shared-account':
        return not route['serves'] or project in route['serves']
    return bool(project) and project in route['serves']


def connector_view(route, project=None):
    """A route as the plain connector record the engines consume (registry bookkeeping removed),
    with the project's own `auth` text when the route keeps one per project."""
    view = {key: value for key, value in route.items() if not key.startswith('_')}
    if isinstance(view.get('auth'), dict) and 'byProject' in view['auth']:
        view['auth'] = route_auth(view, project)
    return view


# ---------------------------------------------------------------------------- project selection

def origin(cwd):
    result = subprocess.run(['git', '-C', str(cwd), 'remote', 'get-url', 'origin'],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def session_boundary(remote, identity):
    work_match = identity.get('workOrgMatch', '')
    return 'work' if remote and work_match and work_match in remote else 'personal'


def select(cwd, remote=None, identity=None, roots=None, strict=True):
    """(project file | None, manifest, boundary) for a workspace.

    Projects match on the git remote first and on the path only when there is no remote; two
    matching projects fail. A root's shared-account routes layer under the project's routes when
    the root's `match` hits the remote or path, or the matched project lives in that root, and only
    when the root's boundary equals the session's. A project route wins a name clash.
    """
    identity = read_identity() if identity is None else identity
    roots = load_all(identity) if roots is None else roots
    if strict:
        errors = [error for root in roots for error in root['errors']
                  if not error.endswith(': missing')]
        if errors:
            raise RegistryError('Unreadable connector registry file: ' + '; '.join(errors))
    remote = origin(cwd) if remote is None else remote
    where = str(Path(cwd).resolve())
    target = remote or where
    boundary = session_boundary(remote, identity)
    matches = []
    for root in roots:
        if not root['index']:
            continue
        for name, entry in (root['index'].get('projects') or {}).items():
            if any(value and value in target for value in entry.get('match', [])):
                matches.append((root, name, entry))
    if len(matches) > 1:
        raise RegistryError('Multiple connector manifests match this project: ' +
                            ', '.join(root['boundary'] + '/' + name for root, name, _ in matches))
    for _, name, entry in matches:
        if 'ignoreProjectInstructions' in entry and not isinstance(entry['ignoreProjectInstructions'], bool):
            raise RegistryError('ignoreProjectInstructions must be a boolean in project ' + name)
    manifest, path, project_root, project = {}, None, None, None
    if matches:
        project_root, project, entry = matches[0]
        if project_root['boundary'] != boundary:
            raise RegistryError('Connector manifest and identity.local.json disagree about the project boundary')
        path = project_root['projectPaths'][project]
        manifest = {'project': project, 'boundary': project_root['boundary'],
                    **{key: value for key, value in entry.items()}}
    connectors, names, shared_from = [], set(), []
    if project_root is not None:
        for route in flat_routes(project_root):
            if route['scope'] == 'per-project' and provisioned_for(route, project) and route['name'] not in names:
                names.add(route['name'])
                connectors.append(connector_view(route, project))
    for root in roots:
        if not root['index'] or root['boundary'] != boundary:
            continue
        hits = any(value and value in remote + where for value in root['index'].get('match', []))
        if not (hits or root is project_root):
            continue
        layered = [route for route in flat_routes(root) if provisioned_for(route, project)]
        if not layered:
            continue
        shared_from.append(str(root['path']))
        for route in layered:
            if route['name'] not in names:
                names.add(route['name'])
                connectors.append(connector_view(route, project))
    manifest['connectors'] = connectors
    if shared_from:
        manifest['sharedFrom'] = shared_from
    return path, manifest, boundary


def project_manifest(name, roots=None):
    """A project's manifest by name, for tools that take --project (health-pulse)."""
    roots = load_all() if roots is None else roots
    for root in roots:
        if root['index'] and name in (root['index'].get('projects') or {}):
            entry = root['index']['projects'][name]
            connectors = [connector_view(route, name) for route in flat_routes(root) if provisioned_for(route, name)]
            return {'project': name, 'boundary': root['boundary'], **entry, 'connectors': connectors}
    raise RegistryError('no connector project named ' + name)


def name_boundaries(name, roots=None):
    """Every boundary under which a connector name is declared, across all roots."""
    roots = load_all() if roots is None else roots
    return sorted({root['boundary'] for root in roots for route in flat_routes(root)
                   if route['name'] == name})


def guard_facts(name, cwd, remote=None, roots=None, identity=None):
    """What the boundary guard needs for one connector name: boundaries + this repo's write policy."""
    roots = load_all() if roots is None else roots
    facts = {'boundaries': name_boundaries(name, roots), 'readOnly': None, 'gated': None}
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        return facts
    record = next((item for item in manifest.get('connectors', []) if item['name'] == name), None)
    if record is None:  # a same-boundary route for another project still carries its write policy
        record = next((connector_view(route) for root in roots if root['boundary'] == boundary
                       for route in flat_routes(root) if route['name'] == name), None)
    if record is not None:
        facts['readOnly'] = record.get('readOnly')
        facts['gated'] = record.get('gated')
    return facts


def cli_profile(cli, cwd, remote=None, roots=None, identity=None):
    try:
        _, manifest, _ = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        return ''
    for item in manifest.get('connectors', []):
        if item.get('kind') == 'cli' and (item.get('cli') or {}).get('name') == cli:
            return (item.get('cli') or {}).get('profile') or ''
    return ''


# ---------------------------------------------------------------------------- resolver + health

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_time(value):
    try:
        stamp = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=datetime.timezone.utc)


def current_claude_account():
    """The email the Claude CLI is signed in as (account field only; no token is read)."""
    try:
        data = json.loads((Path.home() / '.claude.json').read_text())
    except (OSError, ValueError):
        return ''
    return ((data.get('oauthAccount') or {}).get('emailAddress') or '').strip()


def capability_matches(query, route):
    query = query.strip().lower()
    if query == route['provider'].lower():
        return True
    for capability in route['capabilities']:
        capability = capability.lower()
        if capability == query or capability.startswith(query + '.'):
            return True
    return False


def health_state(entry, at):
    """ok | untested | half-open | open, from a route's last success and last failure."""
    success = parse_time((entry.get('lastSuccess') or {}).get('at', '')) if entry.get('lastSuccess') else None
    failure = parse_time((entry.get('lastFailure') or {}).get('at', '')) if entry.get('lastFailure') else None
    if failure and (not success or failure > success):
        hours = (at - failure).total_seconds() / 3600
        return 'open' if hours < COOLDOWN_HOURS else 'half-open'
    return 'ok' if success else 'untested'


def resolve(capability, cwd, remote=None, identity=None, roots=None, claude_account=None, at=None):
    """Routes for a capability inside the session boundary, in the order to try them.

    Order: available before needs-a-human-step, closed circuit before open, routes that serve this
    project (shared-account, listed in `serves`, or with a recorded success here) before the rest of
    the boundary, proven routes before untested ones, then the record's declared preference, then
    the most recent success. A route of the other boundary is never returned.
    """
    identity = read_identity() if identity is None else identity
    roots = load_all(identity) if roots is None else roots
    at = at or now_utc()
    remote = origin(cwd) if remote is None else remote
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        manifest, boundary = {}, session_boundary(remote, identity)
    project = manifest.get('project')
    layered = {item['name'] for item in manifest.get('connectors', [])}
    account = current_claude_account() if claude_account is None else claude_account
    out = []
    for root in roots:
        if root['boundary'] != boundary:
            continue
        for route in flat_routes(root):
            if not capability_matches(capability, route):
                continue
            entry = root['health'].get(route['provider'] + '/' + route['route'], {})
            state = health_state(entry, at)
            success = entry.get('lastSuccess') or {}
            serves_here = (route['scope'] == 'shared-account' or route['name'] in layered
                           or (project and project in route['serves'])
                           or (project and success.get('project') == project))
            blocker = ''
            wanted = (route.get('requires') or {}).get('claudeAccount', '')
            if wanted and '@' not in wanted:
                wanted = identity.get(wanted, '')
            if wanted and account and wanted.lower() != account.lower():
                blocker = 'needs the Claude CLI signed in as ' + wanted + ' (human step: /login)'
            elif route.get('enabledOnDemand'):
                blocker = 'on-demand pathway: enable it and get the per-write yes first'
            secret = secret_location(route)
            if not blocker and secret and secret['store'] == 'vault' and vault_reader(root, secret) is None:
                blocker = 'vault pointer via ' + secret['via'] + ' names no local-key route in this boundary'
            last_ok = parse_time(success.get('at', '')) if success else None
            out.append({
                'provider': route['provider'], 'route': route['route'], 'name': route['name'],
                'kind': route.get('kind', ''), 'scope': route['scope'], 'servesHere': bool(serves_here),
                'state': state, 'blocker': blocker, 'readOnly': route.get('readOnly'),
                'gated': route.get('gated'), 'lastSuccess': entry.get('lastSuccess'),
                'lastFailure': entry.get('lastFailure'), 'recipe': route.get('recipe'),
                'secret': secret,
                'root': str(root['path']),
                '_key': (bool(blocker), state == 'open', not serves_here, route['_store'],
                         0 if state == 'ok' else 1, route['_order'],
                         -(last_ok.timestamp() if last_ok else 0), route['provider']),
            })
    out.sort(key=lambda item: item['_key'])
    for rank, item in enumerate(out, 1):
        item['rank'] = rank
        del item['_key']
    return out, boundary, project


# ---------------------------------------------------------------------------- key loading (run)

def vault_reader(root, secret):
    """The local-key route a vault pointer reads through, from the same root, or None."""
    provider, _, route_id = secret['via'].partition('/')
    record = root['providers'].get(provider) or {}
    route = next((item for item in record.get('routes', []) if item['id'] == route_id), None)
    location = secret_location(route) if route else None
    return route if location and location['store'] == 'local' and location['var'] else None


def read_env_file(path, names):
    """{name: value} for the named KEY=VALUE lines of a key file. Values stay in memory only."""
    values = {}
    for line in expand(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        key, sep, value = line.partition('=')
        if sep and key.strip() in names:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            values[key.strip()] = value.strip()
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise RegistryError('key file ' + str(path) + ' has no value for ' + ', '.join(missing))
    return values


def sql_literal(text):
    return "'" + text.replace("'", "''") + "'"


def read_vault(secret, token, opener=None):
    """{variable: value} for a vault pointer, through the Supabase management API query endpoint.
    Raises with the status only: neither the token nor a value ever reaches an error message."""
    pairs = vault_pairs(secret)
    label = ', '.join(json.dumps(name) for name, _ in pairs)
    query = ('select name, decrypted_secret from vault.decrypted_secrets where name in (' +
             ', '.join(sql_literal(name) for name, _ in pairs) + ')')
    request = urllib.request.Request(
        VAULT_API + secret['project'] + '/database/query', method='POST',
        data=json.dumps({'query': query}).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            rows = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RegistryError('vault read for ' + label + ' failed: HTTP ' + str(exc.code)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RegistryError('vault read for ' + label + ' failed: ' + type(exc).__name__) from None
    # A stored value ending in a newline breaks the child's HTTP header, and its error can echo the key.
    found = {row.get('name'): row['decrypted_secret'].strip() for row in rows
             if isinstance(row, dict) and isinstance(row.get('decrypted_secret'), str)} \
        if isinstance(rows, list) else {}
    missing = [name for name, _ in pairs if not isinstance(found.get(name), str) or not found[name]]
    if missing:
        raise RegistryError('no Vault secret named ' + ', '.join(json.dumps(n) for n in missing) +
                            ' in project ' + secret['project'])
    return {env: found[name] for name, env in pairs}


def route_env(provider, route_id, cwd, remote=None, identity=None, opener=None):
    """{variable: value} a route's consumer needs, from its key file or its vault pointer."""
    identity = read_identity() if identity is None else identity
    roots = load_all(identity)
    remote = origin(cwd) if remote is None else remote
    try:
        _, _, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        boundary = session_boundary(remote, identity)
    root = next((item for item in roots if item['boundary'] == boundary and provider in item['providers']), None)
    if root is None:
        raise RegistryError('no ' + boundary + ' provider named ' + provider)
    route = next((item for item in root['providers'][provider].get('routes', []) if item['id'] == route_id), None)
    if route is None:
        raise RegistryError('provider ' + provider + ' has no route ' + route_id)
    secret = secret_location(route)
    if secret is None:
        raise RegistryError('route ' + provider + '/' + route_id + ' declares no key')
    if secret['store'] == 'local':
        if not secret['var']:
            raise RegistryError('route ' + provider + '/' + route_id + ' names a key file but no variable; '
                                'pass its path to the tool instead')
        return read_env_file(secret['path'], secret['var'])
    reader = vault_reader(root, secret)
    if reader is None:
        raise RegistryError('vault pointer via ' + secret['via'] + ' names no local-key route in this boundary')
    location = secret_location(reader)
    token = read_env_file(location['path'], location['var'][:1])[location['var'][0]]
    return read_vault(secret, token, opener=opener)


def run_with_key(provider, route_id, command, cwd, opener=None):
    """Run COMMAND with the route's key in its environment; return its exit code. Prints no value."""
    if not command:
        raise RegistryError('run needs a command after --')
    env = {**os.environ, **route_env(provider, route_id, cwd, opener=opener)}
    return subprocess.run(command, env=env, cwd=str(cwd)).returncode


def record(provider, route_id, outcome, cwd, reason='', by='', remote=None, identity=None, at=None):
    """Write a route's outcome to its root's health.json (locked, atomic). Same boundary only."""
    identity = read_identity() if identity is None else identity
    roots = load_all(identity)
    remote = origin(cwd) if remote is None else remote
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        manifest, boundary = {}, session_boundary(remote, identity)
    root = next((item for item in roots if item['boundary'] == boundary
                 and provider in item['providers']), None)
    if root is None:
        raise RegistryError('no ' + boundary + ' provider named ' + provider)
    if route_id not in [route['id'] for route in root['providers'][provider].get('routes', [])]:
        raise RegistryError('provider ' + provider + ' has no route ' + route_id)
    if outcome not in ('ok', 'fail'):
        raise RegistryError('outcome must be ok or fail')
    stamp = (at or now_utc()).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    note = {'at': stamp, 'by': by or os.environ.get('CONDUCTOR_WORKSPACE_NAME', '') or 'agent',
            'project': manifest.get('project') or ''}
    if outcome == 'fail':
        note['reason'] = reason or 'unspecified'
    elif reason:
        note['note'] = reason
    path = root['path'] / HEALTH
    with locked(path):
        try:
            health = json.loads(path.read_text())
        except (OSError, ValueError):
            health = {}
        entry = health.setdefault(provider + '/' + route_id, {})
        entry['lastSuccess' if outcome == 'ok' else 'lastFailure'] = note
        write_json(path, health)
    return note


@contextlib.contextmanager
def locked(path):
    import fcntl
    lock = os.fdopen(os.open(str(path.parent / ('.' + path.name + '.lock')),
                             os.O_WRONLY | os.O_CREAT, 0o600), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix='.' + path.name + '.')
    with os.fdopen(handle, 'w') as out:
        json.dump(value, out, indent=2)
        out.write('\n')
    os.chmod(temp, 0o600)
    os.replace(temp, path)


# ---------------------------------------------------------------------------- migration

def provider_of(record, provider_map):
    name = record.get('name', '')
    if record.get('provider'):
        return record['provider']
    if name in provider_map:
        return provider_map[name]
    if record.get('kind') == 'claude-connector' and isinstance(record.get('connector'), str):
        return record['connector'].lower().split()[0]
    return name.split('-')[0] or name


def legacy_body(record):
    """A deep copy without `boundary`, so building a registry never mutates its input."""
    return json.loads(json.dumps({key: value for key, value in record.items() if key != 'boundary'}))


def credential_key(body):
    """Two records with the same key reach the same account: same name, kind, key file, profile,
    transport and write policy. Only their descriptive `auth` text may differ."""
    return json.dumps({key: value for key, value in body.items() if key != 'auth'}, sort_keys=True)


def route_auth(route, project):
    """The auth block a project's legacy record carried: its own entry when the text differed."""
    auth = dict(route.get('auth') or {})
    own = (auth.pop('byProject', None) or {}).get(project)
    return own if own is not None else (auth if 'auth' in route else None)


def build_registry(manifests, provider_map=None):
    """Legacy manifests ({stem: manifest}) -> {boundary: {'index': {...}, 'providers': {...}}}.

    Shared manifests become shared-account routes. A record that is identical in two or more
    project manifests is one shared account, so it becomes one shared-account route listing those
    projects in `serves`. Different same-named records stay separate per-project routes.
    """
    provider_map = provider_map or {}
    out = {}
    for stem in sorted(manifests):
        manifest = manifests[stem]
        boundary = manifest.get('boundary')
        if boundary not in BOUNDARIES:
            raise RegistryError(stem + ': manifest needs boundary work or personal')
        tree = out.setdefault(boundary, {'index': {'boundary': boundary, 'match': [], 'projects': {}},
                                         'providers': {}})
        shared = manifest.get('shared') is True
        if shared:
            for value in manifest.get('match', []):
                if value not in tree['index']['match']:
                    tree['index']['match'].append(value)
            if manifest.get('_comment'):
                tree['index'].setdefault('notes', []).append(manifest['_comment'])
            if 'ignoreProjectInstructions' in manifest:
                tree['index']['ignoreProjectInstructions'] = manifest['ignoreProjectInstructions']
        else:
            project = manifest.get('project') or stem
            tree['index']['projects'][project] = {
                key: value for key, value in manifest.items()
                if key not in ('project', 'boundary', 'connectors', 'shared')}
        for record in manifest.get('connectors', []):
            if record.get('boundary', boundary) != boundary:
                raise RegistryError(stem + ': connector ' + record.get('name', '?') +
                                    ' boundary differs from its manifest')
            provider = provider_of(record, provider_map)
            entry = tree['providers'].setdefault(provider, {'provider': provider, 'routes': []})
            body = legacy_body(record)
            same = next((route for route in entry['routes'] if credential_key(
                {k: v for k, v in route.items() if k not in ROUTE_KEYS}) == credential_key(body)), None)
            if same is not None:
                if shared:
                    same['scope'] = 'shared-account'
                elif project not in same.get('serves', []):
                    same.setdefault('serves', []).append(project)
                    if len(same['serves']) > 1:
                        same['scope'] = 'shared-account'
                if not shared and body.get('auth') != route_auth(same, (same.get('serves') or [project])[0]):
                    same.setdefault('auth', {}).setdefault('byProject', {})[project] = body.get('auth')
                continue
            taken = {route['id'] for route in entry['routes']}
            route_id = record['name'] if record['name'] not in taken else record['name'] + '@' + (
                'shared' if shared else project)
            route = {'id': route_id, **body,
                     'scope': 'shared-account' if shared else 'per-project',
                     'serves': [] if shared else [project]}
            if not route.get('capabilities'):
                verbs = ['read'] if record.get('readOnly') is True else ['read', 'write']
                route['capabilities'] = [provider + '.' + verb for verb in verbs]
            entry['routes'].append(route)
    for tree in out.values():
        for entry in tree['providers'].values():
            scopes = {route['scope'] for route in entry['routes']}
            entry['scope'] = 'shared-account' if scopes == {'shared-account'} else 'per-project'
            entry['capabilities'] = sorted({cap for route in entry['routes'] for cap in route['capabilities']})
            for route in entry['routes']:
                if route['scope'] == entry['scope']:
                    del route['scope']
    return out


def read_legacy(directory):
    manifests = {}
    for file in sorted(Path(directory).glob('*.json')):
        manifests[file.stem] = json.loads(file.read_text())
    return manifests


def write_registry(tree, roots, force=False):
    written = []
    by_boundary = dict(roots)
    for boundary, content in tree.items():
        if boundary not in by_boundary:
            raise RegistryError('no connector root configured for boundary ' + boundary +
                                ' (set connectorRoots.' + boundary + ' in identity.local.json)')
        root = by_boundary[boundary]
        if (root / INDEX).exists() and not force:
            raise RegistryError(str(root / INDEX) + ' exists; pass --force to rebuild it')
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        index = {key: value for key, value in content['index'].items() if key != 'projects'}
        write_json(root / INDEX, index)
        written.append(root / INDEX)
        for project, entry in sorted(content['index']['projects'].items()):
            write_json(root / 'projects' / (project + '.json'), entry)
            written.append(root / 'projects' / (project + '.json'))
        for provider, record in sorted(content['providers'].items()):
            write_json(root / (provider + '.json'), record)
            written.append(root / (provider + '.json'))
    return written


def check_migration(manifests, roots):
    """Problems (empty = pass): every legacy project field and connector field must be reachable."""
    problems = []
    by_boundary = {root['boundary']: root for root in roots}
    for stem, manifest in sorted(manifests.items()):
        root = by_boundary.get(manifest.get('boundary'))
        if root is None or not root['index']:
            problems.append(stem + ': no readable ' + str(manifest.get('boundary')) + ' root')
            continue
        if manifest.get('shared') is True:
            for value in manifest.get('match', []):
                if value not in root['index'].get('match', []):
                    problems.append(stem + ': shared match ' + value + ' missing from the root index')
        else:
            project = manifest.get('project') or stem
            entry = (root['index'].get('projects') or {}).get(project)
            if entry is None:
                problems.append(stem + ': project ' + project + ' missing')
                continue
            for key, value in manifest.items():
                if key in ('project', 'boundary', 'connectors', 'shared'):
                    continue
                if entry.get(key) != value:
                    problems.append(stem + ': project field ' + key + ' differs')
        routes = flat_routes(root)
        project = None if manifest.get('shared') is True else (manifest.get('project') or stem)
        for record in manifest.get('connectors', []):
            body = legacy_body(record)
            found = [route for route in routes if route['name'] == record['name']
                     and all(route.get(key) == value for key, value in body.items() if key != 'auth')
                     and route_auth(route, project) == body.get('auth')]
            if not found:
                problems.append(stem + ': connector ' + record['name'] + ' not reachable with every field')
                continue
            if manifest.get('shared') is not True:
                project = manifest.get('project') or stem
                if not any(route['scope'] == 'shared-account' or project in route['serves'] for route in found):
                    problems.append(stem + ': connector ' + record['name'] + ' does not serve ' + project)
    return problems


# ---------------------------------------------------------------------------- CLI

def print_json(value):
    print(json.dumps(value, indent=2, default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('roots')
    for name in ('manifest',):
        cmd = sub.add_parser(name)
        cmd.add_argument('--cwd', default=os.getcwd())
    cmd = sub.add_parser('project')
    cmd.add_argument('name')
    cmd = sub.add_parser('guard-facts')
    cmd.add_argument('name')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd = sub.add_parser('cli-profile')
    cmd.add_argument('cli')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd = sub.add_parser('resolve')
    cmd.add_argument('capability')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd.add_argument('--claude-account')
    cmd.add_argument('--json', action='store_true')
    cmd = sub.add_parser('record')
    cmd.add_argument('provider')
    cmd.add_argument('route')
    cmd.add_argument('outcome', choices=('ok', 'fail'))
    cmd.add_argument('--reason', default='')
    cmd.add_argument('--by', default='')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd = sub.add_parser('run')
    cmd.add_argument('provider')
    cmd.add_argument('route')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd.add_argument('child', nargs=argparse.REMAINDER, help='-- then the command to run')
    cmd = sub.add_parser('list')
    cmd.add_argument('--json', action='store_true')
    cmd = sub.add_parser('validate')
    cmd.add_argument('root')
    for name in ('migrate', 'check-migration'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--from', dest='source', required=True)
        if name == 'migrate':
            cmd.add_argument('--write', action='store_true')
            cmd.add_argument('--force', action='store_true')
            cmd.add_argument('--provider-map', default='{}')
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (RegistryError, OSError, ValueError) as exc:
        print('connector registry: ' + str(exc), file=sys.stderr)
        return 2


def run(args):
    if args.command == 'roots':
        for root in load_all():
            state = 'ok' if root['index'] else 'unreadable'
            print('\t'.join([root['boundary'], str(root['path']), state,
                             str(len(root['providers'])) + ' providers'] + root['errors']))
        return 0
    if args.command == 'manifest':
        path, manifest, boundary = select(args.cwd, strict=False)
        print_json({**manifest, 'sessionBoundary': boundary, 'index': str(path) if path else None})
        return 0
    if args.command == 'project':
        print_json(project_manifest(args.name))
        return 0
    if args.command == 'guard-facts':
        print_json(guard_facts(args.name, args.cwd))
        return 0
    if args.command == 'cli-profile':
        print(cli_profile(args.cli, args.cwd))
        return 0
    if args.command == 'resolve':
        routes, boundary, project = resolve(args.capability, args.cwd, claude_account=args.claude_account)
        if args.json:
            print_json({'boundary': boundary, 'project': project, 'routes': routes})
            return 0 if routes else 1
        if not routes:
            print('no ' + boundary + ' route declares ' + args.capability +
                  '; check the host tool list, then add the route (/sk:setup-connectors add)')
            return 1
        print(boundary + ' routes for ' + args.capability + (' (project ' + project + ')' if project else '') +
              ', try in this order; record each outcome:')
        for item in routes:
            last = item['lastSuccess'] or {}
            fail = item['lastFailure'] or {}
            notes = [item['state']]
            if last:
                notes.append('ok ' + last.get('at', '')[:10])
            if fail:
                notes.append('failed ' + fail.get('at', '')[:10] + ': ' + fail.get('reason', ''))
            if not item['servesHere']:
                notes.append('declared for another project')
            if item['blocker']:
                notes.append('BLOCKED: ' + item['blocker'])
            secret = item['secret']
            if secret and secret['store'] == 'vault':
                pairs = vault_pairs(secret)
                notes.append('key in Supabase Vault ' + secret['project'] + ' as ' +
                             ', '.join(json.dumps(name) for name, _ in pairs) + ' via ' + secret['via'] +
                             '; load: connector_registry.py run ' + item['provider'] + ' ' + item['route'] +
                             ' -- <cmd reading ' + ' '.join('$' + env for _, env in pairs) + '>')
            elif secret:
                notes.append('key in ' + secret['path'] +
                             (' as ' + ', '.join(secret['var']) if secret['var'] else ''))
            print('%d. %s/%s  [%s %s]  %s' % (item['rank'], item['provider'], item['route'],
                                             item['kind'], item['name'], '; '.join(notes)))
        return 0
    if args.command == 'record':
        note = record(args.provider, args.route, args.outcome, args.cwd, reason=args.reason, by=args.by)
        print('recorded ' + args.outcome + ' for ' + args.provider + '/' + args.route + ' at ' + note['at'])
        return 0
    if args.command == 'run':
        child = args.child[1:] if args.child[:1] == ['--'] else args.child
        return run_with_key(args.provider, args.route, child, args.cwd)
    if args.command == 'validate':
        errors = validate_root(args.root)
        for error in errors:
            print('UNREADABLE ' + error)
        print(('PASS' if not errors else 'FAIL') + ': ' + str(args.root))
        return 1 if errors else 0
    if args.command == 'list':
        rows = []
        for root in load_all():
            for route in flat_routes(root):
                entry = root['health'].get(route['provider'] + '/' + route['route'], {})
                rows.append({'boundary': root['boundary'], 'provider': route['provider'],
                             'route': route['route'], 'name': route['name'], 'kind': route.get('kind'),
                             'capabilities': route['capabilities'], 'scope': route['scope'],
                             'serves': route['serves'], 'state': health_state(entry, now_utc())})
        if args.json:
            print_json(rows)
        else:
            for row in rows:
                print('\t'.join([row['boundary'], row['provider'] + '/' + row['route'], row['kind'] or '',
                                 ','.join(row['capabilities']), row['scope'],
                                 ','.join(row['serves']) or '*', row['state']]))
        return 0
    manifests = read_legacy(args.source)
    if args.command == 'check-migration':
        problems = check_migration(manifests, load_all())
        for problem in problems:
            print('MISSING ' + problem)
        print(('PASS' if not problems else 'FAIL') + ': ' + str(len(manifests)) + ' legacy manifests checked')
        return 1 if problems else 0
    tree = build_registry(manifests, json.loads(args.provider_map))
    for boundary, content in tree.items():
        print(boundary + ': ' + str(len(content['index']['projects'])) + ' projects, ' +
              ', '.join(provider + '(' + str(len(record['routes'])) + ')'
                        for provider, record in sorted(content['providers'].items())))
    if args.write:
        for path in write_registry(tree, configured_roots(), force=args.force):
            print('wrote ' + str(path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
