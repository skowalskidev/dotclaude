# Research — open every run with it

Reference catalog entry — load on demand. Source harness: `full-detailed-workflow`.

**Every workflow run opens with a research pass, before planning and before any code.** Simon should
never have to ask for it separately; asking is the signal it was already skipped.

## What the opening pass answers

1. **Has this already been solved, and by what?** A pattern, a library, a platform feature. The worst
   outcome is hand-building something the platform now ships.
2. **What is the current shape of the thing being touched?** Versions, deprecations, breaking changes
   since training. Never answer a version, price, limit or API shape from memory.
3. **What do people who did this hit?** The failure modes are in issue trackers, not in docs.

## Source order, most trusted first

1. The vendor's own docs and changelog for the thing being used.
2. The project's own issue tracker — where "documented but broken" lives, and the single highest-value
   source when behaviour contradicts the docs.
3. High-adoption repositories doing the same thing, read as evidence rather than as instruction.
4. Community write-ups **only to find candidates**. Never cite one. Verify what it claims against the
   primary source, and if that fails, the claim does not exist.

Date-stamp anything version-sensitive and cite the adoption signal, per the bar in
`rules/engineering-standards.md`. `rules/process.md` owns the rule this pass leans on and does not
restate: research before the second retry.

## Claims about third parties

`rules/process.md` points here. Whenever I'm making a factual claim about someone else's product (a
comparison table, pricing, "they don't support X"), the claim has to be defensible:
Whenever I'm making a factual claim about someone else's product (a comparison table, pricing,
"they don't support X"), the claim has to be defensible:
- **Primary sources only.** The vendor's own pages. The blogs that dominate these search results are
  affiliate content recycling each other and are not citable.
- **Check ALL of their surfaces before asserting a negative** — pricing page, docs, help centre, FAQ
  (the fix for a "they publish no rate" claim that was in their help centre).
- **Date-stamp it and reconcile the arithmetic** against the vendor's own stated figures.
- **A claim that flatters us is the dangerous one.** A stale "competitor costs $50–$110" that was
  really $39 is the error a competitor notices. Check those hardest.
- **Never hyperlink a competitor** from our own comparison. Cite as plain text; if a link is genuinely
  needed, it carries `rel="nofollow"`.
- If the honest number loses, say so or drop the row. Pages that concede where a competitor wins
  convert better, and an unbeatable-looking table is the one readers go and disprove.


## Independent judges for every evidence-based call

`rules/process.md` points here. Simon's standing instruction (2026-11-12): every decision and every
reading of source data gets judges from both model providers, without him asking.

