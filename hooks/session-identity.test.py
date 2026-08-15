#!/usr/bin/env python3
"""
hooks/session-identity.sh is the no-degradation guarantee: it re-injects the untracked identity
overlay's values into every session as context, so genericising the tracked files never costs
adherence. This proves it (a) emits the concrete values when the overlay exists, and (b) emits the
create-it prompt (and no stale values) when it does not. CLAUDE_IDENTITY_FILE points it at a fixture.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).parent / "session-identity.sh"


def run(identity_file: str) -> dict:
    env = {**os.environ, "CLAUDE_IDENTITY_FILE": identity_file}
    out = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env).stdout.strip()
    return json.loads(out) if out else {}


def context(payload: dict) -> str:
    return (payload.get("hookSpecificOutput", {}) or {}).get("additionalContext", "")


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        # (a) overlay present -> the concrete values are injected into context.
        idf = Path(tmp) / "identity.local.json"
        idf.write_text(json.dumps({
            "workOrgMatch": "AcmeCorp",
            "workEmail": "me@acme.example",
            "personalEmail": "me@home.example",
            "workCloudProjects": ["acme-prod", "acme-dev"],
            "personalCloudProject": "sideproject",
        }))
        ctx = context(run(str(idf)))
        for needle in ("me@acme.example", "me@home.example", "acme-prod", "sideproject", "AcmeCorp"):
            if needle not in ctx:
                failures.append(f"injected context is missing the overlay value {needle!r}: {ctx!r}")

        # (b) overlay absent -> a create-it prompt, and NONE of the fixture values leak.
        missing = Path(tmp) / "does-not-exist.json"
        ctx2 = context(run(str(missing)))
        if "identity.local.json" not in ctx2:
            failures.append(f"absent-overlay context does not prompt to create the file: {ctx2!r}")
        if "me@acme.example" in ctx2:
            failures.append("absent-overlay context leaked a stale value")

    for f in failures:
        print(f"FAIL  {f}")
    print(f"\n{2 - min(len(failures), 2)}/2 checks pass ({len(failures)} failing assertions)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
