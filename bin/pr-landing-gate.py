#!/usr/bin/env python3
"""Check a fetched PR against the ship harness landing gate; exit non-zero naming each missing row.

  pr-landing-gate.py --repo <owner/name> --pr <n>

Fetches the PR body markdown and body_html (`gh api ... full+json`) and every review thread (gh
GraphQL), then checks the rows /sk:ship-full-detailed-workflow § Landing gate lists. SECTIONS below
is the ONE home of the PR body's section headings: /sk:ship-pr, references/tldr-report-formats.md
and the harness name this file instead of restating them. A heading matches with any emoji or
punctuation prefix and any case ("## 🚀 Deploy TLDR"), and may carry a suffix after a non-letter
("## Test matrix (head abc1234)"). The Test matrix heading names the PR's current head sha, so a body
written for an earlier head fails (/sk:ship-pr § Rewrite the body when the PR changes). The TLDR table
header names Before, After and Why, in that order. The Test matrix section also holds a Real-environment
walk line. On a deep PR whose changed files touch native app code (ios/ or android/, tests excluded) or a
payment or entitlement path (PAYMENT_PATH), that line names a simulator, device or local-stack walk with
PASS, or a reasoned does-not-apply naming why no user journey changed; a line resting on unit tests, or a
does-not-apply giving any other reason (e.g. "a real purchase cannot run locally"), fails
(references/testing-strategy.md § Pre-merge end-to-end on a local stack).
On a Standard or Deep PR, the Test matrix table whose rows hold COVERED carries a 'Fails without the
change' column, filled on every COVERED row (`base fails`, `mutant <break>: FAILED` or `n/a: <why>`),
and no cell records a surviving mutant (references/testing-strategy.md § Prove each test fails without
the change).
The Regression check section holds one row per pre-existing file the PR modifies, renames or removes
(the PR's file list, `gh api .../pulls/<n>/files`), each with PASS or INTENDED and a filled cell in the
table's Base-vs-head evidence column: the method is references/testing-strategy.md § Regression check.
A PR whose Test matrix names the deep tier holds a Value safety section: its six labelled lines, or a
reasoned does-not-apply (references/testing-strategy.md § Value safety). Unless its Provider lifecycle
line is a reasoned does-not-apply, the section holds a Provider lifecycle sub-heading whose table has
one row per documented provider case (PROVIDER_CASES minimum), each with a doc link and a SAFE, GAP or
N/A verdict, and no GAP row.
A Screenshots or Verification runs section that posts no evidence and states no visible surface (or a
does-not-apply) carries a "Checked outputs:" clause naming what was compared on base and head
(references/screenshot-review.md § Visible surfaces); a bare "No eligible frontend surface" fails, and so
does a reason naming "no new screen", "no new copy", "existing screen", "existing step" or "same screen".
In a repo that ships a native app (a top-level ios/ or android/ directory), a PR that changes any other
runtime file (a server, database, Worker or hosted web file the installed builds call or load) holds,
in Deploy safety, the installed-version table, one `Old build <version> against the new backend: PASS`
line per walked version or an `Installed builds: not reached, <why>` line, and a `Waits for the new
build:` line (references/git-pr-deploy.md § Deploy safety check 4). An `Old build ... BLOCKED` line is
recorded but fails the gate: an unwalked installed build is never a pass. A file matching the project
entry's `installedBuilds.pathsIgnore` globs in the local connector overlay (read through
bin/monitoring_only.py, e.g. a separate marketing-site Worker the app never loads) reaches no installed
build; an unreadable overlay ignores nothing.
In such a repo every Standard or Deep PR's Deploy TLDR, a native-only or web-only PR included, holds an
app build line: `No app build needed: <why>` or `Needs an app build: <which parts wait for it>` (check 4).
A Light PR (the Test matrix's first named tier is light, no deep tier is named, and no changed file is
native app code or a payment or entitlement path) needs fewer rows, because references/testing-strategy.md
§ Size the checks to the change skips those stages at Light: no Prod data or Deploy safety heading, no
Base-vs-head column in the Regression check table (each modified file still has its PASS or INTENDED
row), no Real-environment walk line, and the app build line only when the diff reaches installed builds.
When it does, the installed-build rows above still apply, and the `Installed builds: not reached, <why>`
line alone passes: no version table or Waits line. A Light Screenshots section that posts images posts
the BEFORE/AFTER pair, two images or more: with the PR open, it stands in for the
sk:ship-screenshot-changes stage receipt (hooks/intent-ledger.sh).
A Hotfix PR (the Test matrix's first named tier is hotfix and it names no deep tier) is sized by
references/testing-strategy.md § Hotfix tier: it fails when its changed files hold more than
HOTFIX_MAX_FILES product file (tests, docs and CI excluded) or any migration, schema or SQL file. Its
Test matrix holds the Root cause, Mainstream practice (a link, or departs: <why>) and Judge lines and
the Fails without the change column; its Regression check holds the Base-vs-head column and the Happy
paths and Paid paths lines; its Deploy TLDR holds Check:, Smoke: and Rollback:. It needs no Prod data
heading, no merge-train or rollback row and no Part verdicts. The safety rows stay when the diff touches
them: a payment, entitlement or auth file (VALUE_PATH) needs Value safety, native app code or a payment
path needs the Real-environment walk, and a file installed builds load needs the installed-build lines.
`--feedback-count` prints the PR's reviews, review comments and non-bot comments, so the gate can tell
a Light or Hotfix PR with nothing to resolve (hooks/intent-ledger.sh light_waivers).
A posted Part verdicts section holds a table whose header names Verdict, Mainstream practice, Regression
evidence and a judge column per provider, with a primary-source link in every row
(references/tldr-report-formats.md § Part verdicts). The section is checked when present, so a PR body
written before it existed still passes; the work harness's TEST requires it on Standard and Deep build,
adopt and rebuild PRs. A Light PR's Part verdicts section is never checked: its judges are not required
(references/research.md § Independent judges).
Every posted image renders: body_html holds at least one <img> per image the body references (a Markdown
image with alt text, or an <img> tag, outside code). An <img> whose alt holds a raw double quote ends the
attribute early, so GitHub shows the whole tag as text (references/screenshot-review.md § PR evidence
template; `bin/pr-evidence.py size-images` writes the tags with the alt escaped).

hooks/intent-ledger.sh `gate <branch> <sha> PASS` runs this for a branch with an open PR and refuses
to record PASS unless it exits 0. Exit 0: one PASS line. Exit 1: one FAIL line per missing row.
Exit 2: usage error, or a fetch failed (a fetch failure never passes).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The PR body's section headings, in body order. Key = gate row name, value = canonical heading.
SECTIONS = {
    "TLDR": "TLDR",
    "Deploy TLDR": "Deploy TLDR",
    "User journey": "User journey",
    "System journey": "System journey",
    "Test matrix": "Test matrix",
    "Regression check": "Regression check",
    "Prod data": "Prod data",
    "Value safety": "Value safety",
    "Deploy safety": "Deploy safety",
    "Screenshots": "Screenshots",
    "Verification runs": "Verification runs",
    "Part verdicts": "Part verdicts",
}
MATRIX_COUNTS = ("COVERED", "GAP", "NEEDS-DRIVING", "SKIPPED")
# What each section must hold, printed with a missing heading so one gate run names every requirement
# instead of revealing them one rewrite at a time. Keep in step with the checks in check_body.
NEEDS = {
    "TLDR": "first heading; a | Change | Before | After | Why | table, biggest impact first; a **Do:** line",
    "Deploy TLDR": ("the next heading after the TLDR; numbered deploy steps; in a repo with a native app, "
                    "a 'No app build needed: <why>' or 'Needs an app build: <which parts wait>' line"),
    "User journey": "what the user goes through",
    "System journey": "what the system does, in steps",
    "Test matrix": ("a tier named (hotfix, light, standard or deep) with its trigger; counts for "
                    + ", ".join(MATRIX_COUNTS) + "; a results table; a 'Real-environment walk:' line "
                    "with PASS, a reasoned does-not-apply or a skip line; on a deep PR touching native app "
                    "code or a payment or entitlement path, the simulator, device or local-stack walks with "
                    "PASS, or a does-not-apply naming why no user journey changed; on a standard or deep PR, "
                    "a 'Fails without the change' column filled on every COVERED row, no mutant surviving; "
                    "on a hotfix PR, the Root cause:, Mainstream practice: and Judge: lines"),
    "Regression check": ("a table with a Base-vs-head evidence column; a row per modified pre-existing file, "
                         "each with evidence and PASS or INTENDED"),
    "Prod data": "a PASS or FAIL verdict and a cohort table, or a reasoned does-not-apply; not on a Light PR",
    "Value safety": ("on a deep-tier PR, the lines Happy path:, Failure re-enacted:, Wrong recipient:, "
                     "Incident replay: (with N/N), Provider lifecycle: and Residual risk:, or a reasoned "
                     "does-not-apply; a ### Provider lifecycle table (Case | Provider doc | Verdict | "
                     "Evidence) with a doc link and SAFE, GAP or N/A per row, no GAP, unless the Provider "
                     "lifecycle line is a reasoned does-not-apply"),
    "Deploy safety": ("a merge-train result and a rollback, or a reasoned does-not-apply; in a repo with a "
                      "native app, when the PR changes a file its installed builds call or load: a version "
                      "| share table, 'Old build <version> against the new backend: PASS' per version or "
                      "'Installed builds: not reached, <why>', and 'Waits for the new build: <list or none>'; "
                      "a Light PR needs the heading only for those installed-build lines, and then the "
                      "not-reached line alone"),
    "Screenshots": "an image, or a no-visible-surface reason with a 'Checked outputs:' clause",
    "Part verdicts": ("a table whose header names Verdict, Mainstream practice, Regression evidence and "
                      "a judge column per provider; a primary-source link in every row"),
}


NO_OUTPUTS = ("{}: a no-surface or does-not-apply line with no 'Checked outputs:' clause naming the "
              "outputs compared on base and head (chat replies, messages, bot posts, admin pages)")


def no_heading(row):
    """The missing-heading line for a row, with everything its section must hold."""
    return f"{row}: no {SECTIONS[row]} heading (needs: {NEEDS[row]})"
DOES_NOT_APPLY = re.compile(r"does(?: not|n['’]t) apply|\bN/A\b", re.I)
NO_SURFACE = re.compile(r"no (?:eligible |changed |visible )?(?:frontend |UI |user-facing )?surface|"
                        r"no (?:frontend|UI|visible) change", re.I)
# references/screenshot-review.md § Visible surfaces: a no-surface claim names the outputs it compared.
CHECKED_OUTPUTS = re.compile(r"checked outputs\W{0,3}:\**\s*\S+(?:\s+\S+){2,}", re.I)
# references/screenshot-review.md § Visible surfaces: a change to which existing screen or step a person
# reaches is visible, so "no new screen" or "reuses an existing screen" is never a no-surface reason.
ROUTE_REASON = re.compile(r"no new (?:screens?|copy)\b|\bexisting (?:screens?|steps?)\b|\bsame screens?\b", re.I)
ROUTE_MSG = ("{}: the no-surface reason names a new-screen or new-copy test; a change to which existing screen "
             "or step a person reaches is visible (references/screenshot-review.md § Visible surfaces)")
# references/testing-strategy.md § Size the checks to the change: a Light or Standard PR keeps each
# skipped heading with this line, and its trigger is at least three words.
TIER_SKIP = re.compile(r"Skipped \((?:tier )?(?:hotfix|light|standard)\)\s*:\s*\S+(?:\s+\S+){2,}", re.I)
DEEP_TIER = re.compile(r"\btier\b\W{0,3}deep\b|\bdeep\W{0,3}tier\b", re.I)
LIGHT_TIER = re.compile(r"\btier\b\W{0,3}light\b|\blight\W{0,3}tier\b", re.I)
HOTFIX_TIER = re.compile(r"\btier\b\W{0,3}hotfix\b|\bhotfix\W{0,3}tier\b", re.I)
# references/testing-strategy.md § Hotfix tier: one product file, no migration, schema or SQL file.
HOTFIX_MAX_FILES = 1
MIGRATION_PATH = re.compile(r"(^|/)(migrations?|db|schemas?)/|\.sql$|(^|/)schema\.[a-z]+$|\.prisma$", re.I)
# The lines a Hotfix PR states in place of the stages it skips, each with three or more words after it.
HOTFIX_MATRIX_LINES = ("Root cause", "Mainstream practice", "Judge")
HOTFIX_REGRESSION_LINES = ("Happy paths", "Paid paths")
HOTFIX_DEPLOY_LINES = ("Check", "Smoke", "Rollback")
# A hotfix touching auth or access keeps Value safety beside the payment paths.
AUTH_PATH = re.compile(r"auth|login|sign-?in|permission|polic(?:y|ies)", re.I)
# references/testing-strategy.md § Size the checks to the change: one BEFORE/AFTER pair at Light.
LIGHT_PAIR = 2
# references/testing-strategy.md § Value safety: the labelled lines, in order.
VALUE_LABELS = ("Happy path", "Failure re-enacted", "Wrong recipient", "Incident replay", "Provider lifecycle",
                "Residual risk")
# references/testing-strategy.md § Value safety question 5: one matrix row per documented lifecycle category.
PROVIDER_CASES = 11
LIFECYCLE_HEADING = re.compile(r"^#{3,6}\W*provider lifecycle\b", re.I | re.M)
LIFECYCLE_VERDICT = re.compile(r"\b(SAFE|GAPS?|N/A)\b")
TIER_NAMED = re.compile(r"\btier\b\W{0,3}(?:hotfix|light|standard|deep)\b|\b(?:hotfix|light|standard|deep)\W{0,3}tier\b", re.I)
# /sk:test-automated-full-matrix's real-environment walk: one line in the Test matrix section.
WALK = re.compile(r"^.*real[- ]environment walk.*$", re.I | re.M)
# references/testing-strategy.md § Pre-merge end-to-end: a deep PR touching native app code or a payment or
# entitlement path walks its changed journeys on a real client; unit tests and "cannot run locally" never count.
NATIVE_CODE = re.compile(r"^(?:ios|android)/")
NATIVE_TEST = re.compile(r"(?:Tests|androidTest|/test)/|Tests?\.(?:swift|kt|java|m)$")
PAYMENT_PATH = re.compile(r"payment|paywall|payer|checkout|stripe|revenuecat|entitlement|purchase|subscri|"
                          r"billing|refund|invoice|storekit", re.I)
NATIVE_ENV = re.compile(r"\b(?:simulator|emulator|device|iPhone|iPad|TestFlight)\b", re.I)
WALK_ENV = re.compile(NATIVE_ENV.pattern + r"|\blocal stack\b|\bbrowser\b|\bPlaywright\b", re.I)
UNIT_TESTS = re.compile(r"\bunit[- ]tests?\b|\bXCTest\b", re.I)
WALKED = re.compile(r"\bW\d+\b|\bwalk(?:s|ed)\b|\bjourneys?\b|\bend[- ]to[- ]end\b|\be2e\b|\blocal stack\b", re.I)
NO_JOURNEY = re.compile(r"\bno (?:user[- ]|purchase |payment |sign[- ]in |changed )?journeys?\b|"
                        r"\b(?:changes|touches|alters) no (?:user[- ])?journeys?\b|"
                        r"\bjourneys? (?:is |are |stays? |stay )?(?:unchanged|not changed)\b", re.I)
# A posted video: an inline <video> or a bare GitHub attachment URL alone on its line (images are <img> or ![]()).
VIDEO = re.compile(r"<video\s|^\s*https://github\.com/user-attachments/assets/\S+\s*$", re.I | re.M)
# references/screenshot-review.md § Verification run videos: the labels each run block and the section carry.
RUN_LABELS = ("Findings:", "Fixed during review:", "Not covered:", "Sources:")
# references/testing-strategy.md § Regression check: a row's result, and the file statuses that need a row.
REGRESSION_OK = re.compile(r"\b(?:PASS|INTENDED)\b")
# The column holding each row's proof: a base-vs-head test or screenshot comparison, never empty.
EVIDENCE_COLUMN = re.compile(r"base[- ]vs[- ]head", re.I)
# references/tldr-report-formats.md § Before/after TLDR: the table header names Before, After and Why, in order.
TLDR_HEADER = re.compile(r"^\s*\|[^\n]*\bBefore\b[^\n]*\|[^\n]*\bAfter\b[^\n]*\|[^\n]*\bWhy\b[^\n]*\|", re.M | re.I)
# /sk:ship-pr § Rewrite the body when the PR changes: the Test matrix heading names the head it describes.
HEAD_NAMED = re.compile(r"\bhead\W{0,3}([0-9a-f]{7,40})\b", re.I)
REGRESSION_BAD = re.compile(r"\b(?:FAIL|REGRESSED)\b")
# references/testing-strategy.md § Prove each test fails without the change: on a Standard or Deep PR each
# COVERED row of the Test matrix table names how its test was seen to fail; a mutant the test passed survived.
FAILS_COLUMN = re.compile(r"fails without", re.I)
COVERED_ROW = re.compile(r"\bCOVERED\b")
SURVIVED = re.compile(r"surviv|\bmutant\b[^|;]*:\s*\**PASS", re.I)
PRE_EXISTING = ("modified", "renamed", "removed", "changed")
COLLAPSED = re.compile(r"<details(?![^>]*\bopen\b)[^>]*>", re.I)
# A posted image in the body markdown: a Markdown image (group 1 its alt, group 2 its URL) or an <img> tag.
# An empty-alt `![](url)` is the attachment form of a video (references/screenshot-review.md), never counted.
MD_IMAGE = re.compile(r"!\[((?:\\.|[^\]\\\n])*)\]\(\s*<?([^\s)>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
IMG_TAG = re.compile(r"<img\b", re.I)
THREADS_QUERY = """query($owner:String!,$name:String!,$pr:Int!,$after:String){
  repository(owner:$owner,name:$name){pullRequest(number:$pr){
    reviewThreads(first:100,after:$after){nodes{isResolved} pageInfo{hasNextPage endCursor}}}}}"""


def normalize(text):
    text = re.sub(r"^[^0-9A-Za-z]+", "", text.strip().rstrip("#").strip())
    return text.replace("TL;DR", "TLDR").replace("tl;dr", "tldr").lower()


def headings(body):
    """(level, normalized text, line index) for every ATX heading outside a code fence."""
    out, fence = [], None
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            h = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
            if h:
                out.append((len(h.group(1)), normalize(h.group(2)), i))
    return out, lines


def matches(text, canonical):
    want = canonical.lower()
    return text == want or (text.startswith(want) and not text[len(want)].isalpha())


def sections(body):
    """Row name -> section text (heading to the next heading of the same or a higher level)."""
    found, lines = headings(body)
    out = {}
    for n, (level, text, start) in enumerate(found):
        for row, canonical in SECTIONS.items():
            if row in out or not matches(text, canonical):
                continue
            end = next((s for lv, _, s in found[n + 1:] if lv <= level), len(lines))
            out[row] = "\n".join(lines[start + 1:end])
    return out, found


def has_table(text):
    return re.search(r"^\s*\|.*\|\s*$\n^\s*\|[\s:|-]*-[\s:|-]*\|\s*$\n^\s*\|.*\|", text, re.M) is not None


def count_of(text, label):
    pat = re.escape(label) + ("S?" if label == "GAP" else "")
    return re.search(r"\d+\s*\**\s*" + pat + r"\b|\b" + pat + r"\**\s*[:=]?\s*\**\s*\d+", text)


def route_reason(text):
    """True when the no-surface reason (the text before any Checked outputs clause) rests on a new-screen test."""
    return ROUTE_REASON.search(re.split(r"checked outputs", text, maxsplit=1, flags=re.I)[0]) is not None


def reasoned_na(text):
    """A doesn't-apply verdict with a reason: the line naming it carries 5+ other words."""
    for line in text.splitlines():
        if DOES_NOT_APPLY.search(line) and len(DOES_NOT_APPLY.sub(" ", line).split()) >= 5:
            return True
    return False


