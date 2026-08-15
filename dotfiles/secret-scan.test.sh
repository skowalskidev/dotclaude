#!/usr/bin/env bash
# Proves dotfiles/secret-scan.sh's IDENTIFIER guard: it blocks a commit that stages one of the user's
# real identifiers (from identity.local.json), case- and hyphen-flexibly, and no-ops when the overlay
# is absent or SKIP_IDENTITY_GUARD is set. Runs in a throwaway git repo with a fixture overlay, so it
# touches nothing real.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCAN="$HERE/secret-scan.sh"
FAIL=0
pass(){ printf '  ok   %s\n' "$1"; }
fail(){ printf '  FAIL %s\n' "$1"; FAIL=1; }

command -v jq >/dev/null 2>&1 || { echo "  skip jq not installed; identity-guard test skipped"; echo PASS; exit 0; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
REPO="$TMP/repo"; mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.test; git -C "$REPO" config user.name t
OVER="$TMP/identity.local.json"
cat > "$OVER" <<'JSON'
{"workOrgMatch":"AcmeCorp","workEmail":"me@acme.test","personalEmail":"home@acme.test","workCloudProjects":["acme-prod"],"personalCloudProject":"side-project"}
JSON

# Stage <content>, run the scan with the given env, return its exit code, then unstage.
run_with_staged(){
  local content="$1"; shift
  printf '%s\n' "$content" > "$REPO/f.md"
  git -C "$REPO" add f.md
  ( cd "$REPO" && env "$@" bash "$SCAN" >/dev/null 2>&1 ); local rc=$?
  git -C "$REPO" reset -q
  return $rc
}

echo "secret-scan.sh identity guard"

run_with_staged "we use AcmeCorp for billing" CLAUDE_IDENTITY_FILE="$OVER" \
  && fail "did not block exact identifier" || pass "blocks an exact identifier (AcmeCorp)"

run_with_staged "acmecorp rocks" CLAUDE_IDENTITY_FILE="$OVER" \
  && fail "did not block case variant" || pass "blocks a case variant (acmecorp)"

run_with_staged "the sideproject repo" CLAUDE_IDENTITY_FILE="$OVER" \
  && fail "did not block hyphen variant" || pass "blocks a hyphen variant (side-project -> sideproject)"

run_with_staged "nothing sensitive here at all" CLAUDE_IDENTITY_FILE="$OVER" \
  && pass "passes clean content" || fail "blocked clean content"

run_with_staged "we use AcmeCorp" CLAUDE_IDENTITY_FILE="$TMP/nope.json" \
  && pass "no-ops when the overlay is absent" || fail "blocked with no overlay present"

run_with_staged "AcmeCorp again" CLAUDE_IDENTITY_FILE="$OVER" SKIP_IDENTITY_GUARD=1 \
  && pass "SKIP_IDENTITY_GUARD=1 allows a reviewed exception" || fail "override did not allow"

[ "$FAIL" = 0 ] && echo PASS || echo FAIL
exit "$FAIL"
