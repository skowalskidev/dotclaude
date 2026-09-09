#!/usr/bin/env python3
"""Native Codex adapter. Read shared sources at use time; never store credentials or projections."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from agent_setup import require_provider

ROOT = Path(__file__).resolve().parent.parent
EVENTS = {'SessionStart', 'SessionEnd', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
          'Stop', 'PermissionRequest', 'PreCompact', 'PostCompact', 'SubagentStart',
          'SubagentStop', 'Interrupt'}


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text())


def origin(cwd):
    result = subprocess.run(['git', '-C', str(cwd), 'remote', 'get-url', 'origin'],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def project(cwd):
    """Match remote first; allow path matches only when there is no remote. Fail on ambiguity."""
    remote = origin(cwd)
    target = remote or str(Path(cwd).resolve())
    matches = []
    for path in sorted((ROOT / 'connectors').glob('*.json')):
        manifest = read_json(path)
        if any(value and value in target for value in manifest.get('match', [])):
            matches.append((path, manifest))
    if len(matches) > 1:
        raise ValueError('Multiple connector manifests match this project: ' +
                         ', '.join(path.name for path, _ in matches))
    identity = read_json(ROOT / 'identity.local.json')
    work_match = identity.get('workOrgMatch', '')
    boundary = 'work' if remote and work_match and work_match in remote else 'personal'
    path, manifest = matches[0] if matches else (None, {})
    if manifest.get('boundary', boundary) != boundary:
        raise ValueError('Connector manifest and identity.local.json disagree about the project boundary')
    return path, manifest, boundary


def subscription_home():
    return Path.home() / '.codex'


def subscription_policy(args):
    protected = {'forced_login_method', 'cli_auth_credentials_store', 'model_provider',
                 'model_providers', 'openai_base_url', 'chatgpt_base_url',
                 'preferred_auth_method', 'experimental_realtime_ws_base_url'}
    blocked_flags = {'--with-api-key', '--oss', '--local-provider', '--remote',
                     '--remote-auth-token-env'}
    remaining = iter(args)
    for arg in remaining:
        if arg == '--':
            break
        if arg.split('=', 1)[0] in blocked_flags:
            raise ValueError('Subscription-only Codex: API login and alternate providers are disabled, including reviews.')
        value = None
        if arg in ('-c', '--config'):
            value = next(remaining, '')
        elif arg.startswith('--config='):
            value = arg.split('=', 1)[1]
        elif arg.startswith('-c') and len(arg) > 2:
            value = arg[2:].lstrip('=')
        if value is not None and value.split('=', 1)[0].strip().split('.', 1)[0].strip('\"\'') in protected:
            raise ValueError('Subscription-only Codex: billing and provider overrides are disabled, including reviews.')
    settings = {'forced_login_method': 'chatgpt', 'cli_auth_credentials_store': 'file',
                'model_provider': 'openai', 'model_providers': {},
                'openai_base_url': 'https://chatgpt.com/backend-api/codex',
                'chatgpt_base_url': 'https://chatgpt.com/backend-api/'}
    return [value for key, setting in settings.items() for value in ('-c', key + '=' + toml(setting))]


def subscription_environment():
    environment = dict(os.environ, CODEX_HOME=str(subscription_home()))
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_API_BASE',
                 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT', 'CODEX_BEARER_TOKEN'):
        environment.pop(name, None)
    return environment


def check_subscription_auth(args):
    path = subscription_home() / 'auth.json'
    try:
        auth = read_json(path)
    except (ValueError, OSError):
        raise ValueError('Subscription-only Codex: cannot read saved login; run codex login with ChatGPT.') from None
    if not isinstance(auth, dict) or auth.get('OPENAI_API_KEY') or auth.get('auth_mode') not in (None, 'chatgpt'):
        raise ValueError('Subscription-only Codex: saved login is not ChatGPT; no API call was started.')
    if not auth.get('tokens') and not any(arg in ('login', 'logout', 'app-server', '--help', '-h', '--version', '-V') for arg in args):
        raise ValueError('Subscription-only Codex: sign in with codex login; no API fallback is allowed.')


def launch_cwd(args):
    cwd = Path(os.environ.get('CONDUCTOR_WORKSPACE_PATH') or os.getcwd())
    for index, arg in enumerate(args):
        if arg == '--':
            break
        if arg in ('-C', '--cd') and index + 1 < len(args):
            cwd = Path(args[index + 1]).expanduser()
        elif arg.startswith('--cd='):
            cwd = Path(arg.split('=', 1)[1]).expanduser()
    return cwd.resolve()


def absolute_cwd_args(args, cwd):
    """The launcher chdirs first; prevent Codex from applying a relative --cd a second time."""
    result = list(args)
    for index, arg in enumerate(result):
        if arg == '--':
            break
        if arg in ('-C', '--cd') and index + 1 < len(result):
            result[index + 1] = str(cwd)
        elif arg.startswith('--cd='):
            result[index] = '--cd=' + str(cwd)
    return result


def expand(value):
    if isinstance(value, str):
        return str(Path(value).expanduser()) if value.startswith('~/') else value
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


def codex_server(connector, boundary):
    source = expand(connector.get('mcp', {}))
    transport = source.pop('type', connector.get('kind', '').removeprefix('mcp-'))
    if transport not in ('stdio', 'http'):
        raise ValueError('Unsupported MCP transport for ' + connector['name'])
    if source.get('headers'):
        raise ValueError('Use environment-backed Codex HTTP headers; literal header values are not projected')
    allowed = {'command', 'args', 'env', 'cwd'} if transport == 'stdio' else {'url'}
    unknown = set(source) - allowed
    if unknown:
        raise ValueError('Unsupported MCP fields for ' + connector['name'] + ': ' + ', '.join(sorted(unknown)))
    required = 'command' if transport == 'stdio' else 'url'
    if not source.get(required):
        raise ValueError('Missing MCP ' + required + ' for ' + connector['name'])
    source['enabled'] = (not connector.get('enabledOnDemand', False)
                         and connector.get('boundary', boundary) == boundary)
    return source


def toml(value):
    """Encode the JSON-compatible subset used by CLI TOML overrides, never through a shell."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return '[' + ','.join(toml(item) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ','.join(toml(key) + '=' + toml(item) for key, item in value.items()) + '}'
    raise ValueError('Unsupported value in Codex configuration')


