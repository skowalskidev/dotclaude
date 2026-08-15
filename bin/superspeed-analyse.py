#!/usr/bin/env python3
"""superspeed-analyse — turn one run's logs into waste metrics and concrete next actions.

The point is not a dashboard. Every metric below exists because it maps to a change you can make to
the NEXT partition. A number with no action attached is noise, so each one prints its action.

Usage: python3 ~/.claude/bin/superspeed-analyse.py <run-dir>
Writes <run-dir>/analysis.json and prints a report.
"""
import json
import os
import statistics as st
import sys
from pathlib import Path

RUN = sys.argv[1] if len(sys.argv) > 1 else "."


def jload(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def read(p, default=""):
    try:
        with open(p) as f:
            return f.read().strip()
    except Exception:
        return default


# A DONE.md line is a changed FILE only if it looks like a repo path. Every other line is prose.
#
# This used to take every non-blank, non-heading line, which was true enough when DONE.md was a bare
# list. It stopped being true the moment slices were asked to quote their acceptance criteria and
# their before/after: one run parsed 180 "files" of which 4 were paths, and the two it then reported
# as ownership leaks were both quoted sentences, one slice counted against itself. A metric that is
# 98% noise is worse than an absent one, because it reads as a measurement and gets acted on.
#
# Deliberately strict rather than clever: a real path has a directory separator, no spaces, and a
# source-file extension. Anything else is dropped and COUNTED, so the next time DONE.md changes shape
# the discrepancy is visible instead of silently becoming a plausible number.
PATH_EXTS = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java", ".rb",
    ".json", ".md", ".mdx", ".yml", ".yaml", ".sh", ".sql", ".css", ".scss", ".html", ".vue", ".svelte",
)


# A heading changes what the lines under it MEAN, so a parser that ignores headings misreads any
# structured report. Slices now write sections like "## Not touched" and "## Files reviewed, no change
# needed" (a direct consequence of asking them to verify their acceptance criteria), and a path listed
# there is the slice saying it did NOT write that file. Counting those produced a confident
# "ownership leak" naming two slices for a file one of them had explicitly declined to touch.
NEGATING_HEADINGS = ("not touched", "no change", "not changed", "unchanged", "reviewed",
                     "asserts another", "did not", "untouched", "out of scope", "left alone")


def _verify_exit(path):
    """Exit code the dispatcher recorded for this slice's own scoped check, or None.

    None means the spec declared no verify (or an older run predates the field) — which is a
    different thing from a check that ran and failed, and the two must not be conflated: one is
    a missing guarantee, the other is a caught defect.
    """
    txt = read(path, "")
    if not txt:
        return None
    for line in reversed(txt.splitlines()):
        if line.startswith("[dispatcher] verify exit="):
            try:
                return int(line.rsplit("=", 1)[1])
            except ValueError:
                return None
    return None


def changed_paths(done):
    """Lines of a DONE.md that are actually file paths this slice WROTE."""
    paths, dropped, negated = [], 0, False
    for line in done.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # A new heading re-opens the question: is what follows a claim of work, or a disclaimer?
            negated = any(h in stripped.lower() for h in NEGATING_HEADINGS)
            continue
        if negated:
            continue
        cand = stripped.lstrip("-*").strip().strip("`").rstrip(":,.")
        if "/" in cand and " " not in cand and cand.endswith(PATH_EXTS):
            paths.append(cand)
        else:
            dropped += 1
    changed_paths.dropped = getattr(changed_paths, "dropped", 0) + dropped
    return paths


spec = jload(f"{RUN}/spec.json", {}) or {}
run = jload(f"{RUN}/run.json", {}) or {}
reconcile = jload(f"{RUN}/reconcile.json", {}) or {}

