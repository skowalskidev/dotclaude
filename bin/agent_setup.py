#!/usr/bin/env python3
"""Inherit the current chat provider before launching a delegated workflow."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ASTRA_MODEL = 'gpt-6-astra'
OPENAI_WORKER_MODEL = 'gpt-5.6-sol'
CLAUDE_WORKER_MODEL = 'claude-sonnet-4-6'
CLAUDE_DESIGN_MODEL = 'claude-fable-5-1'
CLAUDE_ORCHESTRATOR_MODEL = 'claude-opus-4-8'
SETUPS = ('full-claude', 'full-astra', 'full-openai')


def model_provider(model):
    if not isinstance(model, str):
        return None
    if re.fullmatch(r'claude-[A-Za-z0-9.-]+', model) or model in ('opus', 'sonnet', 'haiku'):
        return 'anthropic'
    if re.fullmatch(r'(?:gpt-[A-Za-z0-9.-]+|o[1-9][A-Za-z0-9.-]*)', model):
        return 'openai'
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
    if setup == 'full-astra':
        return model == ASTRA_MODEL
    return matches_model(setup, model)


def matches_implementation_model(setup, model):
    if not matches_model(setup, model):
        return False
    if setup in ('full-openai', 'full-astra'):
        return model != ASTRA_MODEL
    return model not in (CLAUDE_ORCHESTRATOR_MODEL, CLAUDE_DESIGN_MODEL)


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
                 'full-astra' if orchestrator == ASTRA_MODEL else 'full-openai')
    if setup not in SETUPS:
        raise ValueError('Unknown agent_setup; derive it from the current chat provider.')
    inherited = os.environ.get('AGENT_SETUP')
    if inherited and inherited != setup:
        raise ValueError('The requested setup differs from this workflow\'s AGENT_SETUP; '
                         'reconcile the stale plan with the current chat before dispatching.')
    if not matches_orchestrator(setup, orchestrator):
        raise ValueError('orchestrator_model must match ' + setup +
                         '; reconcile the stale plan with the actual current chat.')
    model = spec.get('model', OPENAI_WORKER_MODEL if provider == 'openai' else CLAUDE_WORKER_MODEL)
    if not matches_implementation_model(setup, model):
        raise ValueError('Implementation worker must use a smaller ' +
                         ('OpenAI' if provider == 'openai' else 'Claude') +
                         ' model under ' + setup + '; top orchestration and design models do not implement.')
    if 'reviewer_model' in spec and not matches_model(setup, spec['reviewer_model']):
        raise ValueError('Reviewer model does not match ' + setup)
    design_model = spec.get('design_model', CLAUDE_DESIGN_MODEL)
    if setup in ('full-openai', 'full-astra') and design_model != CLAUDE_DESIGN_MODEL:
        raise ValueError('GPT-orchestrated design work must use Fable 5.1 (' + CLAUDE_DESIGN_MODEL + ').')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(resolve(json.loads(args.spec.read_text()))))
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print('agent setup: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
