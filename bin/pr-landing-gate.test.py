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

| | Before | After |
|---|---|---|
| Paid-plan searches | 50 a week | **200 a month** |
| Free plan | 5 a week | unchanged |

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

| # | Feature | Evidence | Verdict |
|---|---|---|---|
| 1 | 201st search refused | db test | COVERED |
| 2 | Rendered cards | e2e with a mocked server | NEEDS-DRIVING |

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
**Residual risk:** none found; checked shared phone numbers and family plans.

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
HTML = '<h2>TLDR</h2><details open=""><summary>video</summary></details>'


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
light = section(PASSING, "Test matrix", "## Test matrix\n\nTier: light (one table cell's CSS).\n\n" + skip
                + "Real-environment walk: " + skip)
light = section(light, "Prod data", "## Prod data\n\n" + skip)
light = section(light, "Deploy safety", "## Deploy safety\n\n" + skip)
check(gate.check_body(light, HTML, 0) == [], f"A light PR with skip lines failed: {gate.check_body(light, HTML, 0)}")
bare_skip = light.replace("Skipped (tier light): style-only change to one table cell", "Skipped (tier light): style")
check({"Test matrix", "Prod data", "Deploy safety"} <= rows(gate.check_body(bare_skip, HTML, 0)),
      "A skip line with no trigger passed")
untiered = PASSING.replace("Tier: deep (a member's search limit and its billing plan).\n\n", "")
check(any("no tier named" in m for m in gate.check_body(untiered, HTML, 0)), "A matrix with no tier named passed")

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

# A missing TLDR fails on the TLDR row; a TLDR with no Do line or no Before/After table fails too.
no_tldr = PASSING[PASSING.index("## 🚀 Deploy TLDR"):]
check("TLDR" in rows(gate.check_body(no_tldr, HTML, 0)), "A body with no TLDR passed the TLDR row")
check(any("Do:" in m for m in gate.check_body(PASSING.replace("**Do:** merge", "Merge"), HTML, 0)),
      "A TLDR with no **Do:** line passed")
check(any("Before" in m for m in gate.check_body(PASSING.replace("| | Before | After |", "| | Old | New |"), HTML, 0)),
      "A TLDR with no Before/After table passed")

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
both = PASSING.replace("**Do:** merge", "Merge").replace("| | Before | After |", "| | Old | New |")
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

# Value safety: required on a deep-tier PR; five labelled lines with evidence, or a reasoned doesn't-apply.
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

# Unresolved review threads fail.
check(rows(gate.check_body(PASSING, HTML, 2)) == {"Review threads"}, "Unresolved review threads passed")


# CLI and hook, against a stub gh serving fixture JSON from $GH_STUB.
STUB = """#!/bin/sh
case "$1 $2" in
  "pr list") f=prlist.json ;;
  "api graphql") f=threads.json ;;
  "api "*/files) f=files.txt ;;
  api*) f=pull.json ;;
  *) exit 1 ;;
esac
[ -f "$GH_STUB/$f" ] || { echo "stub: no $f" >&2; exit 1; }
cat "$GH_STUB/$f"
"""


def serve(stub, body, html=HTML, unresolved=0, prs=(7,), files=("src/auth/Gate.tsx",)):
    for name in ("prlist.json", "pull.json", "threads.json", "files.txt"):
        (stub / name).unlink(missing_ok=True)
    if prs is not None:
        (stub / "prlist.json").write_text(json.dumps([{"number": n, "url": f"https://example.test/{n}"} for n in prs]))
    if body is not None:
        (stub / "pull.json").write_text(json.dumps({"body": body, "body_html": html}))
    if files is not None:
        (stub / "files.txt").write_text("".join(f + "\n" for f in files))
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

    def gate_lines():
        return [ln for ln in ledger.read_text().splitlines() if ln.startswith("gate: ")] if ledger.exists() else []

    serve(stub, summary_only)
    r = hook_gate("feature/x", "HEAD", "PASS")
    check(r.returncode == 1 and "Test matrix" in r.stderr and "PASS refused" in r.stderr and gate_lines() == [],
          f"gate PASS recorded over a failing PR: {r.returncode} {r.stderr}")
    r = hook_gate("feature/x", "HEAD", "BLOCKED", "matrix not posted yet")
    check(r.returncode == 0 and len(gate_lines()) == 1, f"gate BLOCKED changed behaviour: {r.returncode} {r.stderr}")
    serve(stub, None, prs=None)
    r = hook_gate("feature/x", "HEAD", "PASS")
    check(r.returncode == 1 and "gh pr list failed" in r.stderr and len(gate_lines()) == 1,
          f"A failed PR lookup did not refuse PASS: {r.returncode} {r.stderr}")
    serve(stub, PASSING)
    r = hook_gate("feature/x", "HEAD", "PASS")
    check(r.returncode == 0 and "pr-landing-gate: PASS" in r.stdout and gate_lines()[-1].endswith(" PASS "),
          f"gate PASS over a passing PR did not record: {r.returncode} {r.stdout}{r.stderr}")
    serve(stub, None, prs=())
    r = hook_gate("feature/x", "HEAD", "PASS")
    check(r.returncode == 0 and len(gate_lines()) == 3, f"gate PASS with no open PR changed behaviour: {r.stderr}")
    git("remote", "set-url", "origin", "https://example.test/o/r.git")
    serve(stub, None, prs=None)
    r = hook_gate("feature/x", "HEAD", "PASS")
    check(r.returncode == 0 and len(gate_lines()) == 4, f"gate PASS on a non-GitHub origin changed behaviour: {r.stderr}")

if FAILS:
    print("pr-landing-gate.test: FAIL\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("pr-landing-gate.test: PASS")
