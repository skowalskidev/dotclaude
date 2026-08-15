"""How Simon's own skills are named, as data.

The shape is `<group>-<what-it-does>`. Group first, because the group is what you filter the slash
menu on: typing `/sk:claude-config` narrows to 4 instead of scrolling all 16.

Why the tail stays long
-----------------------
Two naming rules, and for a skill they point the same way.

**Intention-revealing names** (Martin, Clean Code ch.2): the name says why the thing exists and what
it does, so nobody opens the implementation to find out. `eyeball` fails that on its own.

**Length proportional to scope** (Pike, Notes on Programming in C; the same rule in Uncle Bob's
"the length of a variable name should be proportional to its scope"): a loop index is `i` because
its declaration is one line away. A skill sits in a global menu with no surrounding context at all,
so it earns a long evocative name.

That second rule is also the limit: a shared helper used in rich local context can be generic. Long
is not automatically better. Clarity is the goal and length is the consequence, not the target. The
full statement lives in `references/code-best-practices.md`, which owns naming for the whole config.

Adding a group is a one-line edit here. `hooks/config-contract.test.py` reads this file and fails
when a skill matches nothing, so a loosely-named skill is caught the day it lands rather than
quietly widening the flat list this was built to fix.
"""

# prefix -> what belongs in it. The trailing hyphen is part of the prefix.
PREFIXES: dict[str, str] = {
    "claude-config-": "Changes ~/.claude itself: its rules, skills, contracts or sync.",
    "work-": "Starting or running a piece of work: scoping, planning, executing, parallelising.",
    "plan-": "Researching and deciding BEFORE building: gathering evidence, comparing options, ranking an approach.",
    "ship-": "Getting a change out and reporting on it: PR, review, the end report.",
    "test-": "Verifying something behaves: driving the UI, pacing a human through a flow.",
    "maintenance-code-": "Improving code that already exists: cleanup, performance.",
    "meta-": "Reporting on Simon's own work rather than on a change: what he did over a period, "
             "written for a person to read or say.",
}

# Skills allowed to carry no prefix. An exception has to be declared here rather than just happening.
# Keep this near-empty: every entry is a skill that will not be found by filtering the menu.
UNPREFIXED: set[str] = {
    # Already reads verb-first, and belongs to no group with a second member.
    "setup-connectors",
}
