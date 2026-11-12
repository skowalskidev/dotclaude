# Code Best Practices

Reference catalog for engineering-quality standards: code quality (DRY/SRP, reuse-before-build), logging/observability/failure handling, UX/UI standards, and scope discipline. Loaded on demand by skills and CLAUDE.md.

## Pin versions in the repo

`rules/engineering-standards.md` § Versions owns the latest-stable default; this section holds the
pinning detail.

**Encode the versions in the repo so they're reproducible:**
- **Node:** a `.nvmrc` pinning the exact version (e.g. `24.18.0`) for `nvm use`, plus `engines.node` as
  a floor (e.g. `>=22`). Keep local dev, `.nvmrc`, and any serverless pin (Firebase
  `functions/package.json` `engines.node`) consistent.
- **Toolchain quirks:** a newer tool can need a newer Node than the project's default (e.g. Vitest 4's
  rolldown needs Node ≥20.12 for `node:util`'s `styleText`) — pin up, document it, tell me to `nvm use`.
- Other ecosystems pin equivalently (`.python-version`/`pyproject`, `.tool-versions` for asdf/mise,
  `packageManager`).

When bumping to "latest", apply then **build + test to verify**, and watch peer-dependency ceilings
(e.g. `firebase-functions@7` peer-requires `firebase-admin <=13`) — pin back what the ecosystem doesn't
support yet and tell me which and why.

## Code quality

- Keep everything DRY and SRP. Reuse existing components, utilities, types, and infrastructure before writing anything new; refactor to extract reusable components when warranted.
- When consolidating several similar components into a shared base, extract ONLY their overlapping/shared behavior into the base; keep each component's unique features intact and lose no functionality in the refactor. DRY where it genuinely removes duplication — don't over-consolidate or force-merge components whose differences outweigh their overlap.
- Decide explicitly whether new types are needed or existing ones should be reused; introduce new ones only when the feature warrants it.
- When logic stops being specific to one provider/service, refactor it to be generic with provider-specific code isolated — especially when adding a second provider of the same kind.
- Use the codebase's existing data-fetch mechanisms rather than inventing new ones (check what's used — search index, direct DB, etc.).
- For any UI work, enumerate every interface element (filters, buttons, controls) and verify each has a working backend handler.
- Before keeping a mechanism (e.g., polling), investigate whether a better one exists and verify online; if the current one turns out best, keep it — but check first.

### Mount a shared part the way its existing callers do

