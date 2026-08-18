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
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_CONFIG_ROOT", Path.home() / ".claude"))

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
     "settings.json still denies Read on every crown-jewel credential path, and Edit/Write on the "
     "key directories. This is the whole mechanical control now that the pattern guard is retired, "
     "so it may not quietly shrink. Path matchers cannot false-positive on a command that merely "
     "MENTIONS a path, which is the failure mode that retired the hook."),
    ("secrets-retired-guard-leaves-no-dangling-claim",
     "Nothing in the config claims the retired security-guard.py still runs. A doc promising "
     "protection that no longer exists is worse than an admitted gap, because it stops anyone "
     "looking."),

    # --- The task-intake gate: what you asked for on 2026-08-03 ---------------------
    ("intake-arms-on-a-task-opening",
     "A prompt that opens substantive work arms the gate and injects the intake protocol, so Claude "
     "proposes the skills and the plan before starting."),
    ("intake-blocks-runaway-fanout",
     "While the gate is armed, Agent / Task / Workflow are DENIED. Sub-processes keep running after "
     "a question is asked, so the stop has to be mechanical, not a polite instruction."),
    ("intake-answering-disarms",
     "An AskUserQuestion result disarms the gate, and nothing else does. That is what makes the "
     "block correspond to a real answer from you rather than to Claude deciding it has asked."),
    ("intake-respects-standing-authorization",
     "A prompt that hands the session over unattended ('I'll be asleep', 'don't ask me') does NOT "
     "arm the gate. Stopping to ask is the one thing you asked not to happen in that case."),
    ("intake-stays-quiet-on-follow-ups",
     "Short replies and continuations ('yes', 'option 2', 'go ahead') do not re-arm. A gate that "
     "fires every turn is a gate you learn to ignore."),
    ("intake-has-an-off-switch",
     "CLAUDE_INTAKE_GATE=off disables arming AND blocking. A gate with no escape hatch deadlocks "
     "the first headless run it meets."),

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
    ("security-bash-guard-blocks-reads-without-false-positives",
     "The Bash crown-jewel guard blocks a literal secret read AND stays silent on ordinary work — "
     "including the four commands that got its predecessor retired. A guard that annoys gets "
     "switched off, and a guard that is off protects nothing, so the must-not-fire half is the "
     "criterion, not a nicety."),
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
    p = run([str(ROOT / "hooks" / "task-intake.sh"), mode], input=json.dumps(payload), env=e)
    return (p.stdout or "") + (p.stderr or "")


def clear_markers() -> None:
    d = ROOT / ".session-intake"
    if d.is_dir():
        for f in d.glob("*.armed"):
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
    """The pattern guard is retired, so these path rules are the entire mechanical control."""
    deny = settings().get("permissions", {}).get("deny", [])
    required = [
        "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.gnupg/**)", "Read(~/.config/gcloud/**)",
        "Read(~/Library/Keychains/**)", "Read(~/.claude/.credentials.json)",
        "Read(~/.config/op/**)", "Read(~/.config/firebase-keys/**)",
        "Read(**/id_rsa)", "Read(**/id_ed25519)", "Read(**/personal-keys.env)",
        "Edit(~/.ssh/**)", "Edit(~/.aws/**)", "Edit(~/.gnupg/**)",
        "Write(~/.ssh/**)", "Write(~/.aws/**)", "Write(~/.gnupg/**)",
    ]
    for rule in required:
        check(rule in deny,
              f"settings.json no longer denies {rule}. With security-guard.py retired this list is "
              f"the whole mechanical control over credential files — it may not quietly shrink.")


def check_secrets_retired_guard_leaves_no_dangling_claim() -> None:
    """A doc promising protection that no longer runs is worse than an admitted gap."""
    live = {c for c in hook_commands()}
    check(not any("security-guard.py" in c for c in live),
          "settings.json still wires security-guard.py, which has been removed from hooks/.")
    check(not (ROOT / "hooks" / "security-guard.py").exists(),
          "hooks/security-guard.py is back on disk but the config says it was retired. Pick one.")

    # Any prose still describing it as live. A line explaining that it was RETIRED is the point of
    # the change and must not trip this, so those are allowed by keyword.
    RETIRED_CONTEXT = re.compile(r"retir|remov|delet|no longer|was\b|former|history|restor", re.I)
    for sub in ("rules", "references"):
        for p in (ROOT / sub).glob("*.md"):
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if "security-guard" not in line:
                    continue
                check(RETIRED_CONTEXT.search(line) is not None,
                      f"{sub}/{p.name}:{i} still describes security-guard as live: {line.strip()[:90]}")


def check_intake_arms_on_a_task_opening() -> None:
    clear_markers()
    out = intake("submit", {"session_id": "contract-a", "prompt": "refactor the billing module"})
    check("TASK INTAKE GATE" in out,
          "A task-opening prompt did not arm the intake gate or inject the protocol.")
    check((ROOT / ".session-intake" / "contract-a.armed").exists(),
          "The intake gate injected its protocol but wrote no marker, so nothing is actually blocked.")
    clear_markers()


