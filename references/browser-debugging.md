# Live browser debugging — chrome-devtools MCP

A user-scope MCP for verifying UI changes in a **real, logged-in browser** — the live-eyes complement to automated tests (Playwright/Cypress/etc.). Use it to sanity-check a flow visually, grab screenshots, and inspect real network calls; keep automated specs as the committed regression coverage.

## The test browser — every browser operation runs in Chrome for Testing

**DO run every browser operation in Chrome for Testing, the visibly marked test browser: co-pilot
walks, eyeball passes, screenshots, login flows, and any state Simon is to look at or click.** Launch
it with `~/.claude/bin/test-browser.sh launch` (resolves the newest Playwright build at run time) and
attach the chrome-devtools MCP to it. Playwright's bundled Chromium is the same browser, so a
Playwright run also qualifies.
**DON'T open, attach to, or drive Simon's everyday Chrome, with any profile or isolated context.** He
cannot tell which window is his, and he clicks in the wrong one. (the fix for a co-pilot walk opened in
his own Chrome window)
**DO seed a state he is to see or click inside the test browser and hold it open: 1 window per viewport
he needs**, sized with `--size` (e.g. 390x844 phone, 1280x800 desktop) and placed with `--pos`. For a
scripted scenario, a headed Playwright run with `headless: false` and no `channel` that walks to the
state and calls `page.pause()` does the same.
**DON'T set Playwright `channel: 'chrome'` or `executablePath` to Google Chrome**, and don't run a state
he is to look at headless.
WHY: a window marked "Chrome for Testing" is unmistakably the agent's, so he clicks only where he is meant to.
TEST: `ps -o command= -p $(lsof -nP -iTCP:9222 -sTCP:LISTEN -t)` names `Google Chrome for Testing`,
and no `/Applications/Google Chrome.app` process carries `--remote-debugging-port`.

**One walk surface: a walk reuses 1 tab, and every window it opens is closed before hand-back.** Owned here; `/sk:test-copilot` and `references/human-pacing.md` point to it.
**DO open 1 walk tab (`new_page`) for the whole walk, plus 1 isolated context per distinct account or fresh-visitor need.** Before opening another tab or context for a step, close the one you opened for the previous step (`close_page`), unless the next step needs it. Reuse a tab by `navigate_page`, never by opening a sibling.
**DO name the surface in every step message by title and host:** "the **Checkout** tab at 127.0.0.1:3000", and say when the previous tab was closed ("closed the old walk tab").
**DO close every tab, window and isolated context you opened at the end of each walk and at hand-back. If you launched Chrome for Testing for the walk, close it too, unless Simon is still using it** (ask in the hand-back message, not before).
**DON'T close, navigate or reuse a tab you did not open.** Another session may own it. A walk that has to share the browser leaves the other tabs as found.
WHY: each isolated context shows as its own window, so a tab per step left Simon asking "which tab? there are many open".
TEST: `list_pages` during the walk shows 1 walk tab per live account plus the tabs you found; after hand-back it shows only the tabs you found, and no Chrome for Testing process you launched is left running.

