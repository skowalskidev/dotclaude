import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp, mkdir, writeFile, symlink, rm } from "node:fs/promises";
import { registerHooks } from "node:module";
import os from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import ts from "typescript";

registerHooks({
  resolve(specifier, context, next) {
    if (specifier.startsWith("./") && !path.extname(specifier)) {
      return next(`${specifier}.ts`, context);
    }
    return next(specifier, context);
  },
  load(url, context, next) {
    if (!url.endsWith(".ts")) return next(url, context);
    return {
      format: "module", shortCircuit: true,
      source: ts.transpileModule(readFileSync(new URL(url), "utf8"), {
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
      }).outputText,
    };
  },
});

test("the loose artifact list keeps its sorted 300-entry limit", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "gauntlet-artifacts-"));
  try {
    const plan = path.join(root, "task-plan.md");
    await writeFile(plan, '# Task\n```dashboard-state\n{"sections":[]}\n```\n');
    const names = Array.from({ length: 305 }, (_, i) => `file-${String(i).padStart(3, "0")}.txt`);
    await mkdir(path.join(root, "a"));
    names.push("a/child.txt", "a.txt");
    await Promise.all(names.map((name) => writeFile(path.join(root, name), "artifact")));
    const spec = await publicSpec(plan);
    assert.equal(spec.unlinkedTruncated, true);
    assert.deepEqual(spec.unlinked.map((item) => item.path), names.sort().slice(0, 300));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

const { subscribe } = await import("./watch.ts");
const { publicSpec } = await import("./plan.ts");

test("live updates and artifact discovery exclude build trees and linked caches", { timeout: 10_000 }, async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "gauntlet-watch-"));
  const dir = path.join(root, ".context");
  const plan = path.join(dir, "task-plan.md");
  const excluded = ["DerivedData", "SourcePackages", "result.xcresult", "node_modules", ".hidden", "coverage", "coverage-final-functions"];
  const state = { schemaVersion: 1, title: "Watcher regression", revision: 1, updatedAt: "now", sections: [] };
  const savePlan = () => writeFile(plan, `# Task\n\n\`\`\`dashboard-state\n${JSON.stringify(state)}\n\`\`\`\n`);
  let unsubscribe = () => {};
  let pulse;
  try {
    await mkdir(dir);
    for (const name of [...excluded, "captures"]) {
      await mkdir(path.join(dir, name, "nested"), { recursive: true });
      await writeFile(path.join(dir, name, "nested", "existing.txt"), "existing");
    }
    const cache = path.join(root, "outside-cache");
    await mkdir(cache);
    await writeFile(path.join(cache, "existing.txt"), "cached");
    await symlink(cache, path.join(dir, "linked-cache"), "dir");
    await savePlan();
    const events = [];
    const errors = [];
    let revisionSeen;
    const ready = new Promise((resolve) => { revisionSeen = resolve; });
    unsubscribe = subscribe(plan, (event) => {
      events.push(event);
      if (event.type === "revision") revisionSeen();
    }, (error) => errors.push(error));
    pulse = setInterval(() => { state.revision += 1; void savePlan(); }, 200);
    await Promise.race([ready, delay(4_000).then(() => { throw new Error("Plan changes were not observed"); })]);
    clearInterval(pulse);
    for (const name of excluded) await writeFile(path.join(dir, name, "nested", "changed.txt"), "generated");
    await writeFile(path.join(cache, "changed.txt"), "linked");
    await writeFile(path.join(dir, "captures", "nested", "changed.txt"), "artifact");
    await delay(500);
    assert.deepEqual(errors, []);
    const assets = events.filter((e) => e.type === "asset").map((e) => e.path);
    assert.ok(assets.includes("captures/nested/changed.txt"));
    assert.deepEqual(assets.filter((name) => name !== "linked-cache"), ["captures/nested/changed.txt"]);
    const spec = await publicSpec(plan);
    assert.deepEqual(spec.unlinked.map((item) => item.path), ["captures/nested/changed.txt", "captures/nested/existing.txt"]);
    unsubscribe();
    const count = events.length;
    await writeFile(path.join(dir, "captures", "nested", "closed.txt"), "closed");
    await delay(250);
    assert.equal(events.length, count);
  } finally {
    clearInterval(pulse);
    unsubscribe();
    await rm(root, { recursive: true, force: true });
  }
});
