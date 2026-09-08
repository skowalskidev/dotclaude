#!/usr/bin/env python3
"""Launch Codex using the current canonical agent configuration, without copied settings."""
from agent_runtime import launch
import sys

if __name__ == '__main__':
    if sys.argv[1:] and sys.argv[1].split('=', 1)[0] in ('-p', '--print'):
        from codex_print import main
        sys.exit(main())
    launch()
