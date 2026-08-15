#!/usr/bin/env bash
# Sync ~/.claude config to your private GitHub repo: stage, secret-scan,
# commit, push. Idempotent (no-op when nothing changed). ON-DEMAND — run manually or via /sk:claude-config-sync;
# there is NO daemon. See README § "Staying in sync".
# SAFETY: aborts the commit if any credential-format value is staged, so a secret can never be
# auto-pushed. The allowlist .gitignore is the first line of defense; this is the second.
set -uo pipefail

REPO="$HOME/.claude"
cd "$REPO" 2>/dev/null || exit 0
[ -d .git ] || exit 0
mkdir -p logs
LOG="$REPO/logs/config-sync.log"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Single-run lock (mkdir is atomic; stock macOS has no flock).
LOCK="$REPO/.git/.config-sync.lock"
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

git add -A
git diff --cached --quiet && exit 0   # nothing changed -> no-op

# SAFETY GATE: never auto-commit a secret (shared scanner: gitleaks + grep fallback).
if ! "$REPO/dotfiles/secret-scan.sh" 2>>"$LOG"; then
  echo "$(stamp)  ABORT: secret detected in staged changes — not committing." >> "$LOG"
  git reset -q
  exit 1
fi

git commit -q -m "chore(auto-sync): config @ $(stamp)" || { echo "$(stamp)  commit failed" >> "$LOG"; exit 1; }
git pull --rebase --autostash -q origin main >> "$LOG" 2>&1 || echo "$(stamp)  pull failed (offline?)" >> "$LOG"
if git push -q origin main >> "$LOG" 2>&1; then
  echo "$(stamp)  synced -> origin/main" >> "$LOG"
else
  echo "$(stamp)  push failed (offline/auth?) — will retry next run" >> "$LOG"
fi
