# Calling real APIs to empirically iterate (env-key isolation + ask-first)

When a task is about the QUALITY of something an API produces (LLM prompt/harness output, an
image/voice model, a scraper, a classifier), the fastest reliable way to get it right is to **run
real API calls through the project's OWN code harness, read the outputs, fix, and repeat** — do not
tune blind. This worked concretely on a personal content-generation project (tuning its prompt harness): generate →
read → fix the prompt → regenerate, until the output met the bar, then freeze it as a gated test.
Generalize that method with these rules:

**Credential isolation — always scope keys to the current project:**
- Use ONLY the current project's own env file (e.g. `.env.local` / `.env` at *this* repo's root, or
  its documented secret source). **Never** read a key from another project's directory, a different
  repo, or a global location, and never carry a key between projects. Each session stays scoped to the
  repo it's running in.
- Load keys the way the repo already does (its dotenv/config, e.g. vitest loading `.env.local`) rather
  than hand-exporting — so the call matches production exactly.

**Ask-first — real API calls are billable/outward-facing:**
- **Always ask before using a key to make a real API request**, and say what you'll call, roughly how
  many calls, and the cost order of magnitude. Proceed only after a clear yes — EXCEPT when the user has
  already explicitly authorized it for this task/session (e.g. "yes, run real generations"), in which
  case that authorization stands for that batch of work.
- Keep the test matrix small and diverse (a handful of representative cases), run billable loops in the
  background, and read the output file. Delete scratch/eval files when done; keep a **gated** permanent
  test (e.g. behind `RUN_INTEGRATION=true`) with hard assertions so the win is locked in but never runs
  (or costs) by default.

**Method that works — drive the project's own harness, not a hand-rolled client:**
- Call the repo's actual service functions (the same ones the app/server calls) so the eval reflects
  production, not an approximation. Iterate: generate → read outputs for inconsistencies → fix the
  prompt/harness → regenerate → repeat until it holds; then assert the stable properties.

**Gotcha — Claude Code injects `ANTHROPIC_BASE_URL`:** the Claude Code shell sets `ANTHROPIC_BASE_URL`
to an internal gateway. Any SDK that reads it (e.g. `@ai-sdk/anthropic`, the Anthropic SDK) will hit
the wrong endpoint and 404 (seen as a request to `…/messages` without `/v1`). For direct real-API
calls from a project, override it to the provider's real base URL for that run (e.g.
`ANTHROPIC_BASE_URL=https://api.anthropic.com/v1 <cmd>`) and use the project's own key from its env
file. (Check the analogous env var for other providers.)
