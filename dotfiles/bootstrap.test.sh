#!/usr/bin/env bash
# Proves dotfiles/bootstrap.sh guides a from-scratch setup: it scaffolds the identity overlay from the
# template, FAILS LOUD (non-zero) while anything is unfinished, stops flagging a step once it is
# satisfied, and never clobbers a real dotfile the user already has. Runs against throwaway ROOT and
# HOME dirs so nothing real is touched (the script writes symlinks + git --global config into HOME).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
FAIL=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAIL=1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ROOT="$TMP/repo"; SBHOME="$TMP/home"
mkdir -p "$ROOT/dotfiles" "$ROOT/hooks" "$ROOT/.githooks" "$ROOT/connectors" "$SBHOME"
cp "$HERE/bootstrap.sh" "$ROOT/dotfiles/bootstrap.sh"
cp "$HERE/../identity.example.json" "$ROOT/identity.example.json"
cp "$HERE/gitignore_global" "$ROOT/dotfiles/gitignore_global" 2>/dev/null || printf '*.key\n' > "$ROOT/dotfiles/gitignore_global"
cp "$HERE/zsh-work-codex.zsh" "$ROOT/dotfiles/zsh-work-codex.zsh" 2>/dev/null || printf '# stub\n' > "$ROOT/dotfiles/zsh-work-codex.zsh"
git -C "$ROOT" init -q 2>/dev/null   # so the core.hooksPath wiring has a repo to write to

# Run bootstrap with a sandboxed HOME so its symlinks + `git config --global` never touch the real one.
run() { HOME="$SBHOME" bash "$ROOT/dotfiles/bootstrap.sh" 2>&1; }

echo "bootstrap.sh"

# 1) Fresh clone: no identity.local.json -> created from the template, and the run FAILS LOUD.
out="$(run)"; rc=$?
[ -f "$ROOT/identity.local.json" ] && pass "creates identity.local.json from the template" \
                                   || fail "did not create identity.local.json"
[ "$rc" -ne 0 ] && pass "fails loudly (exit $rc) while setup is unfinished" \
                || fail "exited 0 with an unfinished setup"
printf '%s\n' "$out" | grep -q 'TODO.*identity.local.json' \
  && pass "flags the freshly-created overlay as needing edits" || fail "did not flag the new overlay"

# 2) The scaffolded copy still holds the template placeholders -> still flagged unfinished.
printf '%s\n' "$(run)" | grep -q 'TODO.*placeholder' \
  && pass "flags placeholder values as unfinished" || fail "did not flag placeholder overlay"

# 3) Filled overlay -> the identity step reports ok, no longer a TODO.
cat > "$ROOT/identity.local.json" <<'JSON'
{"workOrgMatch":"AcmeCorp","workEmail":"me@acme.test","personalEmail":"me@home.test","workCloudProjects":["acme-prod"],"personalCloudProject":"side"}
JSON
printf '%s\n' "$(run)" | grep -q 'ok.*identity.local.json filled in' \
  && pass "stops flagging identity once filled in" || fail "still flags a filled identity.local.json"

# 4) Never clobbers a real ~/.gitignore_global (link_safe must refuse to overwrite a real file).
rm -f "$SBHOME/.gitignore_global"; printf 'MY REAL RULES\n' > "$SBHOME/.gitignore_global"
run >/dev/null 2>&1
{ [ ! -L "$SBHOME/.gitignore_global" ] && grep -q 'MY REAL RULES' "$SBHOME/.gitignore_global"; } \
  && pass "does not clobber a real ~/.gitignore_global" || fail "overwrote a real ~/.gitignore_global"

[ "$FAIL" = 0 ] && echo "PASS" || echo "FAIL"
exit "$FAIL"
