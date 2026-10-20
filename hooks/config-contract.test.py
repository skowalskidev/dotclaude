#!/usr/bin/env python3
"""ACCEPTANCE CRITERIA FOR THIS CONFIG. Plain English first, then a check that proves it.

WHY THIS EXISTS

Every rule in ~/.claude is advisory. A model reads it and mostly complies. Nothing stops a later
session from editing a rule into something weaker, deleting a hook, renaming a skill, or letting
README.md drift away from what is actually on disk — and none of that fails loudly. The config that
governs every project is the one part of the setup with no test.

This is the same discipline a personal project's repo already runs on itself
(`lib/contracts/unit-contracts.ts` + `contract-coverage.test.ts`, and `__tests__/agent-config.test.ts`):
state the expected outcome in a sentence a human can argue with, back it with a predicate, and let a
coverage check refuse to let a criterion exist without one. It is deliberately the same shape so
there is one idea to learn, not two.

WHAT BELONGS HERE

A criterion earns its place when breaking it would be EXPENSIVE and QUIET. "The guard denies reverse
shells" qualifies: if a refactor drops that regex, nothing tells you until it matters. "The prose in
process.md is well written" does not — it is taste, and it fails loudly the moment you read it.

Criterion ids are STABLE and referenced by the check function name (`check_<id>`). Never renumber
them; a renumber silently orphans the mapping the coverage test relies on.

HOW TO RUN

    /usr/bin/python3 ~/.claude/hooks/config-contract.test.py

Zero dependencies beyond the stdlib and /usr/bin/python3, both of which the config already requires.
No network, no cost, no API calls. It is safe to run on every session and in a pre-commit hook.
"""

from __future__ import annotations

import difflib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The checkout this file sits in. A worktree then tests its own files, never the live config.
ROOT = Path(os.environ.get("CLAUDE_CONFIG_ROOT", Path(__file__).resolve().parents[1]))
_INTAKE_TEMP = tempfile.TemporaryDirectory(prefix="claude-intake-tests-")
INTAKE_TEST_DIR = Path(_INTAKE_TEMP.name)
INTAKE_WORK_DIR = INTAKE_TEST_DIR / "workspace"
INTAKE_WORK_DIR.mkdir()
(INTAKE_WORK_DIR / ".git").mkdir()

# Skill plugins this suite governs. TRACKED ones only, deliberately.
#
# Your work-skills plugin (e.g. `sk-work`) is job-specific: the real files live in the untracked
# `work/` directory and reach Claude Code through a symlink at `skills/<plugin>`. The globs below would happily follow that
# symlink, so nothing forces its exclusion — but a tracked test must not assert against untracked,
# machine-local state. On the fresh-clone path in README.md that directory does not exist, the
# symlink dangles, and every skill criterion would fail on a machine where it cannot be fixed.
#
# Consequence recorded on purpose: the work skill is outside this suite's contract coverage AND
# outside `check_secrets_no_credential_material_tracked`, which enumerates via `git ls-files`. That
# is acceptable only because it is never pushed.
TRACKED_SKILL_PLUGINS = ("sk",)

# --------------------------------------------------------------------------------------
# THE CRITERIA. Plain English. Each one is backed by check_<id> below.
# --------------------------------------------------------------------------------------

CRITERIA: list[tuple[str, str]] = [
    ("automatic-config-repair-lifecycle", "Every task session receives scoped repair authority; startup reports unfinished work without committing, merging or discarding it."),
    ("branch-cleanup-closes-owned-inventory", "Task closure accounts for owned refs; requested repo cleanup surfaces unique branches and preserves recovery, activity and remote-write safeguards."),
    ("node24-shell-runtime", "Terminal and agent shells select one installed Node 24 toolchain in every directory."),
    ("session-performance-and-capacity",
     "Task reports arrive independently, stale review hashes remain pending, and competing heavy work cannot take the same machine lease."),
    ("intent-ledger-retains-and-rechecks-new-asks",
     "Full requests survive capture and every later ask or pivot requires fresh reconciliation, without a stop loop."),
    ("codex-subscription-only-inference",
     "Codex workers and reviewers run their own inference on subscription authentication; `pal` is the one model-API route."),
    ("secret-echo-guard-denies-printed-credentials-both-ways",
     "A Bash command that prints a credential value is denied, awkward variants included, while a consumed value, a help verb and text that names a command all pass."),
    ("agent-setups-preserve-provider-choice",
     "Full Claude and Full Astra preserve selected models, fail without fallback, and report only measured telemetry."),
    ("native-codex-shares-canonical-config",
     "Native Codex reads current shared sources and propagates hook decisions; Claude and Codex launchers preserve the selected project's instruction boundary without copying credentials."),
    ("screenshot-report-preserves-evidence",
     "Screenshot reports retain gaps, separate review from capture and render safe portable evidence."),
    ("dashboard-runtime-preserves-completion",
     "The shared dashboard initializes one task record, rejects false completion and lost updates, "
     "exports portable evidence, and stops only its receipt-verified viewer."),
    ("mockup-shell-preserves-reviewed-deep-links",
     "The mockup shell validates version, variant, persona and state routes; optional highlights use the selected state and start off."),
    # --- Structure: the shape config-repo.md promises ---------------------------------
    ("structure-claude-md-is-an-index",
     "CLAUDE.md stays a thin index. It loads in full on every session in every project, so length "
     "costs adherence to the rules that matter. Ceiling: 120 lines."),
    ("structure-every-rule-is-indexed",
     "Every rules/*.md and references/*.md file on disk is named in CLAUDE.md, and every file "
     "CLAUDE.md names exists. A rule nobody is pointed at is a rule nobody follows."),
    ("structure-rules-stay-within-budget",
     "The always-on rules/ directory stays within a total byte budget. Instruction-following decays "
     "geometrically with instruction count, so unbounded rules make every rule weaker."),
    ("structure-one-owner-per-concern",
     "No two config files carry the same rule text. A duplicated rule drifts, and then two files "
     "disagree about what you want."),

    # --- Credential protection ---------------------------------------------------------
    ("secrets-crown-jewel-paths-denied",
     "settings.json keeps the Edit/Write tamper-denies on the key directories (~/.ssh, ~/.aws, "
     "~/.gnupg), so a run cannot corrupt them. The Read-blockers were removed as theatre — a secret "
     "on this machine is reachable by design — so the real control is the provenance rule plus never "
     "echoing a secret value out (rules/security.md). This tamper set may not quietly shrink."),
    ("secrets-retired-guard-leaves-no-dangling-claim",
     "Nothing in the config claims the retired security-guard.py still runs. A doc promising "
     "protection that no longer exists is worse than an admitted gap, because it stops anyone "
     "looking."),

    # --- Shared machine and one record per session --------------------------------------
    ("session-keeps-one-root-in-nested-worktrees",
     "A session keeps ONE plan and ONE ledger when its shell moves into a worktree nested under its "
     "own root. Both hooks ask bin/session-root.sh, so a prompt or a note sent from the nested "
     "worktree lands in the session's root and opens no second record there."),
    ("native-slot-serializes-native-work-across-sessions",
     "The compatibility frontend uses the shared capacity leases, defers conflicts with exit 75, "
     "and a native project hears the protocol while an idle web project stays silent."),

    # --- Advisory task intake -----------------------------------------------------
    ("intake-initializes-task-record", "Substantive prompts initialize or reuse one ordinary plan and canonical dashboard."),
    ("intake-never-blocks-tools", "Intake cannot deny Agent, Task or Workflow, including with stale former markers."),
    ("intake-needs-no-answer-tool", "Intake requires no native or connector AskUserQuestion callback and settings wire only UserPromptSubmit."),
    ("intake-respects-standing-authorization", "Existing authorization proceeds without another generic approval interview."),
    ("intake-stays-quiet-on-follow-ups", "Short acknowledgements and background notifications stay quiet."),
    ("intake-reuses-mid-run-plan", "New requests preserve the active plan and do not depend on approval stamps."),
    ("intake-has-an-off-switch", "CLAUDE_INTAKE_GATE=off skips duplicate plan initialization for delegated headless work."),

    # --- Hooks in general -------------------------------------------------------------
    ("hooks-all-wired-and-executable",
     "Every hook settings.json references exists and is executable, and every hook script on disk "
     "is referenced by settings.json. Both directions: a missing hook is a silent no-op, an "
     "unreferenced one is dead weight that reads as protection."),
    ("hooks-settings-json-is-valid",
     "settings.json parses as JSON. It is hand-edited, and a trailing comma disables every hook in "
     "it at once with no error anyone sees."),

    # --- Reproducibility: the README is the manifest ----------------------------------
    ("repro-no-eol-runtime-pinned",
     "No document pins a runtime version that is past end-of-life. Your own engineering-standards "
     "rule says latest stable / current LTS, so an EOL pin is the config breaking its own rule."),
    ("repro-brewfile-covers-dependencies",
     "Every external CLI the hooks and bin scripts hard-depend on is in dotfiles/Brewfile. The "
     "Brewfile is what makes a new machine reproducible; a missing entry breaks setup silently."),
    ("repro-readme-counts-are-live",
     "README.md quotes no hardcoded count that has since drifted. A stale 'expect 65 pass' teaches "
     "the next agent to accept a wrong number as correct."),

    # --- Secrets ----------------------------------------------------------------------
    ("secrets-gitignore-is-an-allowlist",
     ".gitignore ignores everything by default and opts tracked paths back in. A denylist lets the "
     "next runtime directory Claude Code invents get committed by accident."),
    ("secrets-no-credential-material-tracked",
     "No tracked file in the repo contains credential-shaped material. This repo is pushed to "
     "GitHub, so a leak here is a published leak."),
    ("naming-skills-carry-a-declared-group-prefix",
     "Every skill is named <group>-<what-it-does> using a prefix declared in "
     "contracts/skill_naming.py, or is a declared exception. A flat list of 16 is one you have to "
     "read to find anything, which is what the prefixes exist to fix; one loosely-named skill added "
     "later starts it drifting back. Adding a genuine new group is a one-line edit to the data."),
    ("routing-every-skill-is-reachable-in-simons-words",
     "Every skill declares a trigger phrase you would actually say, and that phrase appears in its "
     "description. A skill whose description is written in the config's language instead of yours fails "
     "SILENTLY: nothing errors, the work just gets done the long way. Coverage is ratcheted, so a new "
     "skill cannot land without stating how it gets reached."),
    ("routing-no-undeclared-trigger-collisions",
     "No trigger phrase matches two skills unless the overlap is declared. Undeclared overlap means "
     "two skills compete for the same request and the model picks whichever looks closest, which is "
     "how the wrong one wins."),
    ("routing-hooks-fire-for-the-tools-they-target",
     "Each settings.json matcher fires for the tool names it is meant to catch and stays off the ones "
     "it is not. This is the bug class that cost a whole session: a matcher that looks right and "
     "never matches the tool the session actually uses."),
    ("retro-log-detects-without-acting",
     "The SessionEnd retro logger writes one JSON line and does nothing else: silent when nothing "
     "triggered, silent when the transcript is missing, no stdout ever, and nothing written outside "
     "~/.claude/logs/. It runs unattended with no provenance gate, so the moment it ACTS it becomes "
     "the thing rules/security.md forbids. Same detect-and-report contract as orphan-worker-sweep.sh."),
    ("contracts-every-config-part-declares-its-purpose",
     "Every part of this config declares, in contracts/config_contracts.py, what it is for and what "
     "must stay true about it — and every declaration names a file that exists. Claude edits this "
     "config through the self-healing rule, and an edit that looks sensible in isolation can destroy "
     "what a file exists to do while it still parses and still exits 0. Coverage is checked BOTH "
     "ways so it cannot rot: a new part with no contract fails, and a contract left behind by a "
     "deleted part fails."),
    ("contracts-no-vague-language-in-contracts",
     "No mission or criterion in the registry contains a hedge word that hides a missing number. "
     "Every banned word stands in for a threshold or an imperative the author did not write, so a "
     "line containing one can be read and leave the reader with no action to take. The check matches "
     "literal words on word boundaries and nothing else — narrow on purpose, because a guard that "
     "cries wolf gets switched off."),
    ("commits-conventional-subject-enforced",
     "The commit-msg hook rejects a non-conventional subject AND accepts every shape you "
     "actually use, git's own generated messages included. rules/process.md mandated conventional "
     "commits for a long time at ~38% compliance, so the written rule is not the control; this "
     "hook is. A hook that rejects a legitimate message would get bypassed with --no-verify, which "
     "also skips the SECRET gate, so the must-accept half matters more than the must-reject half."),
    ("metrics-log-detects-without-acting",
     "The metrics SessionEnd collector records and nothing else: exit 0, no stdout/stderr (unread "
     "output is noise or a crash), and no config edits. A telemetry hook that acts is the failure "
     "rules/security.md forbids for unattended hooks."),
    ("metrics-criticality-tags-name-real-parts",
     "Every part tagged safety or stub in part_criticality.py names a real file, so a renamed or "
     "removed part cannot leave a stale tag that silently exempts the wrong thing from the dead bar."),
    ("metrics-inventory-matches-contract-coverage",
     "The metrics aggregator derives its parts list from config_contracts.py, never a hardcoded "
     "copy, so a part added via /sk:claude-config-update is scored automatically. Parity with the "
     "contract coverage set is asserted, so the inventory can never silently drift."),
]

