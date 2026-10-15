#!/usr/bin/env python3
"""
Both directions for hooks/secret-echo-guard.py: a guard is assumed vacuous until it has been seen to
fail, and assumed harmful until it has been seen NOT to fire on text that merely names a command or
on a credential that is USED rather than printed.

Drives the hook the way the harness does (a tool_use JSON payload on stdin). Nothing real is run:
the guard only parses the command text. Every command below is a string, never executed.

The MUST-NOT-FIRE block is the important half. The class that gets a guard switched off is a
false positive on legitimate use: a value piped into a consumer (`gh auth token | docker login`),
captured into an env var for one command, redirected to a file, or a help/status verb.
"""

import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parent / "secret-echo-guard.py"

# (label, command, substring the deny reason must contain)
MUST_FIRE = [
    # stripe
    ("stripe config --list", "stripe config --list", "stripe config --list"),
    ("stripe config, double space", "stripe config  --list", "stripe config --list"),
    ("stripe config, absolute path", "/opt/homebrew/bin/stripe config --list", "stripe config --list"),
    ("stripe config, profile flag first", "stripe --project-name demo config --list", "stripe config --list"),
    ("stripe config inside sh -c", "sh -c 'stripe config --list'", "stripe config --list"),
    ("stripe config inside bash -lc double-quoted", 'bash -lc "stripe config --list"', "stripe config --list"),
    ("stripe config after &&", "cd /tmp && stripe config --list", "stripe config --list"),
    ("stripe config after ;", "echo hi; stripe config --list", "stripe config --list"),
    ("stripe config piped to head", "stripe config --list | head -20", "stripe config --list"),
    ("stripe config piped to grep (value lines)", "stripe config --list | grep test_mode", "stripe config --list"),
    ("stripe config 2>&1", "stripe config --list 2>&1", "stripe config --list"),
    ("stripe config under env prefix", "FOO=1 env stripe config --list", "stripe config --list"),
    ("stripe config under eval", "eval 'stripe config --list'", "stripe config --list"),
    ("stripe config in a subshell", "(stripe config --list)", "stripe config --list"),
    ("stripe config via xargs", "echo x | xargs stripe config --list", "stripe config --list"),
    ("stripe config echoed through $()", 'echo "$(stripe config --list)"', "stripe config --list"),
    ("stripe listen --print-secret", "stripe listen --print-secret", "--print-secret"),
    # gh
    ("gh auth token", "gh auth token", "gh auth token"),
    ("gh auth token with hostname", "gh auth token --hostname github.com", "gh auth token"),
    ("gh auth token echoed", 'echo "token: $(gh auth token)"', "gh auth token"),
    ("gh auth token piped to cat", "gh auth token | cat", "gh auth token"),
    ("gh auth token to tee", "gh auth token | tee /tmp/t", "gh auth token"),
    ("gh auth status --show-token", "gh auth status --show-token", "--show-token"),
    ("gh auth status -t", "gh auth status -t", "--show-token"),
    # gcloud
    ("gcloud print-access-token", "gcloud auth print-access-token", "print-access-token"),
    ("gcloud print-identity-token", "gcloud auth print-identity-token --audiences=x", "print-identity-token"),
    ("gcloud adc print-access-token", "gcloud auth application-default print-access-token", "print-access-token"),
    # aws
    ("aws configure export-credentials", "aws configure export-credentials", "export-credentials"),
    ("aws export-credentials with profile", "aws --profile p configure export-credentials --format env", "export-credentials"),
    ("aws configure get secret key", "aws configure get aws_secret_access_key", "aws_secret_access_key"),
    ("aws configure get session token", "aws configure get aws_session_token --profile p", "aws_session_token"),
    # firebase
    ("firebase login:ci", "firebase login:ci", "firebase login:ci"),
    # macOS keychain
    ("security find-generic-password -w", "security find-generic-password -s svc -a me -w", "-w"),
    ("security find-internet-password -w", "security find-internet-password -s host -w", "-w"),
    ("security find-generic-password -g", "security find-generic-password -s svc -g", "-g"),
    ("security find-generic-password -g, stdout piped but stderr visible",
     "security find-generic-password -s svc -g | grep acct", "-g"),
    ("security find-generic-password cluster -wa", "security find-generic-password -wa me", "-w"),
    ("security dump-keychain -d", "security dump-keychain -d login.keychain", "dump-keychain"),
    # 1Password
    ("op read", "op read op://vault/item/field", "op read"),
    ("op item get --reveal", "op item get item --fields password --reveal", "--reveal"),
    # environment
    ("bare env", "env", "env"),
    ("bare printenv", "printenv", "printenv"),
    ("env piped to sort", "env | sort", "env"),
    ("env piped to grep for tokens", "env | grep -i token", "env"),
    ("env piped to grep for keys under sh -c", "sh -c 'env | grep KEY'", "env"),
    ("printenv of a token variable", "printenv GITHUB_TOKEN", "printenv"),
    ("printenv of an api key variable", "printenv STRIPE_API_KEY", "printenv"),
]

