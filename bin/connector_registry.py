#!/usr/bin/env python3
"""connector_registry.py: the ONE loader for Simon's connector registry, plus the route resolver.

The registry is local data, never in ~/.claude. One root per boundary, declared in the identity
overlay (`connectorRoots` in identity.local.json), e.g. a work root under the work-projects folder
and a personal root under the personal-projects folder, plus an optional `common` root for
boundary-neutral, account-free tooling (a local container runtime's MCP gateway) that every session
of either boundary layers in. A common route holds no key, account or project list. Each root holds:

  index.json         {"boundary", "match": [...]}: the root itself and the repos its shared routes reach
  projects/<p>.json  {"match": [...], "ignoreProjectInstructions"?, "monitor"?, "monitoringOnly"?, "installedBuilds"?}: one file per project
  <provider>.json    {"provider", "capabilities", "scope", "routes": [route, ...], "repoFiles"?}: one file per provider
  health.json        route outcomes, written only by `record` (state, kept apart from the records)

A provider's optional `repoFiles` lists repo-relative globs holding the repo's own setup for it
(a compose file, an exported MCP profile, a committed .mcp.json). `resolve` reports each one found in
the current checkout (committed) and in the main checkout (local only), so the registry says HOW a
provider works and the repo says WHAT this repo needs.

A route is a connector record (the fields references/connectors-setup.md documents) plus `id`,
optional `capabilities`, `scope` (shared-account | per-project), `serves` (projects it is known to
serve) and optional `requires` ({"claudeAccount": <email or identity-overlay key>}).

A route's optional `quietWindow` ({"minutes": [start, end], "reason", "projects"?, "tools"?}) names
minutes of every hour, UTC, both inclusive, when the route must not be used: e.g. a project's own
monitor sweeps then and shares the provider's rate limit. `run` refuses with exit 75 inside it (or
sleeps it out with --wait), and hooks/work-resource-guard.sh denies the route's MCP tools through
`guard-facts`. `projects` limits it to sessions in those projects; `tools` to those MCP tools.
No window, no change.

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
  connector_registry.py run PROVIDER ROUTE [--cwd DIR] [--wait] -- CMD...   CMD with the route's key in its env;
                                                      exit 75 inside the route's quietWindow (--wait sleeps it out)
  connector_registry.py quiet-check MCP_TOOL [--cwd DIR]   exit 75 naming the resume minute while the MCP
                                                      tool's route is in its quietWindow, else exit 0
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
import time
import urllib.error
import urllib.request
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get('CLAUDE_HOME', str(Path.home() / '.claude')))
BOUNDARIES = ('work', 'personal')
COMMON = 'common'  # the boundary-neutral root: account-free routes every session layers in
ROOT_KINDS = BOUNDARIES + (COMMON,)
COMMON_FORBIDS = ('secret', 'requires', 'serves', 'cli')  # anything tied to an account or a project
SCOPES = ('shared-account', 'per-project')
ROUTE_KEYS = ('id', 'capabilities', 'scope', 'serves', 'requires')  # registry-only route fields
INDEX = 'index.json'
HEALTH = 'health.json'
COOLDOWN_HOURS = 24  # a failed route is skipped for this long unless every other route fails
VAR_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')  # a secret.var entry is a variable NAME, never a value
STORES = ('local', 'vault')  # where a route's key lives: a local key file, or a Supabase Vault pointer
VIA = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.@-]+$')  # provider/route of the route that reads the vault
VAULT_API = os.environ.get('CLAUDE_VAULT_API', 'https://api.supabase.com/v1/projects/')
QUIET_NOW_ENV = 'CLAUDE_QUIET_NOW'  # an ISO time standing in for now: tests and dry checks of a window
QUIET_EXIT = 75  # EX_TEMPFAIL: retry later, the same code bin/local-capacity.py uses for "wait and resume"
QUIET_KEYS = ('minutes', 'reason', 'projects', 'tools', '_comment')


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
        if boundary not in ROOT_KINDS or not value:
            continue
        roots.append((boundary, expand(value)))
    return roots


def in_session(root, boundary):
    """Whether a root's routes are usable in a session of BOUNDARY: its own root, or the common root."""
    return root['boundary'] in (boundary, COMMON)


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
                raise RegistryError('a project file holds match/ignoreProjectInstructions/monitor/monitoringOnly/installedBuilds only')
        except (OSError, ValueError) as exc:
            root['errors'].append(str(file) + ': ' + str(exc))
            continue
        if boundary == COMMON:
            root['errors'].append(str(file) + ': projects belong to a work or personal root, not common')
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
    validate_repo_files(record.get('repoFiles'))
    if boundary == COMMON and record.get('scope', 'shared-account') != 'shared-account':
        raise RegistryError('a common provider is shared-account: it reaches every repo of both boundaries')
    seen = set()
    for route in record.get('routes', []):
        if not route.get('id') or not route.get('name'):
            raise RegistryError('every route needs an "id" and a connector "name"')
        if route['id'] in seen:
            raise RegistryError('duplicate route id ' + route['id'])
        seen.add(route['id'])
        if route.get('boundary', boundary) != boundary:
            raise RegistryError('route ' + route['id'] + ' boundary differs from its root')
        if boundary == COMMON:
            held = [key for key in COMMON_FORBIDS if key in route]
            if held or route.get('scope', 'shared-account') != 'shared-account':
                raise RegistryError('common route ' + route['id'] + ' must be account-free and shared-account; '
                                    'move it to a work or personal root (holds ' + ', '.join(held or ['scope']) + ')')
            continue
        scope = route.get('scope', record.get('scope', 'per-project'))
        if scope not in SCOPES:
            raise RegistryError('route ' + route['id'] + ' has an unknown scope')
        if scope == 'per-project' and not route.get('serves'):
            raise RegistryError('per-project route ' + route['id'] + ' must list the projects it serves')
        validate_secret(route)
        validate_quiet_window(route)
    order = record.get('storeOrder', list(STORES))
    if not isinstance(order, list) or sorted(order) != sorted(STORES):
        raise RegistryError('storeOrder must list ' + ' and '.join(STORES) + ' once each')


