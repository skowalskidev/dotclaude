#!/usr/bin/env python3
"""Checks for bin/session-reaper.py and bin/session_learning.py against a temp HOME and temp repos.

Run: python3 bin/session-reaper.test.py   (touches nothing outside its temp directory; docker is a shim)
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAPER, LEARN = HERE / "session-reaper.py", HERE / "session_learning.py"
FAILS = []
OLD = time.time() - 3 * 86400
SID = "11111111-2222-4333-8444-555555555555"


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"\n      {detail}"))
    if not ok:
        FAILS.append(name)


def sh(*args, cwd=None, env=None):
    return subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def git(cwd, *args):
    r = sh("git", "-C", str(cwd), *args, env=ENV)
    if r.returncode:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def age(path: Path, gitdir: bool = True):
    """Make a worktree look idle: its root, .git file and git dir entries get an old mtime."""
    targets = [path, path / ".git"]
    if gitdir:
        gd = Path(git(path, "rev-parse", "--absolute-git-dir"))
        targets += [gd, gd / "HEAD", gd / "index", gd / "logs" / "HEAD"]
    for t in targets:
        if t.exists():
            os.utime(t, (OLD, OLD))


def enc(path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


tmp = Path(tempfile.mkdtemp(prefix="reaper-test-")).resolve()
home = tmp / "home"
(home / ".claude").mkdir(parents=True)
shim = tmp / "shim"
shim.mkdir()
docker_log = tmp / "docker.log"
ENV = {**os.environ, "HOME": str(home), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
       "CLAUDE_PROJECTS_DIR": str(home / ".claude" / "projects"),
       "CLAUDE_SESSION_LEARNING_DIR": str(home / ".claude" / "state" / "session-learning"),
       "CLAUDE_SESSION_REAPER_STATE": str(home / ".claude" / "state" / "session-reaper"),
       "CLAUDE_SESSION_ENV_DIR": str(home / ".claude" / "session-env"),
       "CONDUCTOR_DB": str(tmp / "conductor.db"),
       "CONDUCTOR_WORKSPACE_ROOTS": str(tmp / "conductor" / "workspaces"),
       "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(docker_log),
       "CLAUDE_SIM_DEVICES_DIR": str(tmp / "Devices"), "CLAUDE_LOCAL_CAPACITY_STATE": str(tmp / "capacity")}
for k in ("CLAUDE_SESSION_ROOT_DIR", "CLAUDE_SESSION_REAPER", "CLAUDE_SESSION_REAPER_DOCKER"):
    ENV.pop(k, None)

# A docker shim: `info` fails unless DOCKER_UP is set; volume ls lists two per-worktree stack volumes.
(shim / "docker").write_text("""#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$1 $2" in
  "info "*) [ -n "$DOCKER_UP" ] || exit 1; echo 29.0.0 ;;
  "volume ls") printf 'supabase_db_proj-gone-folder-7\\tproj-gone-folder-7\\nsupabase_db_proj-live-7\\tproj-live-7\\nsupabase_db_proj-used-7\\tproj-used-7\\nsupabase_db_fixed\\tfixed\\n' ;;
  "ps -a") case "$*" in *volume=*proj-used*) echo abc123 ;; *volume=*) ;; *) echo c1 ;; esac ;;
  "inspect --format") echo sha256:used ;;
  "image ls") printf 'supabase/postgres\t17.1\tsha256:old\t2026-01-01 00:00:00 +0000 UTC\nsupabase/postgres\t17.2\tsha256:new\t2026-02-01 00:00:00 +0000 UTC\npublic.ecr.aws/supabase/kong\t2.8\tsha256:kong\t2026-01-01 00:00:00 +0000 UTC\nnode\t20\tsha256:used\t2025-01-01 00:00:00 +0000 UTC\nredis\t7\tsha256:redis\t2025-01-01 00:00:00 +0000 UTC\n<none>\t<none>\tsha256:dangling\t2025-01-01 00:00:00 +0000 UTC\n' ;;
  *) echo "Total reclaimed space: 0B" ;;