def check_regression(text, modified, light=False):
    """Missing-row strings for the Regression check section; modified = pre-existing paths the PR changes.

    light: a Light PR, whose rows need PASS or INTENDED but no Base-vs-head evidence column.
    """
    if text is None:
        return [no_heading("Regression check")]
    rows = [ln for ln in text.splitlines() if re.match(r"^\s*\|.*\|\s*$", ln)]
    out = []
    if any(REGRESSION_BAD.search(r) for r in rows):
        out.append("Regression check: a row records FAIL")
    if not modified:
        if not has_table(text) and not reasoned_na(text) \
                and not re.search(r"no pre-?existing file", text, re.I):
            out.append("Regression check: no table and no stated no-pre-existing-file reason")
        return out
    if not has_table(text):
        return out + ["Regression check: no table for the PR's modified pre-existing files"]
    cells = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]
    header = next((cells(r) for r in rows if any(EVIDENCE_COLUMN.search(c) for c in cells(r))), None)
    column = next((i for i, c in enumerate(header or []) if EVIDENCE_COLUMN.search(c)), None)
    if column is None and not light:
        out.append("Regression check: the table has no Base-vs-head evidence column")
    unlisted, unresolved, unevidenced = [], [], []
    for path in modified:
        hits = [r for r in rows if path in r.replace("`", "")]
        if not hits:
            unlisted.append(path)
            continue
        if not any(REGRESSION_OK.search(r) for r in hits):
            unresolved.append(path)
        if column is not None and not any(
            len(cells(r)) > column and cells(r)[column] not in ("", "-", "–", "—") for r in hits
        ):
            unevidenced.append(path)
    if unlisted:
        shown = ", ".join(unlisted[:5]) + (f" and {len(unlisted) - 5} more" if len(unlisted) > 5 else "")
        out.append(f"Regression check: no row for {len(unlisted)} modified pre-existing file(s): {shown}")
    if unresolved:
        out.append("Regression check: no PASS or INTENDED result for " + ", ".join(unresolved[:5]))
    if unevidenced:
        out.append("Regression check: no base-vs-head evidence for " + ", ".join(unevidenced[:5]))
    return out