CRITERION_IDS = [cid for cid, _ in CRITERIA]

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

FAILURES: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)


def settings() -> dict:
    return json.loads(read("settings.json"))


def hook_commands() -> list[str]:
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "command" and isinstance(node.get("command"), str):
                out.append(node["command"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(settings().get("hooks", {}))
    return out


def intake(mode: str, payload: dict, env: dict | None = None) -> str:
    e = dict(os.environ)
    e.pop("CLAUDE_INTAKE_GATE", None)
    if env:
        e.update(env)
    e["CLAUDE_INTAKE_STATE_DIR"] = str(INTAKE_TEST_DIR)
    e.setdefault("CLAUDE_SESSION_ROOT_DIR", str(INTAKE_TEST_DIR / "session-roots"))
    e["CLAUDE_CONFIG_ROOT"] = str(ROOT)
    payload = dict(payload)
    payload.setdefault("cwd", str(INTAKE_WORK_DIR))
    p = run([str(ROOT / "hooks" / "task-intake.sh"), mode], input=json.dumps(payload), env=e)
    return (p.stdout or "") + (p.stderr or "")


def clear_markers() -> None:
    d = INTAKE_TEST_DIR
    if d.is_dir():
        for f in (*d.glob("*.armed"), *d.glob("*.approved")):
            f.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Checks. One per criterion, named check_<id with dashes as underscores>.
# --------------------------------------------------------------------------------------

def check_structure_claude_md_is_an_index() -> None:
    lines = len(read("CLAUDE.md").splitlines())
    check(lines <= 120,
          f"CLAUDE.md is {lines} lines, over the 120 ceiling. It loads on EVERY session in EVERY "
          f"project. Move detail into rules/ (always-on, one concern) or references/ (on-demand).")


def check_structure_every_rule_is_indexed() -> None:
    index = read("CLAUDE.md")
    for sub in ("rules", "references"):
        on_disk = {p.stem for p in (ROOT / sub).glob("*.md")}
        for name in sorted(on_disk):
            check(re.search(rf"\b{re.escape(name)}\b", index) is not None,
                  f"{sub}/{name}.md exists but CLAUDE.md never mentions it, so nothing routes to it.")
        for m in re.finditer(rf"`{sub}/([a-z0-9-]+)\.md`", index):
            check(m.group(1) in on_disk,
                  f"CLAUDE.md points at {sub}/{m.group(1)}.md, which does not exist.")


def check_structure_rules_stay_within_budget() -> None:
    total = sum(p.stat().st_size for p in (ROOT / "rules").glob("*.md"))
    check(total <= 70_000,
          f"rules/ totals {total:,} bytes, over the 70,000 budget. These load every session; past "
          f"this, adherence to all of them drops. Move deep how-to into references/.")


def check_structure_one_owner_per_concern() -> None:
    """Find a substantial paragraph that appears in two config files, verbatim OR near-verbatim.

    NEAR-verbatim is the case that matters, and an exact-match check misses it. On 2026-08-03
    references/code-best-practices.md held a copy of the SSOT rule from rules/engineering-standards.md
    that had already lost two of the owner's bullets — so the copy was no longer identical, an
    exact-match check passed, and a reader of the copy got a weaker rule than the one you wrote.
    Drift is not the thing that makes a duplicate acceptable; it is the damage the duplicate does.
    """
    docs: dict[str, str] = {}
    for sub in ("rules", "references"):
        for p in (ROOT / sub).glob("*.md"):
            docs[f"{sub}/{p.name}"] = p.read_text(encoding="utf-8", errors="replace")

    def blocks(text: str) -> list[str]:
        out = []
        for para in re.split(r"\n\s*\n", text):
            norm = re.sub(r"\s+", " ", para).strip().strip("-*# ").lower()
            # Long enough that a collision means copied text, not a coincidence.
            if len(norm) >= 220:
                out.append(norm)
        return out

    indexed = [(name, b) for name, text in sorted(docs.items()) for b in blocks(text)]
    for i, (name_a, a) in enumerate(indexed):
        for name_b, b in indexed[i + 1:]:
            if name_a == name_b:
                continue
            if a == b:
                ratio = 1.0
            else:
                # Cheap length prefilter first; SequenceMatcher is O(n*m) and this runs on every
                # pair of long paragraphs in the config.
                if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.35:
                    continue
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if ratio >= 0.80:
                check(False,
                      f"{name_a} and {name_b} carry the same rule ({ratio:.0%} identical). One must "
                      f"own it; the other becomes a one-line pointer. A near-copy is worse than an "
                      f"exact one — it has already drifted, so the two files now say different "
                      f"things. Starts: {a[:90]}...")
                return  # one report is enough; the fix is the same shape for the rest


def check_secrets_crown_jewel_paths_denied() -> None:
    """Read-blocking was retired as theatre (a secret here is reachable by design). What remains is
    tamper-protection: Edit/Write on the key directories, so a run cannot corrupt them."""
    deny = settings().get("permissions", {}).get("deny", [])
    required = [
        "Edit(~/.ssh/**)", "Edit(~/.aws/**)", "Edit(~/.gnupg/**)",
        "Write(~/.ssh/**)", "Write(~/.aws/**)", "Write(~/.gnupg/**)",
    ]
    for rule in required:
        check(rule in deny,
              f"settings.json no longer denies {rule}. The Edit/Write tamper-denies on the key "
              f"directories are the one mechanical credential control kept after the read-blockers "
              f"were removed — they may not quietly shrink.")


def check_secrets_retired_guard_leaves_no_dangling_claim() -> None:
    """A doc promising protection that no longer runs is worse than an admitted gap. Covers both
    retired read-blockers: security-guard.py (2026-08-04) and crown-jewel-read-guard.py (2026-08-29)."""
    retired = ("security-guard", "crown-jewel-read-guard")
    live = {c for c in hook_commands()}
    for name in retired:
        check(not any(f"{name}.py" in c for c in live),
              f"settings.json still wires {name}.py, which has been removed from hooks/.")
        check(not (ROOT / "hooks" / f"{name}.py").exists(),
              f"hooks/{name}.py is back on disk but the config says it was retired. Pick one.")

    # Any prose still describing a retired guard as live. A line explaining that it was RETIRED is the
    # point of the change and must not trip this, so those are allowed by keyword.
    RETIRED_CONTEXT = re.compile(r"retir|remov|delet|no longer|was\b|former|history|restor", re.I)
    for sub in ("rules", "references"):
        for p in (ROOT / sub).glob("*.md"):
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not any(name in line for name in retired):
                    continue
                check(RETIRED_CONTEXT.search(line) is not None,
                      f"{sub}/{p.name}:{i} still describes a retired guard as live: {line.strip()[:90]}")


def check_intent_ledger_retains_and_rechecks_new_asks() -> None:
    with tempfile.TemporaryDirectory(prefix="gauntlet-ledger-test-") as tmp:
        base = Path(tmp)
        home, repo = base / "home", base / "repo"
        home.mkdir()
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        (repo / ".git" / "info" / "exclude").write_text(".context/\n")
        env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_ROOT": str(ROOT),
               "CLAUDE_INTENT_LEDGER": "on", "CLAUDE_PROJECT_DIR": str(repo)}
        hook = ROOT / "hooks" / "intent-ledger.sh"

        def invoke(mode, prompt=None, active=False):
            payload = {"cwd": str(repo), "session_id": "ledger-contract",
                       "stop_hook_active": active}
            if prompt is not None:
                payload["prompt"] = prompt
            result = subprocess.run(["bash", str(hook), mode], input=json.dumps(payload),
                                    text=True, capture_output=True, cwd=repo, env=env)
            check(result.returncode == 0, "Ledger hook failed: " + result.stderr)
            return result.stdout

        def note(kind, text):
            scratch = base / "note.md"
            scratch.write_text(text)
            result = subprocess.run(["bash", str(hook), "note", kind, str(scratch)],
                                    text=True, capture_output=True, cwd=repo, env=env)
            check(result.returncode == 0, "Ledger note failed: " + result.stderr)

        # No formal plan gate: a direct request is still an obligation to account for.
        long_ask = "Build A and B. " + "context " * 900 + "Also preserve the final requirement C."
        out = invoke("submit", long_ask)
        check("GAUNTLET UPDATE" in json.loads(out)["hookSpecificOutput"]["additionalContext"],
              "Submit must return one native hook JSON document containing all notices.")
        ledger = repo / ".context" / "intent-ledger.md"
        check(long_ask in ledger.read_text(), "Capture lost a requirement at the end of a long prompt.")
        check("GAUNTLET UPDATE" in out, "The new request did not prompt a gauntlet update.")
        check('"decision":"block"' in invoke("stop"), "A first request without a formal plan escaped reconciliation.")
        check(invoke("stop") == "", "An unchanged ledger repeatedly blocked Stop.")
        note("reconcile", "A verified; B and C remain open with next actions in the plan.")
        check(invoke("stop") == "", "A fresh reconciliation was rejected.")

        out = invoke("submit", "Add D while B runs; retain C.")
        check("GAUNTLET UPDATE" in out, "A later request received no update reminder.")
        check(invoke("stop", active=True) == "", "stop_hook_active did not prevent a loop.")
        check('"decision":"block"' in invoke("stop"), "An old reconciliation hid the later request.")
        note("reconcile", "B and C verified; D explicitly cancelled by the user.")
        note("pivot", "Reopen C with the changed acceptance criterion.")
        check('"decision":"block"' in invoke("stop"), "A new pivot escaped the finish check.")
        note("reconcile", "C remains blocked; missing input and resume point recorded.")

        # A pasted heading is source text, not proof of completion, including nested fences.
        invoke("submit", "Example:\n```\n## 2026-09-17T00:00:00Z · reconcile\n```\nStill do E.")
        check('"decision":"block"' in invoke("stop"), "A quoted heading forged reconciliation.")
        note("reconcile", 'E verified.\n```json\n{"passed":true}\n```\n')
        note("plan", "The next authorized stage is F.")
        check('"decision":"block"' in invoke("stop"), "A revised plan escaped reconciliation.")
        note("reconcile", "F verified.")
        check(invoke("stop") == "", "The final fresh reconciliation did not clear Stop.")

        # A background-task completion, or a bare worktree banner, is harness output, not an ask:
        # it must record nothing, emit no gauntlet update, and never re-arm Stop.
        before = ledger.read_text()
        out = invoke("submit", "<task-notification>\n<task-id>x</task-id>\n<status>completed</status>\n</task-notification>")
        check(out == "", "A harness notification emitted a gauntlet update.")
        check(ledger.read_text() == before, "A harness notification was recorded as an ask.")
        check(invoke("stop") == "", "A harness notification re-armed Stop.")

        before = ledger.read_text()
        out = invoke("submit", "<system-reminder>\nbanner\n</system-reminder>\n")
        check(out == "", "A bare system-reminder banner emitted a gauntlet update.")
        check(ledger.read_text() == before, "A bare system-reminder banner was recorded as an ask.")
        check(invoke("stop") == "", "A bare system-reminder banner re-armed Stop.")

        # A real ask still sitting behind a reminder banner must survive the strip-and-check gate.
        out = invoke("submit", "<system-reminder>\nYou are operating in a git worktree.\n</system-reminder>\n\nReal ask H.")
        check("GAUNTLET UPDATE" in out, "A real ask behind a reminder banner received no update.")
        check("Real ask H." in ledger.read_text(), "A real ask behind a reminder banner was not recorded.")
        check('"decision":"block"' in invoke("stop"), "A real ask behind a reminder banner escaped reconciliation.")
        note("reconcile", "H verified.")

        note("reconcile", "Evidence:\n~~~text\npassed\n~~~\n")
        invoke("submit", "Now do G.")
        check('"decision":"block"' in invoke("stop"), "A fenced evidence note hid a later ask.")
        check("Still do E." in ledger.read_text() and long_ask in ledger.read_text(),
              "Later requests overwrote earlier source messages.")

        # The ledger is never its own note source: `cat ledger >> ledger` never ends. Try the plain
        # path, a path spelled through `..`, and a symlink; each must exit 2 with the ledger intact.
        link = base / "ledger-alias.md"
        link.symlink_to(ledger)
        for spelling in (ledger, ledger.parent / ".." / ".context" / ledger.name, link):
            before = ledger.read_bytes()
            try:
                result = subprocess.run(["bash", str(hook), "note", "pivot", str(spelling)],
                                        text=True, capture_output=True, cwd=repo, env=env, timeout=10)
            except subprocess.TimeoutExpired:
                check(False, f"Ledger note with the ledger as its source never ended: {spelling}")
                continue
            check(result.returncode == 2 and "is the ledger itself" in result.stderr,
                  f"Ledger note accepted the ledger as its own source ({spelling}): {result.stderr}")
            check(ledger.exists() and ledger.read_bytes() == before,
                  f"Ledger changed or was deleted by a note naming it as the source ({spelling}).")


def check_intake_initializes_task_record() -> None:
    out = intake("submit", {"session_id": "contract-a", "prompt": "refactor the billing module"})
    check("TASK ROUTING" in out and "Session record ready." in out and "DASHBOARD_PATH=" in out,
          "Task intake did not initialize its plan-backed dashboard and routing advisory.")
    context = INTAKE_WORK_DIR / ".context"
    check(len(list(context.glob("*-plan.md"))) == 1 and len(list(context.glob("*-dashboard.html"))) == 1,
          "Intake did not create exactly one plan and canonical dashboard.")
    plan = next(context.glob("*-plan.md"))
    match = re.search(r"^```dashboard-state\n(.*?)\n```", plan.read_text(), re.M | re.S)
    state = json.loads(match.group(1)) if match else {}
    check((state.get("engine"), state.get("gauntlet"), state.get("optionsConfirmedAt")) == ("current", False, None),
          "Ordinary intake changed the execution defaults.")
    for prompt in ("Can you make the footer blue?", "Could you review the dashboard?", "Why is this route slow?"):
        intake("submit", {"session_id": "contract-a", "prompt": prompt})
        check(len(list(context.glob("*-plan.md"))) == 1, "Repeated intake opened a second plan.")


def check_intake_never_blocks_tools() -> None:
    for suffix in ("armed", "approved", "armed.denials"):
        (INTAKE_TEST_DIR / ("contract-stale." + suffix)).write_text("3")
    for tool in ("Agent", "Task", "Workflow", "Read"):
        check(intake("guard", {"session_id": "contract-stale", "tool_name": tool}).strip() == "",
              "Intake still blocks " + tool)
    out = intake("submit", {"session_id": "contract-stale", "prompt": "continue fixing the panel"})
    check('permissionDecision' not in out and 'TASK INTAKE GATE' not in out,
          "Stale runtime markers restored an approval gate.")


def check_intake_needs_no_answer_tool() -> None:
    for event, groups in json.loads(read("settings.json")).get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command", "")
                check("config-edit-guard.py" not in command, "Removed config sentinel guard is still wired.")
                if "task-intake.sh" in command:
                    check(event == "UserPromptSubmit" and command.endswith(" submit"),
                          "Intake still requires a tool or answer callback.")
    out = intake("submit", {"session_id": "contract-no-question", "prompt": "build the panel"})
    check("No generic confirmation" in out, "A host without AskUserQuestion cannot proceed.")


def check_intake_respects_standing_authorization() -> None:
    out = intake("submit", {"session_id": "contract-standing", "prompt": "Fix the panel while I sleep. Do not ask me again."})
    check("Use existing explicit or standing authorization" in out and 'permissionDecision' not in out,
          "Intake lost standing authorization.")
    check(len(list((INTAKE_WORK_DIR / ".context").glob("*-plan.md"))) == 1,
          "Unattended intake lost the session record.")


def check_intake_stays_quiet_on_follow_ups() -> None:
    for prompt in ("yes", "go ahead", "option 2", "continue", "lgtm", "2", "sounds good", "ship it", "thanks", "no", "ok", "approved",
                   "<task-notification>build finished</task-notification>", "System notification - not user input: done"):
        check(intake("submit", {"session_id": "contract-quiet", "prompt": prompt}).strip() == "",
              "Intake adds noise to acknowledgement/background event: " + prompt)


def check_intake_reuses_mid_run_plan() -> None:
    root = INTAKE_TEST_DIR / "midrun-workspace"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    sid = {"session_id": "contract-midrun", "cwd": str(root)}
    intake("submit", {**sid, "prompt": "investigate the flaky login test"})
    plan = next((root / ".context").glob("*-plan.md"))
    original = plan.read_text()
    plan.write_text(original + "\nRetain the unfinished original request.\n")
    intake("submit", {**sid, "prompt": "check the footer color too"})
    check(len(list((root / ".context").glob("*-plan.md"))) == 1 and
          "Retain the unfinished original request." in plan.read_text(), "Mid-run intake replaced the active work.")
    check(not (INTAKE_TEST_DIR / "contract-midrun.approved").exists(), "Intake still creates approval state.")


def check_session_keeps_one_root_in_nested_worktrees() -> None:
    result = run(["bash", str(ROOT / "bin" / "session-root.test.sh")])
    check(result.returncode == 0,
          f"bin/session-root.test.sh failed:\n{result.stdout}\n{result.stderr}")
    with tempfile.TemporaryDirectory(prefix="session-root-contract-") as tmp:
        base = Path(tmp).resolve()
        home, repo = base / "home", base / "repo"
        home.mkdir()
        git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        subprocess.run([*git, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        (repo / ".git" / "info" / "exclude").write_text(".context/\n")
        nested = repo / ".context" / "nested"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(nested), "-b", "nested"],
                       check=True, capture_output=True)
        roots = str(base / "roots")

        env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_ROOT": str(ROOT),
               "CLAUDE_INTENT_LEDGER": "on", "CLAUDE_PROJECT_DIR": str(repo),
               "CLAUDE_SESSION_ROOT_DIR": roots, "CLAUDE_CODE_SESSION_ID": "root-contract"}
        hook = ROOT / "hooks" / "intent-ledger.sh"

        def submit(cwd: Path, prompt: str) -> None:
            payload = {"cwd": str(cwd), "session_id": "root-contract", "prompt": prompt}
            r = subprocess.run(["bash", str(hook), "submit"], input=json.dumps(payload),
                               text=True, capture_output=True, cwd=cwd, env=env)
            check(r.returncode == 0, "Ledger hook failed: " + r.stderr)

        submit(repo, "First ask, sent from the session root.")
        submit(nested, "Second ask, sent while the shell sits in the nested worktree.")
        scratch = base / "note.md"
        scratch.write_text("Both asks reconciled.")
        r = subprocess.run(["bash", str(hook), "note", "reconcile", str(scratch)],
                           text=True, capture_output=True, cwd=nested, env=env)
        check(r.returncode == 0, "Ledger note from the nested worktree failed: " + r.stderr)
        ledger = repo / ".context" / "intent-ledger.md"
        text = ledger.read_text() if ledger.exists() else ""
        check("First ask" in text and "Second ask" in text,
              "An ask sent from a nested worktree did not reach the session's own ledger.")
        check("Both asks reconciled." in text,
              "A note written from a nested worktree did not reach the session's own ledger.")
        check(not (nested / ".context").exists(),
              "The ledger hook opened a second record inside the nested worktree.")

        other = {"cwd": str(nested), "session_id": "root-contract-other",
                 "prompt": "An ask from a session that started in the nested worktree."}
        r = subprocess.run(["bash", str(hook), "submit"], input=json.dumps(other),
                           text=True, capture_output=True, cwd=nested, env=env)
        check((nested / ".context" / "intent-ledger.md").exists(),
              "A session that STARTED in the nested worktree lost its own ledger.")
        check("started in the nested worktree" not in ledger.read_text(),
              "Another session's ask leaked into this session's ledger.")

        clear_markers()
        work = base / "intake-repo"
        subprocess.run(["git", "init", "-q", str(work)], check=True, capture_output=True)
        subprocess.run([*git, "-C", str(work), "commit", "-q", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        inner = work / ".context" / "inner"
        subprocess.run(["git", "-C", str(work), "worktree", "add", "-q", str(inner), "-b", "inner"],
                       check=True, capture_output=True)
        e = {"CLAUDE_SESSION_ROOT_DIR": roots}
        sid = {"session_id": "contract-root"}
        intake("submit", {**sid, "cwd": str(work), "prompt": "investigate the flaky login test"}, e)
        intake("answered", {**sid, "cwd": str(work), "tool_name": "AskUserQuestion"}, e)
        out = intake("submit", {**sid, "cwd": str(inner), "prompt": "check the footer color too"}, e)
        check("TASK INTAKE GATE" not in out,
              "A message sent from a nested worktree re-armed the gate mid-run: the hook looked for "
              "the plan in the nested worktree instead of the session's root.")
        check(len(list((work / ".context").glob("*-plan.md"))) == 1,
              "The session root does not hold exactly one plan.")
        check(not list(inner.glob(".context/*-plan.md")),
              "The intake hook opened a second plan inside the nested worktree.")
        clear_markers()


def check_native_slot_serializes_native_work_across_sessions() -> None:
    result = run(["bash", str(ROOT / "bin" / "native-slot.test.sh")])
    check(result.returncode == 0,
          f"bin/native-slot.test.sh failed:\n{result.stdout}\n{result.stderr}")
    with tempfile.TemporaryDirectory(prefix="native-sweep-") as tmp:
        config = Path(tmp) / "config"
        (config / "bin").mkdir(parents=True)
        fake = config / "bin" / "native-slot.sh"
        fake.write_text("#!/bin/sh\n"
                        "if [ \"$FAKE_NATIVE_STATE\" = held ]; then printf 'holder=other pid=42 live\\nbooted simulators: none\\n'; "
                        "else printf 'heavy slot 1 of 3: free\\nheavy slot 2 of 3: free\\nheavy slot 3 of 3: free\\nbooted simulators: none\\n"
                        "simulators in use: 0 of 1\\nwatchdog: clear\\ndev stacks: 1 of 2 (Docker VM 7.8 GiB): /w/a (a running)\\n'; "
                        "[ \"$FAKE_NATIVE_STATE\" = hot ] && printf 'watchdog: HOT pid=501 SpringBoard cpu=400%% age=300s\\n'; fi\n")
        fake.chmod(0o700)
        project = Path(tmp) / "project"
        (project / "ios" / "App.xcodeproj").mkdir(parents=True)
        web = Path(tmp) / "web"
        web.mkdir()
        e = {**os.environ, "CLAUDE_CONFIG_ROOT": str(config), "CLAUDE_PROJECT_DIR": str(web),
             "FAKE_NATIVE_STATE": "free"}
        idle = subprocess.run(["bash", str(ROOT / "hooks" / "port-registry-sweep.sh")],
                              text=True, capture_output=True, cwd=web, env=e)
        check("heavy builds and simulators" not in idle.stdout,
              "An idle web session received native capacity instructions.")
        e["CLAUDE_PROJECT_DIR"] = str(project)
        r = subprocess.run(["bash", str(ROOT / "hooks" / "port-registry-sweep.sh")],
                           text=True, capture_output=True, cwd=project, env=e)
        check("native-slot.sh run" in r.stdout,
              "A session opening in a native project was not told the native-slot protocol.")
        check("Exit 75" in r.stdout and "Machine-wide capacity" in r.stdout,
              "The native project was told the old waiting or exit-3 protocol.")
        e.update(CLAUDE_PROJECT_DIR=str(web), FAKE_NATIVE_STATE="held")
        held = subprocess.run(["bash", str(ROOT / "hooks" / "port-registry-sweep.sh")],
                              text=True, capture_output=True, cwd=web, env=e)
        check("holder=other" in held.stdout,
              "A held lease was hidden from a session with no native project.")
        e["FAKE_NATIVE_STATE"] = "hot"
        hot = subprocess.run(["bash", str(ROOT / "hooks" / "port-registry-sweep.sh")],
                             text=True, capture_output=True, cwd=web, env=e)
        check("watchdog: HOT pid=501" in hot.stdout,
              "A runaway process flagged by the capacity watchdog was hidden from a web session at start.")


def check_intake_has_an_off_switch() -> None:
    root = INTAKE_TEST_DIR / "headless-workspace"
    root.mkdir(exist_ok=True)
    out = intake("submit", {"session_id": "contract-off", "cwd": str(root), "prompt": "refactor everything now"},
                 env={"CLAUDE_INTAKE_GATE": "off"})
    check(out.strip() == "" and not (root / ".context").exists(), "Headless opt-out still initializes a duplicate plan.")


def check_hooks_all_wired_and_executable() -> None:
    cmds = hook_commands()
    for c in cmds:
        path = Path(c.split()[0].replace("$HOME", str(Path.home())))
        check(path.exists(), f"settings.json wires a hook that does not exist: {path}")
        if path.exists():
            check(os.access(path, os.X_OK),
                  f"Hook {path.name} is not executable, so it silently no-ops while reading as protection.")
    joined = " ".join(cmds)
    for p in (ROOT / "hooks").glob("*"):
        if p.suffix not in (".sh", ".py") or p.name.endswith(".test.py"):
            continue
        check(p.name in joined,
              f"hooks/{p.name} exists but settings.json never references it. Either wire it or delete it.")


def check_hooks_settings_json_is_valid() -> None:
    try:
        settings()
    except Exception as e:  # noqa: BLE001
        check(False, f"settings.json is not valid JSON: {e}. Every hook in it is disabled right now.")


def check_repro_no_eol_runtime_pinned() -> None:
    # Node 20 reached EOL in April 2026. 22 and 24 are the live LTS lines as of Aug 2026.
    # `Node(?:\.?js)?` and NOT `Node\.?js?` — the latter needs a literal "j" and so silently
    # matches nothing, which is how the README kept its EOL pin through the first run of this test.
    eol = {"Node 18": r"Node(?:\.?js)?\s*18\b", "Node 20": r"Node(?:\.?js)?\s*20\b"}
    for doc in ("README.md", "AGENTS.md", "CLAUDE.md"):
        if not (ROOT / doc).exists():
            continue
        text = read(doc)
        for label, pat in eol.items():
            check(re.search(pat, text) is None,
                  f"{doc} pins {label}, which is past end-of-life. engineering-standards.md says "
                  f"latest stable / current LTS, so this document breaks the config's own rule.")


def check_repro_brewfile_covers_dependencies() -> None:
    brewfile = read("dotfiles/Brewfile") if (ROOT / "dotfiles" / "Brewfile").exists() else ""
    scripts = []
    for d in ("hooks", "bin", "dotfiles", ".githooks"):
        if (ROOT / d).is_dir():
            scripts += [p for p in (ROOT / d).iterdir() if p.is_file() and p.suffix in ("", ".sh")]
    src = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in scripts)
    # Only tools used WITHOUT a `command -v` guard are hard dependencies.
    for tool in ("jq", "gitleaks"):
        used = re.search(rf"(?<![\w-]){re.escape(tool)}\b", src) is not None
        if used:
            check(tool in brewfile,
                  f"{tool} is used by a hook or script but is not in dotfiles/Brewfile, so a fresh "
                  f"machine set up from the README will not have it.")


def check_repro_readme_counts_are_live() -> None:
    if not (ROOT / "README.md").exists():
        return
    text = read("README.md")
    m = re.search(r"expect:\s*(\d+)\s*pass", text)
    if m:
        p = run(["/usr/bin/python3", str(ROOT / "hooks" / "security-guard.test.py")])
        actual = re.search(r"(\d+)\s+pass", p.stdout or "")
        check(actual is not None and actual.group(1) == m.group(1),
              f"README.md says the guard suite should report {m.group(1)} passes but it reports "
              f"{actual.group(1) if actual else '?'}. A stale count teaches the next agent to accept "
              f"a wrong number. State the count in ONE place or not at all.")
    # A doc may legitimately name a file to record that it is GONE. Same allowance the personal-project
    # doc-freshness test carries: "was retired", "removed on", "recoverable from git history".
    HISTORICAL = re.compile(r"\b(retir|remov|delet|no longer|former|history|was\b|used to)", re.I)
    for m in re.finditer(r"`([a-zA-Z0-9_./-]+\.(?:sh|py|json|md|zsh))`", text):
        rel = m.group(1)
        # `~` and `/` are already outside this repo. `.context/` is too: it is the per-worktree agent
        # scratch dir in whatever PROJECT is being worked on, so it can never exist here, and treating
        # it as repo-relative makes this check cry wolf about a path that is correct.
        if rel.startswith(("http", "~", "/", ".context/")) or "*" in rel:
            continue
        line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
        if HISTORICAL.search(line):
            continue
        if "/" in rel and not (ROOT / rel).exists():
            check(False, f"README.md references `{rel}`, which does not exist in the repo.")


def check_secrets_gitignore_is_an_allowlist() -> None:
    gi = read(".gitignore")
    check(re.search(r"^\s*/?\*\s*$", gi, re.M) is not None or re.search(r"^\s*\*\s*$", gi, re.M) is not None,
          ".gitignore is not an allowlist (no bare `*` line). ~/.claude is where Claude Code writes "
          "runtime state, so a denylist means the next directory it invents gets committed.")


def check_secrets_no_credential_material_tracked() -> None:
    p = run(["git", "-C", str(ROOT), "ls-files"])
    patterns = [
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key block"),
        (r"\bsk-ant-[A-Za-z0-9_-]{20,}", "an Anthropic API key"),
        (r"\bsk-[A-Za-z0-9]{32,}", "an OpenAI-style API key"),
        (r"\bghp_[A-Za-z0-9]{30,}", "a GitHub token"),
        (r"\bAKIA[0-9A-Z]{16}\b", "an AWS access key id"),
        (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "a Slack token"),
    ]
    for rel in p.stdout.splitlines():
        f = ROOT / rel
        if not f.is_file() or f.stat().st_size > 2_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, label in patterns:
            for hit in re.finditer(pat, text):
                # The detector patterns live in this file and in the scanner; those are not secrets.
                line = text[max(0, hit.start() - 200):hit.start() + 200]
                if "BEGIN [A-Z" in line or "A-Za-z0-9" in line:
                    continue
                check(False, f"Tracked file {rel} contains what looks like {label}. This repo is "
                             f"pushed to GitHub, so that is a published leak.")


# --------------------------------------------------------------------------------------
_STOPWORDS = {"the", "a", "an", "my", "me", "it", "this", "that", "to", "in", "on", "is", "are",
              "and", "or", "but", "for", "of", "i", "s", "t", "let", "go", "am"}


def _routing() -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(ROOT / "contracts"))
    from routing_scenarios import HOOK_ROUTING, SCENARIOS  # type: ignore[import-not-found]
    return SCENARIOS, HOOK_ROUTING


