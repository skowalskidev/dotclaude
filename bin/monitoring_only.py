#!/usr/bin/env python3
"""monitoring_only.py: the ONE owner of the monitoring-only change class.

A project's registry entry (`projects/<project>.json` in its connector root, read only through
bin/connector_registry.py) may declare the paths that belong to its monitoring bot alone:

  "monitoringOnly": {"paths": ["ops/bot/**", ".github/workflows/bot.yml"],
                     "offlineTests": ["python3 ops/bot/bot_test.py"],
                     "requiredChecks": ["Bot / test"]}

A change is monitoring-only when EVERY file it touches matches one of `paths`. `*` and `?` stay
inside one path segment; `**` spans segments. A workflow file is never matched by a glob: it is
listed as its literal path, and only when that workflow belongs to the bot alone. `offlineTests`
are the bot's own suites, run as part of the monitoring-only bar (references/git-pr-deploy.md
§ Monitoring-only changes); `requiredChecks` names the bot's own CI checks ("<workflow> / <job>"), each
of which must succeed for the merge path. The guard reads a listed workflow's path, never its content.
The project values live in the local overlay, never in this repo.

Readers:
  hooks/git-commit-guard.py   the monitoring-only merge path (spec_for, classify, BAR_PHRASE)
  hooks/task-intake.sh        `pending`: the open monitoring-only PRs, once per session

Usage:
  monitoring_only.py pending --cwd DIR --session SID   one line naming open monitoring-only PRs, or nothing
  monitoring_only.py check --cwd DIR PATH...           exit 0 when every PATH is monitoring-only

Python 3.9 standard library only, like the loader it imports.
"""
import argparse
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent
STATE_DIR = Path(os.path.expanduser("~")) / ".claude" / ".intent-ledger"
WORKFLOWS = ".github/"
GLOB_CHARS = set("*?[")
# Only these GitHub change types count. A renamed or copied file has an old path the PR file list does
# not carry, so it could move a product file into the bot's folder; a missing or unknown type is no
# evidence either way. Both decline.
KNOWN_CHANGES = {"ADDED", "MODIFIED", "DELETED"}  # CHANGED (a mode or type change, e.g. to a symlink) declines
# The exact phrase a gate PASS reason carries once the bar ran (references/testing-strategy.md);
# hooks/git-commit-guard.py requires it verbatim.
BAR_PHRASE = "monitoring-only bar: OpenAI SHIP, Claude SHIP, offline suites pass, replay matches main"
LIST_FIELDS = "number,isDraft,headRefOid,changedFiles,files"
LIST_LIMIT = 100
GH_TIMEOUT = 4  # with the 2 s git read, intake stays well inside its hook's 10 s
LITERAL_ONLY = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "deno.json", "deno.jsonc",
                "deno.lock", "pyproject.toml", "poetry.lock", "requirements.txt", "action.yml", "action.yaml",
                "Dockerfile", "Makefile", ".npmrc", "conftest.py", "lefthook.yml", "tsconfig.json",
                ".gitattributes", ".gitmodules", "CODEOWNERS", ".pre-commit-config.yaml", "setup.py", "setup.cfg",
                "go.mod", "Cargo.toml", "pnpm-workspace.yaml", "turbo.json", ".envrc", "import_map.json",
                "bunfig.toml", "wrangler.toml", "wrangler.json", "wrangler.jsonc", "vercel.json", "netlify.toml",
                "jsconfig.json", "Containerfile", "pytest.ini", "tox.ini", "noxfile.py", ".bazelrc",
                "constraints.txt", "Pipfile", "Pipfile.lock", "Gemfile", "Gemfile.lock", "bun.lockb", "bun.lock",
                "uv.lock", "composer.json", "composer.lock", "go.sum", "Cargo.lock", "go.work", "go.work.sum",
                "BUILD", "BUILD.bazel", "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel", "biome.json", "biome.jsonc",
                "Taskfile.yml", "Taskfile.yaml"}
# Config read by name family (tsconfig.build.json pulled in by an extends, vitest.workspace.ts).
LITERAL_PREFIXES = ("tsconfig.", "jsconfig.", "vitest.workspace.", "wrangler.", "Dockerfile.", "Containerfile.",
                    "requirements", "build.gradle", "settings.gradle")
SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@functools.lru_cache(maxsize=256)
def _segment(pattern):
    """One path segment's pattern: * and ? never cross a /, and each segment holds at most two of them."""
    return re.compile("".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in pattern))


