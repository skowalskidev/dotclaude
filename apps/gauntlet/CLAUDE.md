# Gauntlet app — agent notes

Reusable local dashboard for any project's `.context/<slug>-plan.md`. One server, one fixed port (4747), started by `~/.claude/bin/workflow-dashboard.py serve`.

Live watchers do not follow symlinks into caches. Watchers and the unlinked-artifact scan exclude hidden paths, dependencies, coverage caches, Xcode build/package directories and result bundles before descending. Keep this policy shared in `lib/artifacts.ts`; a task's build output must not exhaust the viewer's file handles. The unlinked scan stops after the first 300 sorted entries plus one to detect truncation. Watcher errors close the affected event stream so the browser can reconnect. Run `node --test lib/watch.test.mjs` for the real-filesystem regression.

Setup: `npm install` (Node 24 via nvm). Check: `npx tsc --noEmit && npm run lint && npm run build`. Dev: `npm run dev -- -p 4747`.

Completed sections open their Current evidence by default. Review sections open their Target; explicit role links retain any available asset. Sections without assets show their recorded summary and criteria. Keep historical targets available without presenting them as the finished implementation.

Contract files nobody but the orchestrator edits: `lib/types.ts`, `lib/paths.ts`, `lib/plan.ts`, `app/p/page.tsx`, `app/globals.css`, `app/layout.tsx`. Every other file states its owning slice in its first comment.

Rules: dark by default, colour only in ≤10px status dots, labels 2–5 words, no sentences unless a cost or data consequence, icon controls carry `aria-label` + `title`, assets are served by `/api/asset` (never base64), mockup html renders in a sandboxed iframe (never srcdoc), no project strings in the app.

# This is NOT the Next.js you know
Read the relevant guide in `node_modules/next/dist/docs/` before writing any code; APIs differ from training data.
