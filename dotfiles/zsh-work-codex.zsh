# Work/personal Codex isolation (managed by Claude). In a WORK git repo (origin matches your identity
# overlay's workOrgMatch) -> use the WORK Codex home (~/.codex-work, work OpenAI API key). Anywhere else
# (personal/other) -> default ~/.codex (personal login). CONDITIONAL per-repo, so one shared shell keeps
# work and personal fully separate.
_work_codex_home() {
  local origin match
  origin="$(command git remote get-url origin 2>/dev/null)"
  match="$(jq -r '.workOrgMatch // ""' "${CLAUDE_IDENTITY_FILE:-$HOME/.claude/identity.local.json}" 2>/dev/null)"
  if [[ -n "$match" && "$origin" == *"$match"* ]]; then
    export CODEX_HOME="$HOME/.codex-work"
  else
    unset CODEX_HOME
  fi
}
# Re-evaluate on every directory change (interactive), and once now (covers login/non-interactive shells).
autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook chpwd _work_codex_home
_work_codex_home
