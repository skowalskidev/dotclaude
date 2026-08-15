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
`rules/engineering-standards.md`. `rules/process.md` owns two rules this pass leans on and does not
restate: research before the second retry, and third-party claims from primary sources only.

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

## Proportion

Scale the pass to the decision, not to the task. A one-line fix in familiar code needs a version check
at most. Choosing a library, adopting a pattern, or touching an unfamiliar platform earns real digging.
The pass is never skipped; it is sometimes two minutes.
