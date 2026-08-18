"""Which part of the config should fire for a given request.

Why this exists
---------------
A skill that never fires fails silently. Nothing errors, nothing warns; the work just gets done the
long way and the skill looks unneeded. The documented root cause is almost always the same: the
`description` is written in the config's language instead of the user's. If Simon says "review my
code" and the description says "audit software artefacts", the connection is never made.

So the test is on ROUTING, not on behaviour. Routing is the deterministic half of an agent, which is
exactly the half a normal unit test can hold. Running the actual task to see which skill fires would
cost a model call per scenario and prove less.

Cost: zero model calls, pure string matching, runs with the rest of the suite in milliseconds.

How a scenario works
--------------------
`phrase` is how Simon would really ask, in his words. The check is that the phrase's content words
all appear in the target's description, so the description is guaranteed to speak his language.

`expect` is the skill folder name under skills/<plugin>/skills/.

`also_matches` lists other skills allowed to match the same phrase. Overlap is not automatically a
bug (a review and a cleanup both care about "code"), but UNDECLARED overlap is: it means two skills
compete for the same request and the model picks whichever looks closest, which may be the wrong one.

Coverage is ratcheted: every skill must appear as `expect` in at least one scenario, so a new skill
cannot land without someone stating how it gets reached.
"""

SCENARIOS: list[dict] = [
    # --- Repo and code -------------------------------------------------------------
    {"phrase": "clean up the repo", "expect": "maintenance-code-cleanup-repo"},
    {"phrase": "find dead code", "expect": "maintenance-code-cleanup-repo"},
    {"phrase": "the README is out of date", "expect": "maintenance-code-cleanup-repo"},

    # --- Frontend ------------------------------------------------------------------
    {"phrase": "check my UI change in the browser", "expect": "test-eyeball"},
    {"phrase": "go eyeball", "expect": "test-eyeball"},

    # --- Testing with Simon --------------------------------------------------------
    {"phrase": "let's test this together", "expect": "test-copilot"},
    {"phrase": "walk me through testing", "expect": "test-copilot"},
    {"phrase": "my tests pass but the app is broken", "expect": "test-copilot"},

    # --- Copilot agile build -------------------------------------------------------
    {"phrase": "let's do this in an agile loop", "expect": "work-copilot-agile-build"},
    {"phrase": "preview it with fake data first", "expect": "work-copilot-agile-build"},
    {"phrase": "copilot this with me", "expect": "work-copilot-agile-build",
     "also_matches": ["test-copilot"]},

    # --- Performance ---------------------------------------------------------------
    {"phrase": "make it faster", "expect": "maintenance-code-optimize-app"},
    {"phrase": "run Lighthouse", "expect": "maintenance-code-optimize-app"},
    {"phrase": "the page is slow", "expect": "maintenance-code-optimize-app"},

    # --- Journey -------------------------------------------------------------------
    # Folded into review-all on 2026-08-05: it was a separate slash command crowding the menu, and
    # a journey pass belongs on the same run as the code review anyway. The method now lives in
    # references/user-journey-review.md, which review-all, eyeball and copilot-testing all read.
    {"phrase": "walk the whole flow", "expect": "ship-review"},
    {"phrase": "walk through this as a user", "expect": "ship-review"},

    # --- Deciding whether to build at all -------------------------------------------
    # Sits UPSTREAM of every building skill: it runs before there is a plan, and its output is a
    # verdict rather than work. Overlap with the proving skill below is declared, not accidental --
    # "can the platform do it" and "should we do it" are different questions about the same ticket.
    {"phrase": "does this make sense to build", "expect": "work-does-this-make-sense-to-build"},
    {"phrase": "does this ticket make sense", "expect": "work-does-this-make-sense-to-build"},
    {"phrase": "is this worth building", "expect": "work-does-this-make-sense-to-build"},

    # --- Research before building ---------------------------------------------------
    # Answers a FACTUAL question with ranked, cited, corroborated evidence; upstream of a build.
    # Distinct from work-does-this-make-sense (judges a specific proposal/ticket, not an open question).
    {"phrase": "research this and compare the options", "expect": "plan-research"},
    {"phrase": "deep dive on this", "expect": "plan-research"},
    {"phrase": "what is the best or most popular way to do this", "expect": "plan-research"},
    {"phrase": "is this claim true", "expect": "plan-research"},
    {"phrase": "corroborate this", "expect": "plan-research"},
    {"phrase": "should we build this", "expect": "work-does-this-make-sense-to-build"},

    # --- Proving before building ---------------------------------------------------
    {"phrase": "let me test this before I build it", "expect": "work-platform-anchor-test-feature-poc-works-before-building"},

    # --- Shipping ------------------------------------------------------------------
    {"phrase": "creating a PR", "expect": "ship-pr"},
    {"phrase": "code review", "expect": "ship-review"},

    # --- Handling review feedback on an existing PR --------------------------------
    # Downstream of ship-review: that one PRODUCES the comments, this one CLEARS them. Distinct verb
    # ("resolve"/"address") and always on an existing PR, so it never collides with opening one.
    {"phrase": "resolve the PR comments", "expect": "ship-resolve-pr-comments"},
    {"phrase": "address the review feedback", "expect": "ship-resolve-pr-comments"},
    {"phrase": "handle the reviewer's comments", "expect": "ship-resolve-pr-comments"},
    {"phrase": "reply to and resolve the threads", "expect": "ship-resolve-pr-comments"},

    # --- Reporting at the end, and making the report true ----------------------------
    # Runs on work that is already done, which is what separates it from review-all (judges quality)
    # and does-this-make-sense-to-build (judges whether to start).
    #
    # The second group is the half that edits code. Simon asks for it in plan language rather than
    # report language ("does this match the plan"), so those phrases have to be in the description
    # too or the skill only ever gets reached for the read-only half it used to be.
    {"phrase": "end report", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "what did you build", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "summarize what this does", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "does this match the plan", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "make sure it does what we planned", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "check it against the acceptance criteria", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "close the gaps", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    #
    # ship-check-merge-readiness — assembling a PR + its stack onto current master and driving every
    # open thread to a decisive ship-ready verdict. Distinct phrases (stacked-PR assembly, ship-to-prod-
    # as-is) so they don't collide with the single-PR ship-* skills.
    {"phrase": "check that these stacked PRs merge together onto master", "expect": "ship-check-merge-readiness"},
    {"phrase": "are these open PRs ready to ship to prod as-is", "expect": "ship-check-merge-readiness"},
    #
    # The third group is the test phase. A verdict's evidence is a committed test rather than a
    # file:line, so he reaches for the skill in test language too. Neither phrase appears verbatim in
    # any other skill's description, so neither needs an `also_matches`.
    {"phrase": "write tests for the acceptance criteria", "expect": "ship-report-and-ensure-correct-user-system-journey"},
    {"phrase": "prove it with tests", "expect": "ship-report-and-ensure-correct-user-system-journey"},

    # --- Reporting on Simon himself, not on a change ---------------------------------
    # Adjacent to the group above and deliberately separate: that one judges ONE change against its
    # plan, this one narrates a PERSON'S week to a room. Both answer "what did I do", so the split
    # is the object (a diff vs a period), and the phrases below never say "this" for that reason.
    {"phrase": "standup report", "expect": "meta-report-standup-weekly"},
    {"phrase": "write my standup", "expect": "meta-report-standup-weekly"},
    {"phrase": "monday morning standup", "expect": "meta-report-standup-weekly"},
    {"phrase": "what did I do last week", "expect": "meta-report-standup-weekly"},
    {"phrase": "clean up merged worktrees", "expect": "meta-cleanup-worktrees"},
    {"phrase": "remove done worktrees and branches", "expect": "meta-cleanup-worktrees"},
    {"phrase": "tidy up my worktrees", "expect": "meta-cleanup-worktrees"},
    {"phrase": "delete merged branches", "expect": "meta-cleanup-worktrees"},
    {"phrase": "which sessions can I archive", "expect": "meta-cleanup-worktrees"},
    {"phrase": "start here", "expect": "meta-dotclaude-copilot-start-here-for-any-task"},
    {"phrase": "what should I use for this", "expect": "meta-dotclaude-copilot-start-here-for-any-task"},
    {"phrase": "run this the right way", "expect": "meta-dotclaude-copilot-start-here-for-any-task"},
    {"phrase": "just handle this", "expect": "meta-dotclaude-copilot-start-here-for-any-task"},
    {"phrase": "which skills for this task", "expect": "meta-dotclaude-copilot-start-here-for-any-task"},

    # --- The config itself ---------------------------------------------------------
    {"phrase": "sync my config", "expect": "claude-config-sync"},
    {"phrase": "commit my config", "expect": "claude-config-sync"},
    {"phrase": "make this correction permanent", "expect": "claude-config-update"},
    {"phrase": "add this rule to my UI conventions", "expect": "claude-config-update"},
    # Any config CHANGE routes here, not just a correction — this is the pair that was missing when
    # "create a new skill" got hand-built instead of run through the skill.
    {"phrase": "create a new skill", "expect": "claude-config-update"},
    {"phrase": "change my config", "expect": "claude-config-update"},
    {"phrase": "what am I missing", "expect": "claude-config-self-development-research"},
    {"phrase": "is my Claude setup current", "expect": "claude-config-self-development-research"},

    # --- Parallel execution ----------------------------------------------------------
    {"phrase": "run this in parallel", "expect": "work-superspeed"},
    {"phrase": "fan this out", "expect": "work-superspeed"},
    {"phrase": "split this across sessions", "expect": "work-superspeed"},
    {"phrase": "hyperspeed", "expect": "work-hyperspeed", "also_matches": ["work-warpspeed"]},
    {"phrase": "paste the parts into separate sessions", "expect": "work-hyperspeed"},
    {"phrase": "hand-parallelise this", "expect": "work-hyperspeed"},
    {"phrase": "split this into paste-and-forget parts", "expect": "work-hyperspeed"},
    {"phrase": "warpspeed", "expect": "work-warpspeed", "also_matches": ["work-hyperspeed"]},
    {"phrase": "run the parts on different VMs", "expect": "work-warpspeed"},
    {"phrase": "keep a single plan", "expect": "plan-stable-persistent-dynamic-complete-full-plan"},
    {"phrase": "stop making me re-read the plan", "expect": "plan-stable-persistent-dynamic-complete-full-plan"},
    {"phrase": "just update the plan", "expect": "plan-stable-persistent-dynamic-complete-full-plan"},
    {"phrase": "one source of truth plan", "expect": "plan-stable-persistent-dynamic-complete-full-plan"},
    {"phrase": "stay in plan mode until I say go", "expect": "plan-stable-persistent-dynamic-complete-full-plan"},
    {"phrase": "what did we waste", "expect": "claude-config-self-optimize-analysis-after-run"},
    {"phrase": "why was that slow", "expect": "claude-config-self-optimize-analysis-after-run"},
    {"phrase": "analyse the run", "expect": "claude-config-self-optimize-analysis-after-run"},

    # --- Environment isolation -----------------------------------------------------
    {"phrase": "isolate my environment", "expect": "work-isolate-environment"},
    {"phrase": "give this session its own ports", "expect": "work-isolate-environment"},
    {"phrase": "run two stacks at once", "expect": "work-isolate-environment"},

    # --- Before/after mockups ----------------------------------------------------------
    {"phrase": "mock this up", "expect": "ship-mockup-before-after"},
    {"phrase": "show me before and after", "expect": "ship-mockup-before-after"},
    {"phrase": "what will this look like", "expect": "ship-mockup-before-after"},
    {"phrase": "I want to see it before you build it", "expect": "ship-mockup-before-after"},
    {"phrase": "implement the mockup", "expect": "ship-mockup-before-after"},
    {"phrase": "the screen doesn't match the mockup", "expect": "ship-mockup-before-after"},

    # --- Phone preview ---------------------------------------------------------------
    {"phrase": "preview this on my phone", "expect": "work-preview-on-phone"},
    {"phrase": "test on mobile", "expect": "work-preview-on-phone"},
    {"phrase": "open this on my iPhone", "expect": "work-preview-on-phone"},
    {"phrase": "serve this over Tailscale", "expect": "work-preview-on-phone"},

    # --- Connectors ----------------------------------------------------------------
    {"phrase": "not enough permissions", "expect": "setup-connectors"},

    # --- Interactive before/after decision artifact --------------------------------
    {"phrase": "make it selectable so I can pick and comment", "expect": "work-ask-reply-in-full-before-after-artifact"},
    {"phrase": "give me an interactive before and after artifact", "expect": "work-ask-reply-in-full-before-after-artifact"},

    # No scenario for your work-skills plugin's timesheet skill (e.g. sk-work): it lives in the untracked work/ directory and
    # is outside this suite's scope. Its routing is not asserted here.

    # --- The harness ---------------------------------------------------------------
    # Deliberately broad: this one is meant to catch substantive work generally, so it carries no
    # narrow trigger phrase and overlap with everything else is expected rather than a defect.
    {"phrase": "substantive or multi-step task", "expect": "work-full-detailed-workflow",
     "also_matches": ["maintenance-code-cleanup-repo", "test-copilot", "work-platform-anchor-test-feature-poc-works-before-building"]},
]


# Which hooks must fire for a given tool call. Fully deterministic: the matcher is a regex in
# settings.json and the tool name is a string, so this is a plain unit test with no judgement in it.
# It catches the class of bug that cost a whole session once already: a matcher that looks right and
# silently never matches the tool the session actually uses (`mcp__conductor__AskUserQuestion`).
HOOK_ROUTING: list[dict] = [
    {"event": "PreToolUse", "tool": "Bash",
     "expect": ["work-resource-guard.sh", "crown-jewel-read-guard.py",
                "git-commit-guard.py", "background-process-guard.py"]},
    {"event": "PreToolUse", "tool": "mcp__firebase__firestore_get_documents",
     "expect": ["work-resource-guard.sh"]},
    # chrome-devtools tools fire the mcp__.* work guard AND the browser-launch guard.
    {"event": "PreToolUse", "tool": "mcp__chrome-devtools__navigate_page",
     "expect": ["work-resource-guard.sh", "browser-launch-guard.py"]},
    {"event": "PreToolUse", "tool": "Agent", "expect": ["task-intake.sh"]},
    {"event": "PreToolUse", "tool": "Workflow", "expect": ["task-intake.sh"]},
    {"event": "PreToolUse", "tool": "Read", "expect": []},
    # The config edit-guard fires only on the edit tools, never on Bash or Read.
    {"event": "PreToolUse", "tool": "Edit", "expect": ["config-edit-guard.py"]},
    {"event": "PreToolUse", "tool": "Write", "expect": ["config-edit-guard.py"]},
    {"event": "PostToolUse", "tool": "AskUserQuestion", "expect": ["task-intake.sh"]},
    # The variant that broke it. Conductor sessions only ever expose this form.
    {"event": "PostToolUse", "tool": "mcp__conductor__AskUserQuestion",
     "expect": ["task-intake.sh"]},
    {"event": "PostToolUse", "tool": "Edit", "expect": []},
    {"event": "SessionEnd", "tool": None, "expect": ["retro-trigger-log.sh"]},
    # Matcher-less like SessionStart, so every UserPromptSubmit hook fires on every prompt.
    {"event": "UserPromptSubmit", "tool": None,
     "expect": ["task-intake.sh", "intent-ledger.sh"]},
    # Stop is the one event where a wrong matcher is unrecoverable from inside the session it hits,
    # so it is pinned even though it currently has a single hook.
    {"event": "Stop", "tool": None, "expect": ["intent-ledger.sh"]},
    # SessionStart hooks carry no matcher, so every one of them fires on every session. Pinned
    # because the list grows, and a hook added to the wrong event silently never runs.
    {"event": "SessionStart", "tool": None,
     "expect": ["config-status.sh", "session-connectors.sh", "orphan-worker-sweep.sh",
                "port-registry-sweep.sh", "session-identity.sh"]},
]
