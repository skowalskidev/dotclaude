#!/usr/bin/env python3
"""bin/monitoring_only.py: the path globs, the overlay validation, and the intake listing.

The listing is what hooks/task-intake.sh adds on a session's first task prompt: it names the open PRs
whose every file is monitoring-only, makes one gh call per session, and says nothing when there are
none or gh fails. Everything runs against a throwaway registry, HOME and fake gh.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("monitoring_only", HERE / "monitoring_only.py")
mo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mo)

PATHS = {"paths": ["ops/bot/**", ".claude/skills/bot-*/**", ".github/workflows/bot.yml"],
         "requiredChecks": ["Bot / test"], "offlineTests": ["python3 ops/bot/bot_test.py"]}
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_GH_MODE", "ok")
if mode == "error":
    sys.exit(1)
def f(*paths, kind="MODIFIED"):
    return [{"path": p, "changeType": kind} for p in paths]
prs = [
    {"number": 11, "isDraft": True, "headRefOid": "a" * 40, "changedFiles": 2,
     "files": f("ops/bot/bot.py", "ops/bot/bot_test.py")},
    {"number": 12, "isDraft": False, "headRefOid": "b" * 40, "changedFiles": 2,
     "files": f(".claude/skills/bot-fix/SKILL.md", ".github/workflows/bot.yml")},
    {"number": 13, "isDraft": False, "headRefOid": "c" * 40, "changedFiles": 2,
     "files": f("ops/bot/bot.py", "site/app.ts")},
    {"number": 14, "isDraft": False, "headRefOid": "d" * 40, "changedFiles": 1,
     "files": f("ops/bot/x.py", kind="RENAMED")},
]
if mode == "none":
    prs = prs[2:]
print(json.dumps(prs))
"""


