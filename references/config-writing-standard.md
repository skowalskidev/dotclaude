# How every line of this config is written

The one standard for `rules/*.md`, `references/*.md`, every `SKILL.md`, and the `mission` and
`criteria` fields in `contracts/config_contracts.py`.

Read it before writing or editing any of them. `hooks/config-contract.test.py` enforces the
mechanical half; the rest is on you.

WHY THIS EXISTS: on 2026-08-08 Claude proposed a config line reading *"Without one, anything
optimising this config has only local metrics to aim at, and will improve them at the mission's
cost."* Simon's verdict: *"which can be read and the reader will think 'ok' but not know what actions
to take after reading it."* The rule against that already existed and nothing checked it, so it was
violated twice in one session. A rule nobody polices is a suggestion.

## The shape of every instruction

**DO write the instruction as a DO line.** Open with an imperative verb. Name the real thing — the
command, the flag, the file, the number.
**DON'T write a description of a situation and leave the reader to infer the action.** A line the
reader finishes by thinking "ok" has failed, however true it is.

**DO add a DON'T line whenever the wrong behaviour is the tempting default** — the thing Claude
would reach for unprompted. Name the specific wrong move, not a category.
**DON'T pad every DO with a mirror-image DON'T.** A prohibition against something nobody would do
spends the reader's attention and dilutes the ones that matter.

**DO give the WHY in one clause, on its own line, when the reason changes how the rule is applied at
the edges.** [Anthropic's prompt-engineering guidance](https://claude.com/blog/best-practices-for-prompt-engineering):
explaining why a constraint exists lets the model make better calls on adjacent cases.
**DON'T write a paragraph of rationale, and don't repeat the incident that produced the rule.** One
clause, or a bracketed `(the fix for X)` tag.

## Reference a config part; never re-explain it

The config is abstraction: every skill, `references/*.md` catalog and hook states its own purpose ONCE,
in its own file. A description of it written anywhere else is a copy that drifts when the original changes.

**DO name a part you compose and stop** — `/sk:work-superspeed`, `references/parallelization.md` — with
no gloss on what it does. Its own `description` or opening line already says that.
**DON'T add a parenthetical or clause re-explaining it** — "`/sk:work-superspeed` (fans work across
sessions)" is the drift surface: the skill's real description moves and the copy lies. The precedent to
copy is `work-copilot-agile-build`'s "Drives X and Y; does not re-explain them".
**DON'T add a pointer the SAME file already carries.** Before naming a sibling skill or catalog, search
the file — if it is already referenced, the addition is pure duplication (e.g. the paragraph that named
isolate-environment, superspeed and end-report when all three were already pointed to elsewhere in the file).
TEST: every part a config file names appears WITHOUT a description of its behaviour, and appears once in
that file.

## The three things a rule must state

**DO state all three, in this order: the DEFAULT to apply, the NUMBER or threshold, the TEST that
catches a violation.**
**DON'T ship a rule missing the TEST.** If you cannot name what a violation looks like, you have not
found the rule yet — you have found the topic.

These qualify:
- "Cut the number of text sections to the minimum a human can scan-read. Count them before and after;
  if the count didn't drop, you compressed instead of deleting."
- "Default to a label only: 2-5 words, no verb. A sentence needs a reason to exist."
- "Every section a human reads is TL;DR-first and actionable. Assume they read the first line only."

These do not, and are the exact drivel this standard exists to stop:
- "Prefer less text." — no default, no number, no test.
- "Consider whether the section is needed." — a question. Claude answers yes and changes nothing.
- "Ask what decision the user makes from this block." — instructs a deliberation, not an act.
- "Be careful with X." — names a feeling.

## Banned words, because each one hides the missing number

**DON'T use: should, consider, try to, where possible, as appropriate, be careful, be mindful,
generally, typically, ideally, aim to, prefer (without a number), make sure to think about.**
**DO replace each with the number or the imperative it is standing in for.** "Prefer shorter" becomes
"at most 40 words". "Be careful with X" becomes "DO X. DON'T Y."

`config-contract.test.py` fails any `mission` or `criteria` string containing one of these.

## Missions

**DO write each `mission` as the OUTCOME the part produces, in one sentence, naming who benefits and
what changes for them.**
**DON'T restate what the part IS — that is `purpose`, and it already exists one field above.**
TEST: read a proposed diff against the mission and say "this serves it" or "this trades against it".
A mission that cannot decide that is not a mission.

- Qualifies: "A task that genuinely divides finishes sooner AND correct, with Simon uninvolved
  between dispatch and the gate."
- Fails: "Runs slices in parallel efficiently." — describes the mechanism, decides nothing.

**DO rank any proposed change against the mission FIRST and the local metric second.**
**DON'T report a change that improves a local metric while working against the mission as an
improvement.** Report it as a TRADE-OFF, labelled, for Simon to decide.

## Length

**DO delete a whole section before shortening it.** Count the sections before and after; if the count
did not drop, you compressed.
**DON'T let any single criterion run past 40 words.** Past that it is a paragraph wearing a bullet.

## Policing, so this cannot rot

**DO run `/usr/bin/python3 ~/.claude/hooks/config-contract.test.py` after every config edit, and loop
until it passes.**
**DON'T narrow a check to make a line pass.** A failure means the line is wrong. Widen the check only
when it fires on text that genuinely qualifies — a guard that cries wolf gets switched off, so a
false positive is a defect in the check.

**DO apply this standard to config edits made through `/sk:claude-config-update`, which is the only
route for them.** Its Step 4 points here rather than restating it.