def native_hooks():
    """One native dispatcher per event; the real wiring remains in settings.json."""
    events = set(read_json(ROOT / 'settings.json').get('hooks', {})) | {'SessionStart', 'PreToolUse'}
    unsupported = events - EVENTS
    if unsupported:
        raise ValueError('Unsupported Codex hook events: ' + ', '.join(sorted(unsupported)))
    command = shlex.join([sys.executable, str(ROOT / 'bin/agent_runtime.py'), 'hook'])
    return {event: [{'hooks': [{'type': 'command', 'command': command + ' ' + event,
                               'timeout': 3 if event in ('SessionEnd', 'Interrupt') else 60,
                               'additionalContextLimit': 120000}]}]
            for event in sorted(events)}


def overrides(cwd):
    _, manifest, boundary = project(cwd)
    result = ['-c', 'hooks=' + toml(native_hooks())]
    for connector in manifest.get('connectors', []):
        if connector.get('kind') not in ('mcp-http', 'mcp-stdio'):
            continue
        server = codex_server(connector, boundary)
        result += ['-c', server_key(connector['name']) + '=' + toml(server)]
    return result, subscription_home()


def server_key(name):
    # Codex splits override paths on dots without decoding quoted key components.
    # Quotes become literal server-name characters; reject names that require quoted paths.
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('MCP server names must contain only letters, digits, underscores or hyphens')
    return 'mcp_servers.' + name


