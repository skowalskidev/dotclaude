#!/usr/bin/env bash
# Scan the STAGED git changes before they can be committed; exit non-zero (block) on a problem.
# ONE implementation, shared by .githooks/pre-commit and dotfiles/sync-config.sh (DRY).
# Two gates run in order:
#   1) SECRETS  — gitleaks (rules + entropy), or a credential-format grep when gitleaks is absent.
#   2) IDENTIFIERS — your own personal/employer identifiers, read from the untracked identity overlay,
#      so publishing this repo can never leak them by accident. No sensitive value is hardcoded here;
#      the patterns come from identity.local.json, which is itself untracked.
set -uo pipefail

# --- 1) SECRET scan -----------------------------------------------------------------------------
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks git --staged --no-banner --redact >/dev/null 2>&1; then
    echo "secret-scan: BLOCKED by gitleaks — a secret appears in the staged changes. Remove it, or add a gitleaks allowlist for a false positive." >&2
    exit 1
  fi
else
  # Fallback: credential-format grep (patterns require real key structure so they don't self-match).
  if git diff --cached | grep -qiE '(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|sk-ant-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})'; then
    echo "secret-scan: BLOCKED — a credential-format value is staged. Remove it or fix .gitignore. (Install gitleaks via 'brew bundle --file ~/.claude/dotfiles/Brewfile' for stronger scanning.)" >&2
    exit 1
  fi
fi

# --- 2) IDENTIFIER guard ------------------------------------------------------------------------
# Blocks committing YOUR real identifiers (work/personal emails, work org, personal project, work
# cloud projects) into a tracked file. The values come from the untracked overlay, so this repo can
# be public without the guard itself leaking anything. Absent overlay (fresh clone) -> nothing to
# protect yet, so it no-ops. Override for a deliberate, reviewed case: SKIP_IDENTITY_GUARD=1.
IDENTITY="${CLAUDE_IDENTITY_FILE:-$(git rev-parse --show-toplevel 2>/dev/null)/identity.local.json}"
if [ -f "$IDENTITY" ] && command -v jq >/dev/null 2>&1; then
  staged="$(git diff --cached)"
  while IFS= read -r val; do
    [ -n "$val" ] || continue
    # Escape regex specials, then make -_/space separators flexible (so "foo-bar" also matches "FooBar"/"foobar").
    pat="$(printf '%s' "$val" | sed -E 's/[][(){}.^$*+?|\\]/\\&/g; s/[-_ ]+/[-_ ]?/g')"
    if printf '%s' "$staged" | grep -iqE "$pat"; then
      if [ "${SKIP_IDENTITY_GUARD:-}" = "1" ]; then
        echo "secret-scan: identity guard matched '$val' but SKIP_IDENTITY_GUARD=1 is set — allowing." >&2
      else
        echo "secret-scan: BLOCKED — staged changes contain one of your identifiers from identity.local.json ('$val')." >&2
        echo "  This repo is public. Genericise it (a placeholder / 'your work org') before committing, or set SKIP_IDENTITY_GUARD=1 for a reviewed exception." >&2
        exit 1
      fi
    fi
  # Only distinctive values (length > 4) so short/common tokens can't cause false positives.
  done <<EOF
$(jq -r '([.workEmail, .personalEmail, .workOrgMatch, .personalCloudProject] + (.workCloudProjects // [])) | .[] | select(. != null and (tostring | length > 4))' "$IDENTITY" 2>/dev/null)
EOF
fi
exit 0