**Fit the window: an emulated phone viewport must fit the test window's visible content area.** Launch with `--size 1280x900` (or taller), and emulate a viewport no taller than the window height minus 150 px for the browser chrome. Default: `402x750` inside `1280x900`. DON'T emulate 402x874 in a 1280x900 window: the page bottom falls below the visible area and the tester cannot reach it (hit twice in one project's walks).
TEST: a screenshot of the window shows the whole emulated viewport, bottom edge included, with no cut-off; `window.innerHeight` from `evaluate_script` is at most the content height.

**Setup:** launch the test browser as a SEPARATE instance with its OWN `--user-data-dir`, never your everyday profile:
`~/.claude/bin/test-browser.sh launch [--port 9222] [--profile "$HOME/.chrome-<project>-debug"] [--size WxH] <url>`. It exits 0 when the port is open (reusing a Chrome for Testing already there), 5 when the port belongs to another browser (pick another `--port`), 4 when no build is cached (`npx playwright install chromium`). The dedicated profile is what makes the port open reliably: passing `--remote-debugging-port` while a Chrome is ALREADY running on that profile just hands the flag to the running instance (it owns the profile's singleton lock), which never opens the port — `DevToolsActivePort` is never written, nothing binds 9222, and the MCP fails with "Could not connect". So poll until `curl -s http://127.0.0.1:9222/json/version` succeeds before attaching. A dedicated profile starts logged OUT, so sign in ONCE in that window; it persists the session across runs. The MCP attaches to that instance.

**Core loop:** `navigate_page` → `wait_for({text:[…]})` → `take_snapshot` (accessibility tree with `uid`s) → act via `click({uid})` / `fill` / `evaluate_script` → `take_screenshot`. `take_screenshot` accepts `{filePath}` (save straight to disk, e.g. for PR screenshots) and `{fullPage}`. Inspect the backend with `list_network_requests` + `get_network_request({reqid})` (status, request/response headers incl. bearer token, body).

**Capabilities = the LIVE tool list; don't scrape docs or cache a feature list.** The connected `chrome-devtools` tool set is authoritative and always current: Claude Code loads it at session start and refreshes on `notifications/tools/list_changed`, so the tools already in context ARE the up-to-date feature list — DO read them for what's actually enabled. This file covers the common debug loop, not all ~58 tools (extensions, performance tracing, memory/heap, emulation and others are flag-gated and often not loaded in a given session), so never assume the loop above is the whole surface. For a tool's full arguments WITHOUT a live connection, fetch the version-matched generated reference `docs/tool-reference.md` from `github.com/ChromeDevTools/chrome-devtools-mcp` (auto-generated from the tool source every release, so it can't drift). DON'T scrape the prose docs, hand-maintain a capability directory, or version-stamp a cached copy — both live sources are already current, so there is nothing to refresh.

**Gotchas (learned the hard way):**
- **Window width is unreliable.** `resize_page` often won't give a true desktop width (`window.innerWidth` can get stuck at ~315–500px regardless). Check it via `evaluate_script` before trusting a screenshot's layout; for authoritative desktop *and* mobile, run the framework's device projects (e.g. Playwright `chromium` 1280 + `mobile-chrome`) rather than the MCP window.
- **It hits whatever the running app points at** — often a **real cloud project**, not an emulator (the API may have no emulator host set even if emulators are running). Confirm the account/project before any write; never cross accounts/projects.
- **304 = cached.** After a backend change the app may keep returning the old body until the dev server reloads; hard-reload once it has.
- **Auth without UI login:** mint an ID token via Admin SDK `createCustomToken(uid)` → Identity Toolkit `signInWithCustomToken` REST (with the project's public web API key) → call the API directly. Lets you test as any user (e.g. a teammate) without switching the browser session. **`createCustomToken` needs a SIGNING credential: init `admin.credential.cert(<sa-key-path>)` with a service-account key that carries a `private_key` (pass the PATH, never cat it).** A user ADC (`application_default_credentials.json` / `gcloud auth application-default login`) CANNOT sign it — it fails `auth/invalid-credential` / `iam.serviceAccounts.signBlob` denied — so reach for a real SA key, not the ADC. For a fully unattended headless login (no way to run JS in the page), seed the minted session straight into the app origin's IndexedDB (`firebase:authUser:<apiKey>:<appName>`) and reload, instead of the page-context `signInWithCustomToken`.

**Password-free preview login pattern (for driving the actual client UI, not just calling APIs):** mint a custom token server-side → call `signInWithCustomToken` in the page context with the app's real client SDK (so `onAuthStateChanged` fires and client-side reads/writes get a token) → POST the resulting ID token to the app's session endpoint to set its session cookie → navigate to the authenticated route; auth then persists through the SDK's normal local persistence. Each project documents its own specifics (test-account id, session endpoint, any dev-only sign-in bridge needed) in its own testing playbook — don't re-derive the pattern per project, but do look up the concrete details there.

**Keep it user-scope** — don't add chrome-devtools to a project's committed `.mcp.json` unless the team adopts it. Per-project specifics (test accounts, ports, URLs, which cloud project it hits) belong in that repo's gitignored `CLAUDE.local.md`, not here.

**Publish an HTML file as a claude.ai artifact when the harness has no Artifact tool:** in the signed-in debug Chrome, open `https://claude.ai/new`, click the composer's "Add files, connectors, and more" menu, call `upload_file` on its "Add files or photos" item with the absolute file path, fill the prompt "Publish the attached file as an HTML artifact exactly as it is, byte for byte, no edits; give me the share link", send, then `wait_for` `claude.ai/artifact/` and read the link. claude.ai's own agent copies the file and reports its hash; compare it with `shasum -a 256` locally. The profile starts signed out: ask Simon to sign in first (`rules/connectors.md` auth gate) and leave that window open through the hand-back; close it only after he replies. (the fix for closing the window he had just been asked to sign into)
