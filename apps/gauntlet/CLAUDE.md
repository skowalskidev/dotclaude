# Gauntlet app — agent notes

Reusable local dashboard for any project's `.context/<slug>-plan.md`. One server, one fixed port (4747), started by `~/.claude/bin/workflow-dashboard.py serve`.

Setup: `npm install` (Node 24 via nvm). Check: `npx tsc --noEmit && npm run lint && npm run build`. Dev: `npm run dev -- -p 4747`.

Contract files nobody but the orchestrator edits: `lib/types.ts`, `lib/paths.ts`, `lib/plan.ts`, `app/p/page.tsx`, `app/globals.css`, `app/layout.tsx`. Every other file states its owning slice in its first comment.

Rules: dark by default, colour only in ≤10px status dots, labels 2–5 words, no sentences unless a cost or data consequence, icon controls carry `aria-label` + `title`, assets are served by `/api/asset` (never base64), mockup html renders in a sandboxed iframe (never srcdoc), no project strings in the app.

# This is NOT the Next.js you know
Read the relevant guide in `node_modules/next/dist/docs/` before writing any code; APIs differ from training data.