**DO read every existing call site before mounting a shared component, screen, hook or helper at a NEW
call site, and copy the mounting contract they share:** the wrappers, frames and providers around it,
the props passed alongside the ones you pass, the layout context it assumes (a full-height parent, a
scroll container, safe-area insets, a theme) and the events or callbacks they wire. Find them with
`git grep -n '<ComponentName\b'` plus its re-exports. NUMBER: read all of them; above 10, read every
caller passing the same props you pass, and count the rest.
**DO state any deliberate difference from the callers and why** in the PR's `## Regression check`
table (`references/testing-strategy.md` § Regression check), one row per newly mounted shared part
holding `mirrors <path>:<line>` and `difference: none`, or the difference and its reason.
**DON'T wire a shared part from its own props type alone:** its signature never shows the frame its
callers wrap it in, so the part renders, type-checks and passes its tests while laid out wrong.
TEST: for each shared part the diff newly mounts, the PR names the existing caller it mirrored, or the
stated difference and reason. (e.g. a sign-in screen mounted with a flag prop but without the
full-height frame every other caller with that prop supplies: its primary buttons floated mid-screen
instead of pinning to the bottom, and unit, type and e2e checks all passed.)

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
**DON'T write a step and its success line as one `&&` list inside a `set -e` script** (`cmd > log
&& echo PASS`): errexit ignores a failing command anywhere but last in an `&&` or `||` list, so the
script continues past the failure and ends with every later line printed as if the run passed. Write
`cmd > log || { echo "FAIL step"; tail -20 log; exit 1; }` or an `if ! cmd; then … exit 1; fi`, so
the failing step itself is the last word (the fix for a real-stack script whose six failed steps
printed no PASS line, exited 0 and reported DONE).
TEST: in a `set -e` script, zero lines of the form `<step> && echo …`; every step's failure path
names the step and exits non-zero.
**DON'T end a tool command inside a subdirectory** (`cd site/web && npx vitest …`): the harness keeps
that directory for the next command, so a later relative path resolves under it. Run a subproject tool
with `npm --prefix <dir> …` or inside a subshell `(cd <dir> && …)`, and start every multi-step command
from an absolute path (the fix for a base worktree created under `site/web/.context` and a results move
that silently did nothing, two commands after a test run that ended in `site/web`).
TEST: no tool command's last `cd` leaves the session in a subdirectory; every path in the next command
is absolute or anchored by its own leading `cd`.
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
carries the problem. Keep the loop's summed waits at least 5 minutes under the background tool's cap (2
hours for a `run_in_background` Bash task): the cap kills the loop with no verdict. Read the first
interim output within 2 minutes of launch and at every check-in.
**DON'T leave a background wait unread until it finishes.** (the fix for a CI wait that spun 30
minutes on usage errors from an empty run id.) The CI wait script lives in `references/git-pr-deploy.md`
§ After a push.
TEST: every background wait states its condition and a timeout below the tool's cap, ends with its own
timeout verdict, and its first output was read within 2 minutes of launch.

**DON'T let a "nothing pending" exit pass on an empty set.** A wait for CI checks, jobs or files first
requires the expected items to exist for the right head or id (e.g. the check count for the head sha is
above zero), then waits for none pending.
TEST: a wait loop whose done-condition is "no pending items" also checks the item count. (the fix for
CI watches that reported done before the PR's checks had registered.)

**DO send a background command's full raw output to a log file and filter only when reading it.** A
watcher on a queued heavy job also fires on the wrapper's first waiting line and on no new output
for 5 minutes, not only on terminal states. When a job Simon is waiting on is queued, tell him at the
first check what it is queued behind and what clears it, before he asks.
**DON'T filter a wrapper's waiting or queued lines out of the command itself** (`| grep -v`).
TEST: no background command contains a `grep -v` of its own status lines; a 0-byte output file at the
2-minute read counts as unknown state, so inspect the capacity status (`local-capacity.py status`)
instead of reading it as progress (the fix for a simulator launch that sat deferred 26 minutes behind
`grep -v "capacity waiting"` until Simon asked whether it was stuck).

**DO stop a watcher, poll, monitor or scheduled wake the moment its target finishes or its owner hands
back,** and stop each one you started before your own hand-back. A delegated worker stops its own
before returning. DON'T leave a timer that wakes an agent whose work is done: every wake is a full model
turn (the fix for stale watcher timers that kept waking finished PR agents and burned quota).
TEST: at hand-back, no background task or wake you started outlives the job it watched.

**DO read a poll's state from a field when the command's exit code encodes a status.** Under `set -o
pipefail`, `gh pr checks` (8 while checks are pending), `grep -q` (1 on no match) and `diff` (1 when files
differ) turn "still running" into "done" inside a loop or `if` condition. Poll a JSON field instead, e.g.
`gh pr view <n> --json statusCheckRollup --jq '[.statusCheckRollup[] | select(if .__typename ==
"StatusContext" then .state == "PENDING" or .state == "EXPECTED" else .status != "COMPLETED" or
(.conclusion // "") == "" end)] | length'`, or guard the command with an inline reason: `(gh pr
checks <n> || true) | grep -q pending  # exit 8 means pending`. (the fix for a CI wait that reported done with 15 checks
still pending.)
**DON'T treat an all-complete rollup as a finished CI wait.** Right after a push the rollup lists only
the checks registered so far, so a fast side workflow can complete it while the required workflow is
still queued. Wait on the head sha's required run with `references/git-pr-deploy.md`'s recipe. (the fix
for a watcher that reported green on 3 checks while the deploy workflow had not started.)
TEST: no loop or `if` condition under pipefail pipes a status-coded command without a guard or a
field read.

**DO judge a CI rollup by the newest entry per check identity (workflow + name), and count an entry
with an empty status or conclusion as pending.** `latest_checks` in `hooks/git-commit-guard.py` is the
reference behaviour. **DON'T fail a wait on a CANCELLED entry with a newer run of the same check:** a
concurrency group cancels the old run when an edit to the PR starts a new one.
**DO exit with its own code (e.g. 3, printing `CONFLICTING`) when `gh pr view <n> --json mergeable`
reads `CONFLICTING`.** GitHub starts no `pull_request` workflow on a conflicting PR, so the wait never
ends on its own.
TEST: a CI or merge watcher dedupes by workflow + name before judging, reads an empty conclusion as
pending, and has a separate exit branch for `CONFLICTING` (the fix for a watcher that failed a PR on a
cancelled run whose rerun had passed).

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