PART_COLUMNS = ("Verdict", "Mainstream", "Regression")
LINK = re.compile(r"https?://|\]\(")


def check_part_verdicts(text):
    """Missing-row strings for a posted Part verdicts section (references/tldr-report-formats.md)."""
    if text is None:
        return []
    if not has_table(text):
        return ["Part verdicts: no table (needs: " + NEEDS["Part verdicts"] + ")"]
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    header = rows[0].lower()
    out = []
    absent = [c for c in PART_COLUMNS if c.lower() not in header]
    if absent:
        out.append("Part verdicts: the table header has no " + ", ".join(absent) + " column")
    if header.count("judge") < 2:
        out.append("Part verdicts: fewer than two judge columns (one per provider)")
    unlinked = [r for r in rows[2:] if not LINK.search(r)]
    if unlinked:
        out.append(f"Part verdicts: {len(unlinked)} row(s) with no primary-source link")
    return out


def check_value_safety(text, deep):
    """Missing-row strings for the Value safety section; required when the Test matrix names the deep tier."""
    if text is None:
        return [no_heading("Value safety")] if deep else []
    if TIER_SKIP.search(text) or (reasoned_na(text) and not any(
            re.search(r"^[\s|*>-]*" + re.escape(label), text, re.I | re.M) for label in VALUE_LABELS)):
        return []
    out = []
    lines = {}
    for label in VALUE_LABELS:
        hit = re.search(r"^[\s|*>-]*" + re.escape(label) + r"\b.*$", text, re.I | re.M)
        if hit:
            lines[label] = hit.group(0)
    absent = [label for label in VALUE_LABELS if label not in lines]
    if absent:
        out.append("Value safety: no " + ", ".join(label + ":" for label in absent) + " line")
    if any(re.search(r"\bFAIL(?:ED|S)?\b", line) for label, line in lines.items() if label != "Residual risk"):
        out.append("Value safety: a line records a FAIL")
    replay = lines.get("Incident replay")
    if replay and not re.search(r"\b\d+\s*/\s*\d+\b", replay) and not reasoned_na(replay):
        out.append("Value safety: the Incident replay line has no N/N count and no doesn't-apply reason")
    lifecycle = lines.get("Provider lifecycle")
    # A count line ("11 rows: 10 SAFE, 1 N/A") is not a does-not-apply, and a posted matrix is always checked.
    counted = re.search(r"\d+\s+(?:SAFE|GAPS?|N/A)\b", lifecycle or "")
    if lifecycle and (counted or not reasoned_na(lifecycle) or LIFECYCLE_HEADING.search(text)):
        out += check_lifecycle_matrix(text)
    return out


