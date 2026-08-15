#!/usr/bin/env python3
"""
Both directions for hooks/work-resource-guard.sh, per the rule in
skills/sk/skills/maintenance-code-cleanup-repo/SKILL.md: a guard is assumed vacuous until it has been
seen to fail.

The guard is a bash PreToolUse hook, so this drives it the way the harness does — a tool_use JSON
payload on stdin — rather than importing anything. It is SELF-CONTAINED and generic: it spins up two
throwaway git repos (one whose origin contains the work-org match, one that does not) and a throwaway
identity overlay with test values, then drives the guard with CLAUDE_PROJECT_DIR (selects the boundary
from the repo's git origin) and CLAUDE_IDENTITY_FILE (the overlay the guard reads its values from). No
real accounts, projects, or checkouts are needed, so this runs anywhere.

The MUST-NOT-FIRE block is the important half. A flag or account name merely APPEARING in a commit
message, a test script or a quoted argument must never trip a rule — that is the false-positive class
that retired the old security-guard.py, and `is_cmd` is what keeps it out. Widen a rule back into a
plain text match and these fail first.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "work-resource-guard.sh"

# Generic test identity — the values the guard compares against. Nothing real.
WORK_ORG_MATCH = "TestWorkOrg"
WORK_EMAIL = "work@test.example"
PERSONAL_EMAIL = "personal@test.example"
WORK_PROJECTS = ["testworkprod", "testworkdev"]
PERSONAL_PROJECT = "testpersonalproj"
IDENTITY = {
    "workOrgMatch": WORK_ORG_MATCH,
    "workEmail": WORK_EMAIL,
    "personalEmail": PERSONAL_EMAIL,
    "workCloudProjects": WORK_PROJECTS,
    "personalCloudProject": PERSONAL_PROJECT,
}

WORKP = "--project-" + "name=work-prod"          # assembled: this file must not be its own test case
PERSP = "--project-" + "name=personal-test"

# (label, "work"|"personal", command). The dir is resolved to the matching throwaway repo in main().
MUST_FIRE = [
    ("bare stripe in a personal repo falls through to the WORK [default] profile",
     "personal", "stripe charges list"),
    ("stripe login with no profile writes [default], which is work",
     "personal", "stripe login"),
    ("an explicit work profile in a personal repo",
     "personal", f"stripe {WORKP} charges list"),
    ("a work GCP project in a personal repo",
     "personal", f"firebase use {WORK_PROJECTS[1]}"),
    ("the work account in a personal repo",
     "personal", f"gcloud config set account {WORK_EMAIL}"),
    ("the work Codex home in a personal repo",
     "personal", "CODEX_HOME=~/.codex-work codex exec 'review this'"),
    # --- the work direction (repo origin contains the work-org match) ---
    ("the personal GCP project driven by a cloud CLI in a work repo",
     "work", f"firebase deploy --project {PERSONAL_PROJECT}"),
    ("working inside the personal project dir with a cloud CLI is still the personal project",
     "work", f"cd ~/dev/{PERSONAL_PROJECT} && firebase deploy"),
    ("a personal service-account key handed to a work process",
     "work", "GOOGLE_APPLICATION_CREDENTIALS=~/dev/secrets/firebase-keys/k.json node migrate.mjs"),
    ("personal API keys read in a work repo",
     "work", "node -e \"require('dotenv').config({path:'~/.config/personal-keys.env'})\""),
    # The pure-git exemption must not become a way in: a compound that also invokes a cloud CLI
    # is not pure git, so this stays blocked even though it opens with git.
    ("git first does not launder the cloud CLI that follows it",
     "work", f"git pull && firebase deploy --project {PERSONAL_PROJECT}"),
]

MUST_NOT_FIRE = [
    ("the personal profile pinned explicitly is the whole point",
     "personal", f"stripe {PERSP} charges list"),
    ("version touches no account",
     "personal", "stripe version"),
    ("help touches no account",
     "personal", "stripe --help"),
    ("a work profile named inside a COMMIT MESSAGE is prose, not an invocation",
     "personal", f"git commit -m 'wire up stripe {WORKP} handling'"),
    ("a work account named inside a quoted argument is prose",
     "personal", f"codex exec 'the docs mention {WORK_EMAIL} here'"),
    ("a retired 1Password path in prose is just a string now",
     "personal", "echo 'op://vault was removed from the config'"),
    ("checking the firebase account is how the fix is found",
     "personal", "firebase login:list"),
    ("ordinary project work",
     "personal", "npm run test:run"),
    ("git is allowed everywhere",
     "personal", "git push origin main"),
    # Reading the manifest that DOCUMENTS the other boundary must not be denied: a boundary name in a
    # FILE PATH is a file being read, not a project being used. A pure-git command is exempt.
    ("the other boundary's manifest is a file to read, not a project to use",
     "work", f"git diff connectors/{PERSONAL_PROJECT}.json"),
    ("the same name in a git log pathspec is still just a path",
     "work", f"git log --oneline -- connectors/{PERSONAL_PROJECT}.json"),
    ("a personal key path named in a diff is prose, and the read guard covers the real read",
     "work", "git show HEAD -- references/connectors-setup.md"),
    ("ordinary work in a work repo",
     "work", "yarn lint"),
]


def _init_repo(path: Path, origin: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def fires(project_dir: Path, identity_file: Path, command: str) -> bool:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "CLAUDE_IDENTITY_FILE": str(identity_file),
    }
    out = subprocess.run(
        ["bash", str(GUARD)], input=payload, capture_output=True, text=True, env=env
    ).stdout.strip()
    return bool(out)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work = root / "work-repo"
        personal = root / "personal-repo"
        _init_repo(work, f"https://github.com/{WORK_ORG_MATCH}/some-repo.git")
        _init_repo(personal, f"https://github.com/some-user/{PERSONAL_PROJECT}.git")
        identity_file = root / "identity.local.json"
        identity_file.write_text(json.dumps(IDENTITY))
        dirs = {"work": work, "personal": personal}

        failures = []
        for name, boundary, cmd in MUST_FIRE:
            if not fires(dirs[boundary], identity_file, cmd):
                failures.append(f"SHOULD HAVE BLOCKED ({name}): {cmd}")
        for name, boundary, cmd in MUST_NOT_FIRE:
            if fires(dirs[boundary], identity_file, cmd):
                failures.append(f"FALSE POSITIVE ({name}): {cmd}")

    total = len(MUST_FIRE) + len(MUST_NOT_FIRE)
    for f in failures:
        print(f"FAIL  {f}")
    print(f"\n{total - len(failures)} pass / {len(failures)} fail "
          f"({len(MUST_FIRE)} must-fire, {len(MUST_NOT_FIRE)} must-not-fire)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