**DO quote a glob-like flag value (`--include='*.ts'`) and give every glob that may match nothing the
`(N)` qualifier (`x*.md(N)`), or run it in `zsh -c 'setopt null_glob; …'` or `bash -c 'shopt -s
nullglob; …'`.** zsh's default NOMATCH aborts the whole command line on one empty glob, so no other
argument is acted on. **DON'T mix a bare possibly-empty glob into a command that also takes literal
paths;** qualify it or list literal paths only. (the fix for `rm -f /tmp/a.sh /tmp/x*.md`, which deleted nothing.)
TEST: no unquoted `*`, `?` or `[` in a flag value, and no bare glob without `(N)` or null_glob shares
a command with literal paths.

**DO apply `references/dev-server-hygiene.md` § Machine-wide capacity to a script that runs leased
steps:** it owns the exit-75 stop.


### Claims from complete reads

**DO rest every absence or timing claim on reads that succeeded over its whole scope: in a data
collector an agent writes, and in every statement Claude sends or submits (dispute evidence, a reply to
a customer or teammate, a PR claim).** Record each read's status; a failed, refused or partial read
(HTTP error, permission denied, truncated page, capped pagination, an inbox no connector reaches, a
second-hand summary) is UNKNOWN, never empty. Name the channels a claim covers ("in the app, by text
or on a support call"), or drop the claim. Compare a timing claim's two messages by their own timestamps.
**DON'T** default a failed read to `[]` or `0`, and **DON'T** write "never asked", "the only
cancellation" or "replied that day" past an unread channel.
TEST: the output names every failed or partial read, and each absence or timing claim lists its
channels and rests on no UNKNOWN read (the fix for dispute evidence filed as "never asked us for a
refund" while the support inbox was unread, and "we replied that day" about a reply sent before the
request; a gatherer whose failed reads became empty lists had nearly done the same).
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

#### Use the industry's name

`rules/communication.md` owns telling Simon the standard term; `rules/engineering-standards.md` owns
naming new artifacts with it. This is the method both point at.

**DO research the term online before the first name exists,** never from memory. Read how at least
4 major vendors in the category name it on their own product or docs pages, plus a vendor-neutral
reference where one exists (a standards body, a foundation glossary, the field's canonical book).
Count the vendors using each term and take the majority term.
**DON'T take one vendor's product brand as the category term, and DON'T coin a name when the field
already has one.**
**DO record in the living plan before creating anything:** Simon's term, the chosen term, the tally
with one link per vendor page, and the date. On a split, say so and name the holdout, e.g. "three of
four call it X, one calls it Y". If research is impossible (no web access, no vendor names it), record
the name as unverified and say so in the first reply. With no shared term, name by the intent rule
above.
**DO apply the term to every name the work creates:** folders, modules, skills, workflows, branches,
env vars and keys, ticket titles, and the external registrations (chat channels, source-host apps,
webhooks, cloud resources). Check the external ones first; each rename there is a manual step outside
the repo.
**DO keep Simon's term once he says so,** and record that choice so the next run does not raise it again.
WHY: a rename after the fact touches the code plus every external app and channel registered under the
old name. (the fix for an incident-triage agent that watches production and opens fix PRs, built and
registered everywhere as a "devops bot"; the tally, run only once Simon asked whether the name was
right, read three of four for "SRE": Microsoft, PagerDuty and Datadog say SRE agent, AWS says DevOps
agent.)
TEST: the plan holds the naming tally with links before the first artifact name appears in a diff; a
hand-off whose new artifacts carry a loose term while a standard one exists fails, unless Simon kept it.

### Single source of truth — derive, don't duplicate (DRY / SRP)

**An archived record is live data with an archived flag, not a legacy schema** (the soft-archive rule in
`rules/engineering-standards.md`, read with its legacy policy of no dead code): the reading code keeps the
one current shape and filters on `archived`. No read-time fallbacks, no second shape.

Owned by **`~/.claude/rules/engineering-standards.md` § "Single source of truth"**, which is always-on
and so already loaded whenever you are reading this. Not restated here.

Worked example: `~/.zsh-work-codex.zsh` and the `~/.claude` repo are one live location each,
symlinked/tracked so `git status` is the whole test. Apply the same discipline in code.

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
- DO give a decision that falls back on a timeout (which screen a user sees, which offer applies) a wait
  at least as long as the longest sibling wait on the same path, and cover a cold start: its fallback is
  a wrong answer, not a degraded one. TEST: each such timeout names its sibling wait and a production
  cold-start timing (the fix for a 1.5 s read that sent new invitees to the wrong first screen while a
  sibling read on the same path waited longer).

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
