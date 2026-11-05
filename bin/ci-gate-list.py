#!/usr/bin/env python3
"""Print every `run:` step of every GitHub Actions job that runs on a pull request, as a gate list.

  ci-gate-list.py [--events pull_request,merge_group] [WORKFLOW.yml ...]

With no files it reads `.github/workflows/*.yml` and `*.yaml` under the current directory. For each
workflow whose `on:` names one of the events, it prints each job (id, `if:`, matrix keys, services,
default working directory) and each run step numbered, with its effective working directory and the
whole command. A step in a job with `services:` is marked `CI-only? needs services: <names>`, and one
whose command starts a container (`docker run`, `supabase start`) `CI-only? starts containers`, so the
local list runs it with that runtime or names it with a reason instead of dropping it. A job that calls a reusable workflow is
printed as a pointer to that file. The last line is `TOTAL <n> run steps ...`: the local gate list
holds that many rows, each run locally or named as skipped with its reason
(references/testing-strategy.md § the project's CI gate list).

Python 3.9+, standard library only. YAML is parsed by the system `ruby` (Psych, YAML 1.1, so a bare
`on:` key arrives as `true`). Exit 0: list printed. Exit 1: no job runs on the events (an empty list
is never a pass). Exit 2: usage error, unreadable file, ruby missing or a parse failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_EVENTS = ("pull_request", "merge_group")
# A run step whose command starts its own container needs a local container runtime too.
CONTAINER_HINTS = ("docker ", "docker-compose", "podman ", "supabase start", "supabase db start")
RUBY_TO_JSON = ("puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), [], [], true))")


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(f"ci-gate-list: {msg}", file=sys.stderr)
    sys.exit(2)


def load_yaml(path: Path) -> dict:
    ruby = shutil.which("ruby")
    if not ruby:
        die("ruby not found; it parses the workflow YAML (python has no stdlib YAML)")
    result = subprocess.run([ruby, "-ryaml", "-rjson", "-e", RUBY_TO_JSON, str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        die(f"cannot parse {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        die(f"{path} is not a workflow mapping")
    return data


def triggers(workflow: dict) -> list[str]:
    on = workflow.get("on", workflow.get("true"))
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(e) for e in on]
    if isinstance(on, dict):
        return [str(e) for e in on]
    return []


def default_wd(node: dict) -> str | None:
    return ((node.get("defaults") or {}).get("run") or {}).get("working-directory")


def describe(path: Path, workflow: dict, events: set[str]) -> tuple[list[str], int, int, int]:
    """Return (lines, run steps, service steps, jobs) for one workflow; empty when not triggered."""
    fired = [t for t in triggers(workflow) if t in events]
    if not fired:
        return [], 0, 0, 0
    lines = [f"{path}  triggers: {', '.join(fired)}"]
    steps_total = service_total = 0
    jobs = workflow.get("jobs") or {}
    wf_wd = default_wd(workflow)
    for job_id, job in jobs.items():
        job = job or {}
        head = f"job {job_id}"
        if job.get("name"):
            head += f" ({job['name']})"
        if job.get("uses"):
            lines.append(f"{head}  calls reusable workflow {job['uses']}: list that file too")
            continue
        job_wd = default_wd(job) or wf_wd or "."
        services = sorted((job.get("services") or {}).keys())
        extras = [f"working-directory: {job_wd}"]
        if services:
            extras.append(f"services: {', '.join(services)}")
        if job.get("container"):
            image = job["container"] if isinstance(job["container"], str) else job["container"].get("image")
            extras.append(f"container: {image}")
        matrix = (job.get("strategy") or {}).get("matrix")
        if isinstance(matrix, dict):
            extras.append(f"matrix: {', '.join(k for k in matrix if k not in ('include', 'exclude'))}")
        if job.get("if") is not None:
            extras.append(f"if: {job['if']}")
        lines.append(f"{head}  " + "  ".join(extras))
        n = 0
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or "run" not in step:
                continue
            n += 1
            label = step.get("name") or str(step["run"]).strip().splitlines()[0]
            marks = []
            if step.get("working-directory"):
                marks.append(f"wd: {step['working-directory']}")
            if step.get("if") is not None:
                marks.append(f"if: {step['if']}")
            starts = [h.strip() for h in CONTAINER_HINTS if h in str(step["run"])]
            if services:
                marks.append(f"CI-only? needs services: {', '.join(services)}")
            elif starts:
                marks.append(f"CI-only? starts containers: {', '.join(starts)}")
            if services or starts:
                service_total += 1
            lines.append(f"  {n}. {label}" + (f"  [{'; '.join(marks)}]" if marks else ""))
            for cmd in str(step["run"]).strip().splitlines():
                lines.append(f"       {cmd}")
        steps_total += n
    return lines, steps_total, service_total, len(jobs)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", default=",".join(DEFAULT_EVENTS),
                        help="comma-separated trigger events (default: pull_request,merge_group)")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args(argv)
    events = {e.strip() for e in args.events.split(",") if e.strip()}
    if not events:
        die("--events is empty")
    files = args.files or sorted(p for pat in ("*.yml", "*.yaml")
                                 for p in Path(".github/workflows").glob(pat))
    if not files:
        die("no workflow files given and none under .github/workflows")
    out, steps, service_steps, jobs = [], 0, 0, 0
    for path in files:
        if not path.is_file():
            die(f"not a file: {path}")
        lines, s, sv, j = describe(path, load_yaml(path), events)
        if lines:
            out += lines + [""]
            steps, service_steps, jobs = steps + s, service_steps + sv, jobs + j
    if not jobs:
        print(f"ci-gate-list: no job runs on {', '.join(sorted(events))} in {len(files)} file(s)",
              file=sys.stderr)
        return 1
    print("\n".join(out).rstrip())
    print(f"TOTAL {steps} run steps in {jobs} jobs ({service_steps} need services)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