slices = []
for s in spec.get("slices", []):
    name = s.get("name")
    sd = f"{RUN}/slices/{name}"
    timing = jload(f"{sd}/timing.json", {}) or {}
    result = jload(f"{sd}/result.json", {}) or {}
    usage = result.get("usage") or {}
    done = read(f"{sd}/DONE.md")
    slices.append({
        "name": name,
        "wall": timing.get("wall", 0),
        # start/end/pid feed the standing parallelism check near the end of this file.
        "start": timing.get("start"),
        "end": timing.get("end"),
        "pid": timing.get("pid"),
        "rc": timing.get("rc"),
        "status": read(f"{sd}/status", "unknown"),
        "api_s": (result.get("duration_api_ms") or 0) / 1000,
        "turns": result.get("num_turns"),
        "cost": result.get("total_cost_usd") or 0,
        "out_tokens": usage.get("output_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        # Load-bearing. Without it _forensics() below gets None on every slice and the whole
        # local-attribution section prints "(no transcript found)" while the transcripts sit on
        # disk — which is how it silently produced nothing for four runs' worth of slices.
        "session_id": result.get("session_id"),
        # Exit code of the slice's own scoped check, re-run by the dispatcher after the slice
        # exited. None when the spec declared no verify. See section 8b.
        "verify_exit": _verify_exit(f"{sd}/verify.txt"),
        "owns": s.get("owns", []),
        "reads": s.get("reads", []),
        "changed": changed_paths(done),
        "blocked": os.path.exists(f"{sd}/BLOCKED.md"),
    })

if not slices:
    print(f"no slices found under {RUN}")
    sys.exit(1)

walls = [s["wall"] for s in slices if s["wall"]]
slowest = max(walls) if walls else 0
fanout = run.get("fanout_seconds", slowest)
findings = []
# Declared here, not at the INSTRUMENTATION GAPS section below, because sections above that
# point also record blind spots (8b does). Initialising it at the point of first REPORT rather
# than first USE is how a gap raised earlier becomes a NameError instead of a finding.
gaps = []

print(f"\n=== superspeed run: {RUN}")
print(f"task: {spec.get('task','(none)')}")
print(f"slices: {len(slices)}   fan-out wall: {fanout}s   total cost: ${sum(s['cost'] for s in slices):.2f}\n")

print(f"{'slice':18} {'wall':>6} {'api':>6} {'turns':>6} {'cost$':>7} {'cacheWR':>9} {'cacheRD':>10} {'status':>16}")
print("-" * 88)
for s in sorted(slices, key=lambda x: -x["wall"]):
    print(f"{s['name']:18} {s['wall']:>5}s {s['api_s']:>5.0f}s {str(s['turns']):>6} {s['cost']:>7.2f} "
          f"{s['cache_write']:>9} {s['cache_read']:>10} {s['status']:>16}")

# 1. IDLE CAPACITY — the dominant waste in every run measured so far.
idle = sum(slowest - s["wall"] for s in slices)
capacity = slowest * len(slices)
idle_pct = (idle / capacity * 100) if capacity else 0
print(f"\n--- WASTE ---")
print(f"idle capacity      : {idle}s of {capacity}s ({idle_pct:.0f}%) sat unused waiting on the slowest slice")
if idle_pct >= 40:
    findings.append({
        "metric": "idle_capacity", "value": f"{idle_pct:.0f}%", "severity": "high",
        "action": f"Re-cut the partition. '{max(slices, key=lambda x: x['wall'])['name']}' took "
                  f"{slowest}s while others finished far earlier. Split the slowest slice, or merge "
                  f"the fastest ones. Fan-out wall-clock is the SLOWEST slice, never the average.",
    })

# 2. IMBALANCE — the actionable form of the same thing.
if len(walls) >= 3:
    med = st.median(walls)
    ratio = slowest / med if med else 1
    print(f"imbalance ratio    : {ratio:.2f}x  (slowest {slowest}s vs median {med:.0f}s)")
    if ratio >= 1.5:
        findings.append({
            "metric": "imbalance", "value": f"{ratio:.2f}x", "severity": "high",
            "action": "Slices differ by more than 1.5x. Size them by expected work, not by file count. "
                      "A slice touching one large module is not equivalent to one touching three small ones.",
        })

# 3. CACHE SHARING — separate sessions in ONE directory share a prefix; worktrees do not.
tot_wr = sum(s["cache_write"] for s in slices)
tot_rd = sum(s["cache_read"] for s in slices)
ratio_rd = (tot_rd / tot_wr) if tot_wr else 0
print(f"cache read:write   : {ratio_rd:.2f}  (write {tot_wr:,} / read {tot_rd:,})")
if ratio_rd < 1.0 and tot_wr > 50000:
    findings.append({
        "metric": "cold_cache", "value": f"{ratio_rd:.2f}", "severity": "medium",
        "action": "Slices are re-reading context rather than sharing it. The prompt cache is scoped to "
                  "the working DIRECTORY, so slices in one directory share a prefix and slices in "
                  "separate worktrees never do. If these ran in worktrees, move them into one "
                  "directory with disjoint file ownership instead.",
    })

# 4. THROTTLE / BACKOFF — wall the slice spent NOT talking to the model.
for s in slices:
    stall = s["wall"] - s["api_s"]
    if s["wall"] >= 30 and stall > 0.5 * s["wall"]:
        findings.append({
            "metric": "backoff", "value": f"{stall:.0f}s of {s['wall']}s in '{s['name']}'",
            "severity": "medium",
            "action": "Over half this slice's wall-clock was not inference: rate-limit backoff or local "
                      "contention. Check /usage, and reduce concurrent slices if the account is loaded.",
        })

# 5. ACHIEVED CONCURRENCY — did fanning out actually overlap anything?
api_sum = sum(s["api_s"] for s in slices)
conc = api_sum / fanout if fanout else 0
print(f"achieved concurrency: {conc:.2f}x  (sum of API time {api_sum:.0f}s inside {fanout}s wall)")
if conc < 1.5 and len(slices) >= 3:
    findings.append({
        "metric": "low_concurrency", "value": f"{conc:.2f}x", "severity": "high",
        "action": f"{len(slices)} slices produced only {conc:.2f}x overlap. They are serialising. Check "
                  "for a shared lock, one slice blocking on another's file, or account-level throttling.",
    })

# 6. OWNERSHIP LEAKS — two slices writing the same file is the expensive failure.
owners = {}
for s in slices:
    for f in s["changed"]:
        owners.setdefault(f, []).append(s["name"])
leaks = {f: n for f, n in owners.items() if len(n) > 1}
if leaks:
    print(f"ownership leaks    : {len(leaks)} file(s) written by more than one slice")
    findings.append({
        "metric": "ownership_leak", "value": f"{len(leaks)} files", "severity": "high",
        "action": "Two slices wrote the same file: " + "; ".join(f"{f} <- {','.join(n)}" for f, n in list(leaks.items())[:5]) +
                  ". Later writes silently clobber earlier ones. Put the shared file in exactly one "
                  "slice's `owns`, and name it in every other slice's `forbid`.",
    })

# 7. DUPLICATED READ CONTEXT — the same file declared as read-only context in many slices.
read_counts = {}
for s in slices:
    for f in s["reads"]:
        read_counts[f] = read_counts.get(f, 0) + 1
dupes = {f: c for f, c in read_counts.items() if c >= 3}
if dupes:
    print(f"duplicated reads   : {len(dupes)} file(s) loaded by 3+ slices")
    findings.append({
        "metric": "duplicated_reads", "value": f"{len(dupes)} files", "severity": "low",
        "action": "These files are re-read by most slices: " + ", ".join(list(dupes)[:5]) +
                  ". Each read is paid once per slice. If it is a shared contract, freeze it in the "
                  "base commit BEFORE fanning out and summarise it in the prompt instead of having "
                  "every slice read it.",
    })

# 8. REWORK — but only the kind a better spec would have prevented.
#
# `files_fixed` used to be a bare list, so three causes collapsed into one number and got one
# prescription. Measured 2026-08-08: run-1's rework was genuine slice error, where "tighten the
# accept line" was the right advice; run-2's was the ask changing after dispatch, where the same
# advice was wrong because the slices were correct. Identical in the data, opposite responses.
# So the cause is declared per file, and only `slice` earns a finding.
rec_entries = reconcile.get("files_fixed", [])
rec_files = [e if isinstance(e, str) else e.get("file", "") for e in rec_entries]
causes = {e.get("file"): e.get("cause") for e in rec_entries if isinstance(e, dict)}
slice_fault = [f for f in rec_files if f in owners and causes.get(f) == "slice"]
late_scope = [f for f in rec_files if causes.get(f) == "late_scope"]
recon_fault = [f for f in rec_files if causes.get(f) == "reconciler"]
# A bare string carries no cause. Reported as a gap rather than guessed at — guessing is what
# produced the wrong prescription in the first place.
undeclared_cause = [f for f in rec_files if f in owners and f not in causes]

if rec_files:
    print(f"reconcile rework   : {len(slice_fault)} slice-fault, {len(late_scope)} late-scope, "
          f"{len(recon_fault)} reconciler's own, of {len(rec_files)} fixed files")
if slice_fault:
    findings.append({
        "metric": "rework", "value": f"{len(slice_fault)} files", "severity": "medium",
        "action": "A slice got these wrong and the reconciler fixed them: " + ", ".join(slice_fault[:5]) +
                  ". Tighten those slices' `accept` criteria so the slice catches it itself, or hand "
                  "the file to the reconciler from the start.",
    })
if recon_fault:
    findings.append({
        "metric": "reconciler_error", "value": f"{len(recon_fault)} files", "severity": "low",
        "action": "The reconciler broke these itself: " + ", ".join(recon_fault[:5]) + ". No slice "
                  "could have caught it — a reconciler's edits are unverified until the whole-tree "
                  "gate. Re-run the affected slice's own `verify` after editing its files.",
    })
if undeclared_cause:
    gaps.append(("a `cause` on each reconcile.json entry",
                 "whether the reconciler fixed a file because a slice got it wrong, because the ask "
                 "changed after dispatch, or because the reconciler broke it. Without it all three "
                 "get one prescription and two of them are wrong."))

# 8b. VERIFICATION — did each slice's own scoped check actually pass?
#
# This is the cause of rework, where section 8 above is only its symptom. A slice that skipped its
# check and a slice that passed it write identical DONE.md files, so without this the reconciler
# discovers the difference by running the gate, having already paid for the slice.
checked = [s for s in slices if s["verify_exit"] is not None]
if checked:
    passed = [s for s in checked if s["verify_exit"] == 0]
    print(f"slices verified    : {len(passed)} of {len(slices)} passed their own scoped check")
    failed = [s for s in checked if s["verify_exit"] != 0]
    if failed:
        findings.append({
            "metric": "verify_failed", "value": ", ".join(s["name"] for s in failed), "severity": "high",
            "action": "These slices' own checks FAILED and the work was handed over anyway: " +
                      ", ".join(f"{s['name']} (exit {s['verify_exit']})" for s in failed) +
                      ". Read slices/<name>/verify.txt before any diff — it names the defect "
                      "directly, which is cheaper than inferring it from the gate.",
        })
    unverified_rework = [s["name"] for s in failed if any(f in s["owns"] for f in rec_files)]
    if unverified_rework:
        findings.append({
            "metric": "unverified_rework", "value": ", ".join(unverified_rework), "severity": "high",
            "action": "These slices failed their own `verify` AND the reconciler then had to fix "
                      "their files: " + ", ".join(unverified_rework) + ". The slice could have "
                      "caught this itself and did not. Check the verify command is allowlisted and "
                      "scoped to what the slice owns — an unrunnable check is indistinguishable "
                      "from a passing one in DONE.md.",
        })
else:
    gaps.append(("slices/*/verify.txt",
                 "whether each slice's own check ran and passed. Without it a slice that inspected "
                 "its work and a slice that ran it are indistinguishable, and rework has no "
                 "attributable cause. Give every slice a `verify` in the spec."))

# 9. DEAD OR BLOCKED SLICES.
bad = [s for s in slices if s["status"] != "ok"]
if bad:
    print(f"slices needing attention: {', '.join(s['name'] + '=' + s['status'] for s in bad)}")
    findings.append({
        "metric": "slice_failures", "value": f"{len(bad)}/{len(slices)}", "severity": "high",
        "action": "Slices did not finish cleanly: " + ", ".join(f"{s['name']} ({s['status']})" for s in bad) +
                  ". A 'no-done-marker' with rc=0 is anthropics/claude-code#74761, where `claude -p` "
                  "exits 0 mid-task. Never trust the exit code; the DONE.md artifact is the evidence.",
    })

# 10. WAS FAN-OUT WORTH IT AT ALL?
if fanout and slowest and len(slices) >= 2:
    serial_estimate = sum(s["wall"] for s in slices)
    print(f"fan-out benefit    : {serial_estimate}s serial estimate vs {fanout}s actual "
          f"({serial_estimate / fanout:.2f}x)")
    if serial_estimate / fanout < 1.4:
        findings.append({
            "metric": "fanout_not_worth_it", "value": f"{serial_estimate / fanout:.2f}x", "severity": "high",
            "action": "Fanning out bought under 1.4x against doing these slices one after another. The "
                      "measured in-session penalty is only ~33s, so at this size a single session is "
                      "simpler and cheaper. Do not fan out work this small.",
        })

# 11. INSTRUMENTATION GAPS — the log's own blind spots.
# A question this analysis could not answer is a log field that should exist next time. Without this
# check the instrumentation never improves, because a missing field looks exactly like a clean run.
# (`gaps` is initialised up beside `findings` — earlier sections raise gaps too.)
# Report what the path filter threw away. A run where almost every DONE.md line is prose is fine and
# expected; a run where NO line parsed as a path means DONE.md changed shape and every file-based
# metric below is now measuring nothing. Saying the number is what makes that difference visible.
_kept = sum(len(s["changed"]) for s in slices)
_dropped = getattr(changed_paths, "dropped", 0)
if _kept == 0 and _dropped > 0:
    gaps.append(("a parseable file list in DONE.md",
                 f"{_dropped} lines were read and none looked like a repo path, so ownership leaks and "
                 "reconcile rework measured nothing this run. Either the slices stopped listing paths "
                 "or the format moved; fix the prompt or `changed_paths`, not the metric."))
if not reconcile:
    gaps.append(("reconcile.json", "how long reconcile took, what it fixed, and whether the gate passed. "
                                   "Without it, rework and the true end-to-end time are invisible, and "
                                   "reconcile is where this design's cost actually lives."))
if not any(s["changed"] for s in slices):
    gaps.append(("slices/*/DONE.md", "the list of files each slice actually changed. Without it, "
                                     "ownership leaks cannot be detected at all."))
if not any(s["api_s"] for s in slices):
    gaps.append(("duration_api_ms in result.json", "inference time per slice. Without it, backoff and "
                                                   "local CPU contention are indistinguishable from slow work."))
if not os.path.exists(f"{RUN}/load.start"):
    gaps.append(("load.start / load.end", "machine load either side of the run. A run measured under "
                                          "load 20 on 8 cores is not comparable to one under load 3."))
if not any(s["reads"] for s in slices):
    gaps.append(("`reads` in the spec", "the read-only context each slice loads. Without it, duplicated "
                                        "context reads cannot be found and the same file is silently "
                                        "paid for N times."))
if not any(s.get("turns") for s in slices):
    gaps.append(("num_turns in result.json", "turn count per slice. A slice with many turns and little "
                                             "output is thrashing on a missing fact, which is invisible "
                                             "from wall-clock alone."))
# TREND — one prior analysis is enough for a delta, and the delta is the point.
#
# This said "fewer than two prior analyses to compare against" with a prior sitting in the adjacent
# directory, and had no comparison code even so. Both halves were the same mistake: a check
# reporting a blind spot it did not have, on a threshold that never fired.
_parent = os.path.dirname(RUN) or "."
PRIOR = None
if os.path.isdir(_parent):
    for d in sorted(os.listdir(_parent), reverse=True):
        cand = os.path.join(_parent, d, "analysis.json")
        if os.path.abspath(os.path.dirname(cand)) == os.path.abspath(RUN):
            continue
        if os.path.exists(cand):
            PRIOR = jload(cand)
            break
if not PRIOR:
    gaps.append(("a prior analysis.json to compare against",
                 "this is the first analysed run in its directory, so there is no trend. Keep the run "
                 "directories rather than deleting them."))

if gaps:
    print(f"\n--- INSTRUMENTATION GAPS ({len(gaps)}) ---")
    for what, why in gaps:
        print(f"  missing {what}")
        print(f"    -> {why}")
    findings.append({
        "metric": "instrumentation_gap", "value": f"{len(gaps)} missing", "severity": "low",
        "action": "This run could not be fully analysed. Add: " + "; ".join(w for w, _ in gaps) +
                  ". Each one is a question the next analysis will otherwise fail to answer.",
    })

# ---- PARALLELISM CHECK (standing) ----------------------------------------------------------------

#
# `achieved_concurrency` above divides summed API time by fan-out wall. Good proxy, but it cannot
# prove the PROCESSES coexisted: API time excludes local tool execution and is self-reported by each
# slice's own result JSON. Three signals here, the last unfakeable because it is observed from
# outside the thing being measured:
#
#   wall_overlap   sum(slice wall) / fan-out wall.  ~N = parallel, ~1 = serialised.
#   pairwise       do the [start,end] intervals actually intersect? Catches a run where slice 2
#                  started only after slice 1 finished, which any averaged ratio hides.
#   sampled        how many `claude -p` processes were ALIVE each second.
#
# Motivation: anthropics/claude-code#53922 documents a server-side concurrency limiter that refuses
# later sessions with "Server is temporarily limiting requests (not your usage limit)" even at low
# quota use. If that fires, slices serialise or die and no existing metric says so.
diag = {}
_t = [(s["name"], s.get("start"), s.get("end")) for s in slices
      if s.get("start") is not None and s.get("end") is not None]
print("\n--- PARALLELISM ---")
if not _t:
    print("  no per-slice start/end recorded; re-run with the instrumented dispatcher")
else:
    wall_sum = sum(e - s for _, s, e in _t)
    overlap = wall_sum / fanout if fanout else 0
    pairs = [(a[0], b[0]) for i, a in enumerate(_t) for b in _t[i + 1:]
             if min(a[2], b[2]) - max(a[1], b[1]) > 0]
    possible = len(_t) * (len(_t) - 1) // 2
    diag = {"wall_overlap_ratio": round(overlap, 2),
            "overlapping_pairs": len(pairs), "possible_pairs": possible}
    print(f"  wall overlap      : {overlap:.2f}x  (sum of slice wall {wall_sum}s inside {fanout}s)")
    print(f"  overlapping pairs : {len(pairs)} of {possible}")

    samples = []
    try:
        with open(f"{RUN}/concurrency.log") as fh:
            samples = [int(ln.split()[1]) for ln in fh if len(ln.split()) == 2]
    except OSError:
        pass
    if samples:
        peak, mean = max(samples), sum(samples) / len(samples)
        diag.update({"sampled_peak": peak, "sampled_mean": round(mean, 2),
                     "samples": len(samples)})
        print(f"  live processes    : peak {peak}, mean {mean:.1f} over {len(samples)} samples")
    else:
        print("  live processes    : not sampled")

    limited = [s["name"] for s in slices
               if "temporarily limiting" in read(f"{RUN}/slices/{s['name']}/stderr.txt")
               or "rate limit" in read(f"{RUN}/slices/{s['name']}/stderr.txt").lower()]
    if limited:
        diag["rate_limited_slices"] = limited
        findings.append({
            "metric": "rate_limited", "value": f"{len(limited)}/{len(slices)}", "severity": "high",
            "action": f"Slices hit a rate/concurrency limit: {', '.join(limited)}. "
                      f"anthropics/claude-code#53922 — the limiter refuses later sessions regardless "
                      f"of quota headroom. Cut fewer, larger slices rather than retrying.",
        })

    # Verdict. The sampler wins when present: it is the only signal not self-reported.
    n = len(_t)
    if samples and max(samples) < 2 and n >= 2:
        verdict = "SERIALISED - never more than one live session. The parallelism is not happening."
    elif overlap < 1.5 and n >= 3:
        verdict = f"SERIALISED - {n} slices produced only {overlap:.2f}x wall overlap."
    elif len(pairs) < possible:
        verdict = f"PARTIAL - only {len(pairs)} of {possible} slice pairs overlapped in time."
    else:
        verdict = f"PARALLEL - all {possible} pairs overlapped, {overlap:.2f}x wall overlap."
    diag["verdict"] = verdict
    print(f"  VERDICT           : {verdict}")
    if verdict.startswith(("SERIALISED", "PARTIAL")):
        findings.append({
            "metric": "parallelism", "value": verdict.split(" -")[0], "severity": "high",
            "action": "Slices are not running concurrently, so this design pays the multi-session "
                      "quota cost for none of the speed. Quota is pooled per account, so N sessions "
                      "burn it N times faster whether or not they overlap. Diagnose before running "
                      "another: check for a concurrency limiter, and compare against one session.",
        })
    print("  (standing check; a regression here would otherwise be silent)")

# ---- SLICE FORENSICS: what each worker actually DID between API calls ----------------------------
# Measured 2026-08-07: `claude -p` workers genuinely overlap. Six workers did 5.62x the API work in
# 1.67x the wall time, and every slice pair intersected in time (15/15). So the dispatch mechanism is
# not the bottleneck, and every remaining suspect is LOCAL work: what a worker runs between calls.
#
# The metric that matters is local_ms = wall - api. It is the time a worker is alive and burning zero
# tokens. The usual cause is a slice running something far wider than it owns, the whole test suite
# being the classic, and no aggregate number ever shows that. This reads each slice's transcript and
# names the command.
#
# The transcript is already on disk: result.json carries session_id, and Claude Code writes
# ~/.claude/projects/<mangled-cwd>/<session_id>.jsonl. Nothing extra is captured at run time, so this
# also works on runs that already finished.
def _transcript(session_id):
    if not session_id:
        return None
    hits = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def _forensics(session_id):
    """Per-slice tool usage with durations, paired tool_use -> tool_result by id."""
    p = _transcript(session_id)
    if not p:
        return None
    import datetime
    started, out = {}, {"tools": {}, "bash": [], "files": set(), "writes": set(),
                       "turns": 0, "refused": []}
    for line in p.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = d.get("timestamp")
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None
        except (ValueError, AttributeError):
            t = None
        msg = d.get("message") or {}
        content = msg.get("content")
        if d.get("type") == "assistant":
            out["turns"] += 1
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                started[b.get("id")] = (b.get("name"), b.get("input") or {}, t)
                inp = b.get("input") or {}
                for k in ("file_path", "path", "notebook_path"):
                    if inp.get(k):
                        out["files"].add(inp[k])
                        # Writes are tracked separately: a write outside `owns` is two slices
                        # fighting over one file; a read outside `reads` is only an
                        # under-declared spec. One finding for both called a read a collision
                        # risk, which it is not.
                        if b.get("name") in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                            out["writes"].add(inp[k])
            elif b.get("type") == "tool_result":
                name, inp, t0 = started.pop(b.get("tool_use_id"), (None, {}, None))
                if not name:
                    continue
                dur = (t - t0) if (t and t0) else 0
                out["tools"][name] = out["tools"].get(name, 0) + dur
                if name == "Bash":
                    cmd = (inp.get("command") or "")[:120]
                    out["bash"].append((dur, cmd))
                    # A refusal SAYS SO. Match the words, never the duration.
                    #
                    # The first version of this check called anything under half a second a
                    # refusal, and fired on all four slices of the run that motivated it —
                    # including the one that demonstrably ran its tests, because a cached
                    # `npm run test:run`, a `grep` and an `echo` are all sub-second too. That is
                    # the same defect that retired the old Bash security guard: a matcher on the
                    # wrong signal, whose false positives get it switched off. The permission
                    # layer states its refusal in the tool_result, so read that instead.
                    txt = b.get("content")
                    if isinstance(txt, list):
                        txt = " ".join(x.get("text", "") for x in txt if isinstance(x, dict))
                    if isinstance(txt, str) and "requires approval" in txt:
                        out["refused"].append(cmd)
    out["files"] = sorted(out["files"])
    return out


refusals = []
print("\n--- WHAT EACH SLICE DID LOCALLY (wall minus API) ---")
for s in sorted(slices, key=lambda x: -(x["wall"] or 0)):
    local = (s["wall"] or 0) - (s["api_s"] or 0)
    pct = (local / s["wall"] * 100) if s["wall"] else 0
    print(f"\n  {s['name']}: {local:.0f}s local of {s['wall']}s wall ({pct:.0f}% burning no tokens)")
    f = _forensics(s.get("session_id"))
    if not f:
        # Say which of the two causes was actually OBSERVED, never both as a guess. The previous
        # wording ("no session_id, or the transcript was pruned") was printed for four slices whose
        # result.json held a session_id and whose transcripts were on disk — the lookup was broken
        # and wore missing-data as a costume. Same defect as a parser reporting a confident zero,
        # one layer up: a reader cannot tell a blind spot from a bug unless the tool distinguishes.
        sid = s.get("session_id")
        why = ("result.json carries no session_id" if not sid else
               f"session_id {sid} is present but no transcript matched it — check the LOOKUP "
               f"before believing the data is missing")
        gaps.append((f"transcript for {s['name']}",
                     why + ". Without it the local time cannot be attributed to a command."))
        print(f"    (no transcript found — {why})")
        continue
    if f["tools"]:
        top = sorted(f["tools"].items(), key=lambda kv: -kv[1])[:4]
        print("    tools: " + ", ".join(f"{n} {d:.0f}s" for n, d in top))
    # Commands the permission layer REFUSED. A headless slice has nobody to approve them, so
    # each one is a check the slice wanted to run and could not, and it has no way to tell you.
    # Measured 2026-08-08: one slice tried `npx vitest` five ways, was refused every time, wrote
    # "verified by careful inspection instead" and shipped two tests that never ran.
    if f["refused"]:
        print(f"    {len(f['refused'])} command(s) REFUSED by the permission layer")
        # Collected, not raised per slice. This is ONE systemic fact — the repo's allowlist does
        # not cover the command slices reach for — and raising it four times over four slices
        # buries the other findings and trains the reader to skim.
        refusals.append((s["name"], f["refused"]))

    # The single most useful line: the command that ate the slice.
    for dur, cmd in sorted(f["bash"], reverse=True)[:3]:
        share = (dur / s["wall"] * 100) if s["wall"] else 0
        print(f"    {dur:5.0f}s ({share:2.0f}%)  {cmd}")
        if share >= 30:
            findings.append({
                "metric": "slice_dominated_by_one_command", "value": f"{share:.0f}% of {s['name']}",
                "severity": "high",
                "action": f"`{cmd}` took {dur:.0f}s, {share:.0f}% of this slice's wall, and burned no "
                          f"tokens while it ran. If it is wider than the slice owns (a whole test "
                          f"suite rather than the slice's own tests), scope it in the slice prompt. "
                          f"This is the dominant cost once dispatch is ruled out, and it was.",
            })
    # A slice touching files it never declared is a partition bug, and it shows up here first.
    owned = set()
    for sl in spec.get("slices", []):
        if sl.get("name") == s["name"]:
            owned = set(sl.get("owns") or []) | set(sl.get("reads") or [])
    # The run directory is where the dispatcher TELLS every slice to write DONE.md, so counting
    # it flagged all 3 slices of run-2 and all 4 of run-1 for obeying their instructions.
    _run_abs = os.path.abspath(RUN)
    def _outside(paths, declared):
        return [x for x in paths
                if declared and _run_abs not in os.path.abspath(x)
                and not any(o in x or x in o for o in declared)]
    owned_writes = set()
    for sl in spec.get("slices", []):
        if sl.get("name") == s["name"]:
            owned_writes = set(sl.get("owns") or [])
    stray_w = _outside(f["writes"], owned_writes)
    stray_r = [x for x in _outside(f["files"], owned) if x not in stray_w]
    if stray_w:
        print(f"    WROTE {len(stray_w)} file(s) it does not own, e.g. {stray_w[0]}")
        findings.append({
            "metric": "undeclared_write", "value": f"{len(stray_w)} in {s['name']}",
            "severity": "high",
            "action": f"{s['name']} WROTE files it does not own: {', '.join(stray_w[:3])}. This is the "
                      f"failure the partition exists to prevent — two slices editing one file. Move "
                      f"each file into exactly one `owns` list.",
        })
    if stray_r:
        findings.append({
            "metric": "undeclared_read", "value": f"{len(stray_r)} in {s['name']}",
            "severity": "low",
            "action": f"{s['name']} read files it never declared: {', '.join(stray_r[:3])}. Harmless "
                      f"in itself, but add them to `reads` so the duplicated-reads metric can see "
                      f"them.",
        })

if refusals:
    total = sum(len(r) for _, r in refusals)
    example = refusals[0][1][0][:70]
    findings.append({
        "metric": "commands_refused",
        "value": f"{total} across {len(refusals)}/{len(slices)} slices",
        "severity": "high",
        "action": f"{total} command(s) were refused for want of an approval a headless slice can "
                  f"never get, across: " + ", ".join(n for n, _ in refusals) +
                  f" (e.g. `{example}`). Each one is a check a slice wanted to run and could not, "
                  f"and nothing in its DONE.md can say so. Add the command to the repo's "
                  f"permissions.allow, or give every slice a `verify` already covered by it — "
                  f"superspeed-dispatch.sh now refuses to dispatch one that is not.",
    })

# TREND — printed before the suggestions, because a delta reframes every number above it.
if PRIOR:
    print(f"\n--- VS {PRIOR.get('run')} ---")
    _now = {"idle_pct": round(idle_pct, 1), "fanout_seconds": fanout,
            "total_cost": round(sum(x["cost"] for x in slices), 4)}
    for k, v in _now.items():
        a = PRIOR.get(k)
        if isinstance(a, (int, float)):
            print(f"  {k:16} {a} -> {v}  ({v - a:+.4g})")
    _was = {x["metric"] for x in PRIOR.get("findings", [])}
    _now_m = {x["metric"] for x in findings}
    if _was - _now_m:
        print(f"  resolved since:  {', '.join(sorted(_was - _now_m))}")
    if _was & _now_m:
        # Severity is INHERITED from the worst recurring finding, never fixed at high. Recurrence
        # raises the priority of a real problem; it does not turn an undeclared read into the most
        # important thing in the run. A report whose top line is trivial trains the reader to skim.
        _rank = {"high": 0, "medium": 1, "low": 2}
        _sev = min((x["severity"] for x in findings if x["metric"] in (_was & _now_m)),
                   key=lambda v: _rank[v], default="low")
        findings.append({
            "metric": "recurring", "value": ", ".join(sorted(_was & _now_m)), "severity": _sev,
            "action": f"These appeared in {PRIOR.get('run')} too: " + ", ".join(sorted(_was & _now_m)) +
                      ". A finding in two consecutive runs is one durable problem, not two "
                      "incidents — change the mechanism, not the next partition.",
        })

print("\n--- SUGGESTIONS ---")
if not findings:
    print("  none. This run was well partitioned; nothing to change.")
for f in sorted(findings, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
    print(f"  [{f['severity']:6}] {f['metric']} = {f['value']}")
    print(f"           {f['action']}")


out = {
    "run": RUN, "task": spec.get("task"), "slices": slices,
    "fanout_seconds": fanout, "idle_seconds": idle, "idle_pct": round(idle_pct, 1),
    "achieved_concurrency": round(conc, 2), "cache_read_write_ratio": round(ratio_rd, 2),
    "parallelism_diagnosis": diag,
    "total_cost": round(sum(s["cost"] for s in slices), 4),
    "instrumentation_gaps": [w for w, _ in gaps],
    "findings": findings,
}
with open(f"{RUN}/analysis.json", "w") as f:

    json.dump(out, f, indent=1)
print(f"\nwritten: {RUN}/analysis.json")

# The last line is the one that gets read, so spend it on the step most likely to be skipped.
# This analysis is mechanical: it finds what the numbers show. Reading the prompts, the BLOCKED.md
# files and the thrashing slices is what finds WHY, and that is a different job.
print(f"\n>>> NEXT: /sk:claude-config-self-optimize-analysis-after-run {RUN}")
if findings:
    hi = sum(1 for f in findings if f["severity"] == "high")
    print(f"    {len(findings)} finding(s){f', {hi} high severity' if hi else ''}. It ranks these by "
          f"seconds recoverable and reads what the numbers cannot see.")
else:
    print("    No mechanical findings, which is a good run. Worth one pass anyway: the prompts and "
          "the slice transcripts hold the problems timings never show.")