def retired_overrides(cwd, home):
    """Remember ownership names only, so deleting a manifest entry masks old native registrations."""
    _, manifest, _ = project(cwd)
    current = {item['name'] for item in manifest.get('connectors', [])
               if item.get('kind') in ('mcp-http', 'mcp-stdio')}
    directory = home / '.agent-runtime'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'managed-mcp-names.json'
    with (directory / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = set(read_json(path, []))
        names = sorted(previous | current)
        if names != sorted(previous):
            temporary = directory / 'managed-mcp-names.tmp'
            temporary.write_text(json.dumps(names) + '\n')
            temporary.replace(path)
    result = []
    for name in sorted(previous - current):
        # A complete disabled descriptor also works when no underlying config entry remains.
        result += ['-c', server_key(name) + '=' + toml({'command': 'false', 'enabled': False})]
    return result


def executable():
    own = (ROOT / 'bin/codex-launch.py').resolve()
    explicit = os.environ.get('AGENT_CODEX_BIN')
    candidates = [explicit] if explicit else [str(Path(part) / 'codex') for part in os.get_exec_path()]
    if not explicit:
        directory = Path(os.environ.get('CONDUCTOR_AGENT_BINARIES_DIR') or
                         Path.home() / 'Library/Application Support/com.conductor.app/agent-binaries')
        bundled = [path for path in (directory / 'codex').glob('*/codex')
                   if re.fullmatch(r'\d+\.\d+\.\d+', path.parent.name)]
        bundled.sort(key=lambda path: tuple(int(part) for part in path.parent.name.split('.')),
                     reverse=True)
        candidates = [str(path) for path in bundled] + candidates
    for name in candidates:
        if name and Path(name).is_file() and os.access(name, os.X_OK) and Path(name).resolve() != own:
            return str(Path(name).resolve())
    raise ValueError('Codex executable not found; install Codex or set AGENT_CODEX_BIN to its executable')


def codex_inference(args):
    """Keep metadata/auth tools usable from either host; guard model-capable launches."""
    options_with_value = {'--cd', '-C', '--model', '-m', '--config', '-c', '--profile', '-p',
                          '--sandbox', '-s', '--ask-for-approval', '-a'}
    remaining = iter(args)
    for arg in remaining:
        if arg in options_with_value:
            next(remaining, None)
        elif arg in ('--help', '-h', '--version', '-V'):
            return False
        elif arg == '--':
            return True
        elif not arg.startswith('-'):
            return arg not in ('mcp', 'login', 'logout', 'features', 'completion')
    return True


def launch():
    try:
        args = sys.argv[1:]
        if codex_inference(args):
            require_provider('openai')
        cwd = launch_cwd(args)
        args = absolute_cwd_args(args, cwd)
        billing = subscription_policy(args)
        check_subscription_auth(args)
        config, home = overrides(cwd)
        manifest_path, _, boundary = project(cwd)
        env = dict(subscription_environment(), AGENT_MODEL_PROVIDER='openai', AGENT_CODEX_LAUNCH_CWD=str(cwd),
                   AGENT_CODEX_MANIFEST=str(manifest_path or ''), AGENT_CODEX_BOUNDARY=boundary)
        # Pass TOML as argv, never shell code. Explicit caller overrides retain native precedence.
        binary = executable()
        config += retired_overrides(cwd, home)
        os.chdir(cwd)
        os.execve(binary, [binary, *config, *billing, *args], env)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print('agent config: ' + str(error), file=sys.stderr)
        raise SystemExit(1)


def context(cwd):
    path, manifest, boundary = project(cwd)
    home = subscription_home()
    lines = ['Shared agent configuration: ' + str(ROOT),
             'Project boundary: ' + boundary, 'Expected Codex home: ' + str(home),
             'Model billing: ChatGPT subscription only, including workers and reviews; API fallback disabled.',
             'Connector manifest: ' + (str(path) if path else 'none matched')]
    for connector in manifest.get('connectors', []):
        name = connector['name']
        state = 'on-demand; disabled' if connector.get('enabledOnDemand') else 'declared; verify live tool/auth status'
        lines.append(name + ': ' + state)
        if connector.get('kind') == 'mcp-http' and 'oauth' in connector.get('auth', {}).get('how', '').lower():
            command = shlex.join([str(ROOT / 'bin/codex-launch.py'), 'mcp', 'login', name])
            lines.append('If OAuth is missing, authenticate from this workspace: ' + command)
    lines += ['Read the manifest and references/connectors-setup.md before reporting a capability unavailable.',
              'Rules below are read from their canonical files, not a generated copy.']
    for file in [ROOT / 'CLAUDE.md', *sorted((ROOT / 'rules').glob('*.md'))]:
        lines += ['\n--- ' + str(file) + ' ---', file.read_text()]
    return '\n'.join(lines)


def adapted_payloads(payload):
    tool = payload.get('tool_name', '')
    aliases = {'exec_command': 'Bash', 'spawn_agent': 'Agent',
               'request_user_input': 'AskUserQuestion'}
    result = dict(payload, tool_name=aliases.get(tool, tool))
    data = payload.get('tool_input', {})
    if tool == 'exec_command':
        result['tool_input'] = dict(data, command=data.get('cmd', data.get('command', '')))
    if tool == 'apply_patch':
        patch = data.get('command', data.get('patch', '')) if isinstance(data, dict) else data
        paths = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M)
        if not paths:
            raise ValueError('Cannot identify apply_patch targets for the shared edit guards')
        return [dict(result, tool_name='Edit', tool_input={'file_path': str(
            (Path(payload.get('cwd') or os.getcwd()) / path).resolve())}) for path in paths]
    return [result]