def _glob_match(pattern, path):
    """Segment by segment, so matching time is linear in the path: no pattern ever backtracks across
    segments. ** stands for any run of whole segments, at least one when it ends the pattern."""
    ps, xs = pattern.split("/"), path.split("/")
    seg = lambda p, x: _segment(p).fullmatch(x) is not None
    if "**" not in ps:
        return len(ps) == len(xs) and all(seg(p, x) for p, x in zip(ps, xs))
    i = ps.index("**")
    pre, post = ps[:i], ps[i + 1:]
    if len(xs) < len(pre) + len(post) + (0 if post else 1):
        return False
    return (all(seg(p, x) for p, x in zip(pre, xs[:len(pre)]))
            and all(seg(p, x) for p, x in zip(post, xs[len(xs) - len(post):])))


def validate(raw):
    """(spec, error). spec is {"paths", "offlineTests", "requiredChecks"} or None when undeclared.

    A declared but malformed entry is an error, never a silent None, so the merge path fails closed."""
    if raw is None:
        return None, ""
    if not isinstance(raw, dict):
        return None, "monitoringOnly must be an object"
    paths = raw.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        return None, "monitoringOnly.paths must be a non-empty list of path globs"
    for p in paths:
        if p.startswith(("/", "*", "?")) or {"", ".", ".."} & set(p.split("/")) or "\\" in p:
            return None, f"monitoringOnly.paths entry {p!r} is absolute, escapes, or starts with a wildcard"
        if GLOB_CHARS & set(p.split("/")[0]):
            return None, f"monitoringOnly.paths entry {p!r}: the first path segment must be a literal directory"
        if "[" in p or "]" in p:
            return None, f"monitoringOnly.paths entry {p!r}: only *, ? and ** are wildcards; [ ] are not allowed"
        # Bounded matching: one ** per entry and at most two * or ? per segment keep the compiled pattern
        # polynomial in a short path, far inside the hook's time budget.
        if p.split("/").count("**") > 1 or any(seg.count("*") + seg.count("?") > 2
                                                for seg in p.split("/") if seg != "**"):
            return None, f"monitoringOnly.paths entry {p!r}: at most one ** and two * or ? per path segment"
        if any("**" in seg and seg != "**" for seg in p.split("/")):
            return None, f"monitoringOnly.paths entry {p!r}: ** must be a whole path segment"
        if p.startswith(WORKFLOWS) and (GLOB_CHARS & set(p) or not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)):
            return None, f"monitoringOnly.paths entry {p!r}: a workflow is listed by its literal file path only"
    tests = raw.get("offlineTests")
    if not isinstance(tests, list) or not tests or not all(isinstance(t, str) and t.strip() for t in tests):
        return None, "monitoringOnly.offlineTests must list the bot's offline suites, one command each"
    checks = raw.get("requiredChecks")
    if not isinstance(checks, list) or not checks or not all(
            isinstance(c, str) and re.fullmatch(r"[^/]+ / [^/]+", c) for c in checks):
        return None, ("monitoringOnly.requiredChecks must list the bot's own CI checks as "
                      "\"<workflow> / <job>\", each of which must pass")
    return {"paths": list(paths), "offlineTests": list(tests), "requiredChecks": list(checks)}, ""


def path_matches(path, spec):
    if not isinstance(path, str) or not path or path.startswith("/") or {"", ".", ".."} & set(path.split("/")):
        return False
    if len(path) > 4096 or any(len(seg) > 255 for seg in path.split("/")):  # bounded match time: never inside
        return False
    base = path.rsplit("/", 1)[-1]
    if (path.startswith(WORKFLOWS) or "/.github/" in path or base in LITERAL_ONLY or base.startswith(".")
            or any(seg.startswith(".") for seg in path.split("/")[1:])  # a dot-folder inside the bot path
            or ".config." in base or ".setup." in base or base == "__init__.py" or "." not in base
            or base.endswith(".pth") or base in ("sitecustomize.py", "usercustomize.py")
            or base.startswith(LITERAL_PREFIXES) or base.endswith((".d.ts", ".gemspec", ".bzl")) or base == "__main__.py"):
        # A workflow, or a file other tooling runs (a package manifest, a composite action, an extensionless
        # runner such as a justfile, a .pth), counts only when listed literally, whatever a glob could reach.
        return path in spec["paths"]
    return any(_glob_match(p, path) for p in spec["paths"])


