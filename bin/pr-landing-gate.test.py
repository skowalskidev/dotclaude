#!/usr/bin/env python3
"""Offline regression tests for bin/pr-landing-gate.py and the `intent-ledger.sh gate PASS` backstop.

Standard library only. A stub `gh` on PATH serves fixture JSON, so nothing reaches GitHub.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = HERE / "pr-landing-gate.py"
HOOK = ROOT / "hooks" / "intent-ledger.sh"
spec = importlib.util.spec_from_file_location("pr_landing_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


PASSING = """## TLDR

| Change (biggest impact first) | Before | After | Why |
|---|---|---|---|
| 1. Paid-plan searches | 50 a week | **200 a month** | Members ran out mid-week |
| 2. Free plan | 5 a week | unchanged | Out of scope |

**Do:** merge. The migration applies itself; no current member is refused.

## 🚀 Deploy TLDR

1. Merge. The pipeline applies the migration first.
2. Smoke: open Settings as a paid test account and read "200 searches a month".

## User journey

1. A paid member opens Settings and reads the new monthly limit.

## System journey

1. The status read returns the limit and its period.

## Verification

| Leg | Result |
|---|---|
| Test matrix | 9 COVERED, 0 GAP, 1 NEEDS-DRIVING, 1 SKIPPED |

## Test matrix

