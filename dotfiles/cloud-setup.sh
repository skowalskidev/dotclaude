#!/usr/bin/env bash
# cloud-setup.sh — wire this config into ~/.claude on a fresh CLOUD box (Claude Code on the web,
# a container, a Codespace) where you can't run the interactive Mac bootstrap.
#
# Paste the CONTENTS of this file into your Claude Code web environment's setup-script field (or run
# it after cloning). It is the cloud counterpart to dotfiles/bootstrap.sh: instead of guiding you
# through brew + shell edits, it non-destructively SYMLINKS this repo's parts into ~/.claude so the
# skills, their rules/ + references/ knowledge base, and the hook layer all load next session.
#
# Idempotent and non-clobbering: it never overwrites a real file the harness already put in ~/.claude.
# Prepend your PROJECT's own setup (e.g. `npm install`) before this block; this script only wires the
# config, nothing project-specific.
set -euo pipefail

REPO_URL="https://github.com/skowalskidev/dotclaude.git"
DOT="$HOME/dotclaude"          # where the config is cloned (kept git-updatable)
CC="$HOME/.claude"             # where Claude Code reads it

# 1. Clone the config (or fast-forward an existing clone).
if [ -d "$DOT/.git" ]; then
  git -C "$DOT" pull --ff-only origin main || true
else
  git clone "$REPO_URL" "$DOT"
fi

mkdir -p "$CC/skills"
chmod +x "$DOT"/hooks/*.sh "$DOT"/hooks/*.py "$DOT"/bin/*.sh "$DOT"/bin/*.py "$DOT"/.githooks/* 2>/dev/null || true

# Symlink <target> to <link> without ever clobbering a real (non-symlink) file already there.
link() { [ -e "$2" ] && [ ! -L "$2" ] && { echo "skip $2 (real file present)"; return; }; ln -sfn "$1" "$2"; echo "linked ${2#$HOME/}"; }

# 2. The skills plugin -> loads next session as sk@skills-dir -> /sk:* .
link "$DOT/skills/sk" "$CC/skills/sk"

# 3. The knowledge base the skills READ (must sit at the ~/.claude ROOT, not inside the plugin).
for item in CLAUDE.md rules references contracts connectors AGENTS.md; do link "$DOT/$item" "$CC/$item"; done

# 4. The guard / hook layer (SessionStart + PreToolUse). Proven to exit 0 on Linux, and the
#    task-intake gate auto-allows Agent/Workflow in cloud (child) sessions. Comment these three
#    lines out for a skills-only install with no guards.
link "$DOT/hooks"         "$CC/hooks"
link "$DOT/bin"           "$CC/bin"
link "$DOT/settings.json" "$CC/settings.json"

# 5. Identity overlay (untracked). Scaffolded from the template so the work/personal guard has a file;
#    EDIT ~/dotclaude/identity.local.json with your real accounts. NEVER commit real accounts/secrets.
[ -f "$DOT/identity.local.json" ] || cp "$DOT/identity.example.json" "$DOT/identity.local.json"
link "$DOT/identity.local.json" "$CC/identity.local.json"

# 6. Verify the plugin loaded.
command -v claude >/dev/null 2>&1 && claude plugin list || true