def check_lifecycle_matrix(text):
    """Missing-row strings for the ### Provider lifecycle case matrix inside Value safety."""
    hit = LIFECYCLE_HEADING.search(text)
    if not hit:
        return ["Value safety: no ### Provider lifecycle case matrix (Case | Provider doc | Verdict | Evidence)"]
    body = text[hit.end():]
    nxt = re.search(r"^#{1,6}\s", body, re.M)
    body = body[:nxt.start()] if nxt else body
    rows = []
    for ln in body.splitlines():
        if ln.strip().startswith("|"):
            rows.append(ln)
        elif rows and ln.strip():
            break  # the first table after the heading is the matrix
    cases = rows[2:] if len(rows) >= 2 and re.fullmatch(r"[\s:|-]*-[\s:|-]*", rows[1].strip()) else []
    out = []
    if len(cases) < PROVIDER_CASES:
        out.append(f"Value safety: the Provider lifecycle matrix has {len(cases)} row(s); every documented "
                   f"category needs one, {PROVIDER_CASES} minimum")
    if any(not LINK.search(r) for r in cases):
        out.append("Value safety: a Provider lifecycle row has no provider doc link")
    header = [c.strip().lower() for c in rows[0].strip().strip("|").split("|")] if rows else []
    col = next((i for i, c in enumerate(header) if "verdict" in c), None)

    def verdict(row):
        cells = row.strip().strip("|").split("|")
        return LIFECYCLE_VERDICT.search(cells[col] if col is not None and col < len(cells) else row)
    verdicts = [verdict(r) for r in cases]
    if any(v is None for v in verdicts):
        out.append("Value safety: a Provider lifecycle row has no SAFE, GAP or N/A verdict")
    if any(v and v.group(1).startswith("GAP") for v in verdicts):
        out.append("Value safety: a Provider lifecycle row is an open GAP")
    return out