class Globs(unittest.TestCase):
    def test_globs_keep_single_star_inside_a_segment(self):
        spec, error = mo.validate(PATHS)
        self.assertEqual(error, "")
        for path in ("ops/bot/bot.py", "ops/bot/deep/nested/x.py", ".claude/skills/bot-fix/SKILL.md",
                     ".github/workflows/bot.yml"):
            self.assertTrue(mo.path_matches(path, spec), path)
        wide = {"paths": ["ops/bot/**", "*hub/**", ".github/workflows/bot.yml"], "requiredChecks": ["Bot / test"],
                "offlineTests": ["x"]}
        self.assertFalse(mo.path_matches("ops/bot/package.json", wide))  # a manifest is literal only
        self.assertFalse(mo.path_matches("ops/bot/action.yml", wide))
        self.assertFalse(mo.path_matches("ops/bot/.github/workflows/x.yml", wide))  # a nested .github too
        for runner in ("ops/bot/justfile", "ops/bot/GNUmakefile", "ops/bot/x.pth", "ops/bot/sitecustomize.py",
                       "ops/bot/tsconfig.build.json", "ops/bot/worker/wrangler.toml", "ops/bot/import_map.json",
                       "ops/bot/vitest.workspace.ts", "ops/bot/types.d.ts", "ops/bot/__main__.py",
                       "ops/bot/.cargo/config.toml", "ops/bot/.husky/pre-commit.sh"):
            self.assertFalse(mo.path_matches(runner, wide), runner)
        self.assertFalse(mo.path_matches(".github/workflows/deploy.yml", wide))  # a workflow is literal only
        for path in ("ops/botty/x.py", "ops/bot", ".claude/skills/bot-fix", ".claude/skills/other/bot-x/a.md",
                     ".github/workflows/deploy.yml", "site/ops/bot/x.py", "ops/bot/../site/x.ts", "/ops/bot/x",
                     "ops/bot//a.py", "ops/bot/./a.py"):
            self.assertFalse(mo.path_matches(path, spec), path)

    def test_validation_rejects_broad_or_globbed_workflow_entries(self):
        valid = {"paths": ["ops/bot/**"], "offlineTests": ["python3 ops/bot/bot_test.py"],
                 "requiredChecks": ["Bot / test"]}
        self.assertEqual(mo.validate(valid)[1], "")
        # Each case changes ONE field of a valid entry, so the error is that field's own.
        cases = [("paths", p) for p in (["**"], ["*/bot/**"], [".github/workflows/*.yml"], ["ops/bot**"],
                                        ["ops/**bot/x"], ["ops/bot/[ab]/**"], ["a*"], [".github/**"],
                                        ["ops/../site/**"], ["ops/bot/**/"], ["ops//bot/*"], ["ops/./bot/*"], ["ops/**/x/**"],
                                        ["ops/*a*b*c"], [], "ops/**")]
        cases += [("requiredChecks", ["test"]), ("requiredChecks", []), ("offlineTests", []),
                  ("offlineTests", [" "]), ("offlineTests", "x"), ("names", ["x;y"])]
        for field, value in cases:
            spec, error = mo.validate(dict(valid, **{field: value}))
            self.assertIsNone(spec, (field, value))
            self.assertIn(field, error, (field, value))
        for field in ("requiredChecks", "offlineTests"):
            spec, error = mo.validate({k: v for k, v in valid.items() if k != field})
            self.assertIsNone(spec, field)
            self.assertIn(field, error, field)
        self.assertIsNone(mo.validate([])[0])
        self.assertEqual(mo.validate(None), (None, ""))

    def test_an_unreadable_project_file_is_an_error_not_undeclared(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-broken-"))
        (reg / "projects").mkdir()
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "bot.json").write_text("{not json")
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            spec, error = mo.spec_for("acme/bot")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIsNone(spec)
        self.assertIn("could not be read", error)

    def test_a_broken_provider_record_does_not_stop_the_lookup(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-provider-"))
        (reg / "projects").mkdir()
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "bot.json").write_text(json.dumps({"match": ["acme/bot"], "monitoringOnly": PATHS}))
        (reg / "slack.json").write_text("{not json")
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            declared, undeclared = mo.spec_for("acme/bot"), mo.spec_for("acme/other")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual(declared[1], "")
        self.assertIsNotNone(declared[0])
        self.assertEqual(undeclared, (None, ""))

    def test_any_broken_project_file_stops_the_lookup(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-other-"))
        (reg / "projects").mkdir()
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "other.json").write_text('{"match": ["acme/widgets"], oops')
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            other, named = mo.spec_for("acme/bot"), mo.spec_for("acme/widgets")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIn("could not be read", other[1])  # a broken file may declare any repo
        self.assertIn("could not be read", named[1])

    def test_declared_owners_reads_project_files(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-owners-"))
        (reg / "projects").mkdir()
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "bot.json").write_text(json.dumps({"match": ["Acme/bot"], "monitoringOnly": PATHS}))
        (reg / "projects" / "web.json").write_text(json.dumps({"match": ["zed/web"]}))
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            owners = mo.declared_owners()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual(owners, {"acme"})

    def test_an_unreadable_identity_file_is_an_error_not_undeclared(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-ident-"))
        ident = reg / "id.json"
        ident.write_text("{not json")
        env = {"CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in ("CLAUDE_IDENTITY_FILE", "CLAUDE_CONNECTOR_ROOTS")}
        os.environ.update(env)
        os.environ.pop("CLAUDE_CONNECTOR_ROOTS", None)
        try:
            spec, error = mo.spec_for("acme/service")
            owners = mo.declared_owners()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIsNone(spec)
        self.assertIn("could not be read", error)
        self.assertIsNone(owners)

    def test_an_unlistable_projects_folder_is_an_error(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-unlist-"))
        (reg / "projects").mkdir()
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "bot.json").write_text(json.dumps({"match": ["acme/bot"], "monitoringOnly": PATHS}))
        os.chmod(reg / "projects", 0)
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            spec, error = mo.spec_for("acme/bot")
        finally:
            os.chmod(reg / "projects", 0o755)
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIsNone(spec)
        self.assertIn("could not be read", error)

    def test_a_missing_index_is_an_error_not_undeclared(self):
        reg = Path(tempfile.mkdtemp(prefix="mo-noindex-"))
        (reg / "projects").mkdir()
        (reg / "projects" / "bot.json").write_text(json.dumps({"match": ["acme/bot"], "monitoringOnly": PATHS}))
        ident = reg / "id.json"
        ident.write_text("{}")
        env = {"CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(ident)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            spec, error = mo.spec_for("acme/bot")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIsNone(spec)
        self.assertIn("could not be read", error)

    def test_a_long_name_is_never_slow_and_never_inside(self):
        import time
        spec, _ = mo.validate({"paths": ["ops/**", "ops/*a*b"], "offlineTests": ["x"], "requiredChecks": ["B / t"]})
        start = time.monotonic()
        self.assertFalse(mo.path_matches("ops/" + "a" * 5000 + ".py", spec))
        self.assertFalse(mo.path_matches("ops/" + "a" * 250 + "c.py", {"paths": ["ops/*a*b"]}))
        near = {"paths": ["ops/*a*a/*a*a/*a*a/*a*a/x.py"]}
        self.assertFalse(mo.path_matches("/".join(["ops"] + ["a" * 250] * 4 + ["y.py"]), near))
        self.assertLess(time.monotonic() - start, 1.0)

    def test_classify_fails_closed(self):
        spec, _ = mo.validate(PATHS)
        ok = [{"path": "ops/bot/a.py", "changeType": "MODIFIED"}]
        self.assertEqual(mo.classify(ok, 1, spec), "")
        self.assertIn("incomplete", mo.classify(ok, 2, spec))
        self.assertIn("incomplete", mo.classify(ok, True, spec))  # a boolean is no file count
        self.assertIn("could not be read", mo.classify([], 0, spec))
        self.assertIn("could not be read", mo.classify(None, None, spec))
        self.assertIn("renamed", mo.classify([{"path": "ops/bot/a.py", "changeType": "RENAMED"}], 1, spec))
        self.assertIn("unknown change type", mo.classify([{"path": "ops/bot/a.py"}], 1, spec))
        self.assertIn("changed", mo.classify([{"path": "ops/bot/a.py", "changeType": "CHANGED"}], 1, spec))
        self.assertIn("could not be read", mo.classify(ok + ok, 2, spec))  # a repeated path
        self.assertIn("site/a.ts is outside", mo.classify(ok + [{"path": "site/a.ts", "changeType": "ADDED"}], 2, spec))


class Pending(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitoring-only-test-"))
        reg = self.tmp / "registry"
        (reg / "projects").mkdir(parents=True)
        (reg / "index.json").write_text(json.dumps({"boundary": "personal", "match": []}))
        (reg / "projects" / "bot.json").write_text(json.dumps({"match": ["acme/bot"], "monitoringOnly": PATHS}))
        (self.tmp / "identity.json").write_text("{}")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)
        self.log = self.tmp / "gh.log"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "CLAUDE_CONNECTOR_ROOTS": f"personal={reg}", "CLAUDE_IDENTITY_FILE": str(self.tmp / "identity.json"),
                    "FAKE_GH_LOG": str(self.log)}
        for leaked in ("AGENT_DELEGATED_WORKER", "CLAUDE_INTAKE_GATE", "CLAUDE_CODE_SESSION_ID", "GH_REPO", "GH_HOST"):
            self.env.pop(leaked, None)

    def checkout(self, name, origin):
        d = self.tmp / name
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "remote", "add", "origin", origin], check=True)
        return d

    def pending(self, cwd, session, mode="ok"):
        p = subprocess.run([sys.executable, str(HERE / "monitoring_only.py"), "pending", "--cwd", str(cwd),
                            "--session", session], capture_output=True, text=True,
                           env={**self.env, "FAKE_GH_MODE": mode})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def gh_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_lists_only_prs_whose_every_file_matches_once_per_session(self):
        bot = self.checkout("bot", "git@github.com:acme/bot.git")
        line = self.pending(bot, "s1")
        self.assertIn("#11 (draft), #12.", line)
        self.assertNotIn("#13", line)  # a mixed-path PR is excluded
        self.assertNotIn("#14", line)  # a renamed file is excluded
        self.assertIn("run the monitoring-only bar on #N and merge when it passes", line)
        self.assertEqual(self.pending(bot, "s1"), "")  # cached: no second call this session
        self.assertEqual(len(self.gh_calls()), 1)

    def test_silent_on_gh_error_and_when_none_match(self):
        bot = self.checkout("bot", "git@github.com:acme/bot.git")
        self.assertEqual(self.pending(bot, "s2", mode="error"), "")
        self.assertEqual(self.pending(bot, "s2"), "")  # the claim stands after a failed read
        self.assertEqual(len(self.gh_calls()), 1)  # one call per session, failure included
        self.assertEqual(self.pending(bot, "s3", mode="none"), "")

    def test_a_repo_with_no_overlay_entry_makes_no_gh_call(self):
        web = self.checkout("web", "git@github.com:acme/web.git")
        self.assertEqual(self.pending(web, "s4"), "")
        bottle = self.checkout("bottle", "git@github.com:acme/bottle.git")  # extends a declared name
        self.assertEqual(self.pending(bottle, "s5"), "")
        self.assertEqual(self.gh_calls(), [])

    def test_a_prompt_the_ledger_cannot_record_leaves_the_unrecorded_marker(self):
        nowhere = self.tmp / "not-a-repo"
        nowhere.mkdir()
        payload = json.dumps({"session_id": "lost1", "cwd": str(nowhere), "prompt": "hold the bot fixes"})
        subprocess.run(["bash", str(HERE.parent / "hooks" / "intent-ledger.sh"), "submit"], input=payload, text=True,
                       capture_output=True, cwd=nowhere,
                       env={**self.env, "CLAUDE_CONFIG_ROOT": str(HERE.parent),
                            "CLAUDE_SESSION_ROOT_DIR": str(self.tmp / "roots"), "CLAUDE_PROJECT_DIR": str(nowhere)})
        self.assertTrue((self.home / ".claude" / ".intent-ledger" / "lost1.unrecorded").exists())

    def test_a_prompt_holding_a_nul_leaves_the_unrecorded_marker(self):
        bot = self.checkout("nulbot", "git@github.com:acme/bot.git")
        payload = json.dumps({"session_id": "nul1", "cwd": str(bot), "prompt": "Actually\u0000wait"})
        subprocess.run(["bash", str(HERE.parent / "hooks" / "intent-ledger.sh"), "submit"], input=payload, text=True,
                       capture_output=True, cwd=bot,
                       env={**self.env, "CLAUDE_CONFIG_ROOT": str(HERE.parent),
                            "CLAUDE_SESSION_ROOT_DIR": str(self.tmp / "roots"), "CLAUDE_PROJECT_DIR": str(bot)})
        self.assertTrue((self.home / ".claude" / ".intent-ledger" / "nul1.unrecorded").exists())

    def test_task_intake_carries_the_line(self):
        bot = self.checkout("bot", "git@github.com:acme/bot.git")
        cfg = HERE.parent
        payload = json.dumps({"session_id": "intake1", "cwd": str(bot), "prompt": "look at the failing alert row"})
        exclude = bot / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".context/\n")
        p = subprocess.run(["bash", str(cfg / "hooks" / "task-intake.sh"), "submit"], input=payload, text=True,
                           capture_output=True, cwd=bot,
                           env={**self.env, "CLAUDE_CONFIG_ROOT": str(cfg),
                                "CLAUDE_SESSION_ROOT_DIR": str(self.tmp / "roots"), "CLAUDE_PROJECT_DIR": str(bot)})
        context = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MONITORING-ONLY PRS open in this repo: #11 (draft), #12.", context)


if __name__ == "__main__":
    unittest.main()