def classify(files, changed, spec):
    """"" when the PR file list is complete and every file is monitoring-only; else the reason."""
    if not isinstance(files, list) or not files:
        return "the PR's file list could not be read"
    if type(changed) is not int or changed != len(files):
        return f"the PR file list holds {len(files)} of {changed} changed files, so it is incomplete"
    seen = set()
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) or f["path"] in seen:
            return "the PR's file list could not be read"
        path = f["path"]
        seen.add(path)
        change = f.get("changeType")
        if not isinstance(change, str) or change not in KNOWN_CHANGES:
            return (f"{path} is {str(change).lower() if change else 'of unknown change type'}, so its "
                    "old path cannot be read from the PR")
        if not path_matches(path, spec):
            return f"{path} is outside the declared monitoring-only paths"
    return ""


def repo_slug(url):
    """owner/name of a github.com remote URL, or ""."""
    m = re.fullmatch(r"(?:(?:https?|ssh|git)://(?:[^@/\s]+@)?|[^@/\s]+@)?github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?",
                     (url or "").strip())
    return m.group(1) if m else ""


def _strict_roots(reg):
    """(identity, roots) read strictly: an identity file that exists but cannot be read or parsed is an
    error, never an empty overlay (the registry's own reader treats it as {} for its other callers)."""
    identity = None
    if os.environ.get("CLAUDE_CONNECTOR_ROOTS") is None:
        path = reg.identity_file()
        if path.exists():
            identity = json.loads(path.read_text())  # OSError or ValueError: the caller's read error
            if not isinstance(identity, dict):
                raise ValueError(f"{path} is not a JSON object")
        else:
            identity = {}
    roots = reg.load_all(identity)
    for root in roots:
        # Path.glob hides an unreadable projects folder: list it, so the error surfaces, and the snapshot
        # must hold exactly the files the listing shows (a read that failed once and then worked differs).
        projects = Path(root["path"]) / "projects"
        if projects.exists():
            listed = {n[:-5] for n in os.listdir(projects) if n.endswith(".json")}
            loaded = set(root.get("projectPaths") or {}) | {
                Path(e.split(": ", 1)[0]).stem for e in root["errors"] if str(projects) in e}
            if listed != loaded:
                raise OSError(f"{projects}: the project files changed while they were read")
    return identity, roots


def spec_for(slug):
    """(spec, error) for one GitHub repository, given as owner/name.

    The project entry must list that exact owner/name in its `match` (case-insensitive): the loader
    matches substrings, which would hand one repo's paths to another whose name extends it. Every
    index and project file, and the identity file naming the roots, must read cleanly; any error there is
    returned, never treated as undeclared. A broken provider record cannot hold a declaration, so it does
    not stop the lookup."""
    if not SLUG_RE.fullmatch(slug or ""):
        return None, ""
    try:
        if str(BIN) not in sys.path:
            sys.path.insert(0, str(BIN))
        import connector_registry as reg
        # The project entry's own spelling of owner/name is used for the lookup, so a slug typed in
        # another case still finds it (the registry's boundary match is case-sensitive).
        identity, roots = _strict_roots(reg)
        # A missing index in a configured root is a read error too: its project files may still declare.
        broken = [e for root in roots for e in root["errors"]
                  if e.startswith(str(Path(root["path"]) / "index.json") + ":")
                  or e.startswith(str(Path(root["path"]) / "projects") + os.sep)]
        if broken:  # an unreadable index or project file could hide the declaration
            return None, ("the connector overlay could not be read (" + "; ".join(broken)[:200]
                          + "); repair it with /sk:setup-connectors")
        listed = [str(m) for root in roots if root["index"]
                  for entry in (root["index"].get("projects") or {}).values()
                  for m in entry.get("match", []) if str(m).lower() == slug.lower()]
        if len(listed) > 1:
            return None, f"the connector overlay lists {slug} in more than one project, so its declaration is unknown"
        canonical = listed[0] if listed else ""
        if not canonical:
            return None, ""
        _, manifest, _ = reg.select(os.getcwd(), remote=f"https://github.com/{canonical}.git", identity=identity,
                                    roots=roots,
                                    strict=False)  # the same snapshot; its declaring files were checked above
    except Exception as exc:  # the loader's own errors and an unreadable root alike
        return None, f"the connector overlay could not be read ({exc})"
    if slug.lower() not in {str(m).lower() for m in manifest.get("match", [])}:
        # The loader matched another project by substring: the declaring entry is not the one read.
        return None, f"the connector overlay picked another project for {slug}, so its declaration is unknown"
    return validate(manifest.get("monitoringOnly"))