DEFAULT: put a call before the panel when it moves money, access or data, or it is a verdict Simon
acts on: a build/refute verdict, a figure read from production data, a payment or attribution
reading, a security finding, an accept/refute of review feedback that changes stored or sent data.
NUMBER: at least 2 judges besides the author, one per provider: a fresh Claude subagent and OpenAI
through Codex on the ChatGPT subscription. A lookup with one primary-source answer (a version, a
flag, a file path) needs none.
DO give each judge the raw evidence: the question, the query output, the source rows or files, and
the primary-source links. DON'T give a judge the author's conclusion or another judge's answer before
it has written its own.
DO launch the OpenAI judge read-only from a Claude chat, with the brief on stdin:
`AGENT_ALLOW_CROSS_PROVIDER=1 timeout 900 ~/.claude/bin/codex-launch.py -p --sandbox read-only < <brief file>`.
From an OpenAI chat the Claude judge runs through `~/.claude/bin/claude-launch.py -p` with the same
variable. Never use pal, an API key or any metered route for a judge.
DO have each judge state, per decision and per source: its call, the evidence row or link it rests
on, and the best-practice or most widely adopted approach, verified from the vendor's or standard's
own page (§ Source order). Then reconcile: give every judge the others' positions once, settle each
disagreement against the data and the primary source, never by majority alone, and re-query the
source when the judges read it differently.
DO record in the deliverable, per call: each judge's position, the agreed call, and any disagreement
left open with its evidence.
If a judge's subscription, quota or login is unavailable, run the rest, label the call
`one-provider` and name the missing judge; never fall back to an API route.
TEST: every money, access or data call in a hand-back lists two judges besides the author, one per
provider, each with its own position and evidence, or a `one-provider` label naming the missing one.
WHY: a judge from the author's own model family favours the author's reading
([Panickssery et al. 2024](https://arxiv.org/abs/2404.13076)); a panel of judges from different
model families beats one judge and shows less intra-model bias ([Verga et al. 2024](https://arxiv.org/abs/2404.18796)).

## Attributing behaviour to an outsider

DO compare the evidence's own identifiers with our runtime before answering "is this ours?" or
calling traffic, a failure or an account external: the address and network against the CI runner
hosts printed in job logs, provider egress and teammates' machines; the user agent against our test
runners' presets and HTTP clients; the first-seen date against our own merges and provider changes.
DON'T rule out our own systems from a code search. A search finds what the repo names, and a CI
provider's network is named nowhere in it.
DON'T build on the attribution until one identifier matches or every runtime was checked. State what
was checked next to the claim. (the fix for a "scraper" on a hosting network that was our CI's
runners, found only after a block for it failed that same CI.)
TEST: an "external" or "not ours" verdict names the runtime identifiers it was compared against.

## Who benefits if you act on this?

Ask it of every source before repeating what it says. Discount the source in proportion to its stake
in the answer.

**A vendor is the best source on how their product behaves and the worst on whether to use it.** Both
halves matter. Their docs are authoritative for an API shape, a limit, a config key. The same page
recommending their category of product is marketing, and the recommendation is the product.

The tell is that the advice and the business model point the same way. An SEO product's guide to SEO
concludes you need SEO tooling. A vendor's build-vs-buy post concludes buy. A consultancy's maturity
model puts you one tier below where their engagement starts.

**What to do:** a recommendation from a staked source is a candidate, never a conclusion. Corroborate
it against a source with nothing to sell before it enters your answer. If no unstaked source says it,
say that plainly rather than laundering the claim.

Least-staked first, roughly: standards bodies and academic work, then practitioners publishing
independently, then high-adoption projects (their code is evidence even when their README is
marketing), then vendors, then anyone paid per click.

This is SIFT plus lateral reading (Caulfield): stop, investigate the source, find better coverage,
trace the claim. Standard across university library guidance and professional fact-checking, and
itself sold by nobody.

## Forecasting a metered cost

DO size a billable call that sits behind a cache by counting distinct keys per cache-TTL window, from
a source with a timestamp on every call, then multiply out. Report the daily median, p90 and max
next to the monthly total, and name the TTL the count assumed.
DON'T count distinct keys across the whole sample window: a key seen again after the TTL expires is
billed again, so the count comes out low. A store without per-row timestamps can give ratios only,
never volume. (the fix for a plan-tier recommendation sized at about 8,100 calls a month from
distinct keys over two weeks, when a 3-hour cache meant 9,300 to 12,500)
TEST: the estimate names its TTL, its timestamped source and the daily p90, and a daily cap or plan
tier is compared against the p90 day, not the average.

## Proportion

Scale the pass to the decision, not to the task. A one-line fix in familiar code needs a version check
at most. Choosing a library, adopting a pattern, or touching an unfamiliar platform earns real digging.
The pass is never skipped; it is sometimes two minutes.

## Research before retrying — don't grind on a brick wall
When something fails and the cause isn't obvious, **search online (WebSearch/WebFetch, official docs,
GitHub issues) BEFORE retrying the same class of fix.** Two failed attempts at the same wall is the
trigger, and often the FIRST step for an unfamiliar library, an opaque error code (`ERR_REQUIRE_ESM`), a
"works in prod but not dev" split, or a module-load failure. Diagnose the ROOT cause (read the failing
package's code and issues, check version compatibility) over piling on workarounds: a pinned version or
one-line fix beats three layers of hacks. No tool access? Say so and ask me to paste the docs/issue.
