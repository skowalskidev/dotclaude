# Session auto-resume: the hourly watchdog

`bin/session-auto-resume.py` is the one persistent background job this config installs. Once an
hour, launchd runs it OUTSIDE Claude: it reads local files only, makes zero model calls for the
check, and resumes each session that stopped with unfinished work, in place, with `claude -p
--resume`. A run with no qualifying session does nothing and costs nothing.

WHY: a session stopped by a usage limit, an API or network error or a crash stays stopped. Claude
Code's own wait lives inside the open interactive process, and an in-session `CronCreate` resume
dies with the session it was meant to rescue (the fix for an overnight Conductor session that stopped
on the 5-hour limit and sat until Simon asked "did you get stuck?").

## Install, check, remove

DO install, check and remove it with the engine itself; each command is idempotent:

```bash
CLAUDE_ALLOW_DAEMON=1 /usr/bin/python3 ~/.claude/bin/session-auto-resume.py install   # writes + loads the LaunchAgent
/usr/bin/python3 ~/.claude/bin/session-auto-resume.py run --dry-run   # lists what it would resume and why, resumes nothing
/usr/bin/python3 ~/.claude/bin/session-auto-resume.py status          # launchd state, last exit, tracked sessions
/usr/bin/python3 ~/.claude/bin/session-auto-resume.py ignore <session-id>   # keep one session stopped
/usr/bin/python3 ~/.claude/bin/session-auto-resume.py uninstall       # boots it out and deletes the plist
```

DON'T run `install` unless Simon asked for this job: `hooks/background-process-guard.py` denies it
without the inline `CLAUDE_ALLOW_DAEMON=1`. `install` fills `dotfiles/session-auto-resume.plist`
from `$HOME` and writes `~/Library/LaunchAgents/com.dotclaude.session-auto-resume.plist`.
DO run `uninstall` before deleting or moving the script: a login item pointing at a deleted script is
the mess to avoid. TEST: `launchctl print gui/$(id -u)/com.dotclaude.session-auto-resume` succeeds
exactly while the plist exists.

## What qualifies

DO resume a session only when ALL of these hold; the dry run names the first that fails:

1. **It stopped on an error or died mid-turn.** Its newest main-thread record (not sidechain, not
   meta) is an API-error record, or a tool call or prompt with no answer after it; or its
   `StopFailure` marker (below) is newer than that record. A normal end of turn, an
   `[Request interrupted by user]` and a pending `AskUserQuestion`/`ExitPlanMode` never qualify.
2. **The error is one waiting can clear:** usage limit, 429, 529 overloaded, 5xx, connection or TLS
   failure, sign-in failure, unknown, or a crash. `invalid_request` (e.g. "Prompt is too long"),
   usage credits required, billing and account holds repeat identically, so they get one
   notification instead.
3. **The config's own record shows unfinished work:** an active living plan
   (`.context/*-plan.md`, `phase` not `complete`) with a section not `done`, an ask in
   `.context/intent-ledger.md` with no `reconcile` after it, or a stop mid tool loop. The root is
   `~/.claude/.session-root/<id>`, else the git top level of the session's first `cwd`.
4. **It is recent and idle:** last record within 48 h and transcript untouched for 15 min.
5. **Nothing holds it:** no live Claude process lists it in `~/.claude/sessions/<pid>.json` (checked
   with `ps -p <pid> -o comm=`, never arguments), the watchdog's own resume of it is not running,
   and Conductor (read-only `conductor.db`) shows it `idle` or `error`, not closed, hidden or in an
   archived workspace.
6. **It belongs to the signed-in account and spends nothing extra:** its `session-owner`
   `accountUuid` matches `~/.claude.json` `oauthAccount`, and that account has
   `hasExtraUsageEnabled` false; with extra usage on, a resume could bill
   (`rules/spend-approval.md`), so every resume pauses and Simon is told once.
7. **It is a main session:** a session whose first record says `entrypoint: sdk-cli` is a headless
   `claude -p` worker its supervisor owns; only `run --session <id>` resumes one.

## Retry, quota and caps

DO wait out a stated usage-limit reset: skip until `quotaLimits.resetsAt` plus 2 min. The newest
reset any session of that account reported holds EVERY session of the account, so no attempt is
spent before the shared limit resets. Everything else retries on the next hourly run.
NUMBER: one attempt per session per run (55 min minimum gap), at most 24 attempts per session in
48 h; the 24th refusal notifies once. A resume that fails on quota or the network writes its own
error record, which the next run reads; nothing retries inside a run.
TEST: two runs inside one hour start at most one resume per session.

## How it resumes

DO start `~/.claude/bin/claude-launch.py -p --resume <id> --output-format json --permission-mode
<the session's last recorded mode>` detached, in the session's first `cwd`, through `/bin/zsh -l`
so the resumed tools get Simon's PATH (Homebrew, nvm Node 24; `claude-launch.py` needs Python 3.11).
DON'T add `--permission-mode` when the transcript records none, and never pass a broader mode:
`claude -p --resume` otherwise starts in a new `-p` run's default mode.
DO send only the fixed prompt in `PROMPT` with a cause from the fixed list. No transcript text
reaches the prompt, so a transcript cannot inject instructions into the resume.
DO set `AGENT_SESSION_RESUMED=1`: `claude-launch.py` then leaves the run unmarked as a delegated
worker (it owns its plan), `hooks/task-intake.sh` gives one continue-your-plan notice, and
`hooks/intent-ledger.sh` records no ask, because the prompt is the watchdog's, not Simon's. The
watchdog writes its own `note plan` line to the session's ledger instead.

