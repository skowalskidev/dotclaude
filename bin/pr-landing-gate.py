#!/usr/bin/env python3
"""Check a fetched PR against the ship harness landing gate; exit non-zero naming each missing row.

  pr-landing-gate.py --repo <owner/name> --pr <n>

Fetches the PR body markdown and body_html (`gh api ... full+json`) and every review thread (gh
GraphQL), then checks the rows /sk:ship-full-detailed-workflow § Landing gate lists. SECTIONS below
is the ONE home of the PR body's section headings: /sk:ship-pr, references/tldr-report-formats.md
and the harness name this file instead of restating them. A heading matches with any emoji or
punctuation prefix and any case ("## 🚀 Deploy TLDR"), and may carry a suffix after a non-letter
("## Test matrix (head abc1234)"). The Test matrix section also holds a Real-environment walk line.

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
    "Prod data": "Prod data",
    "Deploy safety": "Deploy safety",
    "Screenshots": "Screenshots",
}
MATRIX_COUNTS = ("COVERED", "GAP", "NEEDS-DRIVING", "SKIPPED")
DOES_NOT_APPLY = re.compile(r"does(?: not|n['’]t) apply|\bN/A\b", re.I)
NO_SURFACE = re.compile(r"no (?:eligible |changed |visible )?(?:frontend |UI |user-facing )?surface|"
                        r"no (?:frontend|UI|visible) change", re.I)
# references/testing-strategy.md § Size the checks to the change: a Light or Standard PR keeps each
# skipped heading with this line, and its trigger is at least three words.
TIER_SKIP = re.compile(r"Skipped \((?:tier )?(?:light|standard)\)\s*:\s*\S+(?:\s+\S+){2,}", re.I)
TIER_NAMED = re.compile(r"\btier\b\W{0,3}(?:light|standard|deep)\b|\b(?:light|standard|deep)\W{0,3}tier\b", re.I)
# /sk:test-automated-full-matrix's real-environment walk: one line in the Test matrix section.
WALK = re.compile(r"^.*real[- ]environment walk.*$", re.I | re.M)
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


def check_body(body, body_html, unresolved):
    """Return one 'row: what is missing' string per failing landing-gate row."""
    missing = []
    found, order = sections(body)
    heads = [text for _, text, _ in order]

    tldr = found.get("TLDR")
    tldr_first = bool(heads) and matches(heads[0], SECTIONS["TLDR"])
    if not tldr_first:
        missing.append("TLDR: the body's first heading is not a TLDR heading")
    elif not re.search(r"^\s*\|[^\n]*\bBefore\b[^\n]*\|[^\n]*\bAfter\b[^\n]*\|", tldr, re.M | re.I) \
            or not has_table(tldr):
        missing.append("TLDR: no | | Before | After | table")
    elif not re.search(r"^\s*\*\*Do:\*\*", tldr, re.M):
        missing.append("TLDR: no **Do:** line")
    if "Deploy TLDR" not in found:
        missing.append("Deploy TLDR: no Deploy TLDR heading")
    elif tldr_first and not matches(next((t for lv, t, _ in order[1:] if lv <= order[0][0]), ""),
                                    SECTIONS["Deploy TLDR"]):
        missing.append("Deploy TLDR: it is not the next heading after the TLDR")
    for row in ("User journey", "System journey"):
        if row not in found:
            missing.append(f"{row}: no {SECTIONS[row]} heading")

    matrix = found.get("Test matrix")
    if matrix is None:
        missing.append("Test matrix: no Test matrix heading (a summary row elsewhere does not count)")
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

    prod = found.get("Prod data")
    if prod is None:
        missing.append("Prod data: no Prod data heading")
    elif TIER_SKIP.search(prod):
        pass
    elif not re.search(r"\b(PASS|FAIL)\b", prod) and not DOES_NOT_APPLY.search(prod):
        missing.append("Prod data: no verdict (PASS, FAIL or does not apply)")
    elif not has_table(prod) and not reasoned_na(prod):
        missing.append("Prod data: no cohort table and no doesn't-apply reason")

    safety = found.get("Deploy safety")
    if safety is None:
        missing.append("Deploy safety: no Deploy safety heading")
    else:
        na = reasoned_na(safety) or TIER_SKIP.search(safety) is not None
        if not re.search(r"merge[- ]train", safety, re.I) and not na:
            missing.append("Deploy safety: no merge-train result and no doesn't-apply reason")
        if not re.search(r"roll ?back", safety, re.I) and not na:
            missing.append("Deploy safety: no rollback and no doesn't-apply reason")

    shots = found.get("Screenshots")
    if shots is None:
        missing.append("Screenshots: no Screenshots heading")
    elif not re.search(r"<img\s|<video\s|!\[[^\]]*\]\(|user-attachments/assets/", shots, re.I) \
            and not NO_SURFACE.search(shots) and not reasoned_na(shots):
        missing.append("Screenshots: no image and no stated no-eligible-surface reason")

    collapsed = len(COLLAPSED.findall(body_html or ""))
    if collapsed:
        missing.append(f"Visible sections: {collapsed} collapsed <details> in body_html (add open)")
    if unresolved:
        missing.append(f"Review threads: {unresolved} unresolved")
    return missing


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


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
    return data.get("body") or "", data.get("body_html") or "", unresolved


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print(f"pr-landing-gate: usage: --repo must be owner/name, got {args.repo}", file=sys.stderr)
        return 2
    try:
        body, body_html, unresolved = fetch(args.repo, args.pr)
    except (RuntimeError, KeyError, TypeError, ValueError) as err:
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: {err}", file=sys.stderr)
        return 2
    if len(body.strip()) < 200 or not body_html.strip():
        print(f"pr-landing-gate: FETCH FAILED {args.repo}#{args.pr}: body empty or under 200 chars",
              file=sys.stderr)
        return 2
    missing = check_body(body, body_html, unresolved)
    for row in missing:
        print(f"pr-landing-gate: FAIL {args.repo}#{args.pr} {row}")
    if missing:
        return 1
    print(f"pr-landing-gate: PASS {args.repo}#{args.pr}: all {len(SECTIONS) + 2} landing-gate rows present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