def declared_owners():
    """The GitHub owners (lowercase) of every repo a monitoringOnly entry matches; None when the overlay
    cannot be read whole (an unreadable index or project file could declare any owner)."""
    try:
        if str(BIN) not in sys.path:
            sys.path.insert(0, str(BIN))
        import connector_registry as reg
        _, roots = _strict_roots(reg)
    except Exception:
        return None
    owners = set()
    for root in roots:
        if any(e.startswith(str(Path(root["path"]) / "index.json") + ":")
               or e.startswith(str(Path(root["path"]) / "projects") + os.sep) for e in root["errors"]):
            return None
        for entry in ((root["index"] or {}).get("projects") or {}).values():
            if isinstance(entry, dict) and "monitoringOnly" in entry:
                owners |= {str(m).split("/", 1)[0].lower() for m in entry.get("match", []) if "/" in str(m)}
    return owners


def origin_slug(cwd):
    try:
        p = subprocess.run(["git", "-C", str(cwd), "remote", "get-url", "origin"], capture_output=True,
                           text=True, timeout=2)
    except Exception:
        return ""
    return repo_slug(p.stdout) if p.returncode == 0 else ""


def _gh_list(cwd, slug):
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    try:
        p = subprocess.run(["gh", "pr", "list", "--repo", f"github.com/{slug}", "--state", "open", "--limit",
                            str(LIST_LIMIT), "--json", LIST_FIELDS], cwd=cwd, capture_output=True, text=True,
                           timeout=GH_TIMEOUT, env={**env, "GH_HOST": "github.com"})
        prs = json.loads(p.stdout) if p.returncode == 0 else None
    except Exception:
        return None
    return prs if isinstance(prs, list) else None


def pending(cwd, session):
    """The line hooks/task-intake.sh adds, or "". One gh call per session, silent on any error."""
    sid = re.sub(r"[^A-Za-z0-9._-]", "", session or "")
    if not sid:
        return ""
    marker = STATE_DIR / f"{sid}.monitoring-only-listed"
    if marker.exists():  # listed once this session: later prompts make no git, registry or gh read
        return ""
    slug = origin_slug(cwd)
    spec, error = spec_for(slug)
    if error or not spec:  # a repo that declares nothing uses up nothing: a later prompt in one that does lists
        return ""
    try:  # one claim per session, taken before the gh call
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        os.close(os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except OSError:
        return ""
    prs = _gh_list(cwd, slug)
    if not prs:  # none open, or a failed read: silent, and the claim stands (one call per session)
        return ""
    # A malformed entry makes the whole answer unreadable: silence, never a partial list.
    if not all(isinstance(pr, dict) and type(pr.get("number")) is int and pr["number"] > 0
               and isinstance(pr.get("files"), list)
               and type(pr.get("changedFiles")) is int and isinstance(pr.get("isDraft"), bool)
               and all(isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("changeType"), str)
                       for f in pr["files"]) for pr in prs):
        return ""
    found = []
    for pr in prs:
        if isinstance(pr, dict) and isinstance(pr.get("number"), int) and \
                not classify(pr.get("files"), pr.get("changedFiles"), spec):
            found.append(f"#{pr['number']}" + (" (draft)" if pr.get("isDraft") else ""))
    if not found:
        return ""
    limit = f" (only the newest {LIST_LIMIT} open PRs were read)" if len(prs) >= LIST_LIMIT else ""
    return ("MONITORING-ONLY PRS open in this repo: " + ", ".join(found) + limit + ". Add each to the living plan "
            "as one task, \"run the monitoring-only bar on #N and merge when it passes\", and do it "
            "without being asked: references/git-pr-deploy.md § Monitoring-only changes. Mark a draft "
            "ready only once the bar passes, merge with `gh pr merge <N> -R github.com/" + slug + " --match-head-commit "
            "<full head sha> --squash`, verify any deploy, report in one line. Skip a PR another live session owns.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("pending")
    cmd.add_argument("--cwd", default=os.getcwd())
    cmd.add_argument("--session", default="")
    cmd = sub.add_parser("check")
    cmd.add_argument("--cwd", default=os.getcwd())
    cmd.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "pending":
        try:
            line = pending(args.cwd, args.session)
        except Exception:
            line = ""
        if line:
            print(line)
        return 0
    spec, error = spec_for(origin_slug(args.cwd))
    if error or not spec:
        print(error or "this project declares no monitoringOnly paths", file=sys.stderr)
        return 2
    outside = [p for p in args.paths if not path_matches(p, spec)]
    for p in outside:
        print(f"outside: {p}")
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
