---
name: plan-research
description: Answer a research question with a corroborated, ranked, cited TLDR instead of a single-source guess, for any topic or project. Decomposes the question into sub-questions, fans out parallel agents that search the web AND the codebase and production data, then adversarially verifies every load-bearing claim (attempt to refute it, require a second independent non-conflicted source, discount sources by their stake). Ranks the surviving options best-to-worst for the actual use case, corrects the asker where the evidence says so, and hands back a human TLDR with links, never word-vomit. Tracks tasks and sub-tasks as they arise, sends research questions to spin-off agents and reserves real decisions for the user, and self-improves at the end. Use for "research X", "deep dive on X", "what is the best or most popular way to X", "compare these options", "is this claim true", "corroborate this", "what do people actually do for X", or before a decision that turns on facts you do not already hold.
argument-hint: "the research question, the claim to check, or the options to compare"
---

# Research → ranked, corroborated, cited TLDR

The failure this prevents: research that is a single blog post restated, a confident answer from
memory, a vendor's recommendation laundered into a conclusion, or three pages of word-vomit with no
ranked answer. The output is a decision-grade TLDR: the best option first, why, the tradeoffs, and a
link behind every load-bearing claim.

This is the generic engine over four catalogs you READ rather than restate: `references/research.md`
(the source-credibility method), `references/parallelization.md` (the fan-out), `references/tldr-report-formats.md`
+ `rules/copy-quality.md` + `rules/communication.md` (the output and where questions go). Open
`references/research.md` before the first search.

## Step 1 · Frame the question and split it
DO state the real question in one line and name the DECISION it feeds (what changes based on the answer).
DO split it into sub-questions that do not overlap; each becomes one parallel finder.
DO separate FACTS from DECISIONS. A fact ("does Stripe support single-use customer-bound codes?") is for
an agent to find; a decision ("do we bill on it?") is for the user. Never ask the user a fact you can
look up, and never decide for the user a call that is theirs.

## Step 2 · Track it
DO write the angles and sub-tasks into a tracker (`.context/<topic>-research/TRACKER.md` or the Task
tools) and add to it as sub-questions surface mid-run — the ones that surface are the load-bearing ones.
Mechanics: `references/planning-and-tracking.md`.

## Step 3 · Fan out — parallel, multi-source
DO run one agent per angle at once (`references/parallelization.md`). Each agent searches BOTH the web
(WebSearch/WebFetch, source-ordered per `research.md`: primary docs → issue trackers → high-adoption
repos → community as candidates only) AND the codebase/production data when the question touches what WE
already do.
DO use an in-session Workflow fan-out when the angles need WebSearch or MCP connectors. Headless
`claude -p` slices (`/sk:work-superspeed`) run with no permission allowlist, so their web/connector calls
block; reserve superspeed for file-only slices.
DO force STRUCTURED output per agent: the options, pros/cons, ADOPTION evidence, and a cited source per
claim (url + type + conflict-of-interest flag).

## Step 4 · Adversarially verify and corroborate
DO give every load-bearing claim a second independent pass (pipeline the verify stage after each finder):
attempt to refute it, and require a second non-conflicted corroborating source.
DO discount a source in proportion to its stake (`research.md` § "Who benefits if you act on this?"): a
vendor is authoritative on how its own product behaves and biased on whether to use its category. A claim
that survives only on a conflicted vendor with no corroboration does not ship — say that plainly rather
than laundering it.
DON'T recommend a fringe or low-adoption option over a proven, widely-adopted one unless the user asked
for novelty.

## Step 5 · Rank and synthesize
DO order the surviving options best-to-worst FOR THE ACTUAL USE CASE, each with its one tradeoff and the
evidence that carried it.
DO correct the asker where the evidence contradicts a premise in the question, with the evidence attached.
DON'T manufacture an objection to look rigorous, and DON'T agree by default — a premise that checked out
gets a plain "confirmed, here is why" (the bar in `work-does-this-make-sense-to-build`).

## Step 6 · Hand back the TLDR
DO lead with the ranked recommendation, then the tradeoffs, then the evidence, then open questions.
Human, actionable, no word-vomit (`copy-quality.md` + `tldr-report-formats.md`).
DO cite every load-bearing claim with a link.
DO put questions in ONE block at the end (`communication.md`) and include only the ones that are the
user's to answer; anything an agent could answer online, an agent already answered.

## Step 7 · Self-improve
DO review THIS run at the end: which angle was thin, which source type kept being wrong, what the verify
pass caught, what the tracker missed. When a durable improvement to this skill emerges, propose it via
`/sk:claude-config-update` (ask first). Most runs propose nothing — silence is the default
(`rules/self-healing-config.md`).

## Scale to the decision
DO match the pass to the decision: a one-fact lookup gets a version check, not six agents; a
platform/strategy choice earns the full fan-out plus verify. The pass is never skipped; it is sometimes
two minutes (`research.md` § Proportion).