def _skill_descriptions() -> dict[str, str]:
    out: dict[str, str] = {}
    for plugin in TRACKED_SKILL_PLUGINS:
        for p in (ROOT / "skills" / plugin / "skills").glob("*/SKILL.md"):
            text = p.read_text()
            m = re.search(r"^description:\s*(.+?)(?=\n[a-z-]+:\s|\n---)", text, re.S | re.M)
            out[p.parent.name] = " ".join(m.group(1).split()).lower() if m else ""
    return out


def _words(phrase: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", phrase.lower()) if w not in _STOPWORDS}


def check_naming_skills_carry_a_declared_group_prefix() -> None:
    sys.path.insert(0, str(ROOT / "contracts"))
    try:
        from skill_naming import PREFIXES, UNPREFIXED  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        check(False, f"contracts/skill_naming.py could not be imported: {e}")
        return

    names = {p.parent.name for plugin in TRACKED_SKILL_PLUGINS
             for p in (ROOT / "skills" / plugin / "skills").glob("*/SKILL.md")}

    for name in sorted(names):
        if name in UNPREFIXED:
            continue
        if not any(name.startswith(pfx) for pfx in PREFIXES):
            check(False,
                  f"Skill {name!r} carries no declared group prefix. Rename it "
                  f"<group>-<what-it-does> using one of {sorted(PREFIXES)}, add a new group to "
                  f"contracts/skill_naming.py if none fits, or declare it in UNPREFIXED. A skill "
                  f"nobody can filter to is one you have to read the whole list to find.")

    # A stale exception is worse than none: it reads as a considered decision for a skill that is
    # gone, and quietly permits the next unprefixed name to reuse it.
    for stale in sorted(UNPREFIXED - names):
        check(False,
              f"contracts/skill_naming.py exempts {stale!r}, which is not a skill any more. "
              f"Remove the exception.")

    # An empty group means the prefix survived its last member, so the menu gains a filter that
    # matches nothing.
    for pfx in sorted(PREFIXES):
        if not any(n.startswith(pfx) for n in names):
            check(False, f"Prefix {pfx!r} is declared but no skill uses it. Remove it or use it.")


def check_routing_every_skill_is_reachable_in_simons_words() -> None:
    scenarios, _ = _routing()
    descs = _skill_descriptions()

    for sc in scenarios:
        target = sc["expect"]
        check(target in descs, f"Scenario {sc['phrase']!r} expects skill {target!r}, which does not exist.")
        if target not in descs:
            continue
        missing = sorted(w for w in _words(sc["phrase"]) if w not in descs[target])
        check(not missing,
              f"{target}: its description does not contain {missing} from the phrase "
              f"{sc['phrase']!r}. You ask in those words; if the description does not use them, "
              f"the skill silently never fires. Reword the DESCRIPTION, not the scenario.")

    covered = {sc["expect"] for sc in scenarios}
    for skill in sorted(set(descs) - covered):
        check(False,
              f"Skill {skill!r} has no routing scenario. Add one to contracts/routing_scenarios.py "
              f"saying how you would ask for it. A skill nobody can state a trigger for is a skill "
              f"that will never fire.")


def check_routing_no_undeclared_trigger_collisions() -> None:
    scenarios, _ = _routing()
    descs = _skill_descriptions()
    # Collision means another description ADVERTISES the same trigger, i.e. contains the phrase
    # itself. Deliberately NOT "every word appears somewhere in the description": any sufficiently
    # long description satisfies that by accident, which made this check fire on two false positives
    # the first time it ran. A guard that cries wolf gets switched off, so this one is narrow on
    # purpose: it will miss soft overlaps, and it will not manufacture one.
    for sc in scenarios:
        allowed = {sc["expect"], *sc.get("also_matches", [])}
        needle = " ".join(sc["phrase"].lower().split())
        clashes = sorted(name for name, d in descs.items()
                         if name not in allowed and needle in " ".join(d.split()))
        check(not clashes,
              f"Phrase {sc['phrase']!r} is also advertised by {clashes}. Two skills claiming one "
              f"trigger means the model picks whichever looks closest. Either narrow the other "
              f"description, or declare it in `also_matches` if the overlap is genuinely fine.")


def check_routing_hooks_fire_for_the_tools_they_target() -> None:
    _, hook_routing = _routing()
    hooks_cfg = settings().get("hooks", {})
    session_commands = [h.get("command") for group in hooks_cfg.get("SessionStart", [])
                        for h in group.get("hooks", [])]
    check('$HOME/.claude/bin/agent_runtime.py policy-hook' in session_commands,
          "SessionStart must call the project-instruction policy hook before a project doc can supply guidance.")

    for case in hook_routing:
        groups = hooks_cfg.get(case["event"], [])
        fired: list[str] = []
        for group in groups:
            matcher = group.get("matcher")
            tool = case["tool"]
            if matcher is None:
                hit = True  # no matcher = fires for every event of this type
            elif tool is None:
                hit = False
            else:
                hit = re.fullmatch(matcher, tool) is not None
            if hit:
                fired += [Path(h.get("command", "").split()[0]).name
                          for h in group.get("hooks", []) if h.get("command")]
        expected = sorted(case["expect"])
        check(sorted(set(fired)) == expected,
              f"{case['event']} / tool={case['tool']}: expected {expected}, got {sorted(set(fired))}. "
              f"A matcher that silently misses its tool is the bug that deadlocked a whole session.")


def check_retro_log_detects_without_acting() -> None:
    hook = ROOT / "hooks" / "retro-trigger-log.sh"
    check(hook.exists() and os.access(hook, os.X_OK),
          "hooks/retro-trigger-log.sh is missing or not executable.")
    if not hook.exists():
        return

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        def run_hook(transcript: str, home: Path) -> subprocess.CompletedProcess:
            home.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"transcript_path": transcript, "session_id": "t",
                                  "reason": "clear", "cwd": "/tmp/x"})
            return subprocess.run(["bash", str(hook)], input=payload, capture_output=True,
                                  text=True, env={**os.environ, "HOME": str(home)})

        # Triggered: exactly one line, no stdout, nothing outside logs/.
        dirty = base / "dirty.jsonl"
        dirty.write_text("noise\nBlocked: work resource\n")
        h1 = base / "home1"
        p = run_hook(str(dirty), h1)
        check(p.stdout == "" and p.stderr == "",
              f"Logger emitted output. SessionEnd output is never read, so anything printed is "
              f"noise or a crash. stdout={p.stdout!r} stderr={p.stderr!r}")
        log = h1 / ".claude" / "logs" / "retro-triggers.jsonl"
        lines = log.read_text().splitlines() if log.exists() else []
        check(len(lines) == 1, f"Expected exactly 1 log line, got {len(lines)}.")
        if lines:
            try:
                row = json.loads(lines[0])
                check(row.get("guard_denials") == 1,
                      f"Counts wrong: {row}. A renamed guard message silently zeroes a count.")
            except json.JSONDecodeError as e:
                check(False, f"Log line is not valid JSON ({e}): {lines[0]!r}")
        stray = [str(f.relative_to(h1)) for f in h1.rglob("*")
                 if f.is_file() and ".claude/logs/" not in str(f)]
        check(not stray, f"Logger wrote outside ~/.claude/logs/: {stray}")

        # Clean session: no file at all.
        clean = base / "clean.jsonl"
        clean.write_text("nothing interesting\n")
        h2 = base / "home2"
        p2 = run_hook(str(clean), h2)
        check(p2.stdout == "" and p2.stderr == "", "Logger emitted output on a clean session.")
        check(not (h2 / ".claude" / "logs" / "retro-triggers.jsonl").exists(),
              "Logger wrote a row for a session with no triggers. That dilutes the signal it exists "
              "to carry.")

        # Missing transcript: silent, exit 0. A SessionEnd crash must never surface to the user.
        h3 = base / "home3"
        p3 = run_hook("/nope/does-not-exist.jsonl", h3)
        check(p3.returncode == 0 and p3.stdout == "" and p3.stderr == "",
              f"Logger did not fail silently on a missing transcript: rc={p3.returncode} "
              f"stdout={p3.stdout!r} stderr={p3.stderr!r}")