**Conductor sessions resume through the CLI, not Conductor's UI.** Conductor (0.97.0) documents no
local way to message a session: its `conductor` CLI and API (`POST /v0/sessions/{id}/messages`)
manage cloud workspaces with an API token, its deep links only prefill a new workspace's composer,
and its `SendSessionMessage` tool runs inside a Claude session (quota-bound). So the resumed turn
lands in the same transcript; Conductor's chat shows it after the session is reopened. DON'T type in
a resumed Conductor session until `status` shows it no longer running: two writers on one transcript
can drop messages ([Claude Code sessions docs](https://code.claude.com/docs/en/sessions)).

## Telling Simon

DO notify through `osascript` once per cause streak: "resumed after <cause>" on the first attempt
or a changed cause, and "needs you" once per reason for the cap, extra usage or an error waiting
cannot clear. Hourly repeats are logged, not announced.
DO log session ids, causes, counts and outcomes only, to `~/Library/Logs/session-auto-resume.log`
(rotated at 512 KB, 3 kept; the launchd stdout file rotates at 1 MB). State lives in
`~/.claude/state/session-auto-resume/` (untracked). TEST: no log line holds transcript text, a title
or a secret value.

## The StopFailure marker

`settings.json` wires `session-auto-resume.py record-stop` on `StopFailure`, the documented hook
that fires "when the turn ends due to an API error" with an `error` type
([hooks reference](https://code.claude.com/docs/en/hooks)). It writes
`state/session-auto-resume/stops/<id>.json` holding only `error` and `at`, so detection survives a
change in the internal transcript format; a crash fires no hook, so the transcript stays the primary
source. Markers older than 7 days are pruned.

## Research behind it (2026-11-22)

- **Resume from a script:** `claude -p --resume <id> "<prompt>"` sends a follow-up to an existing
  session; `--resume` searches every project by ID; `-p --resume` starts in a new `-p` run's
  permission mode, so the mode is passed explicitly ([CLI reference](https://code.claude.com/docs/en/cli-reference),
  [sessions](https://code.claude.com/docs/en/sessions)).
- **Transcripts:** `~/.claude/projects/<cwd with non-alphanumerics as ->/<session-id>.jsonl`; the
  docs call the entry format internal and version-dependent
  ([sessions](https://code.claude.com/docs/en/sessions#where-transcripts-are-stored)), hence the
  marker and the fixture suite. Observed on Claude Code 2.1.321 to 2.1.329: an assistant record with
  `isApiErrorMessage: true`, `error` (`rate_limit`, `server_error`, `authentication_failed`,
  `invalid_request`), `apiError` (`usage_limit_reached`, `connection_failed`, `tls_untrusted_ca`,
  `model_requires_usage_credits`), `apiErrorStatus` (429, 500, 529) and `quotaLimits.resetsAt`
  (epoch seconds); `session-owner.accountUuid`; `permissionMode` on user records.
- **Built-in options cover open interactive sessions only.** `autoContinueAtUsageLimit` "waits in
  the open session", stops after three continuations and resumes nothing whose process ended
  ([interactive mode](https://code.claude.com/docs/en/interactive-mode#wait-for-a-usage-limit-to-reset),
  [settings](https://code.claude.com/docs/en/settings-reference)); Desktop's "Auto-continue when
  limits reset" is the same idea in the Code tab ([week 33](https://code.claude.com/docs/en/whats-new/2026-w33)).
  Claude Code already retries 5xx, 529 and dropped connections up to 10 times
  (`CLAUDE_CODE_MAX_RETRIES`; `CLAUDE_CODE_RETRY_WATCHDOG=1` retries 429/529 indefinitely in a live
  process) ([errors](https://code.claude.com/docs/en/errors)). The background-session supervisor
  restarts only crashed `--bg` sessions ([agent view](https://code.claude.com/docs/en/agent-view)).
  None of these reaches an Agent SDK (Conductor) session after its process ends.
- **Retry practice:** honor the server's stated wait before retrying (`retry-after`,
  `anthropic-ratelimit-*-reset`, [rate limits](https://platform.claude.com/docs/en/api/rate-limits));
  here that is `quotaLimits.resetsAt`, and the hourly cadence is the backoff.
- **Community tools, rejected:** [terryso/claude-auto-resume](https://github.com/terryso/claude-auto-resume)
  (821 stars, last push 2026-05) runs in a terminal you leave open and passes
  `--dangerously-skip-permissions`, which broadens permissions;
  [cheapestinference/claude-auto-retry](https://github.com/cheapestinference/claude-auto-retry)
  (394 stars, active 2026-10, MIT) wraps a live session in tmux, so it cannot reach a session
  Conductor launched or one whose process ended; its README defers the open-session case to the
  native feature. Neither reads the living plan, so neither can tell finished work from unfinished.
- **Scheduler:** launchd, not cron, per Apple ("cron ... has been deprecated in favor of launchd").
  `StartCalendarInterval` (minute 17) runs on wake after a missed hour; `StartInterval` "will be
  missed" while asleep (`man launchd.plist`,
  [Apple: Scheduling timed jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)).
  No `RunAtLoad` (the man page says avoid it); `ProcessType Background`; `AbandonProcessGroup` plus
  a new session id keep a started resume alive after the run exits. Load with
  `launchctl bootstrap gui/$UID <plist>`, remove with `launchctl bootout gui/$UID/<label>`.
- **Name:** "auto-resume" by vendor tally: resume 3 (Claude Code `--resume`, terryso,
  [the OpenAI community request](https://community.openai.com/t/feature-request-auto-resume-after-usage-limit/1397124)),
  continue 2 (Anthropic Desktop, [oguztecimer/claude-auto-continue](https://github.com/oguztecimer/claude-auto-continue)),
  retry 1 (cheapestinference).
