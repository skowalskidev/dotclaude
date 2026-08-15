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
