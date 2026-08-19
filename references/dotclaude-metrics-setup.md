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

1. **Create a dedicated project** (any id; keep it separate from any work project):
   ```bash
   firebase projects:create YOUR-METRICS-PROJECT --account you@example.com
   ```
   Enable **Firestore (Native mode)**; enable billing if you want TTL auto-deletion (stays within the
   free quota).

2. **Least-privilege service account + key** (personal account):
   ```bash
   PROJ=YOUR-METRICS-PROJECT; ACC=you@example.com
   SA=metrics-writer@$PROJ.iam.gserviceaccount.com
   gcloud iam service-accounts create metrics-writer --project=$PROJ --account=$ACC
   gcloud projects add-iam-policy-binding $PROJ --member="serviceAccount:$SA" \
     --role="roles/datastore.user" --account=$ACC --condition=None
   mkdir -p ~/.config/firebase-keys
   gcloud iam service-accounts keys create ~/.config/firebase-keys/dotclaude-metrics.json \
     --iam-account=$SA --project=$PROJ --account=$ACC
   chmod 600 ~/.config/firebase-keys/dotclaude-metrics.json
   ```
   Rotate this key at least every 90 days.

3. **Isolated venv with the Admin SDK** (the hooks find it automatically):
   ```bash
   python3 -m venv ~/.config/claude-metrics-venv
   ~/.config/claude-metrics-venv/bin/pip install firebase-admin
   ```

4. **Lock the Firestore rules** — raw events server-only, computed aggregates owner-read:
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{db}/documents {
       match /sessions/{d}        { allow read, write: if false; }
       match /session_events/{d}  { allow read, write: if false; }
       match /runs/{d}            { allow read, write: if false; }
       match /pipeline_health/{d} { allow read, write: if false; }
       match /aggregates/{d} {
         allow read: if request.auth != null
                     && request.auth.uid == "YOUR-AUTH-UID"
                     && request.auth.token.email_verified == true;
         allow write: if false;   // Admin SDK only
       }
     }
   }
   ```
   The Admin SDK bypasses these, so the collectors still write.

## Retention

Every doc carries an `expireAt` field. Two ways to expire old data:
- **Firestore TTL policy** (needs billing enabled): `gcloud firestore fields ttls update expireAt
  --collection-group=<coll> --enable-ttl`. Auto-deletes within ~24h of expiry.
- **Billing-free equivalent** (no billing needed): `config-metrics.py --prune` deletes expired docs
  via the Admin SDK (plain deletes are free within quota). Run it periodically; it is a no-op until
  the retention horizon passes. Use this when the project's billing account is at its project quota.

## Config knobs (environment, all optional)

- `CLAUDE_METRICS_SA_KEY` — key path (default `~/.config/firebase-keys/dotclaude-metrics.json`).
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

To view the dashboard from anywhere, deploy `console/` to Firebase Hosting with the Auth Google
provider + App Check enabled and the owner-UID rule above. The client reads only `aggregates/*`. Until
then, `bin/config-metrics.py --html` writes a self-contained local `metrics/dashboard.html`.
