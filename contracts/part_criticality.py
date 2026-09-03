"""Which config parts are EXPECTED to score low, and why — so the metrics self-analysis
never mistakes a warranted-dormant part for a defect.

Why this exists
---------------
The metrics system (bin/config-metrics.py) scores every part by usage + error rate and flags the
dead / underused ones for a trigger fix. Two classes of part are dormant BY DESIGN, and flagging
them would be noise that trains Simon to ignore the report:

- SAFETY — a guard, a security rule, a provenance check, a compliance gate. A guard you seldom trip
  is doing its job; pruning rarely-used safety content measurably degrades alignment
  (arxiv 2402.05162). Its value is in the rare event, so low usage is warranted, never a defect.
- STUB — a part deliberately not built yet (its SKILL.md says so). It is a placeholder awaiting
  implementation, not a dead part; it graduates to normal scoring once built.

The metrics aggregator reads this file and reports SAFETY parts as "healthy-by-design" and STUB
parts as "planned", and proposes NO fix/removal for either on low usage alone.

Keys are the same repo-relative paths config_contracts.py uses, so the two files line up and the
suite can assert every key here names a real, contract-covered part (no stale tags).

This is DATA, not logic — like skill_naming.py. Add a part here only when its low usage is genuinely
expected; do not use it to silence a part that is simply broken.
"""

# Parts whose low or zero usage is warranted by design — safety / security / provenance / compliance.
# The metrics report marks these "healthy-by-design" and never nominates them for a trigger fix or
# removal on low usage. (High DENIAL rates on legitimate work are still surfaced — that is the
# guard misfiring, a real finding; only the low-USAGE dead/underused verdict is suppressed here.)
SAFETY: set[str] = {
    # Security / provenance rules and the guards that back them
    "rules/security.md",
    "hooks/work-resource-guard.sh",
    "hooks/config-edit-guard.py",
    "hooks/background-process-guard.py",
    "hooks/browser-launch-guard.py",
    "hooks/git-commit-guard.py",
    # The intake gate is a compliance guard: its "denials" are the gate arming by design, not misfires.
    "hooks/task-intake.sh",
    # Compliance / correctness gates — low fire count, high cost-of-absence
    "hooks/config-contract.test.py",
    "contracts/config_contracts.py",
    "contracts/routing_scenarios.py",
    "contracts/skill_naming.py",
    "contracts/part_criticality.py",
    ".githooks/commit-msg",
    ".githooks/pre-commit",
}

# Parts deliberately not built yet — placeholders awaiting implementation. Reported "planned",
# never "dead". Remove the entry when the part is actually built.
STUB: set[str] = {
    "skills/sk/skills/work-warpspeed/SKILL.md",
}


def criticality(part_path: str) -> str | None:
    """Return 'safety', 'stub', or None for a repo-relative part path."""
    if part_path in SAFETY:
        return "safety"
    if part_path in STUB:
        return "stub"
    return None


# Every tagged part must be a real file the contract suite already covers. A parity check in
# hooks/config-contract.test.py asserts this, so a renamed/removed part can't leave a stale tag.
ALL_TAGGED: set[str] = SAFETY | STUB