def _tracked_files() -> set[str]:
    """Git-tracked paths, relative to ROOT. Empty if this is not a git checkout (then don't filter)."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, check=True)
        return set(out.stdout.split())
    except Exception:  # noqa: BLE001 — no git; caller falls back to "don't filter"
        return set()


def _declared_config_parts() -> set[str]:
    """Every TRACKED file in this config that must carry a contract.

    Discovered by globbing, never hand-listed, so a new rule or skill is caught the day it lands.
    Test files are excluded: they ARE the checks, so contracting them is circular. Untracked files
    are excluded too: a per-user overlay (e.g. a real connectors/<project>.json created from the
    example) is not tracked config and carries no contract — only the tracked template does.
    """
    parts: set[str] = {"CLAUDE.md", "settings.json"}
    for pattern in ("rules/*.md", "references/*.md", "connectors/*.json",
                    "bin/*.sh", "bin/*.py", "bin/*.zsh", ".githooks/*"):
        parts |= {str(p.relative_to(ROOT)) for p in ROOT.glob(pattern)
                  if p.is_file() and not p.name.endswith(".test.py")}
    for p in (ROOT / "hooks").glob("*"):
        if p.suffix in (".sh", ".py") and not p.name.endswith(".test.py"):
            parts.add(str(p.relative_to(ROOT)))
    for plugin in TRACKED_SKILL_PLUGINS:
        for p in (ROOT / "skills" / plugin / "skills").glob("*/SKILL.md"):
            parts.add(str(p.relative_to(ROOT)))
    tracked = _tracked_files()
    parts = {p for p in parts if p in tracked} if tracked else parts
    # An app under apps/ is one config part keyed by its directory (apps/<name>), discovered by
    # its tracked package.json, so a contract for it neither reads as an orphan nor goes unchecked.
    for pkg in ROOT.glob("apps/*/package.json"):
        if not tracked or str(pkg.relative_to(ROOT)) in tracked:
            parts.add(str(pkg.parent.relative_to(ROOT)))
    return parts


def check_metrics_log_detects_without_acting() -> None:
    """The metrics SessionEnd collector records, never acts: no stdout/stderr (unread output = noise
    or crash), exit 0, and no edits to config. Mirrors retro-trigger-log's detect-without-acting."""
    hook = ROOT / "hooks" / "config-metrics-log.sh"
    check(hook.exists() and os.access(hook, os.X_OK),
          "hooks/config-metrics-log.sh is missing or not executable.")
    if not hook.exists():
        return
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        home.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"transcript_path": "/nonexistent.jsonl", "session_id": "t",
                              "reason": "clear", "cwd": "/tmp/x"})
        p = subprocess.run(["bash", str(hook)], input=payload, capture_output=True,
                           text=True, env={**os.environ, "HOME": str(home)})
        check(p.returncode == 0, f"Collector exited nonzero ({p.returncode}); it must never fail a session.")
        check(p.stdout == "" and p.stderr == "",
              f"Collector emitted output; SessionEnd output is unread. stdout={p.stdout!r} stderr={p.stderr!r}")