# references/git-pr-deploy.md § Deploy safety check 4: a native app's installed builds call the backend.
NATIVE_DIRS = ("ios", "android")
# A file no installed build runs or loads: tests, docs, CI config and the native apps themselves.
NOT_SERVED = re.compile(r"(^|/)(tests?|e2e|__tests__|docs|dev-docs|\.github)/|[._-](test|spec)\.[a-z]+$|"
                        r"_test\.[a-z]+$|\.md$")
VERSION_TABLE = re.compile(r"^\s*\|[^\n]*\bversion\b[^\n]*\|[^\n]*\b(share|installs)\b", re.I | re.M)
OLD_BUILD = re.compile(r"Old build \S+(?: \(\d+\))? against the new backend: (PASS|BLOCKED)\b(.*)", re.I)
NOT_REACHED = re.compile(r"Installed builds: not reached,\s*\S+(?:\s+\S+){2,}", re.I)
WAITS = re.compile(r"Waits for the new build:\s*\S", re.I)
APP_BUILD = re.compile(r"(?:No app build needed|Needs an app build)\W{0,3}:\**[ \t]*\S+(?:[ \t]+\S+){2,}", re.I)
# references/git-pr-deploy.md § A merge word runs the Deploy TLDR: a step never waits on a second yes.
SECOND_APPROVAL = re.compile(r"\bonly (?:on|after|with|once) [^\n.,;]{0,25}?\b(?:word|yes|go-?ahead|say-?so)\b|"
                             r"\bnot part of (?:this|the) (?:merge|deploy)\b|"
                             r"\b(?:separate|second) (?:approval|yes|go-?ahead|confirmation)\b", re.I)
SECOND_APPROVAL_MSG = ("Deploy TLDR: a step waits on a second approval ('{}'); Simon's merge word runs every "
                       "step, so write it as a numbered step or state its trigger condition "
                       "(references/git-pr-deploy.md § A merge word runs the Deploy TLDR)")
APP_BUILD_MSG = ("Deploy TLDR: no app build line for the native app ('No app build needed: <why>' or "
                 "'Needs an app build: <which parts wait for it>'; references/git-pr-deploy.md § Deploy "
                 "safety check 4)")


def ships_native_app(root_dirs):
    """Whether the repo ships a native app, so every PR states whether it needs an app build."""
    return any(d in root_dirs for d in NATIVE_DIRS)


def reaches_installed_builds(changed, root_dirs, ignore=()):
    """Whether a PR changes a file the installed native builds call or load.

    ignore: the project's installedBuilds.pathsIgnore globs, files no installed build calls or loads.
    """
    natives = [d for d in NATIVE_DIRS if d in root_dirs]
    if not natives:
        return False
    return any(not f.startswith(tuple(d + "/" for d in natives)) and not NOT_SERVED.search(f)
               and not (ignore and monitoring_only().matches_any(f, ignore))
               for f in changed)


def monitoring_only():
    """bin/monitoring_only.py, the owner of the strict project-entry read and its path globs."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import monitoring_only as mo
    return mo


def installed_ignore(repo):
    """(globs, warning): the project's installedBuilds.pathsIgnore. Any read or shape error ignores nothing."""
    try:
        mo = monitoring_only()
        manifest, error = mo.project_manifest(repo)
    except Exception as exc:  # an unreadable overlay never loosens the gate
        return (), f"installedBuilds.pathsIgnore not read ({exc}); every runtime file counts"
    if error:
        return (), f"installedBuilds.pathsIgnore not read ({error}); every runtime file counts"
    raw = (manifest or {}).get("installedBuilds")
    if raw is None:
        return (), ""
    globs = raw.get("pathsIgnore") if isinstance(raw, dict) else None
    error = mo.validate_globs(globs, "installedBuilds.pathsIgnore")
    if error:
        return (), f"{error}; every runtime file counts"
    return tuple(globs), ""


def check_installed_builds(safety, light=False):
    """Missing-row strings for the installed-build lines in Deploy safety (check 4).

    light: the PR is Light tier, so a reasoned not-reached line alone passes.
    """
    text = safety or ""
    if light and NOT_REACHED.search(text) and not OLD_BUILD.findall(text):
        return []
    missing = []
    if not VERSION_TABLE.search(text):
        missing.append("Deploy safety: no installed-version table (| version | share |) for the native app")
    lines = OLD_BUILD.findall(text)
    if not lines and not NOT_REACHED.search(text):
        missing.append("Deploy safety: no 'Old build <version> against the new backend: PASS' line and no "
                       "'Installed builds: not reached, <why>' line")
    for verdict, rest in lines:
        if verdict.upper() == "BLOCKED":
            missing.append("Deploy safety: an installed build was not walked (BLOCKED" + rest.rstrip()[:120]
                           + "); record the gate BLOCKED, never PASS")
    if not WAITS.search(text):
        missing.append("Deploy safety: no 'Waits for the new build:' line (the behaviours gated on the new "
                       "build, or none)")
    return missing


def walk_trigger(changed):
    """'native' or 'payment' when a deep PR's changed files require a real-client walk; None otherwise."""
    served = [f for f in changed if not NOT_SERVED.search(f) and not NATIVE_TEST.search(f)]
    if any(NATIVE_CODE.search(f) for f in served):
        return "native"
    if any(PAYMENT_PATH.search(f) for f in served):
        return "payment"
    return None


