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
recorded but fails the gate: an unwalked installed build is never a pass. On a Light PR (the Test matrix
names the light tier) the `Installed builds: not reached, <why>` line alone passes: no version table or
Waits line, because a Light change touches no native-build or backend contract.
In such a repo every PR's Deploy TLDR, a native-only or web-only PR included, holds an app build line:
`No app build needed: <why>` or `Needs an app build: <which parts wait for it>` (check 4).
A posted Part verdicts section holds a table whose header names Verdict, Mainstream practice, Regression
evidence and a judge column per provider, with a primary-source link in every row
(references/tldr-report-formats.md § Part verdicts). The section is checked when present, so a PR body
written before it existed still passes; the work harness's TEST requires it on Standard and Deep build,
adopt and rebuild PRs. A Light PR's Part verdicts section is never checked: its judges are not required
(references/research.md § Independent judges).

hooks/intent-ledger.sh `gate <branch> <sha> PASS` runs this for a branch with an open PR and refuses
to record PASS unless it exits 0. Exit 0: one PASS line. Exit 1: one FAIL line per missing row.
Exit 2: usage error, or a fetch failed (a fetch failure never passes).
"""

import argparse
import json
import re
import subprocess
import sys

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
    "Test matrix": ("a tier named (light, standard or deep) with its trigger; counts for "
                    + ", ".join(MATRIX_COUNTS) + "; a results table; a 'Real-environment walk:' line "
                    "with PASS, a reasoned does-not-apply or a skip line; on a deep PR touching native app "
                    "code or a payment or entitlement path, the simulator, device or local-stack walks with "
                    "PASS, or a does-not-apply naming why no user journey changed"),
    "Regression check": ("a table with a Base-vs-head evidence column; a row per modified pre-existing file, "
                         "each with evidence and PASS or INTENDED"),
    "Prod data": "a PASS or FAIL verdict and a cohort table, or a reasoned does-not-apply",
    "Value safety": ("on a deep-tier PR, the lines Happy path:, Failure re-enacted:, Wrong recipient:, "
                     "Incident replay: (with N/N), Provider lifecycle: and Residual risk:, or a reasoned "
                     "does-not-apply; a ### Provider lifecycle table (Case | Provider doc | Verdict | "
                     "Evidence) with a doc link and SAFE, GAP or N/A per row, no GAP, unless the Provider "
                     "lifecycle line is a reasoned does-not-apply"),
    "Deploy safety": ("a merge-train result and a rollback, or a reasoned does-not-apply; in a repo with a "
                      "native app, when the PR changes a file its installed builds call or load: a version "
                      "| share table, 'Old build <version> against the new backend: PASS' per version or "
                      "'Installed builds: not reached, <why>', and 'Waits for the new build: <list or none>'; "
                      "on a Light PR the not-reached line alone"),
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
TIER_SKIP = re.compile(r"Skipped \((?:tier )?(?:light|standard)\)\s*:\s*\S+(?:\s+\S+){2,}", re.I)
DEEP_TIER = re.compile(r"\btier\b\W{0,3}deep\b|\bdeep\W{0,3}tier\b", re.I)
LIGHT_TIER = re.compile(r"\btier\b\W{0,3}light\b|\blight\W{0,3}tier\b", re.I)
# references/testing-strategy.md § Value safety: the labelled lines, in order.
VALUE_LABELS = ("Happy path", "Failure re-enacted", "Wrong recipient", "Incident replay", "Provider lifecycle",
                "Residual risk")
# references/testing-strategy.md § Value safety question 5: one matrix row per documented lifecycle category.
PROVIDER_CASES = 11
LIFECYCLE_HEADING = re.compile(r"^#{3,6}\W*provider lifecycle\b", re.I | re.M)
LIFECYCLE_VERDICT = re.compile(r"\b(SAFE|GAPS?|N/A)\b")
TIER_NAMED = re.compile(r"\btier\b\W{0,3}(?:light|standard|deep)\b|\b(?:light|standard|deep)\W{0,3}tier\b", re.I)
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
PRE_EXISTING = ("modified", "renamed", "removed", "changed")
COLLAPSED = re.compile(r"<details(?![^>]*\bopen\b)[^>]*>", re.I)
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


def check_regression(text, modified):
    """Missing-row strings for the Regression check section; modified = pre-existing paths the PR changes."""
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
    if column is None:
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
APP_BUILD_MSG = ("Deploy TLDR: no app build line for the native app ('No app build needed: <why>' or "
                 "'Needs an app build: <which parts wait for it>'; references/git-pr-deploy.md § Deploy "
                 "safety check 4)")


def ships_native_app(root_dirs):
    """Whether the repo ships a native app, so every PR states whether it needs an app build."""
    return any(d in root_dirs for d in NATIVE_DIRS)


def reaches_installed_builds(changed, root_dirs):
    """Whether a PR changes a file the installed native builds call or load."""
    natives = [d for d in NATIVE_DIRS if d in root_dirs]
    if not natives:
        return False
    return any(not f.startswith(tuple(d + "/" for d in natives)) and not NOT_SERVED.search(f)
               for f in changed)


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

    native: the repo ships a native app, so the Deploy TLDR carries the app build line.

    changed: every file the PR changes; on a deep PR, native app code or a payment or entitlement path
    in it makes the Real-environment walk name a real-client walk (walk_trigger).

    head: the PR's current head sha. When given, the Test matrix heading must name it
    ("## Test matrix (head <sha>)"), so a body written for an earlier head fails.
    """
    missing = []
    found, order = sections(body)
    heads = [text for _, text, _ in order]

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
    if native and "Deploy TLDR" in found and not APP_BUILD.search(found["Deploy TLDR"]):
        missing.append(APP_BUILD_MSG)
    for row in ("User journey", "System journey"):
        if row not in found:
            missing.append(no_heading(row))

    matrix = found.get("Test matrix")
    if matrix is None:
        missing.append(no_heading("Test matrix") + "; a summary row elsewhere does not count")
    else:
        if not TIER_NAMED.search(matrix):
            missing.append("Test matrix: no tier named (light, standard or deep, with its trigger)")
        if not TIER_SKIP.search(matrix):
            absent = [label for label in MATRIX_COUNTS if not count_of(matrix, label)]
            if absent:
                missing.append("Test matrix: no count for " + ", ".join(absent))
            if not has_table(matrix):
                missing.append("Test matrix: no results table")
        walk = WALK.findall(matrix)
        if not walk:
            missing.append("Test matrix: no Real-environment walk line")
        elif any(re.search(r"\bFAIL", w) for w in walk):
            missing.append("Test matrix: the Real-environment walk records a FAIL")
        elif not any(re.search(r"\bPASS\b", w) or reasoned_na(w) or TIER_SKIP.search(w) for w in walk):
            missing.append("Test matrix: the Real-environment walk has no PASS, doesn't-apply reason or skip line")
        elif DEEP_TIER.search(matrix) and walk_trigger(changed or ()):
            missing += check_walk_required(walk, walk_trigger(changed or ()))

    if matrix is not None and head:
        missing += check_matrix_head(order, head)

    missing += check_regression(found.get("Regression check"), list(modified or ()))

    prod = found.get("Prod data")
    if prod is None:
        missing.append(no_heading("Prod data"))
    elif not TIER_SKIP.search(prod):
        if not re.search(r"\b(PASS|FAIL)\b", prod) and not DOES_NOT_APPLY.search(prod):
            missing.append("Prod data: no verdict (PASS, FAIL or does not apply)")
        if not has_table(prod) and not reasoned_na(prod):
            missing.append("Prod data: no cohort table and no doesn't-apply reason")

    missing += check_value_safety(found.get("Value safety"), matrix is not None and DEEP_TIER.search(matrix) is not None)

    safety = found.get("Deploy safety")
    if safety is None:
        missing.append(no_heading("Deploy safety"))
    else:
        na = reasoned_na(safety) or TIER_SKIP.search(safety) is not None
        if not re.search(r"merge[- ]train", safety, re.I) and not na:
            missing.append("Deploy safety: no merge-train result and no doesn't-apply reason")
        if not re.search(r"roll ?back", safety, re.I) and not na:
            missing.append("Deploy safety: no rollback and no doesn't-apply reason")
    light = matrix is not None and LIGHT_TIER.search(matrix) is not None and DEEP_TIER.search(matrix) is None
    if installed:
        missing += check_installed_builds(safety, light)

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

    if not light:
        missing += check_part_verdicts(found.get("Part verdicts"))

    collapsed = len(COLLAPSED.findall(body_html or ""))
    if collapsed:
        missing.append(f"Visible sections: {collapsed} collapsed <details> in body_html (add open)")
    if unresolved:
        missing.append(f"Review threads: {unresolved} unresolved")
    return missing


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
    installed = reaches_installed_builds(changed, roots)
    head = (data.get("head") or {}).get("sha") or ""
    return (data.get("body") or "", data.get("body_html") or "", unresolved, files, installed, head,
            ships_native_app(roots), changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print(f"pr-landing-gate: usage: --repo must be owner/name, got {args.repo}", file=sys.stderr)
        return 2
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
    print(f"pr-landing-gate: PASS {args.repo}#{args.pr}: all {len(SECTIONS) + 2} landing-gate rows present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
