#!/usr/bin/env python3
"""Check a fetched PR against the ship harness landing gate; exit non-zero naming each missing row.

  pr-landing-gate.py --repo <owner/name> --pr <n>

Fetches the PR body markdown and body_html (`gh api ... full+json`) and every review thread (gh
GraphQL), then checks the rows /sk:ship-full-detailed-workflow § Landing gate lists. SECTIONS below
is the ONE home of the PR body's section headings: /sk:ship-pr, references/tldr-report-formats.md
and the harness name this file instead of restating them. A heading matches with any emoji or
punctuation prefix and any case ("## 🚀 Deploy TLDR"), and may carry a suffix after a non-letter
("## Test matrix (head abc1234)"). The Test matrix section also holds a Real-environment walk line.
The Regression check section holds one row per pre-existing file the PR modifies, renames or removes
(the PR's file list, `gh api .../pulls/<n>/files`), each with PASS or INTENDED and a filled cell in the
table's Base-vs-head evidence column: the method is references/testing-strategy.md § Regression check.
A PR whose Test matrix names the deep tier holds a Value safety section: its five labelled lines, or a
reasoned does-not-apply (references/testing-strategy.md § Value safety).
A Screenshots or Verification runs section that posts no evidence and states no visible surface (or a
does-not-apply) carries a "Checked outputs:" clause naming what was compared on base and head
(references/screenshot-review.md § Visible surfaces); a bare "No eligible frontend surface" fails.

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
}
MATRIX_COUNTS = ("COVERED", "GAP", "NEEDS-DRIVING", "SKIPPED")
# What each section must hold, printed with a missing heading so one gate run names every requirement
# instead of revealing them one rewrite at a time. Keep in step with the checks in check_body.
NEEDS = {
    "TLDR": "first heading; a | | Before | After | table; a **Do:** line",
    "Deploy TLDR": "the next heading after the TLDR; numbered deploy steps",
    "User journey": "what the user goes through",
    "System journey": "what the system does, in steps",
    "Test matrix": ("a tier named (light, standard or deep) with its trigger; counts for "
                    + ", ".join(MATRIX_COUNTS) + "; a results table; a 'Real-environment walk:' line "
                    "with PASS, a reasoned does-not-apply or a skip line"),
    "Regression check": ("a table with a Base-vs-head evidence column; a row per modified pre-existing file, "
                         "each with evidence and PASS or INTENDED"),
    "Prod data": "a PASS or FAIL verdict and a cohort table, or a reasoned does-not-apply",
    "Value safety": ("on a deep-tier PR, the lines Happy path:, Failure re-enacted:, Wrong recipient:, "
                     "Incident replay: (with N/N) and Residual risk:, or a reasoned does-not-apply"),
    "Deploy safety": "a merge-train result and a rollback, or a reasoned does-not-apply",
    "Screenshots": "an image, or a no-visible-surface reason with a 'Checked outputs:' clause",
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
# references/testing-strategy.md § Size the checks to the change: a Light or Standard PR keeps each
# skipped heading with this line, and its trigger is at least three words.
TIER_SKIP = re.compile(r"Skipped \((?:tier )?(?:light|standard)\)\s*:\s*\S+(?:\s+\S+){2,}", re.I)
DEEP_TIER = re.compile(r"\btier\b\W{0,3}deep\b|\bdeep\W{0,3}tier\b", re.I)
# references/testing-strategy.md § Value safety: the labelled lines, in order.
VALUE_LABELS = ("Happy path", "Failure re-enacted", "Wrong recipient", "Incident replay", "Residual risk")
TIER_NAMED = re.compile(r"\btier\b\W{0,3}(?:light|standard|deep)\b|\b(?:light|standard|deep)\W{0,3}tier\b", re.I)
# /sk:test-automated-full-matrix's real-environment walk: one line in the Test matrix section.
WALK = re.compile(r"^.*real[- ]environment walk.*$", re.I | re.M)
# A posted video: an inline <video> or a bare GitHub attachment URL alone on its line (images are <img> or ![]()).
VIDEO = re.compile(r"<video\s|^\s*https://github\.com/user-attachments/assets/\S+\s*$", re.I | re.M)
# references/screenshot-review.md § Verification run videos: the labels each run block and the section carry.
RUN_LABELS = ("Findings:", "Fixed during review:", "Not covered:", "Sources:")
# references/testing-strategy.md § Regression check: a row's result, and the file statuses that need a row.
REGRESSION_OK = re.compile(r"\b(?:PASS|INTENDED)\b")
# The column holding each row's proof: a base-vs-head test or screenshot comparison, never empty.
EVIDENCE_COLUMN = re.compile(r"base[- ]vs[- ]head", re.I)
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
    return out


def check_body(body, body_html, unresolved, modified=()):
    """Return one 'row: what is missing' string per failing landing-gate row."""
    missing = []
    found, order = sections(body)
    heads = [text for _, text, _ in order]

    tldr = found.get("TLDR")
    tldr_first = bool(heads) and matches(heads[0], SECTIONS["TLDR"])
    if not tldr_first:
        missing.append(f"TLDR: the body's first heading is not a TLDR heading (needs: {NEEDS['TLDR']})")
    else:
        if not re.search(r"^\s*\|[^\n]*\bBefore\b[^\n]*\|[^\n]*\bAfter\b[^\n]*\|", tldr, re.M | re.I) \
                or not has_table(tldr):
            missing.append("TLDR: no | | Before | After | table")
        if not re.search(r"^\s*\*\*Do:\*\*", tldr, re.M):
            missing.append("TLDR: no **Do:** line")
    if "Deploy TLDR" not in found:
        missing.append(no_heading("Deploy TLDR"))
    elif tldr_first and not matches(next((t for lv, t, _ in order[1:] if lv <= order[0][0]), ""),
                                    SECTIONS["Deploy TLDR"]):
        missing.append("Deploy TLDR: it is not the next heading after the TLDR")
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

    shots = found.get("Screenshots")
    if shots is None:
        missing.append(no_heading("Screenshots"))
    elif not re.search(r"<img\s|<video\s|!\[[^\]]*\]\(|user-attachments/assets/", shots, re.I):
        if not NO_SURFACE.search(shots) and not reasoned_na(shots):
            missing.append("Screenshots: no image and no stated no-visible-surface reason")
        elif not CHECKED_OUTPUTS.search(shots):
            missing.append(NO_OUTPUTS.format("Screenshots"))

    runs = found.get("Verification runs")
    if runs is None:
        if shots is not None and VIDEO.search(shots):
            missing.append("Verification runs: ## Screenshots posts a video but there is no Verification runs heading")
    elif TIER_SKIP.search(runs):
        pass
    elif not VIDEO.search(runs) and (NO_SURFACE.search(runs) or reasoned_na(runs)):
        if not CHECKED_OUTPUTS.search(runs):
            missing.append(NO_OUTPUTS.format("Verification runs"))
    else:
        if not has_table(runs):
            missing.append("Verification runs: no scenario table")
        if not VIDEO.search(runs):
            missing.append("Verification runs: no posted video")
        absent = [label for label in RUN_LABELS if label.lower() not in runs.replace("*", "").lower()]
        if absent:
            missing.append("Verification runs: no " + ", ".join(absent) + " line")

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
    return data.get("body") or "", data.get("body_html") or "", unresolved, files


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print(f"pr-landing-gate: usage: --repo must be owner/name, got {args.repo}", file=sys.stderr)
        return 2
    try:
        body, body_html, unresolved, modified = fetch(args.repo, args.pr)
    except (RuntimeError, KeyError, TypeError, ValueError) as err:
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: {err}", file=sys.stderr)
        return 2
    if len(body.strip()) < 200 or not body_html.strip():
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: body empty or under 200 chars",
              file=sys.stderr)
        return 2
    missing = check_body(body, body_html, unresolved, modified)
    for row in missing:
        print(f"pr-landing-gate: FAIL {args.repo}#{args.pr} {row}")
    if missing:
        return 1
    print(f"pr-landing-gate: PASS {args.repo}#{args.pr}: all {len(SECTIONS) + 2} landing-gate rows present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