def hook(event, payload):
    cwd = Path(payload.get('cwd') or os.getcwd())
    manifest_path, _, boundary = project(cwd)
    expected = subscription_home()
    active = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    launch_manifest = os.environ.get('AGENT_CODEX_MANIFEST')
    if (active.resolve() != expected.resolve() or
            os.environ.get('AGENT_CODEX_BOUNDARY', boundary) != boundary or
            (launch_manifest is not None and launch_manifest != str(manifest_path or ''))):
        message = 'Codex project/profile mismatch. Restart through ~/.claude/bin/codex-launch.py in this workspace.'
        if event == 'PreToolUse':
            return {'hookSpecificOutput': {'hookEventName': event, 'permissionDecision': 'deny',
                                           'permissionDecisionReason': message}}, 0
        return {'continue': False, 'stopReason': message}, 0
    contexts = [context(cwd)] if event == 'SessionStart' else []
    rules = read_json(ROOT / 'settings.json').get('hooks', {}).get(event, [])
    for adapted in adapted_payloads(payload):
        for group in rules:
            matcher = group.get('matcher', '*')
            if event == 'SessionStart' and matcher not in ('', '*'):
                if not re.search(matcher, payload.get('source', 'startup')):
                    continue
            if event in ('PreToolUse', 'PostToolUse', 'PermissionRequest') and matcher not in ('', '*'):
                if not re.search(matcher, adapted.get('tool_name', '')):
                    continue
            for handler in group.get('hooks', []):
                if handler.get('type') != 'command':
                    raise ValueError('Only command hooks are supported by the shared Codex adapter')
                command = handler['command']
                # Claude's readiness cache and transcript analyzers describe Claude sessions only.
                # Native context above replaces its connector precheck. SessionEnd analyzers are
                # skipped until they accept Codex transcripts; never fabricate cross-host metrics.
                if 'session-connectors.sh' in command or (event == 'SessionEnd' and
                        any(name in command for name in ('retro-trigger-log.sh', 'config-metrics-log.sh'))):
                    continue
                completed = subprocess.run(command, shell=True, executable='/bin/bash',
                    input=json.dumps(adapted), text=True, capture_output=True, cwd=cwd,
                    timeout=min(handler.get('timeout', 30), 1) if event in ('SessionEnd', 'Interrupt')
                    else handler.get('timeout', 30))
                if completed.returncode:
                    return {'continue': False, 'stopReason': 'Shared hook blocked or failed: ' + command}, 2
                if not completed.stdout.strip():
                    continue
                try:
                    output = json.loads(completed.stdout)
                except json.JSONDecodeError:
                    contexts.append(completed.stdout.strip())
                    continue
                specific = output.get('hookSpecificOutput', {})
                if output.get('continue') is False or output.get('decision') == 'block' or specific.get('permissionDecision') in ('deny', 'ask'):
                    return output, 0
                for value in (specific.get('additionalContext'), output.get('systemMessage')):
                    if value:
                        contexts.append(value)
    if contexts:
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': '\n\n'.join(contexts)}}, 0
    return {}, 0


