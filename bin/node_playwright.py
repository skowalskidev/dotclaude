"""Find Node Playwright for the headless-browser tools, and hold the largest page they can screenshot.

One home for both facts, shared by bin/visual-check.py, bin/mockup-shots.py and bin/design-board.py.

Lookup order (first match wins; Chromium launch failures fall through to the next match):
  1. MOCKUP_SHOTS_NODE_MODULES   an explicit node_modules dir
  2. NODE_PATH entries
  3. node_modules in the current directory and each parent (Node's own resolution)
  4. node_modules beside every tracked package.json of the current git repo
  5. the global npm root (npm root -g)
  6. the same package dirs in the repo's other git worktrees (a sibling checkout that ran npm install)
  7. ~/.claude/node_modules
Each dir is searched for playwright, playwright-core and @playwright/test. Nothing is installed; the
documented install is the global one (README.md § Agent setup step 4), found in group 5.

Python 3.9+, standard library only.
"""
import os
import pathlib
import subprocess

PACKAGES = ("playwright", "playwright-core", "@playwright/test")
MAX_DIRS = 60
NOT_FOUND = "SETUP: Node Playwright not found"

# Largest full page Chromium captured in one screenshot, measured with Playwright 1.65 headless Chromium:
# 21256x24800 px (527 Mpx) passed, 21256x25200 px (536 Mpx) failed with "Unable to capture screenshot".
# The limit is the area, not a side: 66000 px tall and 33000 px wide pages passed. Other Chromium builds fail
# lower (a flattened board of about 450 Mpx failed to decode), so builders warn at BUDGET_PIXELS.
# Under the limit Chromium can still return a full-size PNG painted only partway, with no error: a 3866x83332 page
# (322 Mpx) came back painted to about y=32500. bin/visual-check.py detects the flat bottom band and re-captures in tiles.
SCREENSHOT_MAX_PIXELS = 527_000_000
BUDGET_PIXELS = 250_000_000


def _git(cwd: pathlib.Path, *args: str) -> str:
    try:
        res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return res.stdout if res.returncode == 0 else ""


def _npm_root() -> list:
    try:
        res = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [pathlib.Path(res.stdout.strip())] if res.returncode == 0 and res.stdout.strip() else []


def search_groups(cwd=None, env=None) -> list:
    """[(label, [node_modules dirs])] in lookup order."""
    env = os.environ if env is None else env
    cwd = pathlib.Path(cwd or os.getcwd()).resolve()
    groups = [
        ("MOCKUP_SHOTS_NODE_MODULES", [pathlib.Path(env["MOCKUP_SHOTS_NODE_MODULES"])] if env.get("MOCKUP_SHOTS_NODE_MODULES") else []),
        ("NODE_PATH", [pathlib.Path(p) for p in env.get("NODE_PATH", "").split(os.pathsep) if p]),
        ("current directory and parents", [d / "node_modules" for d in (cwd, *cwd.parents)]),
    ]
    top = _git(cwd, "rev-parse", "--show-toplevel").strip()
    package_dirs, worktrees = [], []
    if top:
        tracked = _git(pathlib.Path(top), "ls-files", "--", "*package.json").splitlines()
        package_dirs = sorted({str(pathlib.PurePosixPath(p).parent) for p in tracked if "node_modules/" not in p})
        worktrees = [line[9:] for line in _git(pathlib.Path(top), "worktree", "list", "--porcelain").splitlines()
                     if line.startswith("worktree ") and line[9:] != top]
        groups.append(("this repo's package dirs", [pathlib.Path(top, d, "node_modules") for d in package_dirs]))
    else:
        groups.append(("this repo's package dirs (the current directory is not in a git repo)", []))
    groups.append(("npm root -g", _npm_root()))
    if top:
        groups.append(("other worktrees of this repo",
                       [pathlib.Path(w, d, "node_modules") for w in worktrees for d in package_dirs][:MAX_DIRS]))
    groups.append(("~/.claude", [pathlib.Path(env.get("HOME", str(pathlib.Path.home())), ".claude", "node_modules")]))
    return groups


def find(cwd=None, env=None) -> tuple:
    """(package dirs holding a Playwright, in lookup order; the search groups that were looked in)."""
    groups = search_groups(cwd, env)
    found, seen = [], set()
    for _, roots in groups:
        for root in roots:
            for pkg in PACKAGES:
                path = root / pkg
                if str(path) not in seen and (path / "package.json").is_file():
                    seen.add(str(path))
                    found.append(str(path))
    return found, groups


def not_found_message(groups: list) -> str:
    lines = [f"{NOT_FOUND} (looked for {', '.join(PACKAGES)}). Looked in:"]
    for label, roots in groups:
        shown = ", ".join(str(r) for r in roots[:3]) or "(nothing to search)"
        more = f" (+{len(roots) - 3} more)" if len(roots) > 3 else ""
        lines.append(f"  {label}: {shown}{more}")
    lines.append("Fix: install it once globally (README.md § Agent setup step 4): "
                 "`npm install -g playwright && npx playwright install chromium`. "
                 "Or run `npm install` in a checkout whose package.json lists playwright or @playwright/test, "
                 "or set MOCKUP_SHOTS_NODE_MODULES to a node_modules dir that holds playwright.")
    return "\n".join(lines)


# Node side: try each found package dir until Chromium launches. Expects `createRequire` imported from node:module.
LAUNCH_JS = r"""
async function launchChromium(dirs) {
  const load = createRequire(import.meta.url), tried = [];
  for (const dir of dirs) {
    try { return await load(dir).chromium.launch(); }
    catch (e) { tried.push(dir + ": " + String(e.message).split("\n")[0]); }
  }
  console.error("SETUP: Node Playwright found, but Chromium did not launch from any copy:\n  " + tried.join("\n  ")
    + "\nFix: run `npx playwright install chromium` in that checkout, or set MOCKUP_SHOTS_NODE_MODULES to another node_modules dir.");
  process.exit(2);
}
"""
