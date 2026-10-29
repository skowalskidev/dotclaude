# Code Best Practices

Reference catalog for engineering-quality standards: code quality (DRY/SRP, reuse-before-build), logging/observability/failure handling, UX/UI standards, and scope discipline. Loaded on demand by skills and CLAUDE.md.

## Code quality

- Keep everything DRY and SRP. Reuse existing components, utilities, types, and infrastructure before writing anything new; refactor to extract reusable components when warranted.
- When consolidating several similar components into a shared base, extract ONLY their overlapping/shared behavior into the base; keep each component's unique features intact and lose no functionality in the refactor. DRY where it genuinely removes duplication — don't over-consolidate or force-merge components whose differences outweigh their overlap.
- Decide explicitly whether new types are needed or existing ones should be reused; introduce new ones only when the feature warrants it.
- When logic stops being specific to one provider/service, refactor it to be generic with provider-specific code isolated — especially when adding a second provider of the same kind.
- Use the codebase's existing data-fetch mechanisms rather than inventing new ones (check what's used — search index, direct DB, etc.).
- For any UI work, enumerate every interface element (filters, buttons, controls) and verify each has a working backend handler.
- Before keeping a mechanism (e.g., polling), investigate whether a better one exists and verify online; if the current one turns out best, keep it — but check first.

### Shell commands

#### Agent-written shell fails fast and loud

`rules/process.md` § Agent-written shell points here. Applies to every script, compound command, trap
and background loop an agent writes.

**DO, in a multi-step command run through the agent's shell tool, chain every dependent step with `&&`,
or run the whole script inside `bash -c '<script>'` or a script file.** Open a script file or a
`bash -c` body with `set -euo pipefail`. Use `git -C <dir>` instead of `cd <dir>` for git.
**DON'T rely on `set -e` typed at the top of a tool command.** The harness evaluates the command inside
an `&&` list, where the shell disables errexit, so the next step runs after a failure (the fix for a
config sync where a rejected commit and a failed staged-list check ran on unnoticed).
TEST: a multi-step tool command with no `&&` chain and no `bash -c` or script-file wrapper relies on
`set -e` and broke the rule. Quick check: `set -euo pipefail; false; echo x` prints `x` in the tool.
**DON'T put `;` after a `cd` or after any step a later step depends on.** When the `cd` fails, the steps
after `;` run in whatever directory the shell was already in (the fix for a `git merge --ff-only` that
ran in another checkout and moved its local main after `cd <missing-dir> && …; git merge …`).
TEST: zero `;` after a `cd`, a lookup or a build in the command.

**DO let a lookup, `cd`, cleanup or release step fail loudly.** Silence one (`>/dev/null 2>&1 || true`)
only when its failure is harmless, and say why in an inline comment.
**DON'T silence a release, unclaim or teardown inside a trap.** A swallowed failure leaves the claim
held for another session to chase (the fix for a trap whose silenced simulator `release-sim` failed
and kept the claim). Print the error and exit non-zero.
TEST: every `|| true` or `>/dev/null 2>&1` on a lookup, `cd`, cleanup or release step carries an
inline reason.

**DO check every value a loop depends on (a run id, a PR head sha, a path) non-empty before the loop
starts:** `[ -n "$RUN" ] || { echo "no run for $SHA" >&2; exit 1; }`. An empty or unknown value aborts
with what was looked up; it never reaches the poll.
TEST: no loop body uses a lookup result that was not checked non-empty first.

**DO give every background wait or poll an exit condition, a timeout, and a non-zero exit printing the
last state it saw on timeout or on any state it does not recognise.** The completion notification then
carries the problem. Read the first interim output within 2 minutes of launch and at every check-in.
**DON'T leave a background wait unread until it finishes.** (the fix for a CI wait that spun 30
minutes on usage errors from an empty run id.) The CI wait script lives in `references/git-pr-deploy.md`
§ After a push.
TEST: every background wait states its condition and timeout, and its first output was read within 2
minutes of launch.

**DO stop a watcher, poll, monitor or scheduled wake the moment its target finishes or its owner hands
back,** and stop each one you started before your own hand-back. A delegated worker stops its own
before returning. DON'T leave a timer that wakes an agent whose work is done: every wake is a full model
turn (the fix for stale watcher timers that kept waking finished PR agents and burned quota).
TEST: at hand-back, no background task or wake you started outlives the job it watched.

**DO read a poll's state from a field when the command's exit code encodes a status.** Under `set -o
pipefail`, `gh pr checks` (8 while checks are pending), `grep -q` (1 on no match) and `diff` (1 when files
differ) turn "still running" into "done" inside a loop or `if` condition. Poll a JSON field instead, e.g.
`gh pr view <n> --json statusCheckRollup --jq '[.statusCheckRollup[] | select((.status // "COMPLETED")
!= "COMPLETED")] | length'`, or guard the command with an inline reason: `(gh pr checks <n> || true) |
grep -q pending  # exit 8 means pending`. (the fix for a CI wait that reported done with 15 checks
still pending.)
TEST: no loop or `if` condition under pipefail pipes a status-coded command without a guard or a
field read.