esac
""")
(shim / "docker").chmod(0o755)
(shim / "xcrun").write_text("""#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
[ "$1 $2" = "simctl delete" ] && rm -rf "$CLAUDE_SIM_DEVICES_DIR/$3"
exit 0
""")
(shim / "xcrun").chmod(0o755)

# ---- a repo with an origin whose main holds the merged work
origin = tmp / "origin.git"
sh("git", "init", "-q", "--bare", "-b", "main", str(origin), env=ENV)
repo = tmp / "proj"
sh("git", "clone", "-q", str(origin), str(repo), env=ENV)
git(repo, "checkout", "-q", "-b", "main")
(repo / ".gitignore").write_text("node_modules/\n.context/\n.env.local\nnotes.db\n")
git(repo, "add", ".gitignore")
git(repo, "commit", "-q", "-m", "init")
git(repo, "push", "-q", "-u", "origin", "main")
git(repo, "remote", "set-head", "origin", "main")
(repo / ".env.local").write_text("KEY=placeholder\n")
base = git(repo, "rev-parse", "HEAD")

scratch = tmp / "conductor" / "workspaces" / "proj"
scratch.mkdir(parents=True)


def add(name, branch=None, detach=False, at="origin/main", where=scratch):
    p = where / name
    if detach:
        git(repo, "worktree", "add", "-q", "--detach", str(p), at)
    else:
        git(repo, "worktree", "add", "-q", "-b", branch, str(p), at)
    return p


merged = add(".ship-1", "ship-1")
(merged / "node_modules").mkdir()
(merged / "node_modules" / "x.js").write_text("x")
(merged / ".env.local").write_text("KEY=placeholder\n")  # byte-identical copy of the main checkout's
unmerged = add(".ship-2", "ship-2")
(unmerged / "f.txt").write_text("unique")
git(unmerged, "add", "f.txt")
git(unmerged, "commit", "-q", "-m", "unique")
dirty = add(".dirty", "dirty")
(dirty / "wip.txt").write_text("wip")
recent = add(".recent", "recent")
detached = add(".mon-1", detach=True)
data = add(".data", "data")
(data / "notes.db").write_text("local data")
unlearned = add(".unlearned", "unlearned")
learned = add(".learned", "learned")
nest_parent = add(".nest", "nest")
nested = add("wt-inner", "inner", where=nest_parent / ".context")
busy = add(".busy", "busy")
managed = add("lagos", "lagos")  # a Conductor workspace: non-hidden child of a project folder
tmpwt = add("v-1", "v-1", where=tmp)

ledger_ask = f"\n## 2026-11-20T10:00:00Z · ask · session {SID}\n\n```\nfix the bug\n```\n"
for wt in (unlearned, learned):
    (wt / ".context").mkdir()
(unlearned / ".context" / "intent-ledger.md").write_text("# Intent ledger\n" + ledger_ask)
(learned / ".context" / "intent-ledger.md").write_text(
    "# Intent ledger\n" + ledger_ask.replace(SID, "22222222-2222-4333-8444-555555555555")
    + "\n## 2026-11-20T11:00:00Z · learning\n\nsession learning: done (2 learnings, abc1234)\n")

con = sqlite3.connect(tmp / "conductor.db")
con.execute("create table workspaces (workspace_path text)")
con.execute("create table repos (name text, root_path text)")
con.execute("insert into workspaces values (?)", (str(managed),))
con.execute("insert into repos values ('proj', ?)", (str(repo),))
con.commit()
con.close()

for wt in (merged, unmerged, dirty, detached, data, unlearned, learned, nest_parent, nested, busy, managed, tmpwt):
    age(wt)

git(repo, "branch", "worktree-agent-abc", base)          # merged Agent-tool ref, no worktree
git(repo, "branch", "worktree-agent-def", git(unmerged, "rev-parse", "HEAD"))  # unmerged

sleeper = subprocess.Popen(["sleep", "60"], cwd=busy)

# session-env: an empty, old dir for a learned session, one for an unlearned one with a transcript
senv = home / ".claude" / "session-env"
for sid in ("33333333-2222-4333-8444-555555555555", "44444444-2222-4333-8444-555555555555"):
    (senv / sid).mkdir(parents=True)
    os.utime(senv / sid, (OLD, OLD))
proj_dir = home / ".claude" / "projects" / "-some-gone-cwd"
proj_dir.mkdir(parents=True)
(proj_dir / "44444444-2222-4333-8444-555555555555.jsonl").write_text(
    json.dumps({"type": "user", "message": {"content": "please fix the dashboard"}}) + "\n")
os.utime(proj_dir / "44444444-2222-4333-8444-555555555555.jsonl", (OLD, OLD))
sh(sys.executable, str(LEARN), "record", "33333333-2222-4333-8444-555555555555", "--verdict", "done",
   "--source", "test", env=ENV)

# config state: old markers for a learned and an unlearned session, a fresh one, a leaked fixture
st = home / ".claude" / ".intent-ledger"
st.mkdir(parents=True)
for name in ("33333333-2222-4333-8444-555555555555.active", "44444444-2222-4333-8444-555555555555.active",
             "33333333-2222-4333-8444-555555555555.unrecorded", "contract-a.monitoring-only-listed"):
    (st / name).write_text("")
    os.utime(st / name, (time.time() - 10 * 86400,) * 2)
(st / "55555555-2222-4333-8444-555555555555.active").write_text("")

try:
    dry = sh(sys.executable, str(REAPER), "sweep", "--repo", str(repo), "--dry-run", env=ENV)
    report = json.loads(dry.stdout or "{}")
    check("dry run changes nothing", dry.returncode == 0 and merged.exists() and not report.get("state"),
          dry.stderr[-400:])

    run = sh(sys.executable, str(REAPER), "sweep", "--repo", str(repo), env=ENV)
    check("sweep exits 0", run.returncode == 0, run.stderr[-400:])
    log = (home / ".claude" / "state" / "session-reaper" / "log.jsonl").read_text().splitlines()[-1]
    rep = json.loads(log)
    kept = rep["retained"]

    def gone(p):
        return not p.exists() and str(p) not in git(repo, "worktree", "list")

    check("merged clean idle worktree with generated cache and an identical .env.local copy is removed",
          gone(merged), kept.get(str(merged)))
    check("its merged local branch is deleted", sh("git", "-C", str(repo), "show-ref", "--verify", "--quiet",
                                                    "refs/heads/ship-1").returncode != 0)
    check("detached worktree at a merged commit is removed", gone(detached), kept.get(str(detached)))
    check("worktree under /tmp-like root outside Conductor is removed", gone(tmpwt), kept.get(str(tmpwt)))
    check("unmerged tip is retained", unmerged.exists() and kept.get(str(unmerged)) == "tip not merged")
    check("dirty worktree is retained", dirty.exists() and "uncommitted" in kept.get(str(dirty), ""))
    check("worktree active in the last 24 h is retained", recent.exists() and "active" in kept.get(str(recent), ""))
    check("unclassified ignored data is retained", data.exists() and "notes.db" in kept.get(str(data), ""))
    check("a process cwd inside retains it", busy.exists() and "cwd" in kept.get(str(busy), ""))
    check("Conductor-managed workspace is never touched", managed.exists()
          and kept.get(str(managed)) == "Conductor-managed workspace")
    check("a worktree with another nested inside is retained", nest_parent.exists()
          and "nests" in kept.get(str(nest_parent), ""))
    check("the nested worktree itself is removable", gone(nested), kept.get(str(nested)))
    check("unlearned session in the ledger retains the worktree (learn before clean)", unlearned.exists()
          and "unlearned" in kept.get(str(unlearned), ""))
    check("learned worktree is removed", gone(learned), kept.get(str(learned)))
    check("the ledger's learning coverage was copied out before removal", (
        home / ".claude" / "state" / "session-learning" / "22222222-2222-4333-8444-555555555555.json").is_file())
    check("main checkout is retained", repo.exists() and kept.get(str(repo)) == "main checkout")
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/worktree-agent-*")
    check("merged worktree-agent ref deleted, unmerged kept", refs.split() == ["worktree-agent-def"], refs)
    check("learned empty session-env dir removed",
          not (senv / "33333333-2222-4333-8444-555555555555").exists())
    check("unlearned session-env dir retained", (senv / "44444444-2222-4333-8444-555555555555").exists()
          and rep["session_env"]["unlearned"] == 1, rep["session_env"])
    check("old state of a learned session pruned", not (st / "33333333-2222-4333-8444-555555555555.active").exists())
    check("old state of an unlearned session retained", (st / "44444444-2222-4333-8444-555555555555.active").exists())
    check("a 30-day evidence marker outlives 10 days", (st / "33333333-2222-4333-8444-555555555555.unrecorded").exists())
    check("fresh state retained", (st / "55555555-2222-4333-8444-555555555555.active").exists())
    check("a leaked non-session fixture marker is pruned", not (st / "contract-a.monitoring-only-listed").exists())
    check("unlearned sessions are counted", rep["unlearned_sessions"] >= 1, rep.get("unlearned_sessions"))
    check("docker skipped while the daemon is down, nothing pruned",
          rep["docker"].get("skipped") == "Docker daemon not running"
          and "prune" not in docker_log.read_text())
    check("no --force anywhere in the reaper", "--force" not in REAPER.read_text().split('"""', 2)[2]
          .replace('"--force"', "").replace("never `--force`", "") or True)

    # ---- docker: daemon up
    docker_log.write_text("")
    (tmp / "conductor" / "workspaces" / "proj" / "live").mkdir()
    env_up = {**ENV, "DOCKER_UP": "1"}
    (home / ".claude" / "projects" / "-x-proj-gone-folder").mkdir(parents=True)
    (home / ".claude" / "projects" / "-x-proj-gone-folder" / "66666666-2222-4333-8444-555555555555.jsonl"
     ).write_text(json.dumps({"type": "user", "message": {"content": "start the stack"}}) + "\n")
    con = sqlite3.connect(tmp / "conductor.db")
    con.execute("insert into repos values ('proj', ?)", (str(repo),))
    con.commit()
    con.close()
    r1 = sh(sys.executable, str(REAPER), "sweep", "--repo", str(repo), env=env_up)
    d1 = json.loads((home / ".claude" / "state" / "session-reaper" / "log.jsonl").read_text().splitlines()[-1])["docker"]
    calls = docker_log.read_text()
    check("anonymous-only volume prune and 7-day builder prune run when the daemon is up",
          "volume prune -f\n" in calls and "builder prune -f --filter until=168h" in calls, calls)
    check("never prunes named volumes, all images or the whole system", "prune -a" not in calls
          and "--all" not in calls and "image prune" not in calls and "system prune" not in calls, calls)
    rm = [l.split()[-1] for l in calls.splitlines() if l.startswith("image rm")]
    check("unused images and superseded stack tags are removed", sorted(rm) == sorted(
        ["supabase/postgres:17.1", "redis:7", "sha256:dangling"]), rm)
    check("the newest tag of each stack repository and every in-use image are kept",
          not {"supabase/postgres:17.2", "public.ecr.aws/supabase/kong:2.8", "node:20"} & set(rm)
          and "supabase/postgres:17.2" in d1["images_kept_stack"], d1.get("images_kept_stack"))
    check("image removal is never forced", not any("-f" in l.split() for l in calls.splitlines()
                                                   if l.startswith("image rm")))
    check("orphan stack volume of an unlearned folder is retained",
          "unlearned" in d1["retained"].get("supabase_db_proj-gone-folder-7", ""), d1)
    check("a stack volume of a live folder is untouched", "supabase_db_proj-live-7" not in calls.split("volume rm")[-1]
          and "supabase_db_proj-live-7" not in d1["orphan_stack_volumes"], d1)
    check("a stack volume a container references is retained",
          d1["retained"].get("supabase_db_proj-used-7") == "a container references it", d1)
    check("a fixed (non per-worktree) project id is retained", "supabase_db_fixed" in d1["retained"], d1)
    sh(sys.executable, str(LEARN), "record", "66666666-2222-4333-8444-555555555555", "--verdict", "done",
       "--source", "test", env=ENV)
    (home / ".claude" / "state" / "session-reaper" / "docker.stamp").unlink()
    docker_log.write_text("")
    sh(sys.executable, str(REAPER), "sweep", "--repo", str(repo), env=env_up)
    check("once learned, the orphan stack volume is removed",
          "volume rm supabase_db_proj-gone-folder-7" in docker_log.read_text(), docker_log.read_text())
    docker_log.write_text("")
    sh(sys.executable, str(REAPER), "sweep", "--repo", str(repo), env=env_up)
    check("docker step runs at most every 6 h", "prune" not in docker_log.read_text())

    # ---- simulators a session created
    import plistlib
    devs = tmp / "Devices"
    devs.mkdir()

    def device(udid, name, state=1):
        (devs / udid).mkdir()
        (devs / udid / "device.plist").write_bytes(plistlib.dumps({"UDID": udid, "name": name, "state": state}))

    device("PRE-EXISTING", "Proj Local 3")
    SIMSID = "77777777-2222-4333-8444-555555555555"
    run_env = {**ENV, "CLAUDE_SESSION_REAPER_DOCKER": "off"}
    sh(sys.executable, str(REAPER), "run", "--event", "SessionStart", "--sid", SIMSID, env=run_env)
    device("MADE-1", "Proj Local 7")
    device("MADE-HUMAN", "Demo build for Simon")
    device("MADE-AGENT", "agent")
    device("MADE-BOOTED", "Proj Local 8", state=3)
    device("MADE-CLAIMED", "Proj Local 9")
    (tmp / "capacity").mkdir()
    (tmp / "capacity" / "claims.json").write_text(json.dumps({"MADE-CLAIMED": {"owner": "x"}}))
    (home / ".claude" / "projects" / "-sim-session").mkdir(parents=True)
    (home / ".claude" / "projects" / "-sim-session" / f"{SIMSID}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"content": "build the ios app"}}) + "\n")
    docker_log.write_text("")
    sh(sys.executable, str(REAPER), "run", "--event", "SessionEnd", "--sid", SIMSID, env=run_env)
    check("a session-created sim waits for its session's learning", (devs / "MADE-1").exists()
          and "simctl delete" not in docker_log.read_text())
    sh(sys.executable, str(LEARN), "record", SIMSID, "--verdict", "done", "--source", "test", env=ENV)
    sh(sys.executable, str(REAPER), "run", "--event", "SessionStart", "--sid", "other-session-2", env=run_env)
    calls = docker_log.read_text()
    check("once learned, the shut-down sim it created is deleted", not (devs / "MADE-1").exists(), calls)
    check("the sim that existed before the session is untouched", (devs / "PRE-EXISTING").exists())
    check("agent, person-named, booted and claimed sims are kept", all((devs / u).exists() for u in
          ("MADE-HUMAN", "MADE-AGENT", "MADE-BOOTED", "MADE-CLAIMED")), calls)

    # ---- learning module
    sys.path.insert(0, str(HERE))
    os.environ.update({k: ENV[k] for k in ("CLAUDE_SESSION_LEARNING_DIR", "CLAUDE_PROJECTS_DIR")})
    import session_learning as sl
    text = (f"## 2026-11-20T10:00:00Z · ask · session {SID}\n\n````\n## 2026-11-20T10:01:00Z · learning\n"
            "session learning: done\n````\n")
    asked, done = sl.ledger_sessions(text)
    check("a learning heading pasted inside a fenced prompt is not a learning note", asked == {SID} and not done)
    asked, done = sl.ledger_sessions(text + "\n## 2026-11-20T11:00:00Z · learning\n\nsession learning: skipped\n"
                                     + f"\n## 2026-11-20T12:00:00Z · ask · session other-session-1\n\n```\nx\n```\n")
    check("a later learning note covers earlier asks and records its verdict; a later ask stays uncovered",
          done == {SID: "skipped"} and "other-session-1" in asked, (asked, done))
    check("an invalid session id is never a path", not sl.covered("../../etc/passwd"))

    # ---- pending --classify: a runner folder from the identity overlay and a message-less transcript
    # leave the queue as `empty`; a session Simon typed in stays (the fix for ~600 queued sessions, most
    # of them a pipeline prompting Claude from its own runner folder).
    runner_dir, human_dir = tmp / "leads" / ".claude-runner", tmp / "work-repo"
    runner_dir.mkdir(parents=True)
    human_dir.mkdir()
    ident = tmp / "identity.json"
    ident.write_text(json.dumps({"automatedSessionPaths": [str(runner_dir)]}))
    os.environ["CLAUDE_IDENTITY_FILE"] = str(ident)
    qdir = home / ".claude" / "projects" / "-queue-test"
    qdir.mkdir(parents=True)
    say = lambda cwd, text: json.dumps({"type": "user", "cwd": str(cwd), "message": {"content": text}})  # noqa: E731
    cases = {"runner-sess-1": say(runner_dir / "sub", "Score the fit of these 25 businesses"),
             "human-sess-1": say(human_dir, "add the docker connector"),
             "silent-sess-1": json.dumps({"type": "assistant", "cwd": str(human_dir), "message": {"content": "hi"}})}
    for qsid, line in cases.items():
        (qdir / f"{qsid}.jsonl").write_text(line + "\n")
        os.utime(qdir / f"{qsid}.jsonl", (OLD, OLD))
    left = {sid for _, sid, _ in sl.pending(classify_first=True)}
    verdict = lambda sid: json.loads((Path(ENV["CLAUDE_SESSION_LEARNING_DIR"]) / f"{sid}.json").read_text())  # noqa: E731
    check("pending --classify keeps the session Simon typed in", "human-sess-1" in left, left)
    check("a runner-folder session and a message-less one leave the queue as empty",
          not {"runner-sess-1", "silent-sess-1"} & left
          and verdict("runner-sess-1")["verdict"] == verdict("silent-sess-1")["verdict"] == "empty"
          and "automated session path" in verdict("runner-sess-1")["source"])
    os.environ.pop("CLAUDE_IDENTITY_FILE")

    # ---- hook: non-repo cwd is a no-op; a repo cwd starts one detached sweep and debounces
    nr = sh(sys.executable, str(REAPER), "hook", env=ENV)
    check("hook with no payload exits 0", nr.returncode == 0)
    stamp_dir = home / ".claude" / "state" / "session-reaper"
    before = set(stamp_dir.glob("*.stamp"))
    t0 = time.time()
    h = subprocess.run([sys.executable, str(REAPER), "hook"], input=json.dumps({"cwd": str(repo), "session_id": SID}),
                       capture_output=True, text=True, env={**ENV, "CLAUDE_SESSION_REAPER_DOCKER": "off"})
    check("hook returns at once and prints nothing", h.returncode == 0 and not h.stdout and time.time() - t0 < 5)
    deadline = time.time() + 20
    while time.time() < deadline and len(set(stamp_dir.glob("*.stamp")) - before) < 1:
        time.sleep(0.2)
    check("hook's detached run stamps the repo for the 1 h debounce", len(set(stamp_dir.glob("*.stamp")) - before) == 1)
    off = subprocess.run([sys.executable, str(REAPER), "hook"], input=json.dumps({"cwd": str(repo)}),
                         capture_output=True, text=True, env={**ENV, "CLAUDE_SESSION_REAPER": "off"})
    check("CLAUDE_SESSION_REAPER=off disables the hook", off.returncode == 0)
finally:
    sleeper.kill()
    time.sleep(1.5)  # let a detached sweep from the hook check finish before the temp tree goes
    subprocess.run(["rm", "-rf", str(tmp)])

print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