def install(home, replace=False):
    """Link instructions without losing earlier local files. Never touch authentication stores."""
    target = ROOT / 'dotfiles/codex-AGENTS.md'
    home.mkdir(parents=True, exist_ok=True)
    link = home / 'AGENTS.md'
    if link.is_symlink() and link.resolve() == target.resolve():
        return
    if link.exists() or link.is_symlink():
        if not replace:
            raise ValueError(str(link) + ' already exists; review it, then use install --replace to archive it')
        backup = home / 'AGENTS.md.before-shared-config'
        if backup.exists() or backup.is_symlink():
            raise ValueError('Backup already exists: ' + str(backup))
        link.rename(backup)
    link.symlink_to(target)


def configure_conductor():
    """Set only the supported executable key; leave model/provider preferences intact."""
    path = Path.home() / '.conductor/settings.toml'
    text = path.read_text() if path.exists() else ''
    entry = 'codex_executable_path = ' + toml(str(ROOT / 'bin/codex-launch.py')) + '\n'
    # User-level keys must precede the first table; never append them inside [models].
    first_table = re.search(r'^\s*\[', text, re.M)
    split = first_table.start() if first_table else len(text)
    top, rest = text[:split], text[split:]
    pattern = r'^[ \t]*(?:codex_executable_path|"codex_executable_path")[ \t]*=.*(?:\n|$)'
    if re.search(pattern, top, re.M):
        top = re.sub(pattern, lambda _: entry, top, flags=re.M)
    else:
        top = entry + top
    updated = top + rest
    if updated == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name('settings.toml.before-shared-config')
    if path.exists() and not backup.exists():
        backup.write_text(text)
        backup.chmod(0o600)
    temporary = path.with_name('.settings.agent-runtime.tmp')
    temporary.write_text(updated)
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('context', 'doctor'):
        sub.add_parser(action).add_argument('--cwd', default=os.getcwd())
    hooks = sub.add_parser('hook')
    hooks.add_argument('event', choices=sorted(EVENTS))
    setup = sub.add_parser('install')
    setup.add_argument('--replace', action='store_true')
    setup.add_argument('--conductor', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'install':
            install(subscription_home(), args.replace)
            if args.conductor:
                configure_conductor()
        elif args.action == 'context':
            print(context(args.cwd))
        elif args.action == 'doctor':
            path, manifest, boundary = project(args.cwd)
            print('Manifest:', path or 'none', '\nCodex home:', subscription_home())
            print('Model billing: ChatGPT subscription only; no API review exception')
            for conn in manifest.get('connectors', []):
                state = 'on-demand' if conn.get('enabledOnDemand') else 'manifest-driven; authentication unverified'
                print(conn['name'], conn['kind'], state, sep='\t')
        else:
            output, code = hook(args.event, json.load(sys.stdin))
            print(json.dumps(output))
            raise SystemExit(code)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        # Never dump config values or hook subprocess output: either can carry credentials.
        print('agent config: ' + str(error), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