def check_walk_required(walk, trigger):
    """Missing-row strings when a deep native or payment PR's walk line names no real-client walk."""
    env = NATIVE_ENV if trigger == "native" else WALK_ENV
    client = "simulator or device" if trigger == "native" else "simulator, device, browser or local-stack"
    where = f"the {client} walks"
    scope = "native app code" if trigger == "native" else "a payment or entitlement path"
    if any(reasoned_na(w) and NO_JOURNEY.search(w) for w in walk):
        return []
    passed = [w for w in walk if re.search(r"\bPASS\b", w)]
    if not passed:
        return [f"Test matrix: this deep PR touches {scope}, so the Real-environment walk names {where} "
                "that ran, each with PASS or FAIL, or a does-not-apply naming why no user journey changed; "
                "a step the local stack cannot reach is a 'not run:' row, never the line's N/A "
                "(references/testing-strategy.md § Pre-merge end-to-end on a local stack)"]
    if not any(env.search(w) for w in passed):
        return [f"Test matrix: the Real-environment walk names no {client} walk for a deep PR touching {scope}"]
    if any(UNIT_TESTS.search(w) and not WALKED.search(w) for w in passed):
        return ["Test matrix: the Real-environment walk rests on unit tests; unit tests are not a walk "
                "(keep them in the results table and name the journeys walked)"]
    return []


def table_blocks(text):
    """Each Markdown table in text as a list of its pipe lines, header first."""
    blocks, cur = [], []
    for ln in text.splitlines() + [""]:
        if re.match(r"^\s*\|.*\|\s*$", ln):
            cur.append(ln)
        elif cur:
            blocks.append(cur)
            cur = []
    return blocks


def check_fails_without(matrix):
    """Missing-row strings when a Standard or Deep matrix's COVERED rows do not show their test failing."""
    cells = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]
    out = []
    for block in table_blocks(matrix):
        body = [r for r in block[2:] if COVERED_ROW.search(r)]
        if not body:
            continue
        header = cells(block[0])
        column = next((i for i, c in enumerate(header) if FAILS_COLUMN.search(c)), None)
        if column is None:
            out.append("Test matrix: the results table has no 'Fails without the change' column "
                       "(references/testing-strategy.md § Prove each test fails without the change)")
            continue
        empty = [r for r in body if len(cells(r)) <= column or cells(r)[column] in ("", "-", "–", "—")]
        if empty:
            out.append(f"Test matrix: {len(empty)} COVERED row(s) with an empty 'Fails without the change' cell; "
                       "write 'base fails', 'mutant <break>: FAILED' or 'n/a: <why>'")
        if any(len(cells(r)) > column and SURVIVED.search(cells(r)[column]) for r in body):
            out.append("Test matrix: a mutant survived (its test passed with the code broken); strengthen the "
                       "test until the mutant fails and mark the row GAP until then")
    return out


def is_light(matrix, changed=()):
    """Whether the Test matrix's first named tier is light, it names no deep tier, and no changed file is
    native app code or a payment or entitlement path (those hold a Deep trigger, so a Light label on them
    keeps every row)."""
    if matrix is None or DEEP_TIER.search(matrix):
        return False
    named = TIER_NAMED.search(matrix)
    return bool(named and LIGHT_TIER.fullmatch(named.group(0))) and not walk_trigger(changed or ())


def is_hotfix(matrix):
    """Whether the Test matrix's first named tier is hotfix and it names no deep tier."""
    if matrix is None or DEEP_TIER.search(matrix):
        return False
    named = TIER_NAMED.search(matrix)
    return bool(named and HOTFIX_TIER.fullmatch(named.group(0)))


def labelled(text, label):
    """Whether text holds a `label:` line with three or more words after the colon."""
    return re.search(r"(?:^|\n)[\s*_>-]*" + re.escape(label) + r"\W{0,3}:\**\s*\S+(?:[ \t]+\S+){2,}",
                     text or "", re.I) is not None


def check_hotfix(found, changed):
    """Missing-row strings for a Hotfix PR (references/testing-strategy.md § Hotfix tier)."""
    out = []
    served = [f for f in changed if not NOT_SERVED.search(f) and not NATIVE_TEST.search(f)]
    if len(served) > HOTFIX_MAX_FILES:
        out.append(f"Test matrix: the hotfix tier fits {HOTFIX_MAX_FILES} product file and this PR changes "
                   f"{len(served)} ({', '.join(served[:5])}); size it light, standard or deep")
    moved = [f for f in changed if MIGRATION_PATH.search(f)]
    if moved:
        out.append("Test matrix: the hotfix tier holds no migration, schema or SQL file; this PR changes "
                   + ", ".join(moved[:5]) + "; size it at its Deep trigger")
    matrix, regression, deploy = found.get("Test matrix"), found.get("Regression check"), found.get("Deploy TLDR")
    absent = [label for label in HOTFIX_MATRIX_LINES if not labelled(matrix, label)]
    if absent:
        out.append("Test matrix: a hotfix PR has no " + ", ".join(f"'{a}:'" for a in absent) + " line")
    mainstream = re.search(r"mainstream practice\W{0,3}:([^\n]*)", matrix or "", re.I)
    if mainstream and not LINK.search(mainstream.group(1)) and not re.search(r"\bdeparts?\b", mainstream.group(1), re.I):
        out.append("Test matrix: the hotfix 'Mainstream practice:' line has no primary-source link and no "
                   "'departs: <why>'")
    if regression is not None:
        absent = [label for label in HOTFIX_REGRESSION_LINES if not labelled(regression, label)]
        if absent:
            out.append("Regression check: a hotfix PR has no " + ", ".join(f"'{a}:'" for a in absent)
                       + " line (each path with its test on base and head, or 'none: <why>')")
    if deploy is not None:
        absent = [label for label in HOTFIX_DEPLOY_LINES if not re.search(re.escape(label) + r"\W{0,3}:", deploy, re.I)]
        if absent:
            out.append("Deploy TLDR: a hotfix PR's steps carry no " + ", ".join(f"'{a}:'" for a in absent) + " line")
    return out


