#!/usr/bin/env bash
# bootstrap.sh — set this config up from scratch, or check an existing setup.
#
# The runnable companion to README section "Agent setup". It does the SAFE, idempotent wiring itself
# (executable bits, dotfile symlinks, the repo-local secret-scan gate, the identity-overlay scaffold)
# and GUIDES you through the rest — installing dependencies, filling in your accounts, connectors and
# secrets — printing the exact command for each and FAILING LOUD (exit 1) until nothing is missing.
#
# What it deliberately does NOT do, so it stays a guide and not a package manager or a shell-file
# editor (single responsibility):
#   - install dependencies      -> that is Homebrew's job:  brew bundle --file dotfiles/Brewfile
#   - edit ~/.zprofile/~/.zshrc  -> it prints the one line for you to add, and never touches your shell
#   - overwrite a real file      -> a pre-existing ~/.gitignore_global etc. is reported, never clobbered
#   - fetch a secret             -> there is no vault; secrets are minted per the README, by you
#
# Safe to re-run: every step is idempotent and never overwrites a file you have already filled in.
#
# Usage:  bash dotfiles/bootstrap.sh        (run from the repo root)
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
missing=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
did()  { printf '  \033[36mdid\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mnote\033[0m  %s\n' "$*"; }             # advisory: does not block Ready
todo() { printf '  \033[33mTODO\033[0m  %s\n' "$*"; missing=1; }  # blocks Ready
have() { command -v "$1" >/dev/null 2>&1; }

# Create <linkpath> -> <target> without ever clobbering a real file the user already has there.
link_safe() {
  local target="$1" link="$2" name="${2##*/}"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
    ok "~/$name already linked"
  elif [ -e "$link" ] && [ ! -L "$link" ]; then
    todo "~/$name exists as a real file — back it up, then: ln -sf \"$target\" \"$link\""
  else
    ln -sf "$target" "$link" && did "linked ~/$name"
  fi
}

echo "Setting up your Claude config in $ROOT"
echo

# 1) Placement. The hooks in settings.json use \$HOME/.claude/... paths, so Claude Code must load this
#    repo AS ~/.claude — clone it there, or point ~/.claude at it with a symlink.
echo "1. Location"
if [ "$ROOT" = "$HOME/.claude" ]; then
  ok "repo is at ~/.claude"
elif [ -L "$HOME/.claude" ] && [ "$(cd "$HOME/.claude" 2>/dev/null && pwd -P)" = "$ROOT" ]; then
  ok "~/.claude points at this repo"
else
  todo "this repo is not at ~/.claude — clone/move it there, or: ln -s \"$ROOT\" ~/.claude  (README section Agent setup, step 1)"
fi
echo

# 2) Dependencies — VERIFY only. Installing them belongs to Homebrew + dotfiles/Brewfile, not here.
#    git + jq the config needs at runtime, gitleaks gates every commit -> all block Ready. gh is only
#    for push/sync, so a missing/unauthed gh is advisory: the config runs fully without it.
echo "2. Dependencies  (install any missing with: brew bundle --file dotfiles/Brewfile)"
for dep in git jq gitleaks; do
  if have "$dep"; then ok "$dep"; else todo "$dep missing — brew bundle --file dotfiles/Brewfile"; fi
done
if have gh; then
  if gh auth status >/dev/null 2>&1; then ok "gh authenticated"; else warn "gh not authenticated — run: gh auth login  (only needed to push/sync)"; fi
else
  warn "gh (GitHub CLI) not installed — only needed to push/sync; https://cli.github.com"
fi
echo

# 3) Safe wiring — idempotent, reversible, done for you.
echo "3. Wiring"
chmod +x "$ROOT"/hooks/*.sh "$ROOT"/hooks/*.py "$ROOT"/.githooks/* 2>/dev/null && did "hooks + git-hooks made executable"
git -C "$ROOT" config core.hooksPath .githooks 2>/dev/null && did "secret-scan + commit-msg gate enabled (core.hooksPath)"
link_safe "$ROOT/dotfiles/zsh-work-codex.zsh" "$HOME/.zsh-work-codex.zsh"
if [ -f "$ROOT/dotfiles/gitignore_global" ]; then
  link_safe "$ROOT/dotfiles/gitignore_global" "$HOME/.gitignore_global"
  if [ -L "$HOME/.gitignore_global" ]; then
    git config --global core.excludesFile "$HOME/.gitignore_global" && did "set git core.excludesFile"
    grep -q '\*\*/.claude-slot.json' "$HOME/.gitignore_global" 2>/dev/null || printf '\n**/.claude-slot.json\n' >> "$HOME/.gitignore_global"
  fi
fi
# The shell source line edits ~/.zprofile/~/.zshrc, so it needs your consent — guide, never edit.
srcline='[ -f "$HOME/.zsh-work-codex.zsh" ] && source "$HOME/.zsh-work-codex.zsh"'
if grep -qsF "$srcline" "$HOME/.zprofile" "$HOME/.zshrc" 2>/dev/null; then
  ok "shell sources the work/personal switch"
else
  todo "add this line to BOTH ~/.zprofile and ~/.zshrc:  $srcline"
fi
echo

# 4) Identity overlay — your accounts. Created from the template; FAIL LOUD until you fill it in.
echo "4. Identity overlay (your accounts, untracked)"
if [ ! -f "$ROOT/identity.local.json" ]; then
  if [ -f "$ROOT/identity.example.json" ]; then
    cp "$ROOT/identity.example.json" "$ROOT/identity.local.json"
    todo "created identity.local.json from the template — EDIT it with your real accounts"
  else
    todo "identity.example.json template is gone; cannot create identity.local.json"
  fi
elif grep -qE 'YourOrg|@work\.example|@personal\.example|your-work|your-personal' "$ROOT/identity.local.json" 2>/dev/null; then
  todo "identity.local.json still holds template placeholders — fill in your real accounts"
elif have jq && ! jq -e . "$ROOT/identity.local.json" >/dev/null 2>&1; then
  todo "identity.local.json is not valid JSON — fix it"
else
  ok "identity.local.json filled in"
fi
echo

# 5) Connectors — per-project, optional. Reuse the skill; or restore your own manifests by hand.
echo "5. Connectors (optional, per project)"
if ls "$ROOT"/connectors/*.json >/dev/null 2>&1; then
  ok "$(ls "$ROOT"/connectors/*.json | wc -l | tr -d ' ') connector manifest(s) present"
else
  ok "none yet — in a project run /sk:setup-connectors to set them up, or copy your own connectors/<project>.json in"
fi
echo

# 6) Reinstallable / user-held — pointers only.
echo "6. Optional extras"
ok "third-party skill packs: bin/install-third-party-skills.sh (reinstallable, not tracked)"
ok "secrets to recreate: README section 'Secrets to recreate' (ask, never fabricate)"
echo

# 7) Verdict.
if [ "$missing" -ne 0 ]; then
  echo "NOT READY — clear the TODO items above, then re-run: bash dotfiles/bootstrap.sh"
  exit 1
fi
echo "Ready. Overlay in place and wiring done; the work/personal boundary and its context load next session."
if have python3 && [ -f "$ROOT/hooks/config-contract.test.py" ]; then
  echo "Confirm with the config's own acceptance test:  /usr/bin/python3 hooks/config-contract.test.py"
fi
