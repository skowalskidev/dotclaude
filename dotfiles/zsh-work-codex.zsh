autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook -d chpwd _work_codex_home
unfunction _work_codex_home 2>/dev/null
export CODEX_HOME="$HOME/.codex"

# Always resolve the manifest before the real process starts, including `codex mcp login`.
# Conductor uses this same executable directly; no login-shell initialization is required there.
codex() { "$HOME/.claude/bin/codex-launch.py" "$@"; }