def check_matrix_head(order, head):
    """Missing-row strings when the Test matrix heading does not name the PR's current head sha."""
    title = next((text for _, text, _ in order if matches(text, SECTIONS["Test matrix"])), "")
    named = HEAD_NAMED.search(title)
    if not named:
        return [f"Test matrix: the heading names no head sha; write '## Test matrix (head {head[:9]})'"]
    if not head.lower().startswith(named.group(1).lower()):
        return [f"Test matrix: the heading names head {named.group(1)} but the PR head is {head[:9]}; "
                "rewrite the body from the current diff and re-shoot (/sk:ship-pr § Rewrite the body "
                "when the PR changes)"]
    return []


def check_body(body, body_html, unresolved, modified=(), installed=False, head=None, native=False, changed=()):
    """Return one 'row: what is missing' string per failing landing-gate row.

    native: the repo ships a native app, so the Deploy TLDR carries the app build line (on a Light PR,
    only when installed is true).

    changed: every file the PR changes; on a deep PR, native app code or a payment or entitlement path
    in it makes the Real-environment walk name a real-client walk (walk_trigger).

    head: the PR's current head sha. When given, the Test matrix heading must name it
    ("## Test matrix (head <sha>)"), so a body written for an earlier head fails.
    """
    missing = []
    found, order = sections(body)
    heads = [text for _, text, _ in order]
    matrix = found.get("Test matrix")
    light = is_light(matrix, changed)
    hotfix = is_hotfix(matrix)
    trigger = walk_trigger(changed or ())

    tldr = found.get("TLDR")
    tldr_first = bool(heads) and matches(heads[0], SECTIONS["TLDR"])
    if not tldr_first:
        missing.append(f"TLDR: the body's first heading is not a TLDR heading (needs: {NEEDS['TLDR']})")
    else:
        if not TLDR_HEADER.search(tldr) or not has_table(tldr):
            missing.append("TLDR: no | Change | Before | After | Why | table (Why is the last column)")
        if not re.search(r"^\s*\*\*Do:\*\*", tldr, re.M):
            missing.append("TLDR: no **Do:** line")
    if "Deploy TLDR" not in found:
        missing.append(no_heading("Deploy TLDR"))
    elif tldr_first and not matches(next((t for lv, t, _ in order[1:] if lv <= order[0][0]), ""),
                                    SECTIONS["Deploy TLDR"]):
        missing.append("Deploy TLDR: it is not the next heading after the TLDR")
    if native and (installed or not light) and "Deploy TLDR" in found and not APP_BUILD.search(found["Deploy TLDR"]):
        missing.append(APP_BUILD_MSG)
    second = SECOND_APPROVAL.search(found.get("Deploy TLDR") or "")
    if second:
        missing.append(SECOND_APPROVAL_MSG.format(second.group(0)))
    for row in ("User journey", "System journey"):
        if row not in found:
            missing.append(no_heading(row))

    if matrix is None:
        missing.append(no_heading("Test matrix") + "; a summary row elsewhere does not count")
    else:
        if not TIER_NAMED.search(matrix):
            missing.append("Test matrix: no tier named (hotfix, light, standard or deep, with its trigger)")
        if not TIER_SKIP.search(matrix):
            absent = [label for label in MATRIX_COUNTS if not count_of(matrix, label)]
            if absent:
                missing.append("Test matrix: no count for " + ", ".join(absent))
            if not has_table(matrix):
                missing.append("Test matrix: no results table")
        walk = WALK.findall(matrix)
        if not walk:
            if not light and not (hotfix and not trigger):
                missing.append("Test matrix: no Real-environment walk line")
        elif any(re.search(r"\bFAIL", w) for w in walk):
            missing.append("Test matrix: the Real-environment walk records a FAIL")
        elif not any(re.search(r"\bPASS\b", w) or reasoned_na(w) or TIER_SKIP.search(w) for w in walk):
            missing.append("Test matrix: the Real-environment walk has no PASS, doesn't-apply reason or skip line")
        elif (DEEP_TIER.search(matrix) or hotfix) and trigger:
            missing += check_walk_required(walk, trigger)
        if hotfix or (not TIER_SKIP.search(matrix) and not light):
            missing += check_fails_without(matrix)
    if hotfix:
        missing += check_hotfix(found, list(changed or ()))

    if matrix is not None and head:
        missing += check_matrix_head(order, head)

    missing += check_regression(found.get("Regression check"), list(modified or ()), light)

    prod = found.get("Prod data")
    if prod is None:
        if not light and not hotfix:
            missing.append(no_heading("Prod data"))
    elif not TIER_SKIP.search(prod):
        if not re.search(r"\b(PASS|FAIL)\b", prod) and not DOES_NOT_APPLY.search(prod):
            missing.append("Prod data: no verdict (PASS, FAIL or does not apply)")
        if not has_table(prod) and not reasoned_na(prod):
            missing.append("Prod data: no cohort table and no doesn't-apply reason")

    value_path = any(PAYMENT_PATH.search(f) or AUTH_PATH.search(f) for f in changed or ()
                     if not NOT_SERVED.search(f) and not NATIVE_TEST.search(f))
    missing += check_value_safety(found.get("Value safety"), matrix is not None and (
        DEEP_TIER.search(matrix) is not None or (hotfix and value_path)))

    safety = found.get("Deploy safety")
    if safety is None:
        if not light and not hotfix:
            missing.append(no_heading("Deploy safety"))
    else:
        # Light and Hotfix skip the merge train: their Deploy safety section holds the installed-build lines.
        na = light or hotfix or reasoned_na(safety) or TIER_SKIP.search(safety) is not None
        if not re.search(r"merge[- ]train", safety, re.I) and not na:
            missing.append("Deploy safety: no merge-train result and no doesn't-apply reason")
        if not re.search(r"roll ?back", safety, re.I) and not na:
            missing.append("Deploy safety: no rollback and no doesn't-apply reason")
    if installed:
        missing += check_installed_builds(safety, light or (hotfix and trigger != "native"))

    shots = found.get("Screenshots")
    if shots is None:
        missing.append(no_heading("Screenshots"))
    elif not re.search(r"<img\s|<video\s|!\[[^\]]*\]\(|user-attachments/assets/", shots, re.I):
        if not NO_SURFACE.search(shots) and not reasoned_na(shots):
            missing.append("Screenshots: no image and no stated no-visible-surface reason")
        elif not CHECKED_OUTPUTS.search(shots):
            missing.append(NO_OUTPUTS.format("Screenshots"))
        if route_reason(shots):
            missing.append(ROUTE_MSG.format("Screenshots"))
    elif light and 0 < posted_images(shots) < LIGHT_PAIR:
        missing.append(f"Screenshots: a Light PR posts its BEFORE/AFTER pair ({LIGHT_PAIR} images); "
                       f"this section posts {posted_images(shots)}")

    runs = found.get("Verification runs")
    if runs is None:
        if shots is not None and VIDEO.search(shots):
            missing.append("Verification runs: ## Screenshots posts a video but there is no Verification runs heading")
    elif TIER_SKIP.search(runs):
        pass
    elif not VIDEO.search(runs) and (NO_SURFACE.search(runs) or reasoned_na(runs)):
        if not CHECKED_OUTPUTS.search(runs):
            missing.append(NO_OUTPUTS.format("Verification runs"))
        if route_reason(runs):
            missing.append(ROUTE_MSG.format("Verification runs"))
    else:
        if not has_table(runs):
            missing.append("Verification runs: no scenario table")
        if not VIDEO.search(runs):
            missing.append("Verification runs: no posted video")
        absent = [label for label in RUN_LABELS if label.lower() not in runs.replace("*", "").lower()]
        if absent:
            missing.append("Verification runs: no " + ", ".join(absent) + " line")

    if not light and not hotfix:
        missing += check_part_verdicts(found.get("Part verdicts"))

    collapsed = len(COLLAPSED.findall(body_html or ""))
    if collapsed:
        missing.append(f"Visible sections: {collapsed} collapsed <details> in body_html (add open)")
    missing += check_images(body, body_html)
    if unresolved:
        missing.append(f"Review threads: {unresolved} unresolved")
    return missing