def check_metrics_criticality_tags_name_real_parts() -> None:
    """Every part tagged in part_criticality.py must be a real file — no stale safety/stub tags."""
    pc = ROOT / "contracts" / "part_criticality.py"
    if not pc.exists():
        return
    ns: dict = {}
    exec(compile(pc.read_text(), str(pc), "exec"), ns)  # data-only module, safe to exec
    tagged = ns.get("ALL_TAGGED", set())
    missing = sorted(t for t in tagged if not (ROOT / t).exists())
    check(not missing, f"part_criticality.py tags parts that do not exist: {missing}")


def check_native_codex_shares_canonical_config() -> None:
    # The adapter's isolated TOML round-trip tests use Python 3.11+ (documented in native setup).
    result = run(["python3", str(ROOT / "bin" / "agent_runtime.test.py")])
    check(result.returncode == 0,
          f"Native Codex propagation/boundary suite failed:\n{result.stdout}\n{result.stderr}")
    claude = run(["python3", str(ROOT / "bin" / "claude-launch.test.py")])
    check(claude.returncode == 0,
          f"Native Claude instruction-policy suite failed:\n{claude.stdout}\n{claude.stderr}")


def check_codex_subscription_only_inference() -> None:
    review = (ROOT / "skills/sk/skills/ship-review/SKILL.md").read_text()
    for retired in ("https://api.openai.com", "https://generativelanguage.googleapis.com",
                    "pal `codereview`", "pal `challenge`", "~/.codex-work"):
        check(retired not in review, f"Review policy restored a retired API path: {retired}")
    check("Codex reviews have no API-billing exception" in review,
          "Reviews must state that Codex reviews stay on the subscription")
    shell = (ROOT / "dotfiles/zsh-work-codex.zsh").read_text()
    check('export CODEX_HOME="$HOME/.codex"' in shell and '.codex-work' not in shell,
          "Shell routing must select the subscription home, not the retired work API home")
    result = run(["python3", str(ROOT / "hooks/work-resource-guard.test.py")])
    check(result.returncode == 0,
          f"Subscription/resource guard regressions failed:\n{result.stdout}\n{result.stderr}")
    result = run(["python3", str(ROOT / "hooks/git-commit-guard.test.py")])
    check(result.returncode == 0,
          f"Git commit/push guard regressions failed:\n{result.stdout}\n{result.stderr}")


