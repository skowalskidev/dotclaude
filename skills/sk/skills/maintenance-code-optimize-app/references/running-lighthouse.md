# Running Lighthouse — how to measure (optimize-app)

The measurement mechanics for `/sk:maintenance-code-optimize-app`. SKILL.md holds the rules; this holds the exact commands.
Core principle: measure on a PRODUCTION build, run the tool yourself, and treat the tool itself as a
possible artifact.

## Production build only — dev-mode artifacts to discard (Rule 1 detail)

A `next dev` Lighthouse run is **worthless** for performance and actively misleading. Real case (a personal Next.js app,
2026-07): a localhost dev run reported **Performance 0.59 and LCP 36,338 ms**; the same code on a production
build measured **LCP 1,217 ms** — a ~30x difference. Nothing was wrong with the site.

Dev-mode artifacts that poison the report — recognise these and discard the run:
- `next-devtools` bundle (~750 KB resource / 218 KB transfer)
- `[turbopack]_browser_dev_hmr-client_*.js`
- `unminified-javascript` / `legacy-javascript` flagged **inside Next internals**
- `valid-source-maps` failing with "Map has no `mappings` field" on Next internals
- `bootup-time` dominated by `node_modules_next_dist_compiled_*.js`
- `render-blocking` on a huge unminified dev CSS bundle (~266 KB)

**Always do this instead:**
```bash
source ~/.nvm/nvm.sh && nvm use
npm run build && npx next start -p 3100     # port 3100 avoids clashing with a running dev server
```
Then audit `http://localhost:3100/`. Or audit the deployed site — but remember the deployed site does NOT
contain unmerged branch work.

## Run Lighthouse yourself via the debug Chrome (Rule 2 detail)

Never ask Simon to paste a Lighthouse JSON report. Drive it with the `chrome-devtools` MCP.

**Setup.** Simon's everyday Chrome usually runs WITHOUT `--remote-debugging-port`, and you cannot add the
flag to a running instance. **Do NOT kill his Chrome** — he loses his tabs. Launch a *separate* instance
with its own profile:
```bash
SCRATCH=<your scratchpad dir>
mkdir -p "$SCRATCH/chrome-debug-profile"
nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$SCRATCH/chrome-debug-profile" \
  --no-first-run --no-default-browser-check about:blank > "$SCRATCH/chrome-debug.log" 2>&1 &
sleep 5 && curl -s http://127.0.0.1:9222/json/version
```
A fresh profile is signed out — fine for public pages. For auth-gated pages use the password-free
custom-token login (see the project's testing playbook); **never type a password into a form.**

**`lighthouse_audit` EXCLUDES performance.** It returns accessibility / best-practices / SEO /
agentic-browsing only. For performance you must run `performance_start_trace` separately:
```
emulate: viewport 412x823x2.625,mobile,touch · networkConditions "Slow 4G" · cpuThrottlingRate 4
performance_start_trace { reload: true, autoStop: true }
performance_analyze_insight { insightName: "LCPBreakdown" | "LCPDiscovery" | ... }
```
Reset `cpuThrottlingRate: 1` before running `lighthouse_audit` (it applies its own throttling).

Parse the JSON report yourself rather than eyeballing it:
```bash
node -e 'const r=require("./report.json");
for (const [id,a] of Object.entries(r.audits)) if (a.score!==null && a.score<1)
  console.log(`[${a.score}] ${id} — ${a.title}`);'
```

## Auditing the DEPLOYED URL (no chrome-devtools MCP) — pin Lighthouse to Node 24

When the `chrome-devtools` MCP isn't connected, or the target is the live production URL, run the
Lighthouse CLI yourself against a headless debug Chrome:
```bash
# 1. headless debug Chrome (separate profile — never touch Simon's main Chrome)
nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$SCRATCH/lh-chrome" \
  --no-first-run --no-default-browser-check --headless=new about:blank &>/dev/null &
# 2. install lighthouse into scratch and run it under NODE 24 (see below)
source ~/.nvm/nvm.sh && nvm use 24
npm i --no-save --prefix "$SCRATCH" lighthouse@latest
node "$SCRATCH/node_modules/lighthouse/cli/index.js" https://your-production-site.example/ \
  --port=9222 --only-categories=performance,accessibility,best-practices,seo \
  --output=json --output-path="$SCRATCH/lh.json" --quiet
```
**⚠️ `npx lighthouse` silently runs under whatever Node npx bundles (seen: v20.10.0), and that POISONS the
report** — Lighthouse 13.x audits use `URL.parse()` (needs Node ≥ 20.19/22) and several "insight" audits use
iterator methods that throw on old Node. When an audit **errors**, it nulls its whole category score, which
renders as a fake **`0`** (I got a phantom "SEO 0, Performance 73, LCP 8.9s" on a site that actually scored
SEO 100 / Perf 97 / LCP 2.1s). Always run Lighthouse under Node 24 (invoke `node .../lighthouse/cli/index.js`,
not `npx lighthouse`), and after parsing, **check for errored audits** — a null category score is a tooling
artifact, not a real 0:
```bash
node -e 'const r=require("./lh.json");
for (const [k,c] of Object.entries(r.categories)) console.log(k, c.score===null?"ERRORED (artifact)":Math.round(c.score*100));
const e=Object.entries(r.audits).filter(([i,a])=>a.scoreDisplayMode==="error");
console.log("errored audits:", e.map(x=>x[0]).join(", ")||"none");'
```
This is the same lesson as `next dev`: **the measuring tool itself can be the artifact.** A catastrophic
number that contradicts a healthy `observed*`/known-good baseline is guilty until proven real — check the
runner (Node version, errored audits, dev vs prod) before believing it.

## Lantern simulation ≠ what a user experiences (Rule 3 detail)

Lighthouse's Lantern **simulates** slow-4G + 4x CPU over the observed network graph. A huge simulated LCP
with a tiny `observedLargestContentfulPaint` means the simulation is choking on payload, not that the page is
broken. Always compare `observed*` metrics against the simulated ones before believing a catastrophic number,
and check the LCP breakdown (TTFB / load delay / load duration / render delay) to see where the time actually
is.