MUST_NOT_FIRE = [
    # help, status and list verbs
    ("stripe config --help", "stripe config --help"),
    ("stripe config --set (writes, prints nothing)", "stripe config --set color off"),
    ("stripe listen without the secret flag", "stripe listen --forward-to localhost:3000"),
    ("stripe version", "stripe version"),
    ("gh auth status", "gh auth status"),
    ("gh auth status for a host", "gh auth status --hostname github.com"),
    ("gh pr list", "gh pr list"),
    ("gcloud auth list", "gcloud auth list"),
    ("gcloud config get-value project", "gcloud config get-value project"),
    ("aws configure list", "aws configure list"),
    ("aws configure get region", "aws configure get region"),
    ("aws configure get access key id", "aws configure get aws_access_key_id"),
    ("aws sts get-caller-identity", "aws sts get-caller-identity"),
    ("firebase login:list", "firebase login:list"),
    ("firebase deploy", "firebase deploy --only hosting"),
    ("npm token list (abbreviated tokens only)", "npm token list"),
    ("security find-generic-password without -w or -g", "security find-generic-password -s svc"),
    ("security list-keychains", "security list-keychains"),
    ("op whoami", "op whoami"),
    ("op item get without --reveal", "op item get item --fields label=username"),
    ("op run", "op run -- node server.js"),
    # env, but not a dump
    ("env VAR=x cmd", "env FOO=1 node x.js"),
    ("env -u VAR cmd", "env -u FOO node x.js"),
    ("env with options and an assignment", "env -i PATH=/usr/bin ls"),
    ("printenv of a plain variable", "printenv PATH"),
    ("env piped to grep for a plain name", "env | grep PORT"),
    ("env names only", "env | cut -d= -f1"),
    ("env line count", "env | wc -l"),
    # secret FILES stay readable (rules/security.md: no file-read blockers)
    ("grep display_name in the stripe config file", "grep display_name ~/.config/stripe/config.toml"),
    ("grep names out of the stripe config file", "grep -E '^\\[|display_name|account_id' ~/.config/stripe/config.toml"),
    ("cat a key file", "cat ~/.config/some-tool/keyfile"),
    # text that merely NAMES a command
    ("echo naming the command", 'echo "never run stripe config --list"'),
    ("printf note naming the command", "printf -- '- avoid: gh auth token\\n' > note.md"),
    ("heredoc body naming the command", "cat > note.md <<'EOF'\nstripe config --list\ngh auth token\nEOF"),
    ("grep for the command text", 'grep -rn "gcloud auth print-access-token" docs'),
    ("which stripe", "which stripe"),
    ("command -v", "command -v stripe"),
    ("ls the binary", "ls -l /opt/homebrew/bin/stripe"),
    ("python on a file named after the guard", "python3 -m py_compile hooks/secret-echo-guard.py"),
    ("git commit message naming the command", "git commit -F msg.txt"),
    ("a quoted sh -c that only echoes text", "sh -c 'echo stripe config --list'"),
    # a credential that is USED, not printed
    ("gh auth token into an env var for one command", "GH_TOKEN=$(gh auth token) node release.js"),
    ("gh auth token in an assignment", "TOKEN=$(gh auth token)"),
    ("gh auth token exported", 'export TOKEN="$(gh auth token)"'),
    ("gh auth token in a header argument", 'curl -H "Authorization: Bearer $(gh auth token)" https://api.github.com/user'),
    ("gh auth token piped to a login consumer", "gh auth token | docker login ghcr.io -u me --password-stdin"),
    ("gh auth token piped to pbcopy", "gh auth token | pbcopy"),
    ("gh auth token to a file", "gh auth token > /tmp/token"),
    ("gh auth token to /dev/null", "gh auth token > /dev/null"),
    ("gh auth token length only", "gh auth token | wc -c"),
    ("gh auth token grep -q", "gh auth token | grep -q ghp_"),
    ("gcloud token into a variable inside sh -c", "sh -c 'TOKEN=$(gcloud auth print-access-token) run-it'"),
    ("gcloud token in a header", 'curl -H "Authorization: Bearer $(gcloud auth print-access-token)" https://x.example'),
    ("stripe config --list redirected to a file", "stripe config --list > /tmp/stripe.txt"),
    ("stripe config --list to /dev/null", "stripe config --list >/dev/null 2>&1"),
    ("aws credentials consumed by eval", 'eval "$(aws configure export-credentials --format env)"'),
    ("security password piped to a consumer", "security find-generic-password -s svc -w | pbcopy"),
    ("security -g with stderr hidden", "security find-generic-password -s svc -g 2>/dev/null"),
    ("op read to a file", "op read op://vault/item/field > /tmp/secret"),
    ("op read inside a command substitution argument", 'deploy --token "$(op read op://vault/item/field)"'),
    # robustness: fail open
    ("empty command", ""),
    ("malformed unterminated quote", "echo 'oops stripe config"),
    ("malformed unterminated substitution", "echo $(gh auth"),
]


def run(command: str) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                       capture_output=True)
    if p.returncode != 0:
        return f"CRASH rc={p.returncode} {p.stderr[-200:]}"
    if not p.stdout.strip():
        return ""
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def main() -> int:
    failures, passes = [], 0
    for label, cmd, expect in MUST_FIRE:
        reason = run(cmd)
        if reason and not reason.startswith("CRASH") and expect in reason:
            passes += 1
        else:
            failures.append(f"MUST FIRE: {label}: {cmd!r} -> {reason[:120]!r}")
    for label, cmd in MUST_NOT_FIRE:
        reason = run(cmd)
        if not reason:
            passes += 1
        else:
            failures.append(f"MUST NOT FIRE: {label}: {cmd!r} -> {reason[:120]!r}")
    # Non-Bash tools and a garbage payload are never touched.
    for raw in ('{"tool_name": "Read", "tool_input": {"command": "gh auth token"}}', "not json"):
        p = subprocess.run([sys.executable, str(GUARD)], input=raw, text=True, capture_output=True)
        if p.returncode == 0 and not p.stdout.strip():
            passes += 1
        else:
            failures.append(f"MUST FAIL OPEN: {raw[:40]!r} -> rc={p.returncode} out={p.stdout[:80]!r}")
    for f in failures:
        print(f)
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