def check_secret_echo_guard_denies_printed_credentials_both_ways() -> None:
    settings_cmds = [h.get("command", "") for g in settings().get("hooks", {}).get("PreToolUse", [])
                     if g.get("matcher") == "Bash" for h in g.get("hooks", [])]
    check(any(c.endswith("hooks/secret-echo-guard.py") for c in settings_cmds),
          "settings.json must wire hooks/secret-echo-guard.py on the Bash PreToolUse matcher.")
    result = run(["python3", str(ROOT / "hooks/secret-echo-guard.test.py")])
    check(result.returncode == 0,
          f"Secret-echo guard regressions failed:\n{result.stdout}\n{result.stderr}")


def check_agent_setups_preserve_provider_choice() -> None:
    for command in (["python3", str(ROOT / "bin" / "agent_setup.test.py")],
                    ["bash", str(ROOT / "bin" / "superspeed-dispatch.test.sh")]):
        result = run(command)
        check(result.returncode == 0,
              f"Setup/dispatch regression failed:\n{result.stdout}\n{result.stderr}")
    policy = (ROOT / "rules" / "process.md").read_text()
    check("Inherit the current chat's model provider" in policy and
          "Which setup: Full Claude or Full Astra?" not in policy,
          "Shared process policy must inherit the actual chat provider without a redundant question")