def validate_repo_files(value):
    """`repoFiles`: repo-relative globs, never absolute and never leaving the repo."""
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RegistryError('repoFiles must be a list of repo-relative globs')
    for item in value:
        if item.startswith(('/', '~')) or '..' in Path(item).parts:
            raise RegistryError('repoFiles entry ' + item + ' must stay inside the repo')


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


def validate_quiet_window(route):
    """`quietWindow` is {minutes: [start, end] (0-59, UTC, both inclusive; end < start wraps the hour),
    reason?, projects?, tools?}; it never covers the whole hour."""
    if 'quietWindow' not in route:
        return
    window = route['quietWindow']
    where = 'route ' + route['id'] + ' quietWindow'
    if not isinstance(window, dict):
        raise RegistryError(where + ' must be an object')
    unknown = sorted(set(window) - set(QUIET_KEYS))
    if unknown:
        raise RegistryError(where + ' has unknown keys: ' + ', '.join(unknown))
    minutes = window.get('minutes')
    if (not isinstance(minutes, list) or len(minutes) != 2
            or not all(type(m) is int and 0 <= m <= 59 for m in minutes)):
        raise RegistryError(where + '.minutes must be [start, end]: minutes of the hour 0-59, UTC, both inclusive')
    if (minutes[1] + 1) % 60 == minutes[0]:
        raise RegistryError(where + ' covers the whole hour, so the route could never run')
    if not isinstance(window.get('reason', ''), str):
        raise RegistryError(where + '.reason must be text')
    for key in ('projects', 'tools'):
        values = window.get(key)
        if values is not None and not (isinstance(values, list) and values
                                       and all(isinstance(v, str) and v.strip() for v in values)):
            raise RegistryError(where + '.' + key + ' must be a non-empty list of names')


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
    if boundary not in ROOT_KINDS:
        return [str(path / INDEX) + ': boundary must be one of ' + ', '.join(ROOT_KINDS)]
    try:
        root = load_root(boundary, path)
    except RegistryError as exc:
        return [str(exc)]
    errors = list(root['errors'])
    others = [item for item in load_all() if item['boundary'] != boundary and item['path'] != path]
    errors += name_clashes([root] + others, only=root)
    for provider, record in root['providers'].items():
        for route in record.get('routes', []):
            secret = secret_location(route)
            if secret and secret['store'] == 'vault' and vault_reader(root, secret) is None:
                errors.append(provider + '/' + route['id'] + ': vault pointer via ' + secret['via'] +
                              ' names no local-key route in this root')
    return errors


def load_all(identity=None):
    roots = [load_root(boundary, path) for boundary, path in configured_roots(identity)]
    for root in roots:
        root['errors'] += name_clashes(roots, only=root)
    return roots


