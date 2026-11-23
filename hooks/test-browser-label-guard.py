#!/usr/bin/env python3
"""
Deny a chrome-devtools navigate_page that would load a document without the tab label.

references/browser-debugging.md § Tab labels and stale tabs: every test-browser tab Claude opens
carries a persistent label naming its task, persona and owner session. A label set once with
`document.title = ...` is lost when the app rewrites its title or the page reloads (a walk window
read just the app name beside three stale ones), so the label rides in navigate_page's `initScript`,
which runs on each new document before the page's own scripts.

WHAT IT BLOCKS: mcp__chrome-devtools__navigate_page whose `initScript` is missing or is not the
label keeper printed by bin/test-browser-tabs.py (it carries the marker GLOBAL). A navigation to
about:blank passes, and so does any malformed payload (fail open: a guard that breaks the session
gets switched off).

HEARTBEAT: an allowed labelled navigation touches the label owner's heartbeat file, so another
session's sweep sees this walk as driven and keeps its tab.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

TOOL = "mcp__chrome-devtools__navigate_page"
ENGINE = Path(__file__).resolve().parent.parent / "bin" / "test-browser-tabs.py"
OWNER = re.compile(r'"owner":\s*"([A-Za-z0-9._-]+)"')


def engine():
    spec = importlib.util.spec_from_file_location("test_browser_tabs", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tabs = engine()
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != TOOL:
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    if tool_input.get("type", "url") == "url" and str(tool_input.get("url", "")).strip() == "about:blank":
        return 0
    script = tool_input.get("initScript")
    if isinstance(script, str) and tabs.GLOBAL in script:
        owner = OWNER.search(script)
        if owner:
            tabs.touch(owner.group(1))
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Blocked: navigate_page without the tab label, so the tab would show only the app's own "
                "title and Simon cannot tell which window is this walk's.\n"
                "Fix: run `python3 ~/.claude/bin/test-browser-tabs.py label --task \"<PR or ticket>\" "
                "[--persona \"<WHO tail>\"]` and pass its output as `initScript` on this and every "
                "navigate_page (reload, back and forward included).\n"
                "Rule: ~/.claude/references/browser-debugging.md § Tab labels and stale tabs."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