def check_metrics_inventory_matches_contract_coverage() -> None:
    """The metrics aggregator must derive its parts list from config_contracts.py, never a hardcoded
    copy — so a newly-added part is always scored. Asserts parity: config-metrics.py._contracts_parts()
    == the scored subset of CONTRACTS keys."""
    agg = ROOT / "bin" / "config-metrics.py"
    contracts_py = ROOT / "contracts" / "config_contracts.py"
    if not agg.exists() or not contracts_py.exists():
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("config_metrics_probe", agg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    derived = set(mod._contracts_parts())
    cns: dict = {}
    exec(compile(contracts_py.read_text(), str(contracts_py), "exec"), cns)
    scored = {k for k in cns.get("CONTRACTS", {}) if k.endswith((".md", ".py", ".sh", ".json"))}
    check(derived == scored,
          f"Metrics inventory drifted from contract coverage. "
          f"only-in-aggregator={sorted(derived - scored)} only-in-contracts={sorted(scored - derived)}")


def check_contracts_every_config_part_declares_its_purpose() -> None:
    sys.path.insert(0, str(ROOT / "contracts"))
    try:
        from config_contracts import CONTRACTS  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        check(False, f"contracts/config_contracts.py could not be imported: {e}")
        return

    actual = _declared_config_parts()
    declared = set(CONTRACTS)

    for missing in sorted(actual - declared):
        check(False,
              f"{missing} exists but declares no contract. Add an entry to "
              f"contracts/config_contracts.py saying what it is for and what must stay true, or "
              f"delete the file. A part with no stated purpose is one a future edit can quietly gut.")
    for orphan in sorted(declared - actual):
        check(False,
              f"contracts/config_contracts.py declares {orphan}, which does not exist. A contract "
              f"for a deleted file is worse than none: it reads as coverage while checking nothing.")

    for path, entry in sorted(CONTRACTS.items()):
        check(bool(entry.get("mission", "").strip()),
              f"{path} has no mission. WRITE ONE: the outcome this part produces, one sentence, "
              f"naming who benefits and what changes for them. TEST it by reading a proposed diff "
              f"against it — if it cannot say \"this serves it\" or \"this trades against it\", "
              f"rewrite it. Format and examples: references/config-writing-standard.md.")
        check(bool(entry.get("purpose", "").strip()),
              f"{path} has an empty purpose. One line: what it produces or prevents.")
        crit = entry.get("criteria") or []
        check(bool(crit),
              f"{path} declares no criteria. State at least one property a change must preserve, "
              f"or the contract cannot catch a regression.")


# Each banned word stands in for a number or an imperative the author did not write. Matching the
# WORD and nothing else is deliberate: a guard that fires on topic or on sentence length cries wolf
# and gets switched off, which is what retired the old Bash security guard. If a legitimate string
# trips this, the fix is that string.
CONFIG_HEDGE_WORDS = (
    "should", "consider", "try to", "where possible", "as appropriate", "be careful",
    "be mindful", "generally", "typically", "ideally", "aim to", "make sure to think about",
)


def check_contracts_no_vague_language_in_contracts() -> None:
    sys.path.insert(0, str(ROOT / "contracts"))
    try:
        from config_contracts import CONTRACTS  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        check(False, f"contracts/config_contracts.py could not be imported: {e}")
        return

    for path, entry in sorted(CONTRACTS.items()):
        fields = [("mission", entry.get("mission", ""))]
        fields += [(f"criteria[{i}]", c) for i, c in enumerate(entry.get("criteria") or [])]
        for field, text in fields:
            low = text.lower()
            for word in CONFIG_HEDGE_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", low):
                    check(False,
                          f"{path} {field} contains \"{word}\". REPLACE IT with the number or the "
                          f"imperative it stands in for: \"prefer shorter\" becomes \"at most 40 "
                          f"words\"; \"be careful with X\" becomes \"DO X. DON'T Y.\" Banned list and "
                          f"worked examples: references/config-writing-standard.md.")
            # `prefer` is only vague when it names no threshold to prefer toward.
            if re.search(r"\bprefer\b", low) and not re.search(r"\d", text):
                check(False,
                      f"{path} {field} says \"prefer\" with no number. STATE THE THRESHOLD being "
                      f"preferred toward, or rewrite as a DO line naming the action.")


def check_commits_conventional_subject_enforced() -> None:
    hook = ROOT / ".githooks" / "commit-msg"
    check(hook.exists(), ".githooks/commit-msg is missing, so nothing enforces commit shape.")
    if not hook.exists():
        return
    check(os.access(hook, os.X_OK),
          "commit-msg is not executable, so it silently no-ops while reading as enforcement.")
    check(run(["git", "-C", str(ROOT), "config", "core.hooksPath"]).stdout.strip() == ".githooks",
          "core.hooksPath is not .githooks, so neither the commit-msg nor the secret hook runs. "
          "Fix: git -C ~/.claude config core.hooksPath .githooks")

    # Must ACCEPT: the shapes you write, plus the messages git generates itself.
    accept = [
        "fix(rules): make ui-conventions actually load",
        "feat: add the self-development-research skill",
        "chore(skills)!: drop the duplicate clone",
        "refactor(connectors/firebase): pin the target dir",
        "Merge branch 'main' into feature",
        'Revert "fix(rules): make ui-conventions load"',
        "fixup! fix(rules): tweak",
    ]
    # Must REJECT: the shapes that made `git log --oneline` unreadable.
    reject = [
        "updated some stuff",
        "Fix(rules): make it load",
        "fix(rules): Make ui-conventions actually load",
        "fix(rules): make ui-conventions actually load.",
        "wip",
        "fix: " + "a subject line far past the point of staying readable in a one line log " * 2,
        "",
    ]
    with tempfile.TemporaryDirectory() as td:
        msg = Path(td) / "COMMIT_EDITMSG"
        for subject, want_ok in [(s, True) for s in accept] + [(s, False) for s in reject]:
            msg.write_text(subject + "\n")
            got_ok = run(["bash", str(hook), str(msg)]).returncode == 0
            check(got_ok == want_ok,
                  f"commit-msg {'rejected' if want_ok else 'accepted'} {subject!r}. "
                  + ("A false rejection pushes you to --no-verify, which also skips the secret "
                     "gate." if want_ok else "This is the shape the hook exists to stop."))


def check_automatic_config_repair_lifecycle() -> None:
    """A clean start still queues repair; reporting never mutates owned or foreign work."""
    hook = ROOT / 'hooks/config-status.sh'
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        repo = home / '.claude'
        repo.mkdir()
        env = {**os.environ, 'HOME': str(home)}
        def git(*args):
            result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()
        def context():
            result = subprocess.run(['bash', str(hook)], env=env, capture_output=True,
                                    text=True, timeout=10)
            check(result.returncode == 0, 'SessionStart repair hook failed: ' + result.stderr)
            output = result.stdout.strip()
            if output.startswith('{'):
                return json.loads(output)['hookSpecificOutput']['additionalContext']
            return output
        check(context() == '', 'A missing config repository produced a repair directive')
        git('init', '-q', '-b', 'main')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (repo / 'note.txt').write_text('base\n')
        git('add', 'note.txt')
        git('commit', '-q', '-F', '/dev/null', '--allow-empty-message')
        git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        (repo / '.git/.last-config-fetch').touch()
        clean = context()
        check('rules/self-healing-config.md' in clean and 'manual skill invocation' in clean,
              'Clean sessions do not receive the automatic repair lifecycle')
        check('OUT OF SYNC' not in clean, 'Clean config incorrectly reported dirty')
        git('checkout', '-q', '-b', 'config-update/fixture')
        (repo / 'note.txt').write_text('repair\n')
        git('add', 'note.txt')
        git('commit', '-q', '-F', '/dev/null', '--allow-empty-message')
        git('checkout', '-q', 'main')
        (repo / 'note.txt').write_text('unrelated WIP\n')
        before = git('status', '--porcelain'), git('show-ref'), (repo / 'note.txt').read_text()
        pending = context()
        check('config-update/fixture' in pending and 'owner' in pending,
              'Pending repair lacks ownership reconciliation')
        check('OUT OF SYNC' in pending, 'Dirty config not reported')
        check(before == (git('status', '--porcelain'), git('show-ref'), (repo / 'note.txt').read_text()),
              'SessionStart mutated work or refs instead of reporting')
    policy = (ROOT / 'rules/self-healing-config.md').read_text()
    check('Standing authorization' in policy and 'Do not ask again' in policy,
          'Repair policy lost scoped standing authorization')
    for relative in ('rules/config-repo.md', 'references/parallelization.md',
                     'skills/sk/skills/claude-config-update/SKILL.md',
                     'skills/sk/skills/claude-config-sync/SKILL.md'):
        content = (ROOT / relative).read_text().lower()
        for stale in ('never auto-applies', 'auto-analyse, never auto-optimize',
                      'offer to commit + push', 'still preview and confirm as normal'):
            check(stale not in content, relative + ' restored obsolete repair gate: ' + stale)


def check_branch_cleanup_closes_owned_inventory() -> None:
    """Guard the instruction boundary; these checks do not delete any real refs."""
    process = (ROOT / 'rules/process.md').read_text()
    cleanup = (ROOT / 'skills/sk/skills/meta-cleanup-worktrees/SKILL.md').read_text()
    check('created or adopted by this task' in process and 'not a' in process
          and 'repo-wide purge' in process and 'zero owned refs or paths' in process,
          'Task closure lost owned-scope or disposition accounting')
    check('left untouched and unlisted' not in cleanup,
          'Cleanup hides unresolved unique branches again')
    check(all(text in cleanup for text in ('every BRANCH-ONLY local head',
          'unique-commit', 'owner or unknown ownership', 'reason and next action',
          'every local head', 'before/after inventory')),
          'Cleanup inventory omits unresolved unique refs or final reconciliation')
    check(all(text in cleanup for text in ('explicitly authorizes needed merges',
          'full unique diff', 'required checks before',
          'cleanup request alone', 'never authorizes merging')),
          'Cleanup no longer distinguishes an authorized merge from branch disposal')
    check(all(text in cleanup for text in ('authority covering that draft',
          'entire unique diff', 'zero unexplained still-needed changes',
          'verify that recovery can be read back', 'every local-only commit')),
          'Superseded draft retirement lost authority, review or recovery proof')
    check(all(text in cleanup for text in ('reuse that authorization', 'private external bundle',
          'all reachable history', 'restoring it into a temporary local repository',
          'restored tip and object integrity', 'never authorizes publishing history')),
          'Recovery migration lost existing authority, private preservation or restoration proof')
    check(all(text in cleanup for text in ('current, main, default, detached HEAD',
          'backup/recovery refs', 'explicit keep-list', 'no process except',
          'Conductor-managed workspace', 'OWN opt-in question',
          'repo-wide remote purge')),
          'Closure weakened protected refs, live work, Conductor or remote-write safeguards')


def check_node24_shell_runtime():
    result = run(["/usr/bin/python3", str(ROOT / "bin/node-runtime.test.py")])
    check(result.returncode == 0, "Node shell fixtures failed: " + result.stdout + result.stderr)


def check_session_performance_and_capacity() -> None:
    for script in ("session-performance.test.py", "local-capacity.test.py"):
        result = run(["/usr/bin/python3", str(ROOT / "bin" / script)])
        check(result.returncode == 0, script + ": " + result.stdout + result.stderr)
    rule = (ROOT / "rules/self-healing-config.md").read_text()
    check("Every task reaches hand-back" in rule and "references/session-performance.md" in rule,
          "After-run analysis is not routed from the always-on task lifecycle")


def check_screenshot_report_preserves_evidence() -> None:
    result = run(["/usr/bin/python3", str(ROOT / "bin" / "screenshot-report.test.py")])
    check(result.returncode == 0, "Screenshot report regression: " + result.stdout + result.stderr)


def check_dashboard_runtime_preserves_completion() -> None:
    package = ROOT / "bin"
    for name in ("workflow-dashboard.py", "workflow-dashboard.html", "workflow-dashboard.test.py"):
        check((package / name).is_file(), f"Missing dashboard runtime file: {name}")
    result = run(["/usr/bin/python3", str(package / "workflow-dashboard.test.py")])
    check(result.returncode == 0, "Dashboard runtime regression: " + result.stdout + result.stderr)


def check_mockup_shell_preserves_reviewed_deep_links() -> None:
    shell = ROOT / "bin" / "mockup-shell.html"
    check(shell.is_file(), "Missing mockup shell runtime")
    source = shell.read_text()
    required = ("readShellRoute", "stateExists", "applyShellRoute", "new URLSearchParams(location.hash.replace",
                "currentFlashSelector", "currentState && currentState.flashSelector", "def.flashSelector",
                "presentation-highlight", "dashboard-mockup-route")
    check(all(token in source for token in required), "Mockup route/highlight contract is incomplete")
    check(all(token not in source for token in ("function deepDiff", "function renderDiff", 'id="history-diff"')),
          "Design history exposes implementation field-diff controls")
    shared = (ROOT / "bin" / "presentation-shell.html").read_text()
    check("connect-src 'none'" in shared and "setCollapsed" in shared and "setTheme" in shared,
          "Shared frame lost offline policy, sidebar or theme behavior")
    check(all(token not in shared for token in ('id="copy-spec"', 'id="save-html"', '<textarea')),
          "Shared design viewer exposes implementation or export controls")
    decision = (ROOT / "bin" / "decision-artifact.html").read_text()
    check(all(token in decision for token in ("feedback=SPEC.feedback===true", 'id="generate-copy"', "navigator.clipboard.writeText(text)", "snapshot===revision")),
          "Proposal response must be explicit, fresh and copied in one action")
    check(all(token not in decision for token in ("position:fixed", "generate-response", "copy-response", "data-count", "data-select-all")),
          "Proposal cards restored covering chrome or separate response actions")
    for adapter in ("mockup-build.py", "design-board.py", "decision-artifact.py"):
        check("compose(" in (ROOT / "bin" / adapter).read_text(), f"{adapter} bypasses the shared frame")



# The coverage ratchet: a criterion with no check, or a check with no criterion, is a bug.
# --------------------------------------------------------------------------------------

def main() -> int:
    module = sys.modules[__name__]
    checks = {n[len("check_"):]: fn for n, fn in inspect.getmembers(module, inspect.isfunction)
              if n.startswith("check_")}
    expected = {cid.replace("-", "_") for cid in CRITERION_IDS}

    missing = sorted(expected - set(checks))
    orphan = sorted(set(checks) - expected)
    if missing:
        print("COVERAGE FAILURE — criteria with no check:", file=sys.stderr)
        for m in missing:
            print(f"  - {m.replace('_', '-')}  (add def check_{m}())", file=sys.stderr)
    if orphan:
        print("COVERAGE FAILURE — checks with no criterion:", file=sys.stderr)
        for o in orphan:
            print(f"  - check_{o}  (add it to CRITERIA, or delete it)", file=sys.stderr)
    if missing or orphan:
        return 1

    failed_ids: list[str] = []
    for cid, statement in CRITERIA:
        before = len(FAILURES)
        try:
            checks[cid.replace("-", "_")]()
        except Exception as e:  # noqa: BLE001
            FAILURES.append(f"check for {cid} raised {type(e).__name__}: {e}")
        if len(FAILURES) > before:
            failed_ids.append(cid)
            print(f"FAIL  {cid}\n      {statement}", file=sys.stderr)
            for msg in FAILURES[before:]:
                print(f"      -> {msg}", file=sys.stderr)
        else:
            print(f"PASS  {cid}")

    print(f"\n{len(CRITERIA) - len(failed_ids)} pass / {len(failed_ids)} fail "
          f"({len(CRITERIA)} criteria)")
    return 1 if failed_ids else 0


if __name__ == "__main__":
    sys.exit(main())
