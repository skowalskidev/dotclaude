---
name: work-preview-on-phone
description: Put this project's running dev server on Simon's phone over Tailscale, with login working, in any repo. Serves the local port to the tailnet only, adds the host to the dev server's cross-origin allowlist, mints a dev-only API credential when a referrer-locked key blocks auth, and tears the share down after. Use for "preview this on my phone", "test on mobile", "open this on my iPhone", "serve this over Tailscale", "check the mobile layout on a real device", or when a phone shows the page but nothing is clickable. Tailscale only, on purpose — it is tailnet-private, unlike a public tunnel.
argument-hint: "[optional: port, e.g. '3100']"
---

# Preview this project on the phone

**Why this exists:** the three things that break are invisible in the browser and each one looks like
one of the others. The page renders and nothing is clickable. Login fails with an error naming a URL.
A fix that worked reads as broken because the phone cached the old page. Each has a one-line cause
and none of them announce themselves.

**DO use `tailscale serve`. DON'T use `tailscale funnel`.** Serve routes "traffic from other devices
on your Tailscale network"; Funnel is "publicly available" and drops the identity headers
([Tailscale docs](https://tailscale.com/kb/1312/serve)). A dev server holds real credentials, real
data and no rate limiting, so Funnel puts all of it on the internet. This skill is Tailscale-only for
that reason — a public tunnel (zrok `share public`, ngrok) hits the identical three traps below AND
exposes the box.

## Step 1 · Bind the dev server to loopback, THEN serve it

**DO bind the dev server to `127.0.0.1` before sharing it.** Most dev servers bind every interface by
default, which puts a box holding real credentials, real data and no rate limiting on whatever network
the machine is on — a café or co-working Wi-Fi is every device on that Wi-Fi. Tailscale Serve proxies
from the machine's OWN loopback, so binding to loopback costs nothing and closes the LAN completely.

```bash
npm run dev -- -H 127.0.0.1      # Next; Vite: --host 127.0.0.1
```

TEST: `lsof -nP -iTCP:<port> -sTCP:LISTEN` shows `127.0.0.1:<port>`, not `*:<port>`. Then confirm the
hole is shut, from the machine's LAN address:

```bash
curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 "http://$(ipconfig getifaddr en0):<port>/"
```

TEST: it fails to connect. A `200` means it is still bound wide and the LAN can reach it.

## Step 2 · Serve the port to the tailnet

Take the port from the project's own dev command, never assume 3000 — a worktree may hold a lane
(`references/dev-server-hygiene.md`).

```bash
tailscale serve --bg http://localhost:<port>
```

First run per tailnet prints `Serve is not enabled on your tailnet` with a `login.tailscale.com/f/serve?node=…`
link. **DO hand Simon that exact link and wait.** It is a one-time tailnet setting only he can accept.

It prints the URL to open. **DO read the printed hostname and use it verbatim** — it is the host every
step below must match.

## Step 3 · Allow the host on the dev server, and verify the pattern MATCHES

**DO expect this to be already broken, because its failure is silent.** The dev server keeps returning
200 for every page and refuses only its own client assets, so the HTML renders, no JavaScript arrives,
and the page sits there un-hydrated. Nothing is clickable. It reads as "still loading". The only
signal is one warning line in the dev server log.

**DO grep the dev server's log for a blocked-origin warning before touching anything else.** It names
the host and the config key.

| Dev server | Key |
|---|---|
| Next.js | `allowedDevOrigins` in `next.config.*` |
| Vite | `server.allowedHosts` |
| Others | grep the startup log for "blocked", "origin" or "host" |

**DO run the host through the framework's own matcher rather than reading the pattern.** Next matches
per DNS LABEL: `*` is exactly one label, `**` is any depth. A MagicDNS name like
`machine-name.tailnet-id.ts.net` has TWO labels before `.ts.net`, so `*.ts.net` matches NOTHING and
looks correct while doing nothing.

```bash
node -e 'const {isCsrfOriginAllowed}=require("./node_modules/next/dist/server/app-render/csrf-protection.js");
console.log(isCsrfOriginAllowed("<the-printed-host>", ["**.ts.net"]))'
```

TEST: it prints `true`. If it prints `false` the pattern is wrong, whatever it looks like.

**DO add `100.*.*.*` alongside**, for the CGNAT address used when MagicDNS is off.
**DO restart the dev server.** A config change does not hot-reload.

## Step 4 · Auth, when the API key is origin-locked

A browser key restricted by HTTP referrer rejects every request from the new host. The error names the
URL, e.g. Firebase's `auth/requests-from-referer-<url>-are-blocked`.

**DON'T widen the production key's allowlist.** That restriction is the only thing stopping the key —
which ships publicly in the client bundle — being used from anywhere.

**DO mint a SEPARATE credential used only in development**, and gate it so production cannot reach it.
`NODE_ENV` is inlined into the client bundle at build, so the guard is compile-time, not a runtime hope:

```ts
apiKey: (process.env.NODE_ENV === "development" && process.env.<VAR>_DEV) || process.env.<VAR>
```

**DO restrict the dev credential by API, not by origin**, to every API the client actually calls. A
missing one fails LATER than login and looks unrelated — an app that signs in and then cannot load its
data. For Firebase web that is Identity Toolkit, Token Service, Cloud Firestore, Cloud Storage for
Firebase and Firebase Installations.

**DO write a test that the dev credential cannot be used in production.** TEST: set both variables with
`NODE_ENV=production` and assert the production one is chosen.

**DO check the cloud CLI's active account before creating anything** (`rules/security.md`): the active
account and the target project are set separately and are routinely from different identities. **DO
scope the command with an explicit account flag** rather than switching the global one, which would
disturb whatever else is signed in.

**DON'T print the credential.** Pipe it into the gitignored env file and confirm with a masked read.

**DO verify the new credential against the real API before believing it**, with no referer header:

```bash
curl -s -X POST "<api-endpoint>?key=$DEV" -H 'Content-Type: application/json' -d '<deliberately invalid body>'
```

TEST: it returns a VALIDATION error. A restriction error means the credential is wrong.

## Step 5 · The phone is caching the page

**DO open it in a private tab.** Safari caches the HTML document, which points at the previous asset
URLs, so a correct fix reads as no fix at all. This costs a whole debugging round every time it is
missed.

A `?v=<n>` query also works. Clearing website data is the last resort — it signs him out everywhere.

## Step 6 · Tear the share down

**DO stop serving when the preview is done** — it survives reboots otherwise.

```bash
tailscale serve --https=443 off
```

**DO confirm nothing was ever public**, since serve and funnel are one command apart:

```bash
tailscale funnel status    # expect: No serve config
```

Leave the dev-origin entry and the dev credential in place; both are development-only and are what
makes the next preview a single command.

## Report

Give him the URL, one line saying login works, and the teardown command. **DON'T claim it works
without a real load from the phone** — every failure here renders a page that looks fine.