Tier: deep (a member's search limit and its billing plan).

**9 COVERED · 0 GAP · 1 NEEDS-DRIVING · 1 SKIPPED**

| # | Feature | Evidence | Fails without the change | Verdict |
|---|---|---|---|---|
| 1 | 201st search refused | db test | base fails; mutant limit 201: FAILED | COVERED |
| 2 | Rendered cards | e2e with a mocked server | | NEEDS-DRIVING |

Real-environment walk: PASS, 6 of 6 source rows judged with screenshots and request logs.

## Regression check

| File | Hunks | Existing callers checked | Base-vs-head evidence | Result |
|---|---|---|---|---|
| `src/settings/Limit.tsx` | 2 | Settings, Billing | design-diff 0.0% changed outside the limit row | INTENDED: monthly limit wording |
| `src/auth/Gate.tsx` | 1 | Sign-in, Invite | buttons 0 px from the viewport bottom on base and head | PASS |
| `Gate` newly mounted | - | mirrors `src/invite/Invite.tsx:41` | difference: none | PASS |

## Prod data

**PASS with unknowns** (read-only).

| Cohort | Accounts | Refused on deploy |
|---|---|---|
| Free | 120 | same as today |
| Paid | 80 | 0 |

## Value safety

**Happy path:** checkout, webhook and grant files untouched (list in the matrix); payer suites pass on base and head; a returning payer's walk adds 0 requests and 0 error lines.
**Failure re-enacted:** a member over the old limit searches on web; the walk fails on base and passes on head.
**Wrong recipient:** only the member's own session reads the limit; a second account's token gets a 403 in `limit_test.ts`.
**Incident replay:** 12/12 refused members admitted, 12/12 refused for another account (production rows, live definitions).
**Provider lifecycle:** 11 rows: 10 SAFE, 1 N/A (matrix below).
**Residual risk:** none found; checked shared phone numbers and family plans.

### Provider lifecycle

| Case | Provider doc | Verdict | Evidence |
|---|---|---|---|
| Purchase success, cancel, decline, pending | [doc](https://docs.example.com/lifecycle#0) | SAFE | limit.ts:10 |
| Renewal billing retry and grace | [doc](https://docs.example.com/lifecycle#1) | SAFE | limit.ts:11 |
| Refund, revocation, chargeback | [doc](https://docs.example.com/lifecycle#2) | SAFE | limit.ts:12 |
| Transfer between accounts | [doc](https://docs.example.com/lifecycle#3) | SAFE | limit.ts:13 |
| Trial and intro offer | [doc](https://docs.example.com/lifecycle#4) | SAFE | limit.ts:14 |
| Sandbox and test environment | [doc](https://docs.example.com/lifecycle#5) | SAFE | limit.ts:15 |
| Family sharing | [doc](https://docs.example.com/lifecycle#6) | N/A | the plan has no shared access |
| Restore | [doc](https://docs.example.com/lifecycle#7) | SAFE | limit.ts:17 |
| Outage, rate limit, stale read | [doc](https://docs.example.com/lifecycle#8) | SAFE | limit.ts:18 |
| Concurrent webhooks | [doc](https://docs.example.com/lifecycle#9) | SAFE | limit.ts:19 |
| Plan change | [doc](https://docs.example.com/lifecycle#10) | SAFE | limit.ts:20 |

## Deploy safety

| Merge train (squash onto main) | Result |
|---|---|
| this PR alone | applies; order check passes |

| State | Effect | Rollback |
|---|---|---|
| New db, old functions | wording only | run the rollback file, then revert |

## Screenshots

### Settings
<img src="https://github.com/user-attachments/assets/00000000-0000-0000-0000-000000000000" width="800" alt="Settings">
"""
HTML = ('<h2>TLDR</h2><details open=""><summary>video</summary></details><a href="#"><img '
        'src="https://private-user-images.githubusercontent.com/1/settings.png" width="800" alt="Settings"></a>')


# A Light PR posts its BEFORE/AFTER pair: a second image after the fixture's one, rendered in HTML_PAIR.
AFTER_IMG = ('<img src="https://github.com/user-attachments/assets/11111111-1111-1111-1111-111111111111" '
             'width="800" alt="Settings after">\n')
HTML_PAIR = HTML + '<img src="https://private-user-images.githubusercontent.com/1/after.png" alt="Settings after">'


def paired(body):
    return body.replace('alt="Settings">\n', 'alt="Settings">\n' + AFTER_IMG, 1)


def section(body, heading, replacement):
    """Replace the `## heading` section (up to the next `## `) with replacement text."""
    start = body.index("## " + heading + "\n")
    end = body.find("\n## ", start + 3)
    end = len(body) if end < 0 else end + 1
    return body[:start] + replacement + body[end:]


def rows(missing):
    return {m.split(":", 1)[0] for m in missing}


# The full body passes.
check(gate.check_body(PASSING, HTML, 0) == [], f"Passing body failed: {gate.check_body(PASSING, HTML, 0)}")

# Only a one-row matrix summary in the Verification table fails on the matrix row, and only there.
summary_only = section(PASSING, "Test matrix", "")
missing = gate.check_body(summary_only, HTML, 0)
check(rows(missing) == {"Test matrix"}, f"One-row matrix summary did not fail on the matrix row alone: {missing}")

# A tier skip line stands in for the matrix, prod-data and deploy-safety legs; the tier must be named.
skip = "Skipped (tier light): style-only change to one table cell\n\n"
light = section(paired(PASSING), "Test matrix", "## Test matrix\n\nTier: light (one table cell's CSS).\n\n" + skip
                + "Real-environment walk: " + skip)
light = section(light, "Prod data", "## Prod data\n\n" + skip)
light = section(light, "Deploy safety", "## Deploy safety\n\n" + skip)
check(gate.check_body(light, HTML_PAIR, 0) == [], f"A light PR with skip lines failed: {gate.check_body(light, HTML_PAIR, 0)}")
bare_skip = light.replace("Skipped (tier light): style-only change to one table cell", "Skipped (tier light): style")
check({"Test matrix", "Prod data"} <= rows(gate.check_body(bare_skip, HTML, 0)),
      "A skip line with no trigger passed")
# Light runs no merge train, so its Deploy safety section is held only to installed-build lines; Standard
# keeps the merge-train and rollback rows.
bare_standard = bare_skip.replace("Tier: light", "Tier: standard").replace("(tier light)", "(tier standard)")
check({"Test matrix", "Prod data", "Deploy safety"} <= rows(gate.check_body(bare_standard, HTML, 0)),
      "A Standard skip line with no trigger passed")
untiered = PASSING.replace("Tier: deep (a member's search limit and its billing plan).\n\n", "")
check(any("no tier named" in m for m in gate.check_body(untiered, HTML, 0)), "A matrix with no tier named passed")

# references/testing-strategy.md § Prove each test fails without the change: Standard and Deep COVERED rows
# name how the test failed with the change removed; a surviving mutant fails; Light is exempt.
no_column = PASSING.replace("| # | Feature | Evidence | Fails without the change | Verdict |\n|---|---|---|---|---|",
                            "| # | Feature | Evidence | Verdict |\n|---|---|---|---|").replace(
    " | base fails; mutant limit 201: FAILED | COVERED |", " | COVERED |").replace(
    " | e2e with a mocked server | | NEEDS-DRIVING |", " | e2e with a mocked server | NEEDS-DRIVING |")
check(any("no 'Fails without the change' column" in m for m in gate.check_body(no_column, HTML, 0)),
      "A deep matrix with no Fails without the change column passed")
standard_no_column = no_column.replace("Tier: deep (a member's search limit and its billing plan).",
                                       "Tier: standard (logic inside the search limit feature).")
check(any("no 'Fails without the change' column" in m for m in gate.check_body(standard_no_column, HTML, 0)),
      "A standard matrix with no Fails without the change column passed")
light_no_column = no_column.replace("Tier: deep (a member's search limit and its billing plan).",
                                    "Tier: light (one admin page button, team-only).")
check(not [m for m in gate.check_body(light_no_column, HTML, 0) if "Fails without" in m],
      "A Light matrix was held to the Fails without the change column")
blank_cell = PASSING.replace("base fails; mutant limit 201: FAILED", "")
check(any("empty 'Fails without the change' cell" in m for m in gate.check_body(blank_cell, HTML, 0)),
      "A COVERED row with an empty Fails without the change cell passed")
survived = PASSING.replace("mutant limit 201: FAILED", "mutant limit 201: PASSED")
check(any("a mutant survived" in m for m in gate.check_body(survived, HTML, 0)), "A surviving mutant passed")
check(any("a mutant survived" in m for m in gate.check_body(PASSING.replace(
          "mutant limit 201: FAILED", "mutant limit 201 survived"), HTML, 0)), "A 'survived' mutant passed")
check(not [m for m in gate.check_body(PASSING.replace("base fails; mutant limit 201: FAILED",
                                                      "n/a: migration order check, no behaviour"), HTML, 0)
           if "Fails without" in m], "An n/a reason in the Fails without the change cell failed")

# The matrix section holds the real-environment walk line: PASS, a reasoned N/A or a skip line, never FAIL.
WALK_LINE = "Real-environment walk: PASS, 6 of 6 source rows judged with screenshots and request logs."
check(any("no Real-environment walk line" in m for m in gate.check_body(PASSING.replace(WALK_LINE, ""), HTML, 0)),
      "A matrix with no walk line passed")
check(any("walk records a FAIL" in m for m in
          gate.check_body(PASSING.replace(WALK_LINE, "Real-environment walk: FAIL, partner page example is stale."), HTML, 0)),
      "A failing walk passed")
walk_na = "Real-environment walk: does not apply, the repo has no runnable local stack."
check(gate.check_body(PASSING.replace(WALK_LINE, walk_na), HTML, 0) == [], "A reasoned walk N/A failed")
check(any("walk has no PASS" in m for m in
          gate.check_body(PASSING.replace(WALK_LINE, "Real-environment walk: N/A"), HTML, 0)),
      "A bare walk N/A passed")

# A deep PR touching native app code or a payment or entitlement path names a real-client walk with PASS,
# or a does-not-apply naming why no user journey changed (testing-strategy.md § Pre-merge end-to-end).
NATIVE_FILES = ("ios/App/Core/PurchaseConfirmation.swift", "ios/AppTests/PurchaseConfirmationTests.swift")
PAYMENT_FILES = ("supabase/functions/revenuecat/index.ts", "supabase/functions/revenuecat/index_test.ts")
sim_walk = ("Real-environment walk: PASS, 7 of 7, on the iOS Simulator, head Debug build with the StoreKit "
            "configuration, against the local stack.")
cannot_run = ("Real-environment walk: does not apply locally, because a grant needs a real production App "
              "Store subscription, which no local stack or sandbox purchase can produce.")
unit_only = "Real-environment walk: PASS, simulator unit tests 44 of 44 in the purchase confirmation suite."
no_journey = ("Real-environment walk: does not apply, the diff changes no user journey: it renames a log "
              "field in the purchase helper.")


def walk_body(line):
    return PASSING.replace(WALK_LINE, line)


def walk_missing(line, changed, body=None):
    return gate.check_body(body or walk_body(line), HTML, 0, changed=changed)


check(any("touches native app code" in m for m in walk_missing(cannot_run, NATIVE_FILES)),
      "A deep native PR whose walk N/A says the purchase cannot run locally passed (the #1350 gap)")
check(walk_missing(sim_walk, NATIVE_FILES) == [], f"A deep native PR with a simulator walk failed: "
      f"{walk_missing(sim_walk, NATIVE_FILES)}")
check(any("rests on unit tests" in m for m in walk_missing(unit_only, NATIVE_FILES)),
      "A deep native PR whose walk line is simulator unit tests passed")
check(any("names no simulator or device walk" in m for m in walk_missing(WALK_LINE, NATIVE_FILES)),
      "A deep native PR whose walk names no simulator or device passed")
check(walk_missing(no_journey, NATIVE_FILES) == [], "A deep native PR whose N/A names no changed journey failed")
check(any("walk has no PASS" in m for m in walk_missing("Real-environment walk: N/A", NATIVE_FILES)),
      "A deep native PR with a bare walk N/A passed")
check(any("walk records a FAIL" in m for m in
          walk_missing("Real-environment walk: FAIL, W2 restore on the iOS Simulator.", NATIVE_FILES)),
      "A deep native PR with a failing simulator walk passed")
check(walk_missing(WALK_LINE, ("ios/AppTests/PurchaseConfirmationTests.swift",)) == [],
      "A deep PR changing only native tests was held to the walk rule")
check(any("touches a payment or entitlement path" in m for m in walk_missing(cannot_run, PAYMENT_FILES)),
      "A deep payment-path PR whose walk N/A gives another reason passed")
check(any("names no simulator, device, browser or local-stack walk" in m
          for m in walk_missing(WALK_LINE, PAYMENT_FILES)),
      "A deep payment-path PR whose walk names no real client passed")
browser_walk = "Real-environment walk: PASS, W1-W3 in the browser against the local stack with Stripe test mode."
check(walk_missing(browser_walk, PAYMENT_FILES) == [], "A deep payment-path PR with a browser walk failed")
check(walk_missing(WALK_LINE, ("supabase/functions/revenuecat/index_test.ts", "docs/billing.md")) == [],
      "A deep PR changing only payment tests and docs was held to the walk rule")
standard = walk_body(cannot_run).replace("Tier: deep (a member's search limit and its billing plan).",
                                         "Tier: standard (one feature's logic past the Light size).")
check(not any("touches" in m for m in walk_missing(None, NATIVE_FILES, standard)),
      "A Standard PR was held to the deep walk rule")
check(gate.walk_trigger(("site/web/app/display/Card.tsx",)) is None, "A 'display' path counted as a payment path")

# A matrix section missing one count label names that label.
no_gap = PASSING.replace("· 0 GAP ", "")
check(any("GAP" in m for m in gate.check_body(no_gap, HTML, 0)), "A matrix with no GAP count passed")
bare = PASSING.replace("1 NEEDS-DRIVING", "NEEDS-DRIVING")
bare = bare.replace("| NEEDS-DRIVING |", "| driving |")
check(any("NEEDS-DRIVING" in m for m in gate.check_body(bare, HTML, 0)),
      "A NEEDS-DRIVING label with no number passed")

# A collapsed <details> fails; one carrying open passes.
collapsed = gate.check_body(PASSING, "<details><summary>Screens</summary></details>" + HTML, 0)
check(rows(collapsed) == {"Visible sections"}, f"A collapsed <details> did not fail alone: {collapsed}")

# Every posted image renders: an alt holding a raw double quote ends the attribute and GitHub shows the
# tag as text, so body_html renders fewer <img> than the body posts (2 of 17 images in one PR body).
quoted = PASSING.replace('alt="Settings">', 'alt="Step "Add your cards" before and after">')
as_text = HTML.split("<a ")[0] + "<p>&lt;img src=&quot;https://github.com/user-attachments/assets/0&quot;</p>"
broken = gate.check_body(quoted, as_text, 0)
check(rows(broken) == {"Images"} and "show as text" in broken[0] and "size-images" in broken[0],
      f"An <img> GitHub showed as text did not fail alone, naming the fix: {broken}")
escaped = PASSING.replace('alt="Settings">', 'alt="Step &quot;Add your cards&quot; before and after">')
check(gate.check_body(escaped, HTML, 0) == [], "An escaped alt that rendered failed")
md_shot = PASSING + "\n![Mobile before and after](https://github.com/user-attachments/assets/1)\n"
check(rows(gate.check_body(md_shot, HTML, 0)) == {"Images"}, "A Markdown image missing from body_html passed")
check(gate.check_body(md_shot, HTML + '<img src="x">', 0) == [], "A rendered Markdown image failed")
coded = PASSING + "\n`![x](https://h/x)` and `<img>`\n```\n<img src=\"y\">\n```\n<!-- <img> -->\n![](https://h/video)\n"
check(gate.check_body(coded, HTML, 0) == [], "Code, a comment or the empty-alt video form counted as a posted image")

# A missing TLDR fails on the TLDR row; a TLDR with no Do line or no Before/After table fails too.
no_tldr = PASSING[PASSING.index("## 🚀 Deploy TLDR"):]
check("TLDR" in rows(gate.check_body(no_tldr, HTML, 0)), "A body with no TLDR passed the TLDR row")
check(any("Do:" in m for m in gate.check_body(PASSING.replace("**Do:** merge", "Merge"), HTML, 0)),
      "A TLDR with no **Do:** line passed")
check(any("Before" in m for m in gate.check_body(PASSING.replace("| Before | After | Why |", "| Old | New | Reason |"), HTML, 0)),
      "A TLDR with no Before/After table passed")
check(any("Why" in m for m in gate.check_body(PASSING.replace("| Before | After | Why |", "| Before | After | Notes |"), HTML, 0)),
      "A TLDR table with no Why column passed")

# The Test matrix heading names the PR's current head; a body written for an earlier head fails
# (/sk:ship-pr § Rewrite the body when the PR changes).
HEAD = "abc1234def5678900000000000000000000000000"
stamped = PASSING.replace("## Test matrix\n", "## Test matrix (head abc1234)\n", 1)
check(gate.check_body(stamped, HTML, 0, head=HEAD) == [], "A body naming the current head failed")
check(any("PR head is" in m for m in gate.check_body(stamped, HTML, 0, head="fff" + HEAD[3:])),
      "A body naming an earlier head passed")
check(any("names no head sha" in m for m in gate.check_body(PASSING, HTML, 0, head=HEAD)),
      "A Test matrix heading with no head sha passed when the PR head is known")
check(gate.check_body(PASSING, HTML, 0) == [], "The head check fired with no PR head given")

# One run names every requirement: a missing heading lists what its section must hold, and the
# independent checks inside a present section all report together (the fix for a PR body that took
# eight rewrites because each run revealed one more hidden requirement).
tldr_only = PASSING[:PASSING.index("## 🚀 Deploy TLDR")]
for line in gate.check_body(tldr_only, HTML, 0):
    if "heading" in line and not line.startswith(("TLDR", "Visible")):
        check("(needs: " in line, f"A missing heading did not list its requirements: {line}")
matrix_need = next((m for m in gate.check_body(tldr_only, HTML, 0) if m.startswith("Test matrix")), "")
check(all(k in matrix_need for k in ("tier", "COVERED", "Real-environment walk")),
      f"The missing Test matrix line did not name the tier, counts and walk: {matrix_need}")
check(set(gate.SECTIONS) - {"Verification runs"} <= set(gate.NEEDS), "A gated section has no NEEDS entry")

# references/tldr-report-formats.md § Part verdicts: checked when posted, so an older body still passes.
PARTS = ("\n## Part verdicts\n\n"
         "| Part | Verdict | Mainstream practice | Regression evidence | Claude judge | OpenAI judge |\n"
         "|---|---|---|---|---|---|\n"
         "| 1. Retry | BUILD: 4% fail once | Backoff with jitter ([AWS](https://aws.amazon.com/x)) "
         "| suites PASS | agrees | agrees |\n")
check(not [m for m in gate.check_body(PASSING, HTML, 0) if m.startswith("Part verdicts")],
      "A body with no Part verdicts section failed the gate")
check(not [m for m in gate.check_body(PASSING + PARTS, HTML, 0) if m.startswith("Part verdicts")],
      "A well-formed Part verdicts section failed the gate")
unlinked = PASSING + PARTS.replace("([AWS](https://aws.amazon.com/x))", "")
check(any("no primary-source link" in m for m in gate.check_body(unlinked, HTML, 0)),
      "A Part verdicts row with no primary-source link passed")
one_judge = PASSING + PARTS.replace(" OpenAI judge |", "").replace(" agrees |\n", "\n")
check(any("judge columns" in m for m in gate.check_body(one_judge, HTML, 0)),
      "A Part verdicts table with one judge column passed")
no_cols = PASSING + PARTS.replace("Mainstream practice", "Approach").replace("Regression evidence", "Tests")
miss = [m for m in gate.check_body(no_cols, HTML, 0) if m.startswith("Part verdicts")]
check(any("Mainstream" in m and "Regression" in m for m in miss),
      f"A Part verdicts header with no Mainstream or Regression column passed: {miss}")
check(any(m.startswith("Part verdicts: no table") for m in
          gate.check_body(PASSING + "\n## Part verdicts\n\nAll parts make sense.\n", HTML, 0)),
      "A Part verdicts section with no table passed")
both = PASSING.replace("**Do:** merge", "Merge").replace("| Before | After | Why |", "| Old | New | Reason |")
tldr_rows = [m for m in gate.check_body(both, HTML, 0) if m.startswith("TLDR")]
check(len(tldr_rows) == 2, f"A TLDR missing both its table and Do line did not report both: {tldr_rows}")
bare_prod = section(PASSING, "Prod data", "## Prod data\n\nChecked the accounts.\n\n")
prod_rows = [m for m in gate.check_body(bare_prod, HTML, 0) if m.startswith("Prod data")]
check(len(prod_rows) == 2, f"Prod data with no verdict and no table did not report both: {prod_rows}")

# Deploy TLDR must follow the TLDR; an emoji or case variant of a heading still matches.
moved = section(PASSING, "🚀 Deploy TLDR", "") + "\n## Deploy TLDR\n\n1. Merge.\n"
check(any("next heading" in m for m in gate.check_body(moved, HTML, 0)), "A Deploy TLDR out of order passed")
check(gate.check_body(PASSING.replace("## Prod data", "## 📊 PROD DATA"), HTML, 0) == [],
      "An emoji or upper-case heading variant did not match")

# A heading inside a code fence is source text, not a section.
fenced = section(PASSING, "User journey", "```\n## User journey\n```\n\n")
check("User journey" in rows(gate.check_body(fenced, HTML, 0)), "A fenced heading counted as a section")

# Prod data and deploy safety accept a named doesn't-apply reason, never a bare one.
na = "## Prod data\n\nDoes not apply: the diff changes only a build script, no stored data or runtime path.\n\n"
check(gate.check_body(section(PASSING, "Prod data", na), HTML, 0) == [], "A reasoned prod-data N/A failed")
check("Prod data" in rows(gate.check_body(section(PASSING, "Prod data", "## Prod data\n\nN/A\n\n"), HTML, 0)),
      "A bare prod-data N/A passed")
safety_na = "## Deploy safety\n\nDoes not apply: no migration, no open PR touches these files, nothing to roll.\n\n"
check(gate.check_body(section(PASSING, "Deploy safety", safety_na), HTML, 0) == [],
      "A reasoned deploy-safety N/A failed")
check("Deploy safety" in rows(gate.check_body(section(PASSING, "Deploy safety", "## Deploy safety\n\nFine.\n\n"),
                                              HTML, 0)), "Deploy safety with no merge train or rollback passed")

# Value safety: required on a deep-tier PR; six labelled lines with evidence, or a reasoned doesn't-apply.
no_value = section(PASSING, "Value safety", "")
check(rows(gate.check_body(no_value, HTML, 0)) == {"Value safety"}, "A deep PR with no Value safety section passed")
standard = no_value.replace("Tier: deep (a member's search limit and its billing plan).",
                            "Tier: standard (logic inside the search limit feature).")
check(gate.check_body(standard, HTML, 0) == [], f"A standard PR with no Value safety section failed: "
      f"{gate.check_body(standard, HTML, 0)}")
for label in gate.VALUE_LABELS:
    cut = "\n".join(ln for ln in PASSING.splitlines() if not ln.startswith("**" + label))
    check(any(label + ":" in m for m in gate.check_body(cut, HTML, 0)), f"Value safety with no {label} line passed")
failed_value = PASSING.replace("a second account's token gets a 403", "a second account's token FAILED to be refused")
check(any("records a FAIL" in m for m in gate.check_body(failed_value, HTML, 0)), "A FAIL value-safety line passed")
uncounted = PASSING.replace("12/12 refused members admitted, 12/12 refused for another account", "all admitted")
check(any("no N/N count" in m for m in gate.check_body(uncounted, HTML, 0)), "An incident replay with no N/N passed")
replay_na = PASSING.replace("**Incident replay:** 12/12 refused members admitted, 12/12 refused for another account",
                            "**Incident replay:** does not apply, the PR fixes no production incident")
check(gate.check_body(replay_na, HTML, 0) == [], "A reasoned incident-replay N/A failed")
# Value safety question 5: the provider lifecycle matrix, one linked, verdicted row per documented category.
matrix_rows = [ln for ln in PASSING.splitlines() if ln.startswith("| ") and "docs.example.com" in ln]
check(len(matrix_rows) == gate.PROVIDER_CASES, "The passing fixture no longer holds a full lifecycle matrix")
short = PASSING.replace(matrix_rows[-1] + "\n", "")
check(any("row(s); every documented" in m for m in gate.check_body(short, HTML, 0)), "A short lifecycle matrix passed")
unlinked_row = PASSING.replace(matrix_rows[0], matrix_rows[0].replace("[doc](https://docs.example.com/lifecycle#0)", "docs"))
check(any("no provider doc link" in m for m in gate.check_body(unlinked_row, HTML, 0)), "A lifecycle row with no doc link passed")
gap_row = PASSING.replace(matrix_rows[2], matrix_rows[2].replace("| SAFE |", "| GAP |"))
check(any("open GAP" in m for m in gate.check_body(gap_row, HTML, 0)), "A lifecycle GAP row passed")
no_verdict = PASSING.replace(matrix_rows[3], matrix_rows[3].replace("| SAFE |", "| checked |"))
check(any("no SAFE, GAP or N/A" in m for m in gate.check_body(no_verdict, HTML, 0)), "A lifecycle row with no verdict passed")
gap_in_case = PASSING.replace(matrix_rows[4], matrix_rows[4].replace("Trial and intro offer", "Trial GAP window"))
check(gate.check_body(gap_in_case, HTML, 0) == [], "A GAP word outside the Verdict column failed the matrix")
no_matrix = PASSING[:PASSING.index("\n### Provider lifecycle")] + PASSING[PASSING.index("\n## Deploy safety"):]
check(any("no ### Provider lifecycle" in m for m in gate.check_body(no_matrix, HTML, 0)), "A missing lifecycle matrix passed")
lifecycle_na = no_matrix.replace("**Provider lifecycle:** 11 rows: 10 SAFE, 1 N/A (matrix below).",
                                 "**Provider lifecycle:** does not apply, no provider-backed paid access in the diff")
check(gate.check_body(lifecycle_na, HTML, 0) == [], "A reasoned provider-lifecycle N/A failed: "
      f"{gate.check_body(lifecycle_na, HTML, 0)}")
value_na = section(PASSING, "Value safety",
                   "## Value safety\n\nDoes not apply: the diff moves no money, credit, entitlement, auth or ownership.\n\n")
check(gate.check_body(value_na, HTML, 0) == [], "A reasoned value-safety N/A failed")
check("Value safety" in rows(gate.check_body(section(PASSING, "Value safety", "## Value safety\n\nN/A\n\n"), HTML, 0)),
      "A bare value-safety N/A passed")

# Screenshots need an image, or a no-visible-surface reason with a Checked outputs clause.
none = ("## Screenshots\n\nNo visible surface: the diff renames an internal helper. Checked outputs: the chat "
        "reply text and the Slack post blocks, base vs head on the run fixture: identical.\n")
check(gate.check_body(section(PASSING, "Screenshots", none), HTML, 0) == [], "A no-surface line with checked outputs failed")
bold = none.replace("Checked outputs:", "**Checked outputs:**")
check(gate.check_body(section(PASSING, "Screenshots", bold), HTML, 0) == [], "A bold Checked outputs label failed")
bare = "## Screenshots\n\nNo eligible frontend surface: the diff changes only server code.\n"
check(any("Checked outputs" in m for m in gate.check_body(section(PASSING, "Screenshots", bare), HTML, 0)),
      "A bare no-eligible-frontend-surface line passed")
na_bare = "## Screenshots\n\nDoes not apply: the change only alters the bot's sweep logic.\n"
check(any("Checked outputs" in m for m in gate.check_body(section(PASSING, "Screenshots", na_bare), HTML, 0)),
      "A does-not-apply Screenshots line with no Checked outputs clause passed")
thin = none.replace("the chat reply text and the Slack post blocks, base vs head on the run fixture: identical.", "none")
check(any("Checked outputs" in m for m in gate.check_body(section(PASSING, "Screenshots", thin), HTML, 0)),
      "A one-word Checked outputs clause passed")
# A route change between existing screens is visible: a new-screen or new-copy test is never the reason.
route = ("## Screenshots\n\nNo visible surface changed: no new screen or copy, the paywall reuses an existing "
         "screen. Checked outputs: the paywall request logs in the unit tests, base vs head: identical.\n")
check(any("existing screen or step" in m for m in gate.check_body(section(PASSING, "Screenshots", route), HTML, 0)),
      "A no-surface reason of 'no new screen or copy' passed")
for phrase in ("No new copy", "reuses the Existing step", "lands on the same screen"):
    variant = route.replace("no new screen or copy, the paywall reuses an existing screen", phrase)
    check(any("existing screen or step" in m for m in gate.check_body(section(PASSING, "Screenshots", variant), HTML, 0)),
          f"A no-surface reason of '{phrase}' passed")
route_runs = PASSING + ("\n## Verification runs\n\nNo visible surface: same screen as before. Checked outputs: the "
                        "sign-in screen, base vs head: identical.\n")
check(any("Verification runs" in m and "existing screen or step" in m for m in gate.check_body(route_runs, HTML, 0)),
      "A Verification runs no-surface reason of 'same screen' passed")
outputs_named = none.replace("the chat reply text", "the same screen's chat reply text")
check(gate.check_body(section(PASSING, "Screenshots", outputs_named), HTML, 0) == [],
      "A Checked outputs clause naming the same screen failed a valid no-surface reason")
check("Screenshots" in rows(gate.check_body(section(PASSING, "Screenshots", "## Screenshots\n\nSee below.\n"),
                                            HTML, 0)), "Screenshots with no image or reason passed")

# Verification runs: required once ## Screenshots posts a video; when present, it carries a table, a
# video and its Findings, Fixed during review, Not covered and Sources lines, or a skip/no-surface reason.
ATTACH = "https://github.com/user-attachments/assets/11111111-1111-1111-1111-111111111111"
with_video = PASSING.rstrip("\n") + "\n\n### Settings flow\n\n" + ATTACH + "\n"
check(rows(gate.check_body(with_video, HTML, 0)) == {"Verification runs"},
      "A Screenshots video with no Verification runs section passed")
RUNS = ("## Verification runs\n\n| Scenario | Steps | Outcome | Video |\n|---|---|---|---|\n"
        "| Change the plan | 6 | New limit shown | [video](#change-the-plan) |\n\n### Change the plan\n\n"
        "Opens Settings, picks the monthly plan, reads the new limit.\n\n**Findings:** none\n\n"
        "**Fixed during review:** limit read 0 at 00:14 · abc1234\n\n" + ATTACH + "\n\n"
        "Not covered: the yearly plan (a paid supplier step, about $0.40).\n\n"
        "Sources: https://playwright.dev/docs/videos\n")
complete = with_video + "\n" + RUNS
check(gate.check_body(complete, HTML, 0) == [], f"A complete Verification runs section failed: "
      f"{gate.check_body(complete, HTML, 0)}")
check(gate.check_body(PASSING + "\n" + RUNS, HTML, 0) == [], "Verification runs beside image-only screenshots failed")
for label in ("**Findings:** none", "**Fixed during review:**", "Not covered:", "Sources:"):
    cut = complete.replace(label, "")
    check(any("Verification runs" in m for m in gate.check_body(cut, HTML, 0)),
          f"Verification runs with no {label} line passed")
no_vid = with_video + "\n" + RUNS.replace(ATTACH + "\n\n", "")
check(any("no posted video" in m for m in gate.check_body(no_vid, HTML, 0)), "Verification runs with no video passed")
skipped = with_video + "\n## Verification runs\n\nSkipped (tier standard): no journey changed, only one copy string\n"
check(gate.check_body(skipped, HTML, 0) == [], "A Verification runs skip line failed")
runs_none = PASSING + "\n## Verification runs\n\nNo visible surface: no journey reaches the changed helper.\n"
check(any("Verification runs" in m and "Checked outputs" in m for m in gate.check_body(runs_none, HTML, 0)),
      "A Verification runs no-surface line with no Checked outputs clause passed")
runs_checked = runs_none.rstrip("\n") + " Checked outputs: the reply card and the bot post, base vs head: identical.\n"
check(gate.check_body(runs_checked, HTML, 0) == [], "A Verification runs no-surface line with checked outputs failed")
na_inside = complete.replace("Not covered: the yearly plan", "Not covered: does not apply to the yearly plan, a paid supplier")
check(gate.check_body(na_inside, HTML, 0) == [], "A complete Verification runs section mentioning N/A failed")

# Regression check: one row per modified pre-existing file, each PASS or INTENDED, none FAIL.
MODIFIED = ["src/settings/Limit.tsx", "src/auth/Gate.tsx"]
check(gate.check_body(PASSING, HTML, 0, MODIFIED) == [],
      f"A complete regression check failed: {gate.check_body(PASSING, HTML, 0, MODIFIED)}")
no_reg = section(PASSING, "Regression check", "")
check(rows(gate.check_body(no_reg, HTML, 0, MODIFIED)) == {"Regression check"}, "A body with no regression check passed")
unlisted = gate.check_body(PASSING, HTML, 0, MODIFIED + ["src/app/Frame.tsx"])
check(any("no row for 1" in m and "src/app/Frame.tsx" in m for m in unlisted),
      f"A modified pre-existing file with no row passed: {unlisted}")
bare_row = PASSING.replace("buttons 0 px from the viewport bottom on base and head | PASS |",
                           "buttons 0 px from the viewport bottom on base and head | looked fine |")
check(any("no PASS or INTENDED" in m and "src/auth/Gate.tsx" in m for m in gate.check_body(bare_row, HTML, 0, MODIFIED)),
      "A row with no PASS or INTENDED result passed")
failed = PASSING.replace("on base and head | PASS |", "buttons 220 px above the bottom on head | FAIL |")
check(any("records FAIL" in m for m in gate.check_body(failed, HTML, 0, MODIFIED)), "A FAIL regression row passed")
untabled = section(PASSING, "Regression check", "## Regression check\n\nAll good.\n\n")
check(any("no table" in m for m in gate.check_body(untabled, HTML, 0, MODIFIED)), "A regression check with no table passed")
new_only = section(PASSING, "Regression check",
                   "## Regression check\n\nNo pre-existing file modified: the diff only adds a new script and its test.\n\n")
check(gate.check_body(new_only, HTML, 0, []) == [], "A stated no-pre-existing-file reason failed")
check("Regression check" in rows(gate.check_body(new_only, HTML, 0, MODIFIED)),
      "A no-pre-existing-file claim passed while the PR modifies existing files")

# The table carries the base-vs-head evidence the rule names, for every modified file's row.
two_col = section(PASSING, "Regression check",
                  "## Regression check\n\n| File | Result |\n|---|---|\n"
                  "| `src/settings/Limit.tsx` | INTENDED: monthly limit wording |\n"
                  "| `src/auth/Gate.tsx` | PASS |\n\n")
check(any("Base-vs-head evidence column" in m for m in gate.check_body(two_col, HTML, 0, MODIFIED)),
      "A regression table with no evidence column passed")
blank = PASSING.replace("| buttons 0 px from the viewport bottom on base and head | PASS |", "|  | PASS |")
check(any("no base-vs-head evidence for" in m and "src/auth/Gate.tsx" in m
          for m in gate.check_body(blank, HTML, 0, MODIFIED)),
      "A modified file's row with an empty evidence cell passed")
dash = PASSING.replace("| buttons 0 px from the viewport bottom on base and head | PASS |", "| - | PASS |")
check(any("no base-vs-head evidence for" in m for m in gate.check_body(dash, HTML, 0, MODIFIED)),
      "A modified file's row with a dash for evidence passed")

# Installed native builds (references/git-pr-deploy.md § Deploy safety check 4).
check(gate.reaches_installed_builds(["site/web/app/page.tsx"], ["ios", "site"]),
      "A hosted web file in a repo with an iOS app was not seen as reaching installed builds")
check(not gate.reaches_installed_builds(["ios/App.swift", "site/web/a.test.tsx", "docs/x.md",
                                         ".github/workflows/ci.yml"], ["ios", "site"]),
      "Native, test, doc or CI files alone were seen as reaching installed builds")
check(not gate.reaches_installed_builds(["src/api.ts"], ["src"]), "A repo with no native app was gated")
INSTALLED = """
| Version | Share (30 days) |
|---|---|
| 1.4.9 (115) | 52.6% |

Old build 1.4.9 (115) against the new backend: PASS (runs/old-1.4.9)
Waits for the new build: none
"""
with_installed = PASSING.replace("## Screenshots", INSTALLED + "\n## Screenshots", 1)
check(gate.check_body(with_installed, HTML, 0, (), True) == [],
      f"Installed-build lines failed: {gate.check_body(with_installed, HTML, 0, (), True)}")
bare_installed = gate.check_body(PASSING, HTML, 0, (), True)
check(len([m for m in bare_installed if m.startswith("Deploy safety:")]) == 3,
      f"Missing installed-build lines did not name all three: {bare_installed}")
check(gate.check_body(PASSING, HTML, 0, (), False) == [], "The installed check ran for a PR that reaches no build")
blocked = with_installed.replace("against the new backend: PASS (runs/old-1.4.9)",
                                 "against the new backend: BLOCKED, release commit unknown")
check(any("not walked" in m for m in gate.check_body(blocked, HTML, 0, (), True)),
      "A BLOCKED old-build walk passed the gate")
unreached = with_installed.replace("Old build 1.4.9 (115) against the new backend: PASS (runs/old-1.4.9)",
                                   "Installed builds: not reached, the diff only changes the admin site")
check(gate.check_body(unreached, HTML, 0, (), True) == [], "A reasoned not-reached line failed")

# A Deploy TLDR step never waits on a second approval (references/git-pr-deploy.md § A merge word runs the
# Deploy TLDR); a stated trigger condition and Simon's own keep-it-off pass.
STEP2 = '2. Smoke: open Settings as a paid test account and read "200 searches a month".\n'
for held in ("3. Turn the feature switch on to 50%, only on Simon's word (not part of this merge).\n",
             "3. Turn the feature switch on after a separate approval.\n",
             "3. Turn the switch on only with his yes.\n"):
    got = gate.check_body(PASSING.replace(STEP2, STEP2 + held, 1), HTML, 0)
    check(any(m.startswith("Deploy TLDR: a step waits on a second approval") for m in got),
          f"A Deploy TLDR step held for a second approval passed: {held!r} {got}")
for ok in ("3. Turn the feature switch on to 50%. Check: the switch reads 0. Smoke: it reads 50. Rollback: set 0.\n",
           "3. Turn the new header on once the new app build runs on 50% of active installs.\n",
           "3. Leave the feature switch off (Simon: keep it off).\n"):
    got = gate.check_body(PASSING.replace(STEP2, STEP2 + ok, 1), HTML, 0)
    check(got == [], f"A Deploy TLDR activation step was refused: {ok!r} {got}")

# The app build line (references/git-pr-deploy.md § Deploy safety check 4): every PR in a native-app repo.
APP_LINE = "No app build needed: every changed file is hosted web, loaded on the next page open.\n\n"
with_app = with_installed.replace("1. Merge. The pipeline", APP_LINE + "1. Merge. The pipeline", 1)
check(gate.check_body(with_app, HTML, 0, (), True, native=True) == [],
      f"A native-app PR with its app build line failed: {gate.check_body(with_app, HTML, 0, (), True, native=True)}")
check(gate.ships_native_app(["ios", "site"]) and not gate.ships_native_app(["src", "docs"]),
      "ships_native_app misread the repo's top-level folders")
check(any(m.startswith("Deploy TLDR: no app build line") for m in
          gate.check_body(with_installed, HTML, 0, (), True, native=True)),
      "A native-app PR with no app build line passed")
check(any(m.startswith("Deploy TLDR: no app build line") for m in gate.check_body(PASSING, HTML, 0, native=True)),
      "A native-app PR that reaches no installed build skipped the app build line")
needs = with_app.replace(APP_LINE, "**Needs an app build:** the new header waits for 1.5.0.\n\n")
check(gate.check_body(needs, HTML, 0, (), True, native=True) == [], "A bold 'Needs an app build:' line failed")
bare = with_app.replace(APP_LINE, "No app build needed: yes\n\n")
check(any(m.startswith("Deploy TLDR: no app build line") for m in gate.check_body(bare, HTML, 0, (), True, native=True)),
      "An app build line with no reason passed")
elsewhere = with_installed.replace("## User journey", "## Notes\n\n" + APP_LINE + "## User journey", 1)
check(any(m.startswith("Deploy TLDR: no app build line") for m in
          gate.check_body(elsewhere, HTML, 0, (), True, native=True)),
      "An app build line outside the Deploy TLDR passed")
check(gate.check_body(with_installed, HTML, 0, (), True) == [],
      "The app build line was required in a repo with no native app")

# A Light PR (references/testing-strategy.md § Size the checks to the change): a reasoned not-reached line
# alone passes the installed-build check, and a posted Part verdicts section needs no judge columns.
light = paired(PASSING).replace("Tier: deep (a member's search limit and its billing plan).",
                                "Tier: light (one admin page button, team-only).")
light_unreached = light.replace("## Screenshots",
                                "Installed builds: not reached, only the team admin site changes\n\n## Screenshots", 1)
check(gate.check_body(light_unreached, HTML_PAIR, 0, (), True) == [],
      f"A Light PR's not-reached line alone failed: {gate.check_body(light_unreached, HTML_PAIR, 0, (), True)}")
check(any("installed-version table" in m for m in gate.check_body(
          PASSING.replace("## Screenshots", "Installed builds: not reached, only the team admin site changes\n\n## Screenshots", 1),
          HTML, 0, (), True)),
      "A deep PR's not-reached line passed without its version table")
check(len([m for m in gate.check_body(light, HTML, 0, (), True) if m.startswith("Deploy safety:")]) == 3,
      "A Light PR with no installed-build line at all passed")
check(not [m for m in gate.check_body(light + PARTS.replace(" OpenAI judge |", "").replace(" agrees |\n", "\n"),
                                      HTML, 0) if m.startswith("Part verdicts")],
      "A Light PR's Part verdicts section was held to two judge columns")

# A Light PR needs only the rows its tier runs (references/testing-strategy.md § Size the checks to the
# change): no Prod data or Deploy safety heading, no Base-vs-head column, no walk line, and in a native-app
# repo no app build line or installed-build rows while the diff reaches no installed build. The fix for a
# one-rule CSS fix to a separate marketing-site Worker that took two body rewrites to pass.
SITE = "marketing/public/index.html"
LIGHT_MIN = """## TLDR

| Change | Before | After | Why |
|---|---|---|---|
| Hero at 1200 px and wider | The ask box covered the headline | The box sits 34 px under it | The headline was unreadable |

**Do:** merge. It deploys only the marketing-site Worker.

## Deploy TLDR

1. Merge. Smoke: the marketing page at 1440 px shows the box under the headline.

## User journey

1. A visitor on a laptop reads the whole headline, then the ask box.

## System journey

1. One media rule loses its negative margin; the 810 px rule applies.

## Test matrix

Tier: light (one CSS rule on a static marketing page). Skipped (tier light): full matrix, prod data, deploy safety.

| Check | Result |
|---|---|
| landing suite | 4/4 pass |

## Regression check

| File | Result |
|---|---|
| `marketing/public/index.html` | INTENDED: the hero gap at 1200 px and wider |

## Screenshots

![Before, 1440 px](https://github.com/user-attachments/assets/22222222-2222-2222-2222-222222222222)
![After, 1440 px](https://github.com/user-attachments/assets/33333333-3333-3333-3333-333333333333)
"""
HTML_MIN = '<h2>TLDR</h2><img src="a.png" alt="Before, 1440 px"><img src="b.png" alt="After, 1440 px">'
IGNORE = ("marketing/**",)
ROOTS = ["ios", "site", "marketing"]
check(not gate.reaches_installed_builds([SITE], ROOTS, IGNORE),
      "A file under installedBuilds.pathsIgnore was seen as reaching installed builds")
check(gate.reaches_installed_builds([SITE], ROOTS), "With no pathsIgnore, the marketing Worker file did not count")
check(gate.reaches_installed_builds([SITE, "site/web/app/page.tsx"], ROOTS, IGNORE),
      "pathsIgnore hid a hosted web file outside its globs")
reached = gate.reaches_installed_builds([SITE], ROOTS, IGNORE)
light_min = gate.check_body(LIGHT_MIN, HTML_MIN, 0, (SITE,), reached, native=True, changed=(SITE,))
check(light_min == [], f"A Light marketing-page PR with the minimal sections failed: {light_min}")
# The same body on a diff a shipped build loads still needs the native rows.
web = "site/web/app/page.tsx"
reached_web = gate.check_body(LIGHT_MIN.replace(SITE, web), HTML_MIN, 0, (web,), True, native=True, changed=(web,))
check(any(m.startswith("Deploy TLDR: no app build line") for m in reached_web)
      and any("installed-version table" in m for m in reached_web)
      and any("not reached" in m for m in reached_web),
      f"A Light PR reaching installed builds passed without the native rows: {reached_web}")
unreached_min = LIGHT_MIN.replace(SITE, web).replace(
    "## Screenshots", "## Deploy safety\n\nInstalled builds: not reached, the app never loads this page\n\n## Screenshots")
unreached_min = unreached_min.replace("1. Merge.", "No app build needed: the app never loads this page.\n\n1. Merge.")
check(gate.check_body(unreached_min, HTML_MIN, 0, (web,), True, native=True, changed=(web,)) == [],
      "A Light PR reaching installed builds failed with its app build and not-reached lines: "
      f"{gate.check_body(unreached_min, HTML_MIN, 0, (web,), True, native=True, changed=(web,))}")
# Standard keeps every row on the same body.
standard_min = gate.check_body(LIGHT_MIN.replace("Tier: light", "Tier: standard").replace("(tier light)", "(tier standard)"),
                               HTML_MIN, 0, (SITE,), reached, native=True, changed=(SITE,))
check({"Prod data", "Deploy safety"} <= rows(standard_min)
      and any("Base-vs-head evidence column" in m for m in standard_min)
      and any("no Real-environment walk line" in m for m in standard_min)
      and any(m.startswith("Deploy TLDR: no app build line") for m in standard_min),
      f"A Standard PR with the Light sections passed a row its tier keeps: {standard_min}")
# A Light label on a payment or native-code diff keeps every row: those paths hold a Deep trigger.
pay = "site/web/app/checkout/Pay.tsx"
pay_min = gate.check_body(LIGHT_MIN.replace(SITE, pay), HTML_MIN, 0, (pay,), False, native=True, changed=(pay,))
check({"Prod data", "Deploy safety"} <= rows(pay_min), f"A Light label on a payment path dropped rows: {pay_min}")
# The first named tier decides: a Standard matrix that mentions the light tier is not Light.
mention = LIGHT_MIN.replace("Tier: light (one CSS rule on a static marketing page).",
                            "Tier: standard (past the light tier's size).")
check("Prod data" in rows(gate.check_body(mention, HTML_MIN, 0, (SITE,), reached, native=True, changed=(SITE,))),
      "A Standard matrix mentioning the light tier was read as Light")
# Still checked on Light: the per-file row, its result, a FAIL walk, and the BEFORE/AFTER pair.
check(any("no row for 1" in m for m in gate.check_body(LIGHT_MIN, HTML_MIN, 0, ("marketing/x.css",), reached,
                                                        native=True, changed=(SITE,))),
      "A Light PR with no row for a modified file passed")
check(any("walk records a FAIL" in m for m in gate.check_body(
          LIGHT_MIN.replace("| landing suite", "Real-environment walk: FAIL, box still overlaps.\n\n| landing suite"),
          HTML_MIN, 0, (SITE,), reached, native=True, changed=(SITE,))),
      "A Light PR whose walk line records a FAIL passed")
one = LIGHT_MIN.replace("![Before, 1440 px](https://github.com/user-attachments/assets/22222222-2222-2222-2222-222222222222)\n", "")
check(any("BEFORE/AFTER pair" in m for m in gate.check_body(one, HTML_MIN, 0, (SITE,), reached, native=True,
                                                            changed=(SITE,))),
      "A Light PR posting one image passed without its pair")

# Unresolved review threads fail.
check(rows(gate.check_body(PASSING, HTML, 2)) == {"Review threads"}, "Unresolved review threads passed")


# CLI and hook, against a stub gh serving fixture JSON from $GH_STUB.
STUB = """#!/bin/sh
case "$1 $2" in
  "pr list") f=prlist.json ;;
  "pr view") f=prview.json ;;
  "run list") f=runs.json ;;
  "api graphql") f=threads.json ;;
  "api "*/files) f=files.txt ;;
  "api "*/reviews) f=reviews.txt ;;
  "api "*/pulls/*/comments) f=inline.txt ;;
  "api "*/issues/*/comments) f=people.txt ;;
  "api "*/contents) f=contents.txt ;;
  api*) f=pull.json ;;
  *) exit 1 ;;
esac
[ -f "$GH_STUB/$f" ] || { echo "stub: no $f" >&2; exit 1; }
cat "$GH_STUB/$f"
"""


def serve(stub, body, html=HTML, unresolved=0, prs=(7,), files=("src/auth/Gate.tsx",), head=None,
          ci=("SUCCESS",), roots=("src",), feedback=("1",)):
    """ci: one conclusion per check on `head` (PENDING = still running); head None serves no PR view.

    feedback: the ids gh prints for the PR's reviews; None serves no feedback files (a failed read)."""
    for name in ("prlist.json", "pull.json", "threads.json", "files.txt", "prview.json", "runs.json",
                 "contents.txt", "reviews.txt", "inline.txt", "people.txt"):
        (stub / name).unlink(missing_ok=True)
    if feedback is not None:
        (stub / "reviews.txt").write_text("".join(i + "\n" for i in feedback))
        (stub / "inline.txt").write_text("")
        (stub / "people.txt").write_text("")
    if head is not None:
        rollup = [{"__typename": "CheckRun", "name": f"check{i}", "workflowName": "ci",
                   "status": "IN_PROGRESS" if c == "PENDING" else "COMPLETED",
                   "conclusion": "" if c == "PENDING" else c, "startedAt": "2026-11-12T10:00:00Z",
                   "completedAt": "2026-11-12T10:00:00Z"} for i, c in enumerate(ci)]
        (stub / "prview.json").write_text(json.dumps({"mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                                                      "headRefOid": head, "statusCheckRollup": rollup}))
        (stub / "runs.json").write_text(json.dumps([{"databaseId": 1, "workflowName": "ci", "name": "ci",
                                                     "status": "in_progress" if "PENDING" in ci else "completed",
                                                     "conclusion": ""}]))
    if prs is not None:
        (stub / "prlist.json").write_text(json.dumps([{"number": n, "url": f"https://example.test/{n}"} for n in prs]))
    if body is not None:
        (stub / "pull.json").write_text(json.dumps({"body": body, "body_html": html}))
    if files is not None:
        (stub / "files.txt").write_text("".join(f + "\n" for f in files))
    (stub / "contents.txt").write_text("".join(d + "\n" for d in roots))
    nodes = [{"isResolved": False}] * unresolved + [{"isResolved": True}]
    (stub / "threads.json").write_text(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}))


with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    bindir, stub, home, repo = base / "bin", base / "stub", base / "home", base / "repo"
    for d in (bindir, stub, home, repo):
        d.mkdir()
    (bindir / "gh").write_text(STUB)
    (bindir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_STUB": str(stub), "HOME": str(home),
           "CLAUDE_CONFIG_ROOT": str(ROOT), "CLAUDE_INTENT_LEDGER": "on", "CLAUDE_PROJECT_DIR": str(repo),
           "CLAUDE_CODE_SESSION_ID": "landing-gate-test"}
    env.pop("AGENT_DELEGATED_WORKER", None)

    def cli():
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", "example-org/example-repo", "--pr", "7"],
                              capture_output=True, text=True, env=env)

    serve(stub, PASSING)
    r = cli()
    check(r.returncode == 0 and r.stdout.startswith("pr-landing-gate: PASS"), f"CLI pass: {r.returncode} {r.stdout}{r.stderr}")
    serve(stub, stamped)
    (stub / "pull.json").write_text(json.dumps({"body": stamped, "body_html": HTML, "head": {"sha": "fff" + HEAD[3:]}}))
    r = cli()
    check(r.returncode == 1 and "PR head is fff1234de" in r.stdout,
          f"CLI did not fail a body written for an earlier head: {r.returncode} {r.stdout}{r.stderr}")
    (stub / "pull.json").write_text(json.dumps({"body": stamped, "body_html": HTML, "head": {"sha": HEAD}}))
    r = cli()
    check(r.returncode == 0, f"CLI failed a body naming the current head: {r.returncode} {r.stdout}{r.stderr}")
    serve(stub, summary_only)
    r = cli()
    check(r.returncode == 1 and "FAIL example-org/example-repo#7 Test matrix" in r.stdout,
          f"CLI did not print the missing matrix row: {r.returncode} {r.stdout}")
    serve(stub, PASSING, files=("src/auth/Gate.tsx", "src/app/Frame.tsx"))
    r = cli()
    check(r.returncode == 1 and "Regression check: no row for 1" in r.stdout and "src/app/Frame.tsx" in r.stdout,
          f"CLI did not fail a modified file with no regression row: {r.returncode} {r.stdout}{r.stderr}")
    serve(stub, PASSING, files=None)
    r = cli()
    check(r.returncode == 2 and "FETCH FAILED" in r.stderr, f"A failed file-list fetch did not exit 2: {r.returncode} {r.stderr}")
    serve(stub, None)
    r = cli()
    check(r.returncode == 2 and "FETCH FAILED" in r.stderr, f"A fetch failure did not exit 2: {r.returncode} {r.stderr}")

    # The hook: a fixture worktree on a GitHub origin with a ledger.
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "feature/x")
    (repo / ".git" / "info" / "exclude").write_text(".context/\n")
    (repo / "a.txt").write_text("a")
    git("add", "a.txt")
    git("commit", "-q", "-m", "a")
    git("remote", "add", "origin", "https://github.com/example-org/example-repo.git")
    payload = json.dumps({"cwd": str(repo), "session_id": "landing-gate-test", "prompt": "Ship X"})
    subprocess.run(["bash", str(HOOK), "submit"], input=payload, text=True, capture_output=True, cwd=repo, env=env)
    ledger = repo / ".context" / "intent-ledger.md"
    check(ledger.exists(), "Fixture ledger was not created")

    def hook_gate(*args):
        return subprocess.run(["bash", str(HOOK), "gate", *args], text=True, capture_output=True, cwd=repo, env=env)

    # Every stage receipt on the fixture head, so these cases exercise the landing gate and CI legs.
    listed = subprocess.run(["bash", str(HOOK), "stages", "deep"], text=True, capture_output=True, cwd=repo,
                            env=env).stdout.split()
    check(len(listed) == 9, f"intent-ledger.sh stages deep did not list the deep stages: {listed}")
    for stage in listed:
        subprocess.run(["bash", str(HOOK), "skill"], text=True, capture_output=True, cwd=repo, env=env,
                       input=json.dumps({"cwd": str(repo), "session_id": "landing-gate-test", "tool_name": "Skill",
                                         "tool_input": {"skill": stage}}))
    LIGHT = ("light", "fixture; skipped: matrix")

    def gate_lines():
        return [ln for ln in ledger.read_text().splitlines() if ln.startswith("gate: ")] if ledger.exists() else []

    serve(stub, summary_only)
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 1 and "Test matrix" in r.stderr and "PASS refused" in r.stderr and gate_lines() == [],
          f"gate PASS recorded over a failing PR: {r.returncode} {r.stderr}")
    r = hook_gate("feature/x", "HEAD", "BLOCKED", "matrix not posted yet")
    check(r.returncode == 0 and len(gate_lines()) == 1, f"gate BLOCKED changed behaviour: {r.returncode} {r.stderr}")
    serve(stub, None, prs=None)
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 1 and "gh pr list failed" in r.stderr and len(gate_lines()) == 1,
          f"A failed PR lookup did not refuse PASS: {r.returncode} {r.stderr}")
    # CI on the gate's head: every check green, or PASS records nothing whatever the reason says.
    head = git("rev-parse", "HEAD")
    serve(stub, PASSING, head=head, ci=("SUCCESS", "FAILURE"))
    r = hook_gate("feature/x", "HEAD", "PASS", "deep", "All stages ran; the failing check fails by design")
    check(r.returncode == 1 and "FAILED" in r.stderr and "ci / check1" in r.stderr and "not all green" in r.stderr
          and len(gate_lines()) == 1, f"gate PASS recorded over a failing CI check: {r.returncode} {r.stderr}")
    serve(stub, PASSING, head=head, ci=("SUCCESS", "PENDING"))
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 1 and "PENDING" in r.stderr and "exit 6" in r.stderr and len(gate_lines()) == 1,
          f"gate PASS recorded over a pending CI check: {r.returncode} {r.stderr}")
    serve(stub, PASSING, head="b" * 40)
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 1 and "HEAD MOVED" in r.stderr and len(gate_lines()) == 1,
          f"gate PASS recorded for a sha that is not the PR head: {r.returncode} {r.stderr}")
    serve(stub, PASSING)
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 1 and "not all green" in r.stderr and len(gate_lines()) == 1,
          f"gate PASS recorded when the CI read failed: {r.returncode} {r.stderr}")
    serve(stub, PASSING, head=head)
    r = hook_gate("feature/x", head[:9], "PASS", *LIGHT)
    check(r.returncode == 0 and "pr-landing-gate: PASS" in r.stdout and "PASSED" in r.stdout
          and gate_lines()[-1] == f"gate: feature/x {head} PASS light fixture; skipped: matrix; "
          "stood in for by the open PR: sk:ship-screenshot-changes",
          f"gate PASS over a passing PR with green CI did not record the full sha: {r.returncode} {r.stdout}{r.stderr}")
    r = hook_gate("feature/x", "0123abcd", "PASS", *LIGHT)
    check(r.returncode == 2 and "Not run:" in r.stderr and len(gate_lines()) == 2,
          f"gate PASS accepted a short sha with no stage receipts: {r.returncode} {r.stderr}")
    serve(stub, None, prs=())
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 0 and len(gate_lines()) == 3, f"gate PASS with no open PR changed behaviour: {r.stderr}")
    git("remote", "set-url", "origin", "https://example.test/o/r.git")
    serve(stub, None, prs=None)
    r = hook_gate("feature/x", "HEAD", "PASS", *LIGHT)
    check(r.returncode == 0 and len(gate_lines()) == 4, f"gate PASS on a non-GitHub origin changed behaviour: {r.stderr}")

    # A Light head with an open PR: the PR stands in for the screenshot stage (the landing gate checks its
    # Screenshots section) and, with no review or comment, for the feedback stage. A fresh head behind a
    # Deep path, so no earlier receipt carries to it.
    git("remote", "set-url", "origin", "https://github.com/example-org/example-repo.git")
    (repo / "ios").mkdir()
    (repo / "ios" / "a.swift").write_text("a")
    git("add", "ios/a.swift")
    git("commit", "-q", "-m", "ios")

    def stages_light(*extra):
        return subprocess.run(["bash", str(HOOK), "stages", "light", "HEAD", "feature/x", *extra], text=True,
                              capture_output=True, cwd=repo, env=env)
    serve(stub, PASSING, feedback=())
    r = stages_light()
    check(r.returncode == 1 and r.stdout.splitlines()[-1] == "Not run: sk:ship-pr"
          and "Stood in for by the open PR: sk:ship-screenshot-changes sk:ship-resolve-pr-comments" in r.stdout,
          f"A Light head whose open PR has no feedback still needed the feedback and screenshot stages: {r.stdout}{r.stderr}")
    serve(stub, PASSING, feedback=("12",))
    r = stages_light()
    check(r.stdout.splitlines()[-1] == "Not run: sk:ship-resolve-pr-comments, sk:ship-pr",
          f"A Light head whose open PR has a review skipped the feedback stage: {r.stdout}{r.stderr}")
    serve(stub, PASSING, feedback=None)
    r = stages_light()
    check(r.stdout.splitlines()[-1] == "Not run: sk:ship-resolve-pr-comments, sk:ship-pr",
          f"A failed feedback read waived the feedback stage: {r.stdout}{r.stderr}")
    serve(stub, None, prs=())
    r = stages_light()
    check(r.stdout.strip() == "Not run: sk:ship-resolve-pr-comments, sk:ship-screenshot-changes, sk:ship-pr",
          f"A Light head with no open PR waived a stage: {r.stdout}{r.stderr}")
    serve(stub, PASSING, feedback=())
    r = subprocess.run(["bash", str(HOOK), "stages", "standard", "HEAD", "feature/x"], text=True,
                       capture_output=True, cwd=repo, env=env)
    check("sk:ship-resolve-pr-comments" in r.stdout and "sk:ship-screenshot-changes" in r.stdout
          and "Stood in for" not in r.stdout, f"A Standard head waived a stage: {r.stdout}{r.stderr}")
    r = subprocess.run(["bash", str(HOOK), "gate", "feature/x", "HEAD", "PASS", "light", "fixture; skipped: matrix"],
                       text=True, capture_output=True, cwd=repo, env={**env, "LIGHT_WAIVED": "sk:ship-pr"})
    check(r.returncode == 2 and "Not run: sk:ship-pr" in r.stderr,
          f"An inherited LIGHT_WAIVED waived a stage: {r.returncode} {r.stderr}")

    # The CLI reads the repo's top-level folders: a hosted web change in a repo with an iOS app needs the lines.
    serve(stub, PASSING, files=("src/auth/Gate.tsx",), roots=("ios", "src"))
    r = cli()
    check(r.returncode == 1 and "no installed-version table" in r.stdout,
          f"CLI passed a native-app PR with no installed-build lines: {r.returncode} {r.stdout}")
    serve(stub, with_installed, files=("src/auth/Gate.tsx",), roots=("ios", "src"))
    r = cli()
    check(r.returncode == 1 and "no app build line" in r.stdout,
          f"CLI passed a native-app PR with no app build line: {r.returncode} {r.stdout}")
    serve(stub, with_app, files=("src/auth/Gate.tsx",), roots=("ios", "src"))
    r = cli()
    check(r.returncode == 0, f"CLI failed a native-app PR with its installed-build and app build lines: {r.stdout}{r.stderr}")

    # installedBuilds.pathsIgnore from the local overlay: the marketing Worker reaches no installed build.
    reg = base / "registry"
    (reg / "projects").mkdir(parents=True)
    (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
    (reg / "projects" / "site.json").write_text(json.dumps({
        "match": ["example-org/example-repo"], "installedBuilds": {"pathsIgnore": list(IGNORE)}}))
    (base / "identity.json").write_text("{}")
    env.update({"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(base / "identity.json")})
    serve(stub, LIGHT_MIN, html=HTML_MIN, files=(SITE,), roots=tuple(ROOTS))
    r = cli()
    check(r.returncode == 0, f"CLI failed a Light marketing-page PR whose path the overlay ignores: {r.stdout}{r.stderr}")
    serve(stub, LIGHT_MIN.replace(SITE, web), html=HTML_MIN, files=(web,), roots=tuple(ROOTS))
    r = cli()
    check(r.returncode == 1 and "no app build line" in r.stdout and "installed-version table" in r.stdout,
          f"CLI passed a Light PR reaching installed builds without the native rows: {r.returncode} {r.stdout}")
    (reg / "projects" / "site.json").write_text(json.dumps({
        "match": ["example-org/example-repo"], "installedBuilds": {"pathsIgnore": ["**"]}}))
    serve(stub, LIGHT_MIN, html=HTML_MIN, files=(SITE,), roots=tuple(ROOTS))
    r = cli()
    check(r.returncode == 1 and "starts with a wildcard" in r.stderr,
          f"A malformed pathsIgnore loosened the gate: {r.returncode} {r.stdout}{r.stderr}")
    (reg / "projects" / "site.json").write_text("{broken")
    r = cli()
    check(r.returncode == 1 and "not read" in r.stderr, f"An unreadable overlay loosened the gate: {r.returncode} {r.stderr}")
    for k in ("CLAUDE_CONNECTOR_ROOTS", "CLAUDE_IDENTITY_FILE"):
        env.pop(k)

    # --feedback-count: reviews, review comments and comments by a person.
    def feedback(*ids, inline=(), people=()):
        serve(stub, PASSING, feedback=ids)
        (stub / "inline.txt").write_text("".join(i + "\n" for i in inline))
        (stub / "people.txt").write_text("".join(i + "\n" for i in people))
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", "example-org/example-repo", "--pr", "7",
                               "--feedback-count"], capture_output=True, text=True, env=env)
    r = feedback()
    check(r.returncode == 0 and r.stdout.strip() == "0", f"A PR with no feedback did not count 0: {r.stdout}{r.stderr}")
    r = feedback("9", inline=("4",), people=("5", "6"))
    check(r.returncode == 0 and r.stdout.strip() == "4", f"Feedback was miscounted: {r.stdout}{r.stderr}")
    serve(stub, PASSING, feedback=None)
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", "example-org/example-repo", "--pr", "7",
                        "--feedback-count"], capture_output=True, text=True, env=env)
    check(r.returncode == 2 and "FETCH FAILED" in r.stderr, f"A failed feedback read did not exit 2: {r.returncode}")

    # The CLI passes the PR's whole changed-file list to the walk rule.
    native_rows = "".join(f"| `{f}` | 1 | Purchase | unit suite on base and head | PASS |\n" for f in NATIVE_FILES)
    with_native = with_app.replace("| `Gate` newly mounted", native_rows + "| `Gate` newly mounted", 1)
    serve(stub, with_native.replace(WALK_LINE, cannot_run), files=NATIVE_FILES, roots=("ios", "src"))
    r = cli()
    check(r.returncode == 1 and "touches native app code" in r.stdout,
          f"CLI passed a deep native PR whose walk was an N/A for another reason: {r.returncode} {r.stdout}")
    serve(stub, with_native.replace(WALK_LINE, sim_walk), files=NATIVE_FILES, roots=("ios", "src"))
    r = cli()
    check(r.returncode == 0, f"CLI failed a deep native PR with a simulator walk: {r.stdout}{r.stderr}")

if FAILS:
    print("pr-landing-gate.test: FAIL\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("pr-landing-gate.test: PASS")
