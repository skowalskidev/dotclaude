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


def run(identity_file: str, account_file: str = "/nonexistent", cwd: str | None = None) -> dict:
    env = {**os.environ, "CLAUDE_IDENTITY_FILE": identity_file, "CLAUDE_ACCOUNT_FILE": account_file}
    out = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env, cwd=cwd).stdout.strip()
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

        # (c) a work repo on another Claude login warns; the work login or another repo does not.
        for name, url in (("work", "https://github.com/AcmeCorp/app.git"), ("other", "https://github.com/me/app.git")):
            subprocess.run(["git", "init", "-q", name], cwd=tmp, check=True)
            subprocess.run(["git", "remote", "add", "origin", url], cwd=Path(tmp) / name, check=True)
        account = Path(tmp) / "account.json"
        account.write_text(json.dumps({"oauthAccount": {"emailAddress": "me@home.example"}}))
        work_repo, other_repo = str(Path(tmp) / "work"), str(Path(tmp) / "other")
        if "WRONG CLAUDE LOGIN" not in context(run(str(idf), str(account), work_repo)):
            failures.append("a work repo on another login did not warn")
        if "WRONG CLAUDE LOGIN" in context(run(str(idf), str(account), other_repo)):
            failures.append("another repo warned about the login")
        account.write_text(json.dumps({"oauthAccount": {"emailAddress": "me@acme.example"}}))
        if "WRONG CLAUDE LOGIN" in context(run(str(idf), str(account), work_repo)):
            failures.append("a work repo on the work login warned")

        # (d) workClaudeLogins: a listed login in a work repo is accepted, an unlisted one still warns,
        # and an overlay without the key behaves as before (only workEmail accepted).
        account.write_text(json.dumps({"oauthAccount": {"emailAddress": "me2@acme.example"}}))
        if "WRONG CLAUDE LOGIN" not in context(run(str(idf), str(account), work_repo)):
            failures.append("a second login not in the overlay was accepted without workClaudeLogins")
        idf2 = Path(tmp) / "identity2.json"
        idf2.write_text(json.dumps({**json.loads(idf.read_text()), "workClaudeLogins": ["me2@acme.example"]}))
        if "WRONG CLAUDE LOGIN" in context(run(str(idf2), str(account), work_repo)):
            failures.append("a login listed in workClaudeLogins warned in a work repo")
        account.write_text(json.dumps({"oauthAccount": {"emailAddress": "me3@acme.example"}}))
        warn = context(run(str(idf2), str(account), work_repo))
        if "WRONG CLAUDE LOGIN" not in warn or "me2@acme.example" not in warn:
            failures.append(f"an unlisted login did not warn naming the accepted list: {warn!r}")
        account.write_text(json.dumps({"oauthAccount": {"emailAddress": "me@acme.example"}}))
        if "WRONG CLAUDE LOGIN" in context(run(str(idf2), str(account), work_repo)):
            failures.append("workEmail stopped being accepted when workClaudeLogins is set")

    for f in failures:
        print(f"FAIL  {f}")
    print(f"\n{len(failures)} failing assertions" if failures else "\nall checks pass")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