def name_clashes(roots, only=None):
    """A common connector name that a work or personal root also declares: the guard could not
    tell which policy applies, so the clash makes the common root unreadable."""
    common = [root for root in roots if root['boundary'] == COMMON]
    if not common or (only is not None and only['boundary'] != COMMON):
        return []
    bound = {route['name'] for root in roots if root['boundary'] in BOUNDARIES for route in flat_routes(root)}
    errors = []
    for root in common if only is None else [only]:
        for route in flat_routes(root):
            if route['name'] in bound:
                errors.append(str(root['path']) + ': common connector name ' + route['name'] +
                              ' is also declared in a work or personal root; rename one')
    return errors


def flat_routes(root):
    """Every route of a root as a connector record, with provider, boundary and scope filled in."""
    out = []
    for provider, record in root['providers'].items():
        for order, route in enumerate(record.get('routes', [])):
            item = {key: value for key, value in route.items() if key not in ('boundary',)}
            item['provider'] = provider
            item['route'] = route['id']
            item['boundary'] = root['boundary']
            default = 'shared-account' if root['boundary'] == COMMON else 'per-project'
            item['scope'] = route.get('scope', record.get('scope', default))
            item['capabilities'] = list(route.get('capabilities') or record.get('capabilities') or [provider])
            item['serves'] = list(route.get('serves', []))
            item['_order'] = order
            item['_store'] = store_rank(route, record)
            item['_repoFiles'] = list(record.get('repoFiles') or [])
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
    for root in sorted(roots, key=lambda item: item['boundary'] == COMMON):  # common layers last
        if not root['index'] or not in_session(root, boundary):
            continue
        hits = any(value and value in remote + where for value in root['index'].get('match', []))
        if not (hits or root is project_root or root['boundary'] == COMMON):
            continue
        layered = [route for route in flat_routes(root) if provisioned_for(route, project)]
        if not layered:
            continue
        shared_from.append(str(root['path']))
        for route in layered:
            if route['name'] not in names:
                names.add(route['name'])
                view = connector_view(route, project)
                if root['boundary'] == COMMON:  # consumers see it as this session's route
                    view.update(boundary=boundary, layer=COMMON)
                connectors.append(view)
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
    found = set()
    for root in roots:
        if any(route['name'] == name for route in flat_routes(root)):
            found.update(BOUNDARIES if root['boundary'] == COMMON else (root['boundary'],))
    return sorted(found)