def prose_mask(body):
    """body with every fenced code block, inline code span and HTML comment blanked to spaces, the same
    length, so offsets of a match in it point into body."""
    out, fence = [], None
    for line in body.splitlines(keepends=True):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            out.append(re.sub(r"[^\n]", " ", line))
            continue
        out.append(re.sub(r"[^\n]", " ", line) if fence else line)
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"<!--.*?-->", blank, "".join(out), flags=re.S)
    return re.sub(r"(`+)(?!`).+?(?<!`)\1(?!`)", blank, text)


def posted_images(body):
    """How many images the body posts: Markdown images with alt text plus <img> tags, outside code."""
    mask = prose_mask(body)
    return sum(1 for m in MD_IMAGE.finditer(mask) if m.group(1).strip()) + len(IMG_TAG.findall(mask))


def check_images(body, body_html):
    """A FAIL row when body_html renders fewer <img> than the body posts: one did not render."""
    posted, rendered = posted_images(body), len(IMG_TAG.findall(body_html or ""))
    if rendered >= posted:
        return []
    as_text = len(re.findall(r"&lt;img\b", body_html or "", re.I))
    return [f"Images: the body posts {posted} images but body_html renders {rendered}"
            + (f"; {as_text} <img> tags show as text" if as_text else "")
            + ". A raw double quote in an alt ends the attribute: escape it (python3 ~/.claude/bin/pr-evidence.py "
            "size-images BODY.md) and save the body again"]


def gh_out(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def gh(*args):
    return json.loads(gh_out(*args))


def gh_lines(*args):
    return [ln.strip() for ln in gh_out(*args).splitlines() if ln.strip()]


def fetch(repo, pr):
    owner, name = repo.split("/", 1)
    data = gh("api", f"repos/{repo}/pulls/{pr}", "-H", "Accept: application/vnd.github.full+json")
    unresolved, after = 0, None
    while True:
        args = ["api", "graphql", "-f", "query=" + THREADS_QUERY, "-F", f"owner={owner}",
                "-F", f"name={name}", "-F", f"pr={pr}"]
        if after:
            args += ["-F", f"after={after}"]
        threads = gh(*args)["data"]["repository"]["pullRequest"]["reviewThreads"]
        unresolved += sum(1 for t in threads["nodes"] if not t["isResolved"])
        if not threads["pageInfo"]["hasNextPage"]:
            break
        after = threads["pageInfo"]["endCursor"]
    statuses = "|".join(PRE_EXISTING)
    files = gh_lines("api", f"repos/{repo}/pulls/{pr}/files", "--paginate",
                     "--jq", f'.[] | select(.status | test("^({statuses})$")) | .filename')
    changed = gh_lines("api", f"repos/{repo}/pulls/{pr}/files", "--paginate", "--jq", ".[].filename")
    roots = gh_lines("api", f"repos/{repo}/contents", "--jq", '.[] | select(.type == "dir") | .name')
    ignore, warning = installed_ignore(repo) if ships_native_app(roots) else ((), "")
    if warning:
        print(f"pr-landing-gate: note {repo}#{pr}: {warning}", file=sys.stderr)
    installed = reaches_installed_builds(changed, roots, ignore)
    head = (data.get("head") or {}).get("sha") or ""
    return (data.get("body") or "", data.get("body_html") or "", unresolved, files, installed, head,
            ships_native_app(roots), changed)


def feedback_count(repo, pr):
    """Every review and review comment on the PR, plus every comment a person (not a bot) posted on it.

    A bot comment (a ticket link, a CI runner note) is no review feedback; a bot review is."""
    reviews = gh_lines("api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate", "--jq", ".[] | .id")
    inline = gh_lines("api", f"repos/{repo}/pulls/{pr}/comments", "--paginate", "--jq", ".[] | .id")
    people = gh_lines("api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq",
                      '.[] | select(.user.type != "Bot") | .id')
    return len(reviews) + len(inline) + len(people)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--feedback-count", action="store_true",
                    help="print the PR's reviews, review comments and non-bot comments, then exit")
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print(f"pr-landing-gate: usage: --repo must be owner/name, got {args.repo}", file=sys.stderr)
        return 2
    if args.feedback_count:
        try:
            print(feedback_count(args.repo, args.pr))
        except RuntimeError as err:
            print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: {err}", file=sys.stderr)
            return 2
        return 0
    try:
        body, body_html, unresolved, modified, installed, head, native, changed = fetch(args.repo, args.pr)
    except (RuntimeError, KeyError, TypeError, ValueError) as err:
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: {err}", file=sys.stderr)
        return 2
    if len(body.strip()) < 200 or not body_html.strip():
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: body empty or under 200 chars",
              file=sys.stderr)
        return 2
    missing = check_body(body, body_html, unresolved, modified, installed, head, native, changed)
    for row in missing:
        print(f"pr-landing-gate: FAIL {args.repo}#{args.pr} {row}")
    if missing:
        return 1
    print(f"pr-landing-gate: PASS {args.repo}#{args.pr}: all {len(SECTIONS) + 3} landing-gate rows present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
