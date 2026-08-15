---
name: claude-config-sync
description: Commit + push changes to Simon's ~/.claude config repo (his config source of truth — a private GitHub repo) SAFELY. Review the diff, NEVER commit secrets, write a conventional commit, push, confirm in sync. Use whenever ~/.claude has uncommitted config changes (the SessionStart hook flags them), right after editing any config under ~/.claude (CLAUDE.md, a hook, an sk/sk-work skill, settings.json), or when Simon says "sync my config" / "commit my config".
allowed-tools:
  - Bash(git -C ~/.claude *)
---

# Sync Simon's Claude config repo

## Current state of the repo

Gathered before this skill was handed to you, so step 1 is already done. Read it, do not re-run it.

```!
git -C ~/.claude status -sb
echo "--- staged/unstaged summary ---"
git -C ~/.claude diff --stat HEAD
echo "--- last 3 commits ---"
git -C ~/.claude log -3 --format='%h %s'
```

The full diff is deliberately **not** injected here: it can be thousands of lines and most syncs do
not need it in full. Read it with `git -C ~/.claude diff` when the summary above shows anything you
cannot already account for, and always before step 2's secret check.

`~/.claude` is a git repo and Simon's **single source of truth** for his Claude setup, mirrored to a
**private** GitHub repo. An uncommitted change there = out of sync. This
skill commits + pushes those changes safely.

## Absolute rules
- **NEVER commit a secret.** Not an API key, token, private key, password, `.env`, `*.credentials*`,
  service-account JSON, cookie, or anything that authenticates. Two automated gates exist (the allowlist
  `.gitignore` + a `gitleaks`/grep pre-commit hook), but they are a backstop, not a licence to stop
  looking — **read the diff yourself.** If anything looks secret-like, or you're unsure, **STOP and ask
  Simon** rather than commit it.
- **Human authority:** propose the commit; confirm with Simon before pushing (unless he already said
  "commit and push"). Never force-push. Never rewrite published history.
- **Scope:** only Simon's own config (CLAUDE.md, hooks/, settings.json, contracts/, skills/sk,
  references/ (shared on-demand catalogs), rules/ (if present), dotfiles/, README/AGENTS, .githooks/).
  Never add third-party skills or runtime data — the allowlist `.gitignore` handles this; don't fight it.
  **`skills/sk-work` and `work/` are deliberately untracked** (job-specific, see README). They will
  never appear in a diff; if they ever do, something force-added them and that is a bug to report,
  not a change to commit.

## Steps
1. **See what changed:** already injected above. Summarize it for Simon. Pull the full
   `git -C ~/.claude diff` only for the files you need to inspect properly.
2. **Eyeball for secrets** in the diff (see the rules above). This step reads the REAL diff, not the
   summary — `--stat` shows names and line counts, never content, so it cannot clear a file of
   secrets. If clean, continue; if not, stop and ask.
3. **Stage:** `git -C ~/.claude add -A` (or stage selectively if only some changes should go).
4. **Commit with the message in a FILE, never `-m`:** write it with the Write tool, then
   `git -C ~/.claude commit -F <file>`. The shell interprets `-m` and heredocs (a backtick runs, a
   `$VAR` expands) and it fails SILENTLY, which is why `~/.claude/references/git-pr-deploy.md` makes
   `-F` absolute at any length. That catalog also owns the subject and body shape — read it there
   rather than composing a message from scratch. Two hooks gate the result: `.githooks/commit-msg`
   rejects a non-conforming subject, and the pre-commit hook runs `gitleaks` (or the grep fallback)
   and **blocks on any secret**. If either blocks, surface the reason to Simon and fix it; never
   bypass with `--no-verify`, which skips the secret gate too.
5. **Push:** `git -C ~/.claude push`.
6. **Confirm in sync:** `git -C ~/.claude status -sb` shows a clean tree and `## main...origin/main`
   with nothing ahead.

## Notes
- Manual one-shot equivalent: `bash ~/.claude/dotfiles/sync-config.sh` (stages, secret-scans, commits with
  a timestamp message, pushes). Prefer a descriptive commit via the steps above for real changes; the
  script is the catch-all.
- If `gitleaks` flags a genuine false positive (e.g. a detection pattern in a scanner file), add a narrow
  allowlist to a repo `.gitleaks.toml` rather than disabling the gate.
- If a secret was *already* committed, don't just delete it — tell Simon; it needs history rewrite +
  rotation of the exposed credential.
