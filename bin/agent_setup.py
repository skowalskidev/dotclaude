#!/usr/bin/env python3
"""Inherit the current chat provider before launching a delegated workflow.

Every delegated worker's model resolves to the current model of its TIER by a live check at
dispatch time (resolve_tier), never a pinned version or family name. Claude resolves by CLI alias;
OpenAI resolves by rank in the live Codex model cache. This is the one resolver both providers use.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

# Complexity mapping (the only place this is decided):
#   small  - mechanical, high-volume fan-out: one unambiguous rule, no judgement required.
#   mid    - substantive implementation edits: the default worker tier.
#   top    - orchestration and judgement only: never implements.
#   design - GPT-orchestrated design discovery, mockups and visual judgement; routed to Claude's
#            design tier regardless of which provider is orchestrating.
TIERS = ('top', 'design', 'mid', 'small')

# The ONLY model-ish names allowed in engine code: Claude's own CLI tier aliases, which Anthropic
# keeps pointed at the recommended current model per tier. No version is pinned here. OpenAI has no
# such alias, so its tiers resolve live from the ranked Codex model cache (see resolve_tier).
CLAUDE_TIER_ALIASES = {'top': 'opus', 'design': 'fable', 'mid': 'sonnet', 'small': 'haiku'}
SETUPS = ('full-claude', 'full-astra', 'full-openai')  # full-astra: OpenAI top-tier orchestrator
STALE_CACHE_DAYS = 7


def codex_home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def claude_catalog_dir():
    override = os.environ.get('CLAUDE_MODEL_CATALOG_DIR')
    return Path(override) if override else Path.home() / '.claude/cache/model-catalog'


def model_provider(model):
    if not isinstance(model, str):
        return None
    if re.fullmatch(r'claude-[A-Za-z0-9.-]+', model) or model in CLAUDE_TIER_ALIASES.values():
        return 'anthropic'
    if re.fullmatch(r'(?:gpt-[A-Za-z0-9.-]+|o[1-9][A-Za-z0-9.-]*)', model):
        return 'openai'
    return None


def openai_cache():
    """Read and validate the Codex-maintained, account-scoped model cache."""
    path = codex_home() / 'models_cache.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('No OpenAI model cache at ' + str(path) +
                         '; launch Codex once to refresh it.') from None
    if not isinstance(data, dict) or not isinstance(data.get('models'), list):
        raise ValueError('OpenAI model cache at ' + str(path) +
                         ' is malformed; launch Codex once to refresh it.')
    return data


def openai_ranked_models():
    """Listed (visibility == 'list'), non-retiring (upgrade falsy) OpenAI models, sorted by
    priority (lower = earlier in Codex's own picker)."""
    models = openai_cache()['models']
    listed = [m for m in models
             if isinstance(m, dict) and m.get('visibility') == 'list' and not m.get('upgrade')]
    listed.sort(key=lambda m: m.get('priority', 0))
    ranked = [m['slug'] for m in listed if m.get('slug')]
    if not ranked:
        raise ValueError('No listed OpenAI models in the Codex model cache; launch Codex once to refresh it.')
    return ranked


def claude_catalog():
    """The newest Claude model-catalog cache file's models, or None if none is readable."""
    directory = claude_catalog_dir()
    try:
        candidates = [p for p in directory.glob('*.json')
                     if p.name.endswith('-cc.json') and 'headless-failed' not in p.name]
    except OSError:
        return None
    if not candidates:
        return None
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    models = raw.get('catalog', {}).get('config', {}).get('models')
    if not isinstance(models, list):
        return None
    return {'path': path, 'fetchedAt': raw.get('fetchedAt'), 'models': models}


def resolve_tier(provider, tier):
    """The one resolver every default-model decision calls. Claude: the CLI tier alias. OpenAI:
    the model at that rank in the live, priority-sorted Codex cache, clamped to the last available
    rank when fewer models are listed."""
    if tier not in TIERS:
        raise ValueError('Unknown tier: ' + str(tier))
    if provider == 'anthropic':
        return CLAUDE_TIER_ALIASES[tier]
    if provider == 'openai':
        if tier == 'design':
            raise ValueError('OpenAI has no design tier; GPT-orchestrated design routes to the Claude Fable tier.')
        rank = {'top': 1, 'mid': 2, 'small': 3}[tier]
        ranked = openai_ranked_models()
        return ranked[min(rank, len(ranked)) - 1]
    raise ValueError('Unknown provider: ' + str(provider))


def tier_of(model):
    """The tier `model` currently resolves to, or None if it matches none.

    Anthropic: a bare alias matches directly; a full id is matched through the Claude catalog's
    short_name for that id, lowercased; failing that, through the id containing one of
    CLAUDE_TIER_ALIASES' own values as a fallback family word (never a separate hardcoded list).
    OpenAI: whichever tier resolve_tier currently resolves to this model's rank.
    """
    provider = model_provider(model)
    if provider == 'anthropic':
        reverse = {alias: tier for tier, alias in CLAUDE_TIER_ALIASES.items()}
        if model in reverse:
            return reverse[model]
        catalog = claude_catalog()
        if catalog:
            for entry in catalog['models']:
                if isinstance(entry, dict) and entry.get('id') == model:
                    short = (entry.get('short_name') or '').lower()
                    if short in reverse:
                        return reverse[short]
        for alias, tier in reverse.items():
            if alias in model:
                return tier
        return None
    if provider == 'openai':
        try:
            ranked = openai_ranked_models()
        except ValueError:
            return None
        if model not in ranked:
            return None
        for tier in ('top', 'mid', 'small'):
            if resolve_tier('openai', tier) == model:
                return tier
        return None
    return None


def current_provider():
    """Use native process evidence, never a saved plan, to constrain launches."""
    providers = set()
    if os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID'):
        providers.add('openai')
    if os.environ.get('CLAUDECODE') == '1':
        providers.add('anthropic')
    inherited = os.environ.get('AGENT_MODEL_PROVIDER')
    if inherited:
        if inherited not in ('openai', 'anthropic'):
            raise ValueError('Unknown inherited AGENT_MODEL_PROVIDER.')
        providers.add(inherited)
    if len(providers) > 1:
        # Under an explicit cross-provider override, a worker launched from the other host legitimately
        # carries both signals (its own AGENT_MODEL_PROVIDER plus the launching chat's native marker).
        # The inherited AGENT_MODEL_PROVIDER is then authoritative; without the flag this still fails closed.
        if inherited and os.environ.get('AGENT_ALLOW_CROSS_PROVIDER') == '1':
            return inherited
        raise ValueError('Conflicting native provider signals; start the matching chat before delegation.')
    return next(iter(providers), None)


def require_provider(provider):
    active = current_provider()
    if active and active != provider:
        if os.environ.get('AGENT_ALLOW_CROSS_PROVIDER') == '1':
            print('agent setup: OVERRIDE cross-provider worker allowed by explicit '
                  'AGENT_ALLOW_CROSS_PROVIDER=1 (chat=' + active + ', worker=' + provider +
                  '); subscription-billing guard is unaffected.', file=sys.stderr)
            return
        raise ValueError('Current chat provider is ' + active + '; no cross-provider worker or reviewer is allowed.')


def matches_model(setup, model):
    return model_provider(model) == ('openai' if setup in ('full-openai', 'full-astra') else 'anthropic')


def matches_orchestrator(setup, model):
    if not matches_model(setup, model):
        return False
    if setup == 'full-astra':  # OpenAI top-tier orchestrator
        return tier_of(model) == 'top'
    return True


def matches_implementation_model(setup, model):
    return matches_model(setup, model) and tier_of(model) in ('mid', 'small')


def is_design_route(item):
    return item.get('model_route') == 'design'


def resolve(spec):
    orchestrator = spec.get('orchestrator_model')
    provider = model_provider(orchestrator)
    if not provider:
        raise ValueError('Record the actual orchestrator_model from the current chat before dispatching.')
    require_provider(provider)
    setup = spec.get('agent_setup')
    if setup is None:
        setup = ('full-claude' if provider == 'anthropic' else
                 'full-astra' if tier_of(orchestrator) == 'top' else 'full-openai')
    if setup not in SETUPS:
        raise ValueError('Unknown agent_setup; derive it from the current chat provider.')
    inherited = os.environ.get('AGENT_SETUP')
    if inherited and inherited != setup:
        raise ValueError('The requested setup differs from this workflow\'s AGENT_SETUP; '
                         'reconcile the stale plan with the current chat before dispatching.')
    if not matches_orchestrator(setup, orchestrator):
        raise ValueError('orchestrator_model must match ' + setup +
                         '; reconcile the stale plan with the actual current chat.')
    model = spec.get('model') or resolve_tier(provider, 'mid')
    if not matches_implementation_model(setup, model):
        raise ValueError('Implementation worker must use a smaller ' +
                         ('OpenAI' if provider == 'openai' else 'Claude') +
                         ' model under ' + setup + '; top orchestration and design models do not implement.')
    if 'reviewer_model' in spec and not matches_model(setup, spec['reviewer_model']):
        raise ValueError('Reviewer model does not match ' + setup)
    design_model = spec.get('design_model', resolve_tier('anthropic', 'design'))
    if setup in ('full-openai', 'full-astra') and tier_of(design_model) != 'design':
        raise ValueError('GPT-orchestrated design work must use the Claude Fable tier.')
    if setup not in ('full-openai', 'full-astra') and 'design_model' in spec:
        raise ValueError('design_model only applies to a GPT-orchestrated workflow.')
    slices = spec.get('slices')
    if not isinstance(slices, list) or not slices:
        raise ValueError('Declare at least one slice before dispatching.')
    names = set()
    for item in slices:
        name = item.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name in names:
            raise ValueError('Slice names must be unique letters, digits, underscores or hyphens.')
        names.add(name)
        if 'model' in item or 'agent_setup' in item:
            raise ValueError('Set model and agent_setup once at the workflow level, not per slice.')
        route = item.get('model_route', 'general')
        if route not in ('general', 'design'):
            raise ValueError('Slice model_route must be general or design.')
        if is_design_route(item) and setup not in ('full-openai', 'full-astra'):
            raise ValueError('model_route design only applies to a GPT-orchestrated workflow.')
    resolved = dict(spec, agent_setup=setup, model=model, model_provider=provider)
    if setup in ('full-openai', 'full-astra'):
        resolved['design_model'] = design_model
    return resolved


def _parse_iso_timestamp(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()


def _maybe_update_codex_config(home):
    """If CODEX_HOME/config.toml's TOP-LEVEL `model = "..."` names an OpenAI model that is not in
    openai_ranked_models(), rewrite just that value to the resolved mid tier, in place, preserving
    every other byte, comment and section and the file's mode. Leaves the file alone when there is
    no top-level model line, or when the current value is still listed. Returns (old, new) or None.
    """
    config_path = home / 'config.toml'
    if not config_path.is_file():
        return None
    ranked = openai_ranked_models()  # may raise ValueError; caller decides what that means
    text = config_path.read_text()
    section = re.search(r'^[ \t]*\[', text, re.M)
    top = text[:section.start()] if section else text
    rest = text[section.start():] if section else ''
    found = re.search(r'(?m)^([ \t]*model[ \t]*=[ \t]*")((?:\\.|[^"\\])*)("[ \t]*(?:#.*)?)$', top)
    if not found:
        return None
    current = re.sub(r'\\(.)', r'\1', found.group(2))
    if current in ranked:
        return None
    new_model = resolve_tier('openai', 'mid')
    escaped = new_model.replace('\\', '\\\\').replace('"', '\\"')
    new_top = top[:found.start()] + found.group(1) + escaped + found.group(3) + top[found.end():]
    mode = config_path.stat().st_mode
    config_path.write_text(new_top + rest)
    os.chmod(config_path, stat.S_IMODE(mode))
    return current, new_model


def check_models():
    """Warn about stale model caches, pinned aliases and catalog tier drift; auto-repair the native
    Codex default model when it names an unlisted/retired one. Never raises."""
    warnings = []
    now = time.time()
    home = codex_home()

    codex_cache_path = home / 'models_cache.json'
    try:
        codex_data = json.loads(codex_cache_path.read_text())
        age_days = (now - _parse_iso_timestamp(codex_data.get('fetched_at'))) / 86400
        if age_days > STALE_CACHE_DAYS:
            warnings.append('OpenAI model cache is %.1f days old; launch Codex once to refresh it.' % age_days)
    except (OSError, ValueError, TypeError, AttributeError):
        warnings.append('OpenAI model cache is missing or unreadable at ' + str(codex_cache_path) +
                        '; launch Codex once to refresh it.')

    catalog = claude_catalog()
    if catalog is None:
        warnings.append('No Claude model catalog cache found under ' + str(claude_catalog_dir()) +
                        '; launch Claude once to refresh it.')
    else:
        fetched_ms = catalog.get('fetchedAt')
        if isinstance(fetched_ms, (int, float)):
            age_days = (now - fetched_ms / 1000) / 86400
            if age_days > STALE_CACHE_DAYS:
                warnings.append('Claude model catalog cache is %.1f days old; launch Claude once to refresh it.' % age_days)
        main_short_names = {(m.get('short_name') or '').lower() for m in catalog['models']
                            if isinstance(m, dict) and m.get('section') == 'main' and m.get('short_name')}
        alias_values = set(CLAUDE_TIER_ALIASES.values())
        for name in sorted(main_short_names - alias_values):
            warnings.append('Claude catalog main section lists "' + name +
                            '", which is not a known tier alias; a new tier may exist.')
        for alias in sorted(alias_values - main_short_names):
            warnings.append('Claude catalog main section has no model for the "' + alias +
                            '" alias; that tier may have been retired.')

    for alias in ('OPUS', 'SONNET', 'HAIKU', 'FABLE'):
        var = 'ANTHROPIC_DEFAULT_' + alias + '_MODEL'
        if os.environ.get(var):
            warnings.append(var + ' is set; it silently pins the ' + alias.lower() + ' alias.')

    try:
        update = _maybe_update_codex_config(home)
        if update:
            warnings.append('Codex config.toml top-level model updated: %s -> %s' % update)
    except ValueError:
        pass  # cache unreadable; nothing to validate the current value against, so leave it alone

    picks = ['anthropic top=%s mid=%s small=%s design=%s' % tuple(
        resolve_tier('anthropic', t) for t in ('top', 'mid', 'small', 'design'))]
    try:
        picks.append('openai top=%s mid=%s small=%s' % tuple(
            resolve_tier('openai', t) for t in ('top', 'mid', 'small')))
    except ValueError:
        warnings.append('OpenAI tiers unavailable: launch Codex once to refresh the model cache.')
    warnings.append('tiers: ' + '; '.join(picks))
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    args = parser.parse_args()
    try:
        lines = check_models()
    except Exception as error:  # check_models must never block a launch
        lines = ['model check failed unexpectedly: ' + str(error)]
    for line in lines:
        print('agent setup: ' + line, file=sys.stderr)
    try:
        print(json.dumps(resolve(json.loads(args.spec.read_text()))))
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print('agent setup: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