def guard_facts(name, cwd, remote=None, roots=None, identity=None, tool=None, at=None):
    """What the boundary guard needs for one connector name: boundaries + this repo's write policy,
    plus `quiet`, the deny message while TOOL (mcp__<name>__<tool>) is inside its route's quietWindow."""
    roots = load_all() if roots is None else roots
    facts = {'boundaries': name_boundaries(name, roots), 'readOnly': None, 'gated': None, 'quiet': ''}
    if tool:
        facts['quiet'] = mcp_quiet('mcp__' + name + '__' + tool, cwd, remote=remote, roots=roots,
                                   identity=identity, at=at)
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        return facts
    record = next((item for item in manifest.get('connectors', []) if item['name'] == name), None)
    if record is None:  # a same-boundary route for another project still carries its write policy
        record = next((connector_view(route) for root in roots if in_session(root, boundary)
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


def git_out(cwd, *args):
    result = subprocess.run(['git', '-C', str(cwd)] + list(args), capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def repo_files(patterns, cwd):
    """The repo's own setup files for a provider: [{path, where}] with where `committed` (tracked in
    this checkout), `local` (present here, untracked) or `main checkout` (untracked, only in the main
    checkout, the home of gitignored per-machine files a fresh worktree lacks)."""
    if not patterns:
        return []
    top = git_out(cwd, 'rev-parse', '--show-toplevel')
    if not top:
        return []
    common = git_out(cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    main = str(Path(common).parent) if common else top
    tracked = set(git_out(top, 'ls-files', '--', *patterns).splitlines())
    out, seen = [], set()
    for base, where in ((top, None), (main, 'main checkout')):
        if where and Path(main).resolve() == Path(top).resolve():
            continue
        for pattern in patterns:
            for file in sorted(Path(base).glob(pattern)):
                rel = str(file.relative_to(base))
                if rel in seen or not file.is_file():
                    continue
                if where and rel in tracked:
                    continue
                seen.add(rel)
                out.append({'path': str(file), 'where': where or ('committed' if rel in tracked else 'local')})
    return out


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
    out, found = [], {}
    for root in roots:
        if not in_session(root, boundary):
            continue
        for route in flat_routes(root):
            if not capability_matches(capability, route):
                continue
            if route['provider'] not in found:
                found[route['provider']] = repo_files(route['_repoFiles'], cwd)
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
                'secret': secret, 'quietWindow': route.get('quietWindow'),
                'root': str(root['path']), 'layer': COMMON if root['boundary'] == COMMON else boundary,
                'repoFiles': found[route['provider']],
                '_key': (bool(blocker), state == 'open', not serves_here, route['_store'],
                         0 if state == 'ok' else 1, route['_order'],
                         -(last_ok.timestamp() if last_ok else 0), route['provider']),
            })
    out.sort(key=lambda item: item['_key'])
    for rank, item in enumerate(out, 1):
        item['rank'] = rank
        del item['_key']
    return out, boundary, project


# ---------------------------------------------------------------------------- quiet windows

class QuietWindow(RegistryError):
    """A route's quietWindow is in effect; `resume` is the UTC time it ends."""

    def __init__(self, message, resume):
        super().__init__(message)
        self.resume = resume


def quiet_now():
    """Now, UTC, or the CLAUDE_QUIET_NOW stand-in (tests and dry checks)."""
    raw = os.environ.get(QUIET_NOW_ENV, '').strip()
    if raw:
        stamp = parse_time(raw)
        if stamp is None:
            raise RegistryError(QUIET_NOW_ENV + ' must be an ISO time, e.g. 2026-11-20T21:25:00Z')
        return stamp.astimezone(datetime.timezone.utc)
    return now_utc()


def window_label(window):
    start, end = window['minutes']
    return ':%02d-:%02d UTC' % (start, end)


def quiet_resume(window, at, project=None, tool=None):
    """The UTC time WINDOW ends when AT falls inside it and it applies to PROJECT and TOOL, else None."""
    if not window:
        return None
    if window.get('projects') and project not in window['projects']:
        return None
    if tool is not None and window.get('tools') and tool not in window['tools']:
        return None
    start, end = window['minutes']
    minute = at.minute
    inside = start <= minute <= end if start <= end else (minute >= start or minute <= end)
    if not inside:
        return None
    ahead = (end - minute) % 60 + 1
    return at.replace(second=0, microsecond=0) + datetime.timedelta(minutes=ahead)


def quiet_message(label, window, resume, at, hint='connector_registry.py run --wait sleeps it out.'):
    wait = max(1, int(round((resume - at).total_seconds() / 60.0)))
    reason = window.get('reason') or 'declared in the connector registry'
    return ('%s is in its quiet window %s (%s). Wait until :%02d UTC (about %d min), then run it; '
            'nothing ran. %s' % (label, window_label(window), reason, resume.minute, wait, hint))


def route_windows(root, route):
    """[(label, window)] a run of ROUTE honours: its own and, for a vault pointer, its reader's."""
    out = [(route.get('_label') or route['id'], route.get('quietWindow'))]
    secret = secret_location(route)
    if secret and secret['store'] == 'vault':
        reader = vault_reader(root, secret)
        if reader is not None:
            out.append((secret['via'] + ' (its vault reader)', reader.get('quietWindow')))
    return [(label, window) for label, window in out if window]


def quiet_block(windows, at, project=None):
    """(message, resume) for the first window in effect at AT, else None."""
    for label, window in windows:
        resume = quiet_resume(window, at, project)
        if resume is not None:
            return quiet_message(label, window, resume, at), resume
    return None


def quiet_wait_until(windows, at, project=None):
    """The time every window has ended, following back-to-back windows on a virtual clock."""
    for _ in range(len(windows) + 1):
        hit = quiet_block(windows, at, project)
        if hit is None:
            return at
        at = hit[1]
    return at


def mcp_quiet(tool_name, cwd, remote=None, roots=None, identity=None, at=None):
    """The deny message for an mcp__<server>__<tool> call while its route's window is in effect, else ''.

    The route is this project's connector named <server>, else a same-boundary route of that name
    (as guard_facts finds the write policy)."""
    if not tool_name.startswith('mcp__') or '__' not in tool_name[5:]:
        return ''
    server, tool = tool_name[5:].split('__', 1)
    roots = load_all(identity) if roots is None else roots
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
    except RegistryError:
        return ''
    project = manifest.get('project')
    record = next((item for item in manifest.get('connectors', []) if item['name'] == server), None)
    if record is None:
        record = next((connector_view(route) for root in roots if in_session(root, boundary)
                       for route in flat_routes(root) if route['name'] == server), None)
    window = (record or {}).get('quietWindow')
    at = at or quiet_now()
    resume = quiet_resume(window, at, project, tool)
    if resume is None:
        return ''
    return quiet_message(tool_name + ' (route ' + record['provider'] + '/' + record['route'] + ')',
                         window, resume, at, hint='Do other work meanwhile; never reach the same data another way.')


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


def locate(provider, route_id, cwd, remote=None, identity=None):
    """(root, route record, session project) of PROVIDER/ROUTE_ID in the session boundary for CWD."""
    identity = read_identity() if identity is None else identity
    roots = load_all(identity)
    remote = origin(cwd) if remote is None else remote
    project = None
    try:
        _, manifest, boundary = select(cwd, remote=remote, identity=identity, roots=roots, strict=False)
        project = manifest.get('project')
    except RegistryError:
        boundary = session_boundary(remote, identity)
    root = next((item for item in roots if in_session(item, boundary) and provider in item['providers']), None)
    if root is None:
        raise RegistryError('no ' + boundary + ' provider named ' + provider)
    route = next((item for item in root['providers'][provider].get('routes', []) if item['id'] == route_id), None)
    if route is None:
        raise RegistryError('provider ' + provider + ' has no route ' + route_id + ' in the ' + boundary +
                            ' boundary resolved from ' + str(cwd) + '; run from the project checkout or pass --cwd')
    return root, {**route, '_label': provider + '/' + route_id}, project


def route_env(provider, route_id, cwd, remote=None, identity=None, opener=None, located=None):
    """{variable: value} a route's consumer needs, from its key file or its vault pointer."""
    root, route, _ = located or locate(provider, route_id, cwd, remote=remote, identity=identity)
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


def run_with_key(provider, route_id, command, cwd, opener=None, wait=False, sleep=None):
    """Run COMMAND with the route's key in its environment; return its exit code. Prints no value.

    Inside the route's quietWindow (or its vault reader's) it raises QuietWindow before any key is
    read; with WAIT it sleeps until every window has ended, then runs."""
    if not command:
        raise RegistryError('run needs a command after --')
    located = locate(provider, route_id, cwd)
    root, route, project = located
    windows = route_windows(root, route)
    at = quiet_now()
    hit = quiet_block(windows, at, project)
    if hit is not None:
        if not wait:
            raise QuietWindow(*hit)
        until = quiet_wait_until(windows, at, project)
        print('connector registry: ' + hit[0].split(' Wait until')[0] + ' Waiting until :%02d UTC.' % until.minute,
              file=sys.stderr)
        (sleep or time.sleep)(max(0.0, (until - at).total_seconds()))
    env = {**os.environ, **route_env(provider, route_id, cwd, opener=opener, located=located)}
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
    root = next((item for item in roots if in_session(item, boundary)
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
    cmd.add_argument('--tool', default='', help='the MCP tool (after mcp__<name>__) to check for a quiet window')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd = sub.add_parser('quiet-check')
    cmd.add_argument('tool', help='mcp__<server>__<tool>')
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
    cmd.add_argument('--wait', action='store_true', help='inside a quiet window, sleep until it ends, then run')
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
    except QuietWindow as exc:
        print('connector registry: ' + str(exc), file=sys.stderr)
        return QUIET_EXIT
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
        print_json(guard_facts(args.name, args.cwd, tool=args.tool or None))
        return 0
    if args.command == 'quiet-check':
        message = mcp_quiet(args.tool, args.cwd)
        if message:
            print(message)
            return QUIET_EXIT
        print('clear: ' + args.tool + ' has no quiet window in effect')
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
            if item['quietWindow']:
                notes.append('quiet window ' + window_label(item['quietWindow']) +
                             ': run refuses then (exit 75), --wait sleeps it out')
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
            if item['layer'] == COMMON:
                notes.append('common layer (account-free, both boundaries)')
            print('%d. %s/%s  [%s %s]  %s' % (item['rank'], item['provider'], item['route'],
                                             item['kind'], item['name'], '; '.join(notes)))
        shown = set()
        for item in routes:
            if item['provider'] in shown or not item['repoFiles']:
                continue
            shown.add(item['provider'])
            print('repo setup for ' + item['provider'] + ' (read before using it here): ' +
                  '; '.join(entry['path'] + ' (' + entry['where'] + ')' for entry in item['repoFiles']))
        return 0
    if args.command == 'record':
        note = record(args.provider, args.route, args.outcome, args.cwd, reason=args.reason, by=args.by)
        print('recorded ' + args.outcome + ' for ' + args.provider + '/' + args.route + ' at ' + note['at'])
        return 0
    if args.command == 'run':
        child = args.child[1:] if args.child[:1] == ['--'] else args.child
        return run_with_key(args.provider, args.route, child, args.cwd, wait=args.wait)
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
