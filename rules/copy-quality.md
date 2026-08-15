# Copy quality

## Never write copy that reads as AI-generated

Applies to **everything a human will read**: UI strings, landing/marketing copy, emails, error and
toast messages, user-facing docs, README, changelog, PR/commit bodies, and anything you draft for me
to send. Exempt, because they're read by engineers and agents rather than users: code comments, and
the repo's internal agent/dev docs — specifically `CLAUDE.md`, `AGENTS.md`, and `ABOUT.md`. An em
dash in any of those is fine, so don't spend effort stripping them there.

**The em dash (—) is the single biggest tell. Do not use it in prose.** Use a period, a comma, or
parentheses instead. Never swap it for a semicolon or a colon — those are the same tell in a
different hat. En dashes (–) in numeric ranges (`$200–$800`, `2–3 photos`) are correct typography,
are NOT a tell, and must be left alone. They are a different character.

**Banned constructions:**
- `It's not just X, it's Y` / `Not only X, but Y` / `No X. No Y. Just Z.` — fake insight.
- Question openers: "Are you tired of…", "Have you ever…", "Ever wondered…".
- Hedging throat-clearing: "It's worth noting that", "At its core", "In today's fast-paced world",
  "Let's dive in", "In the realm of".
- Filler transitions: moreover, furthermore, additionally.
- Engagement bait: "tag a friend", "comment below", "don't miss out".
- Empty summary paragraphs that restate what was just said.

**Banned vocabulary** (inflated verbs / dramatic nouns / consultant-speak): delve, leverage, utilize,
streamline, unleash, robust, harness, unlock, empower, elevate, scalable, holistic, revolutionize,
transformative, game-changer, synergy, cutting-edge, innovative, seamless, paradigm, tapestry, realm,
foster, pivotal, underscore, crucially, meticulously, embark, beacon, testament, navigate, journey,
supercharge, effortless, world-class, best-in-class, state-of-the-art, professional (as a filler
adjective — "professional-looking"), boost, ROI/return on ad spend, solution (as a product noun).

**Write like this instead:** short declarative sentences, concrete specifics and real numbers over
adjectives, active voice, plain words, contractions. Say the thing, then stop. If a sentence would
survive being deleted, delete it.

**A rhetorical triple (tricolon) is NOT an AI tell** — it's ancient rhetoric and often the best line
on the page ("No credits. No tiers. No surprises."). Don't strip these in the name of de-AI-ing;
that flattens my voice. What IS banned is the *triadic comma-list* (`X, Y, and Z`) used as filler.

**A personal project already encodes this** in a dedicated prompt-format module (`BANNED_WORDS`,
`BANNED_PHRASES`, `BANNED_PATTERNS`) because it enforces it on every generation. When working in
that repo, treat those constants as the source of truth and keep this list in sync with them. If a
project has its own ban list, that list wins.

**When editing existing copy for this, change ONLY the tell.** Preserve meaning, tone, and roughly
the length. Do not "improve" the copy while you're in there.

## Say enough, and no more — every written section earns its length

Same surfaces as above: anything a human reads. The economy half also applies to agent docs
(`CLAUDE.md`, `ABOUT.md`, plans, PR bodies) — bloat there costs context on every future run.

**Lead with the answer.** Write the shortest version that still lets the reader act, then stop.
Reams of prose are not thoroughness; they bury the one line the reader needed.

**Check every explanation BOTH ways before shipping it** — most writing fails on one side or the other:
- **Cut what's redundant** — anything restating a heading, a label, an adjacent element, or a point
  already made. If a sentence would survive being deleted, delete it.
- **Add what's missing** — the reader must finish knowing what this is and what to do next. A short
  section that leaves them guessing has failed exactly as badly as a long one that buried it.

**Use the Five Ws as the completeness check:** who it's for, what it is, when it applies, where it
lives or goes, why it matters — plus the how, the concrete next step. Not a template to write out
literally; a checklist to catch the one that's missing, because unclear writing is usually missing
exactly one of them.

**Give an action path, not a description of the work.** Numbered steps, the actual command, the file
to open. Prefer a one-line TL;DR, then short bullets, then detail only where it changes what the
reader does.
