#!/usr/bin/env python3
"""Validate one explicit model setup before launching a delegated workflow."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ASTRA_MODEL = 'gpt-6-astra'
CLAUDE_WORKER_MODEL = 'claude-sonnet-4-6'
SETUPS = ('full-claude', 'full-astra')


def matches_model(setup, model):
    if not isinstance(model, str):
        return False
    if setup == 'full-astra':
        return model == ASTRA_MODEL
    return bool(re.fullmatch(r'claude-[A-Za-z0-9.-]+', model)) or model in ('opus', 'sonnet', 'haiku')


def resolve(spec):
    setup = spec.get('agent_setup')
    if setup not in SETUPS:
        raise ValueError('Ask Simon: Which setup, Full Claude or Full Astra? '
                         'Record agent_setup as full-claude or full-astra; there is no default.')
    inherited = os.environ.get('AGENT_SETUP')
    if inherited and inherited != setup:
        raise ValueError('The requested setup differs from this workflow\'s AGENT_SETUP; '
                         'return to the orchestrator instead of mixing setups.')
    orchestrator = spec.get('orchestrator_model')
    if not matches_model(setup, orchestrator):
        raise ValueError('orchestrator_model must match ' + setup +
                         '; switch the orchestrator session/model before dispatching.')
    model = spec.get('model', ASTRA_MODEL if setup == 'full-astra' else CLAUDE_WORKER_MODEL)
    if not matches_model(setup, model):
        raise ValueError('Worker model does not match ' + setup + '; no cross-model fallback is allowed.')
    if 'reviewer_model' in spec and not matches_model(setup, spec['reviewer_model']):
        raise ValueError('Reviewer model does not match ' + setup)
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
    return dict(spec, agent_setup=setup, model=model)


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