def check_intake_blocks_runaway_fanout() -> None:
    clear_markers()
    intake("submit", {"session_id": "contract-b", "prompt": "build a new dashboard page"})
    for tool in ("Agent", "Task", "Workflow"):
        out = intake("guard", {"session_id": "contract-b", "tool_name": tool})
        check('"deny"' in out or "deny" in out.lower(),
              f"{tool} was NOT denied while the intake gate was armed. Sub-processes outlive the "
              f"question, so this block is the only thing that actually stops a runaway fan-out.")
    out = intake("guard", {"session_id": "contract-b", "tool_name": "Read"})
    check(out.strip() == "",
          "The intake gate blocked Read. It must only gate the fan-out tools, never ordinary work.")
    clear_markers()


def check_intake_answering_disarms() -> None:
    clear_markers()
    intake("submit", {"session_id": "contract-c", "prompt": "migrate the database schema"})
    check((ROOT / ".session-intake" / "contract-c.armed").exists(), "gate did not arm for the disarm test")
    intake("answered", {"session_id": "contract-c", "tool_name": "AskUserQuestion"})
    check(not (ROOT / ".session-intake" / "contract-c.armed").exists(),
          "AskUserQuestion did not disarm the intake gate, so Claude stays blocked after the user answers.")
    out = intake("guard", {"session_id": "contract-c", "tool_name": "Agent"})
    check(out.strip() == "", "Agent is still denied after the gate was disarmed.")
    clear_markers()


def check_intake_respects_standing_authorization() -> None:
    clear_markers()
    for prompt in (
        "Clean up the whole codebase. I will be sleeping so answer all of your questions by "
        "browsing online and make the best decision yourself, there should be no loose ends left.",
        "Refactor the auth layer and centralize the duplicated validation. Do not ask me anything, "
        "just make the calls yourself and get it finished tonight please.",
        "Please implement the new pricing page and proceed without asking me to confirm any of the "
        "intermediate steps along the way, I trust your judgement on all of it.",
    ):
        out = intake("submit", {"session_id": "contract-d", "prompt": prompt})
        check(out.strip() == "",
              f"The intake gate armed despite standing authorization to run unattended. Stopping to "
              f"ask is the one thing that prompt rules out. Prompt: {prompt[:70]}...")
    clear_markers()


def check_intake_stays_quiet_on_follow_ups() -> None:
    clear_markers()
    for prompt in ("yes", "go ahead", "option 2", "continue", "lgtm", "2", "sounds good",
                   "ship it", "thanks", "no", "ok", "approved"):
        out = intake("submit", {"session_id": "contract-e", "prompt": prompt})
        check(out.strip() == "",
              f"The intake gate re-armed on the follow-up {prompt!r}. It must fire on a task "
              f"opening, not on every turn, or it becomes noise you learn to ignore.")
    clear_markers()


def check_intake_has_an_off_switch() -> None:
    clear_markers()
    out = intake("submit", {"session_id": "contract-f", "prompt": "refactor everything now"},
                 env={"CLAUDE_INTAKE_GATE": "off"})
    check(out.strip() == "", "CLAUDE_INTAKE_GATE=off did not stop the intake gate arming.")
    (ROOT / ".session-intake").mkdir(exist_ok=True)
    (ROOT / ".session-intake" / "contract-f.armed").touch()
    out = intake("guard", {"session_id": "contract-f", "tool_name": "Agent"},
                 env={"CLAUDE_INTAKE_GATE": "off"})
    check(out.strip() == "",
          "CLAUDE_INTAKE_GATE=off did not stop the intake gate BLOCKING. An off-switch that only "
          "half works still deadlocks a headless run.")
    clear_markers()


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


def check_security_bash_guard_blocks_reads_without_false_positives() -> None:
    """Runs the guard's own both-directions suite, so there is one home for the cases."""
    suite = ROOT / "hooks" / "crown-jewel-read-guard.test.py"
    check(suite.exists(), f"{suite.name} is missing — the guard would be unproven")
    if not suite.exists():
        return
    result = subprocess.run(
        [sys.executable, str(suite)], capture_output=True, text=True, timeout=60
    )
    check(
        result.returncode == 0,
        "crown-jewel-read-guard.test.py failed:\n" + (result.stdout or result.stderr).strip(),
    )
    # The suite passing is not enough on its own: it must still be TESTING both directions.
    src = suite.read_text()
    check("MUST_NOT_FIRE" in src and src.count('("') >= 20,
          "the guard suite lost its must-not-fire half, which is the half that keeps it usable")
    for fp in ["cat .npmrc", "nvm use", "~/.gnupg is denied", "settings.json"]:
        check(fp in src, f"the historical false positive {fp!r} is no longer a test case")


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
        dirty.write_text("noise\nBlocked: work resource\ncrown-jewel read denied\n")
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
                check(row.get("guard_denials") == 1 and row.get("crown_denials") == 1,
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
                    "bin/*.sh", "bin/*.py", ".githooks/*"):
        parts |= {str(p.relative_to(ROOT)) for p in ROOT.glob(pattern)
                  if p.is_file() and not p.name.endswith(".test.py")}
    for p in (ROOT / "hooks").glob("*"):
        if p.suffix in (".sh", ".py") and not p.name.endswith(".test.py"):
            parts.add(str(p.relative_to(ROOT)))
    for plugin in TRACKED_SKILL_PLUGINS:
        for p in (ROOT / "skills" / plugin / "skills").glob("*/SKILL.md"):
            parts.add(str(p.relative_to(ROOT)))
    tracked = _tracked_files()
    return {p for p in parts if p in tracked} if tracked else parts


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