**DO brace every variable that a colon follows: `"${src}:${dst}"`, never `"$src:refs/..."`.** zsh reads an
unbraced `$var:` plus a letter (`:r`, `:h`, `:t`, `:e`, `:a`, `:l`, `:u` and more) as a history modifier,
even inside double quotes, and rewrites the value with no error. This hits git refspecs, `host:port`,
`user:group` and `key:value` (the fix for `git push origin "$c:refs/..."`, which zsh expanded as
`${c:r}efs/...` and git rejected with `src refspec <sha>efs/... does not match any`).
TEST: no `$name:` without braces in the command.

**DON'T keep a command or a word list in a scalar variable.** zsh does not word-split an unquoted `$var`:
`L="lockf -k …"; $L xcodebuild` exits 127, `sed -i … $files` receives the whole list as one path, and
`for p in $ids` runs once. Write the command out or use a function; hold a list in an array, expand
it with `${=var}`, or pipe a NUL-separated producer into `xargs -0`.
TEST: no `$VAR` in command position, and no scalar holding several words is expanded as arguments or
a loop list.

### Naming — the reader must not have to open the implementation

Applies to anything someone else reads to decide what a thing does: variables, functions, files,
skills, rules, config keys, commit scopes.

**Make the name reveal the intent.** It should say why the thing exists and what it does, so nobody
opens it to find out (Martin, *Clean Code* ch.2). `eyeball` and `d` fail this. `test-eyeball` and
`elapsedTimeInDays` pass. Avoid names that mislead: don't call something a `List` unless it is one.

**Scale the length to the scope.** The greater the distance between where a name is declared and
where it is used, the longer it should be (Pike, *Notes on Programming in C*; the same rule in Uncle
Bob's "the length of a variable name should be proportional to its scope"). A loop index is `i`
because its meaning is one line away. A globally-visible thing has no surrounding context at all, so
it earns a long evocative name.

**Both halves matter.** The second is the limit on the first: a shared helper used in rich local
context should stay generic, and a reusable utility named after its first caller is a worse name,
not a better one. Length is the consequence of clarity, never the target. If a shorter name is
equally unambiguous to someone who has not read the code, it wins.

**Worked example, `~/.claude` itself:** skills are `<group>-<what-it-does>` because they appear in a
flat global menu. The group list is data in `contracts/skill_naming.py` and the config suite fails on
a skill that matches no group.

### Single source of truth — derive, don't duplicate (DRY / SRP)

Owned by **`~/.claude/rules/engineering-standards.md` § "Single source of truth"**, which is always-on
and so already loaded whenever you are reading this. Not restated here.

That is not tidiness for its own sake. This file used to carry its own copy of that rule, and by
2026-08-03 the copy had silently lost two of the owner's bullets — "share BEHAVIOUR, not just values"
and "a new guard belongs on every path that needs it". Anyone reading the copy got a weaker rule than
the one Simon wrote, which is precisely the failure the rule predicts. `hooks/config-contract.test.py`
now fails on a paragraph that appears in two config files.

## Logging, observability, failure handling

- Add verbose logging to everything at every step so final testing and debugging is easy.
- Log data shapes so correct types can be verified at every point in the flow.
- Handle version/compatibility requirements (e.g., minimum API version) at the connection-verification stage and tell the user exactly what's wrong; pin third-party API versions explicitly so payload shapes match SDK types.
- Ensure all errors land in centralized logging (cloud logs or equivalent) so production bugs are diagnosable without relying on a customer's recollection or reproduction attempts.
- Surface failures to the end user whenever an automated action fails and needs manual intervention — never fail silently.
- Implement every failure branch the plan/docs call out (declines, misses, retries) using existing infrastructure unless the plans say otherwise.

## UX/UI

- Research current best UX/UI practices online for the feature, and include mobile design.
- Add loading skeletons wherever data loads into interface elements.
- Interactions must never freeze the interface: use optimistic updates; on navigation, show the next page immediately with a loading state instead of blocking until data arrives.
- Every item/state the feature surfaces to the user must be resolvable/actionable — no dead ends.

## Scope discipline

- Don't invent new things: if the existing system already provides a behavior, the new feature retains that behavior and scope — do not change present behavior unless explicitly asked.
- Note what already works in the codebase and build on it rather than rebuilding it.
- **DO make at most one small, reversible change for a defect in code outside your task that you cannot
  reproduce** (a screen on the tester's device), then write the finding up with its evidence and stop.
  A second unconfirmed attempt is a ticket, not a fix. DON'T iterate on the tester's device by guesswork:
  each unconfirmed change risks a regression in code you do not own. TEST: at most one change per such
  defect, and a finding naming the evidence (the fix for three layout tweaks to an unowned
  screen, two reverted, when the cause was the viewport height with the keyboard open).
