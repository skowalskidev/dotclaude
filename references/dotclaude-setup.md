# dotclaude metrics — set up your own project

Generic setup for the config metrics system. Nothing here names a specific account, project, or org:
this repo is a public template, so anyone can stand up their own instance. Your specifics live
machine-local and gitignored; only placeholders are ever committed.

## What it does

A SessionEnd hook parses each session's transcript into minimized per-part events and writes them to a
personal Cloud Firestore project. `bin/config-metrics.py` scores every config part by usage + error
rate and renders a scoreboard + HTML console. `/sk:claude-config-metrics-self-analysis` reads it and
proposes trigger fixes for dead/underused parts.

**Zero-setup is fine.** With no project configured the collectors no-op to a local outbox and never
error — the system just collects nothing until you provision a project.

## One-time setup (your own personal account)

1. **Create a dedicated project + Firestore** (any id; keep it separate from any work project):
   ```bash
   PROJ=YOUR-METRICS-PROJECT; ACC=you@example.com
   firebase projects:create $PROJ --display-name "your name" --account $ACC
   gcloud services enable firestore.googleapis.com identitytoolkit.googleapis.com --project=$PROJ --account=$ACC
   gcloud firestore databases create --location=us-central1 --type=firestore-native --project=$PROJ --account=$ACC
   ```
   The Firestore create can 404 for a minute right after the API is enabled (propagation) — just
   retry. Billing is NOT required (TTL is the only thing that needs it; use `--prune` instead, below).

2. **Least-privilege service account + key** (personal account):
   ```bash
   PROJ=YOUR-METRICS-PROJECT; ACC=you@example.com
   SA=metrics-writer@$PROJ.iam.gserviceaccount.com
   gcloud iam service-accounts create metrics-writer --project=$PROJ --account=$ACC
   gcloud projects add-iam-policy-binding $PROJ --member="serviceAccount:$SA" \
     --role="roles/datastore.user" --account=$ACC --condition=None
   mkdir -p ~/.config/firebase-keys
   gcloud iam service-accounts keys create ~/.config/firebase-keys/dotclaude.json \
     --iam-account=$SA --project=$PROJ --account=$ACC
   chmod 600 ~/.config/firebase-keys/dotclaude.json
   ```
   Rotate this key at least every 90 days.

3. **Isolated venv with the Admin SDK** (the hooks find it automatically):
   ```bash
   python3 -m venv ~/.config/claude-metrics-venv
   ~/.config/claude-metrics-venv/bin/pip install firebase-admin
   ```

