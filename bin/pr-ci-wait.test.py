#!/usr/bin/env python3
"""Offline regression tests for bin/pr-ci-wait.py, with gh stubbed. Standard library only."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "pr-ci-wait.py"
FAILS = []
SHA = "a" * 40

# The stub answers `gh pr view` and `gh run list` from a scenario file: the Nth call of each kind
# gets the Nth response, the last one repeating. A response is {"out": <json>} or {"rc", "err"}.
STUB = r'''#!/usr/bin/env python3
import json, os, sys
kind = "pr" if sys.argv[1:3] == ["pr", "view"] else "runs" if sys.argv[1:3] == ["run", "list"] else "other"
scenario = json.load(open(os.environ["STUB_SCENARIO"]))
state_path = os.environ["STUB_SCENARIO"] + ".count"
counts = json.load(open(state_path)) if os.path.exists(state_path) else {}
n = counts.get(kind, 0)
counts[kind] = n + 1
json.dump(counts, open(state_path, "w"))
with open(os.environ["STUB_SCENARIO"] + ".calls", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
seq = scenario.get(kind) or [{"rc": 1, "err": "unexpected gh call: " + " ".join(sys.argv[1:])}]
r = seq[min(n, len(seq) - 1)]
if "out" in r:
    print(json.dumps(r["out"]))
sys.stderr.write(r.get("err", ""))
sys.exit(r.get("rc", 0))
'''


def pr(rollup, mergeable="MERGEABLE", state="CLEAN", head=SHA):
    return {"out": {"mergeable": mergeable, "mergeStateStatus": state, "headRefOid": head,
                    "statusCheckRollup": rollup}}


def check(name, status="COMPLETED", conclusion="SUCCESS", wf="ci", t="2026-11-12T10:00:00Z"):
    return {"__typename": "CheckRun", "name": name, "workflowName": wf, "status": status,
            "conclusion": conclusion if status == "COMPLETED" else "", "completedAt": t, "startedAt": t}


def runs(*statuses):
    return {"out": [{"databaseId": i + 1, "status": s, "conclusion": "", "workflowName": f"wf{i}",
                     "name": f"wf{i}"} for i, s in enumerate(statuses)]}


CASES = 0


def run_case(name, scenario, args, want_rc, want_text, want_run_sha=None):
    global CASES
    CASES += 1
    with tempfile.TemporaryDirectory() as d:
        stub = Path(d) / "gh"
        stub.write_text(STUB)
        stub.chmod(0o755)
        sc = Path(d) / "scenario.json"
        sc.write_text(json.dumps(scenario))
        env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "STUB_SCENARIO": str(sc),
               "PR_CI_WAIT_RETRY_SEC": "0"}
        p = subprocess.run([sys.executable, str(SCRIPT), "--repo", "owner/name", "--pr", "7",
                            "--poll-sec", "0", *args], capture_output=True, text=True, env=env, timeout=60)
        out = p.stdout + p.stderr
        if p.returncode != want_rc or want_text not in out:
            FAILS.append(f"{name}: rc={p.returncode} (want {want_rc}), want '{want_text}' in:\n{out}")
        if want_run_sha:
            calls_path = Path(str(sc) + ".calls")
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
            shas = [c[c.index("--commit") + 1] for c in calls if c[:2] == ["run", "list"]]
            if not shas or any(s != want_run_sha for s in shas):
                FAILS.append(f"{name}: gh run list --commit got {shas}, want only {want_run_sha}")


def main() -> int:
    green = [check("preflight"), check("test")]
    run_case("conflicting PR exits 3 with the instruction",
             {"pr": [pr([], mergeable="CONFLICTING", state="DIRTY")]}, [], 3, "Merge the base in and push")
    run_case("DIRTY merge state alone counts as a conflict",
             {"pr": [pr([], mergeable="UNKNOWN", state="DIRTY")]}, [], 3, "CONFLICTING")
    run_case("no run for the sha within the start window exits 4 with the merge state",
             {"pr": [pr([])], "runs": [{"out": []}]}, ["--start-min", "0"], 4, "mergeStateStatus=CLEAN")
    run_case("all green exits 0 with counts",
             {"pr": [pr(green)], "runs": [runs("completed")]}, [], 0, "2 checks (2 success)")
    run_case("one failure exits 1 and names it",
             {"pr": [pr([check("preflight"), check("test", conclusion="FAILURE")])],
              "runs": [runs("completed")]}, [], 1, "failing: ci / test")
    run_case("'no checks reported' is never done: waits, then passes once checks appear",
             {"pr": [pr([]), pr([]), pr(green)], "runs": [{"out": []}, {"out": []}, runs("completed")]},
             ["--start-min", "5"], 0, "PASSED")
    run_case("'no checks reported' with a run already started keeps waiting to its own timeout",
             {"pr": [pr([])], "runs": [runs("in_progress")]}, ["--timeout-min", "0.002"], 6, "TIMEOUT")
    run_case("gh 503 then success retries and passes",
             {"pr": [{"rc": 1, "err": "HTTP 503: Service Unavailable"}, pr(green)],
              "runs": [runs("completed")]}, [], 0, "transient error")
    run_case("a non-transient gh error exits 2 without retrying",
             {"pr": [{"rc": 1, "err": "HTTP 404: Not Found"}, pr(green)]}, [], 2, "404")
    run_case("pending checks past the timeout exit 6",
             {"pr": [pr([check("test", status="IN_PROGRESS")])], "runs": [runs("in_progress")]},
             ["--timeout-min", "0.002"], 6, "1 pending")
    run_case("a cancelled run superseded by a passing rerun passes",
             {"pr": [pr([check("test", conclusion="CANCELLED", t="2026-11-12T09:00:00Z"),
                         check("test", t="2026-11-12T10:00:00Z")])], "runs": [runs("completed")]},
             [], 0, "1 checks (1 success)")
    run_case("a required check not yet registered holds the wait",
             {"pr": [pr([check("meta")])], "runs": [runs("completed")]},
             ["--require", "preflight", "--timeout-min", "0.002"], 6, "required check not seen: preflight")
    run_case("a head that moved off --sha exits 5",
             {"pr": [pr(green, head="b" * 40)]}, ["--sha", SHA], 5, "HEAD MOVED")
    head = "91ae5c6c1e96" + "0" * 28
    run_case("an abbreviated --sha that prefixes the head passes and reads runs by the full sha",
             {"pr": [pr(green, head=head)], "runs": [runs("completed")]}, ["--sha", "91AE5C6C1"], 0,
             "PASSED 91ae5c6c1e96", want_run_sha=head)
    run_case("an abbreviated --sha that does not prefix the head exits 5",
             {"pr": [pr(green, head=head)]}, ["--sha", "91ae5c6c2"], 5, "HEAD MOVED")
    run_case("a non-hex --sha is a usage error before any gh call",
             {}, ["--sha", "main"], 2, "7-40 hex characters")
    run_case("a --sha shorter than 7 characters is a usage error",
             {}, ["--sha", "91ae5c"], 2, "7-40 hex characters")
    for f in FAILS:
        print("FAIL", f)
    print(f"pr-ci-wait: {CASES - len(FAILS)}/{CASES} cases pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
