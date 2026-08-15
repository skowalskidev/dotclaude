#!/usr/bin/env bash
# Install the third-party skill packs this config STACKS ON but deliberately does not track.
#
# WHY THEY ARE NOT IN THE REPO
# They are other people's repos (~1.6 GB together) and they are reinstallable. Vendoring them would
# make `git -C ~/.claude status` — the whole sync litmus test — permanently noisy.
#
# WHY THIS SCRIPT EXISTS ANYWAY
# Until now README step 5 said "ask the user for the source URLs; do not fabricate them", which meant a
# fresh machine could not be set up without them. The URLs are not secrets. The gap was that nothing
# recorded them, so setup stalled on a question that had a written answer.
#
# ADOPTION BAR: every pack here cleared it (stars verified 2026-08-03, see references/skill-stack.md).
# Adding one below roughly ten thousand stars breaks rules/engineering-standards.md. A skill runs with
# full tool access, so a niche pack is a security decision, not a convenience one.
#
#   ./install-third-party-skills.sh          # install or update all packs
#   ./install-third-party-skills.sh --check  # report only, change nothing

set -uo pipefail

SKILLS_DIR="$HOME/.claude/skills"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# name|git url|minimum stars expected (documents WHY it is on the list)
PACKS=(
  "gstack|https://github.com/garrytan/gstack.git|125000"
  "impeccable|https://github.com/pbakaus/impeccable.git|54000"
  "agency-agents|https://github.com/msitarzewski/agency-agents.git|138000"
)

# Anthropic's own skills + the official plugin marketplace are installed through Claude Code itself,
# not by cloning, so they are reported rather than fetched.
note_official() {
  printf '  %-18s %s\n' "anthropic/skills" "165.8k stars — install via: /plugin marketplace add anthropics/skills"
  printf '  %-18s %s\n' "claude-plugins" "33.0k stars — install via: /plugin marketplace add anthropics/claude-plugins-official"
}

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
mkdir -p "$SKILLS_DIR" || exit 1

rc=0
echo "Third-party skill packs (stacked on by references/skill-stack.md):"
for entry in "${PACKS[@]}"; do
  IFS='|' read -r name url _stars <<< "$entry"
  dest="$SKILLS_DIR/$name"

  if [ -d "$dest/.git" ]; then
    if [ "$CHECK_ONLY" -eq 1 ]; then
      printf '  %-18s present (%s)\n' "$name" "$(git -C "$dest" log -1 --format=%as 2>/dev/null)"
    else
      printf '  %-18s updating... ' "$name"
      # Report WHY a pull failed. This used to swallow stderr and print a generic
      # "SKIPPED (local changes or diverged)", which is how all three packs silently drifted
      # months behind upstream: a failing update was indistinguishable from an up-to-date one.
      # These are read-only clones of other people's repos, so a shallow clone that cannot
      # fast-forward is recovered by re-cloning, not by hand-merging.
      before="$(git -C "$dest" rev-parse --short HEAD 2>/dev/null)"
      if err="$(git -C "$dest" pull --ff-only 2>&1)"; then
        after="$(git -C "$dest" rev-parse --short HEAD 2>/dev/null)"
        if [ "$before" = "$after" ]; then echo "ok (already current, $after)"
        else echo "ok ($before -> $after)"; fi
      else
        echo "FAILED"
        printf '%s\n' "$err" | sed 's/^/      /' >&2
        printf '      recover with: rm -rf %s && %s\n' "$dest" "$0" >&2
        rc=1
      fi
    fi
  elif [ -d "$dest" ]; then
    printf '  %-18s present but NOT a git checkout — leaving alone\n' "$name"
  elif [ "$CHECK_ONLY" -eq 1 ]; then
    printf '  %-18s MISSING — run this script without --check\n' "$name"; rc=1
  else
    printf '  %-18s cloning... ' "$name"
    if git clone -q --depth 1 "$url" "$dest" 2>/dev/null; then
      # core.fileMode=false, or the next update refuses to run. Something on this machine chmods
      # +x across these trees, which git reports as 395 modified files with zero content change;
      # `pull --ff-only` then aborts to avoid overwriting "local changes" that are only mode bits.
      # That is what held impeccable at 2026-03-21 for four and a half months.
      git -C "$dest" config core.fileMode false
      echo "ok"
    else echo "FAILED ($url)"; rc=1; fi
  fi
done

echo "Installed through Claude Code rather than cloned:"
note_official

if [ "$CHECK_ONLY" -eq 1 ] && [ "$rc" -ne 0 ]; then
  echo
  echo "Some packs are missing. references/skill-stack.md stacks on them, so those rows will not work."
fi
exit "$rc"