4. **Lock the Firestore rules** — every raw collection server-only, computed aggregates owner-read.
   List ALL seven raw collections explicitly (an unlisted path defaults to deny, but be explicit):
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /sessions/{d}         { allow read, write: if false; }
       match /session_events/{d}   { allow read, write: if false; }
       match /runs/{d}             { allow read, write: if false; }
       match /retro_triggers/{d}   { allow read, write: if false; }
       match /intent_reconcile/{d} { allow read, write: if false; }
       match /isolate_runs/{d}     { allow read, write: if false; }
       match /pipeline_health/{d}  { allow read, write: if false; }
       match /aggregates/{d} {
         allow read: if request.auth != null
                     && request.auth.token.email == "you@example.com"
                     && request.auth.token.email_verified == true;
         allow write: if false;   // Admin SDK only
       }
     }
   }
   ```
   Deploy with `firebase deploy --only firestore:rules` (needs a machine-local `firebase.json` +
   `.firebaserc` pinning the project). The Admin SDK bypasses these, so the collectors still write.
   (Match on the verified email — simplest for a single owner; switch to `request.auth.uid == "..."`
   if you prefer the immutable id.)

## Retention

Every doc carries an `expireAt` field. Two ways to expire old data:
- **Firestore TTL policy** (needs billing enabled): `gcloud firestore fields ttls update expireAt
  --collection-group=<coll> --enable-ttl`. Auto-deletes within ~24h of expiry.
- **Billing-free equivalent** (no billing needed): `config-metrics.py --prune` deletes expired docs
  via the Admin SDK (plain deletes are free within quota). Run it periodically; it is a no-op until
  the retention horizon passes. Use this when the project's billing account is at its project quota.

## Config knobs (environment, all optional)

- `CLAUDE_METRICS_SA_KEY` — key path (default `~/.config/firebase-keys/dotclaude.json`).
- `CLAUDE_METRICS_PROJECT` — expected project id; if set, the writer refuses to write to any other
  project (fail-closed). If unset, it trusts the key's own `project_id`.
- `CLAUDE_METRICS_RETENTION_DAYS` — TTL horizon (default 365).
- `CLAUDE_METRICS_OUTBOX` — outbox path (default `~/.claude/metrics/outbox.jsonl`).

## What is captured (need-to-know only)

Which part fired, how it was triggered (the request's shape), the outcome, the error. Secrets and PII
are scrubbed and file/code content is dropped by `bin/dotclaude-redact.py` before anything leaves the
machine. Work-boundary sessions (see `identity.local.json`) contribute the config-part signal but
never their request text — work content never reaches a personal project.

## The hosted console (optional)

View the dashboard from anywhere. `bin/config-metrics.py --html` always writes a self-contained local
`metrics/dashboard.html`; the hosted version adds owner-only remote access. It reads only
`aggregates/*` (raw collections stay deny-all).

1. **Create a web app + get its config:**
   ```bash
   firebase apps:create web "metrics-console" --project YOUR-METRICS-PROJECT --account you@example.com
   firebase apps:sdkconfig web --project YOUR-METRICS-PROJECT --account you@example.com
   ```
2. **Enable Auth** — in the Firebase console, Authentication → Get started → enable **Google** (set a
   support email). (Auth cannot be initialized headlessly on a fresh project; this is the one console
   step. Afterwards, providers can be toggled via the Identity Toolkit admin API.)
3. **Owner-read rule** on `aggregates` — match your verified email (or UID):
   `allow read: if request.auth.token.email == "you@example.com" && request.auth.token.email_verified == true;`
4. **Deploy** — inject the web config (and App Check site key, below) into `console/index.html`, write
   it to a machine-local `public/`, and `firebase deploy --only hosting,firestore:rules`.

## Harden the project (do all of these)

Mirrors a well-secured Firebase project. None of these need billing.

- **App Check (reCAPTCHA Enterprise)** — attests every client request comes from your real app, so the
  public apiKey alone cannot mint a valid token:
  ```bash
  gcloud services enable firebaseappcheck.googleapis.com recaptchaenterprise.googleapis.com --project=P
  gcloud recaptcha keys create --web --domains=YOUR-PROJECT.web.app --integration-type=score --project=P
  # The firebaseappcheck admin API needs BOTH an auth token AND the x-goog-user-project header
  # (without it you get a quota-project 403). Base: https://firebaseappcheck.googleapis.com/v1
  TOKEN=$(gcloud auth print-access-token --account $ACC)
  H=(-H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: P" -H "Content-Type: application/json")
  # register the returned site key with App Check, then enforce it on Firestore:
  curl "${H[@]}" -X PATCH ".../v1/projects/P/apps/APP_ID/recaptchaEnterpriseConfig?updateMask=siteKey" -d '{"siteKey":"..."}'
  curl "${H[@]}" -X PATCH ".../v1/projects/P/services/firestore.googleapis.com?updateMask=enforcementMode" -d '{"enforcementMode":"ENFORCED"}'
  ```
  Init it in the client with `ReCaptchaEnterpriseProvider(siteKey)` (import `firebase-app-check.js`,
  `initializeAppCheck` before the first Firestore call). The Admin SDK bypasses enforcement, so the
  collectors keep writing. Auth's Identity Toolkit admin API needs the same `x-goog-user-project`
  header, and its config only exists AFTER you click Authentication → Get started once in the console.
- **Restrict the web API key** to your domains + the Firebase APIs only (the key is public by design,
  but restricting it limits misuse):
  ```bash
  gcloud services api-keys update KEY_ID --allowed-referrers="https://YOUR-PROJECT.web.app/*,http://localhost:*" \
    --api-target=service=identitytoolkit.googleapis.com --api-target=service=securetoken.googleapis.com \
    --api-target=service=firestore.googleapis.com --api-target=service=firebaseappcheck.googleapis.com \
    --api-target=service=recaptchaenterprise.googleapis.com --api-target=service=firebaseinstallations.googleapis.com
  ```
- **Least-privilege service account** — `roles/datastore.user` only (done in step 2 of setup). It cannot
  read Auth users or touch anything but Firestore.
- **Enforce email verification** in the owner rule (`email_verified == true`, above).
- **Deny-all raw collections; owner-read aggregates only** (the rules above). Verify with an
  unauthenticated read — it must return HTTP 403.

## Seed + verify

- **Seed** (optional, so the console isn't empty): `config-metrics.py --backfill 2` replays recent
  transcripts (signal only), and `--import-logs` ships the legacy `logs/*.jsonl` into the store.
- **Verify security**: an unauthenticated `GET` of any collection returns HTTP 403; the Admin SDK
  (collectors) still reads/writes after App Check is enforced.
- **Note on billing/TTL**: linking billing can fail with a project-quota error if your billing account
  is already at its project limit — that's why `--prune` exists (no billing needed). `expireAt` is
  stamped regardless, so a real TTL policy works retroactively if you enable billing later.
