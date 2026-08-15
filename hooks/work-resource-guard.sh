#!/usr/bin/env bash
# work-resource-guard.sh
# PreToolUse hook enforcing WORK <-> PERSONAL resource isolation (both directions).
# Work repo == git origin remote contains your work org (identity.local.json "workOrgMatch").
#   * WORK repos     : block PERSONAL resources (personal Codex CLI, your personal cloud project,
#                      personal secrets, ~/.config/personal-keys.env, direct personal Gemini API).
#   * PERSONAL repos : block WORK resources (the `pal` MCP server; the ~/.codex-work Codex
#                      home; your work email account; your work cloud projects; and firebase
#                      commands while the CLI's active account is the work one).
# git/gh and gstack's Claude review are allowed everywhere.
#
# The work/personal VALUES this guard compares against live in an untracked overlay,
# ~/.claude/identity.local.json (copy identity.example.json and fill in your accounts). Only the
# literals are read from the file; all logic and messages stay here. An empty/absent value makes the
# one rule that needs it no-op (fail open) rather than match everything.

PY=/usr/bin/python3
input="$(cat)"

meta="$(printf '%s' "$input" | "$PY" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
ti=d.get("tool_input",{}) or {}
print(d.get("tool_name","") or "")
print((ti.get("command","") or "").replace(chr(10)," "))' 2>/dev/null)"
tool="$(printf '%s\n' "$meta" | sed -n 1p)"
cmd="$(printf '%s\n' "$meta" | sed -n 2p)"

# --- identity overlay: the work/personal values this guard compares against ---
# CLAUDE_IDENTITY_FILE overrides the path (used by the test to drive off a fixture overlay).
ID_FILE="${CLAUDE_IDENTITY_FILE:-$HOME/.claude/identity.local.json}"
WORK_ORG_MATCH=""; WORK_EMAIL=""; PERSONAL_EMAIL=""; WORK_PROJECTS_RE=""; PERSONAL_PROJECT=""
if [ -f "$ID_FILE" ] && command -v jq >/dev/null 2>&1; then
  WORK_ORG_MATCH="$(jq -r '.workOrgMatch // ""' "$ID_FILE" 2>/dev/null)"
  WORK_EMAIL="$(jq -r '.workEmail // ""' "$ID_FILE" 2>/dev/null)"
  PERSONAL_EMAIL="$(jq -r '.personalEmail // ""' "$ID_FILE" 2>/dev/null)"
  # Alternation for a regex, longest-first so a prefix can't shadow a longer id.
  WORK_PROJECTS_RE="$(jq -r '(.workCloudProjects // []) | sort_by(-length) | join("|")' "$ID_FILE" 2>/dev/null)"
  PERSONAL_PROJECT="$(jq -r '.personalCloudProject // ""' "$ID_FILE" 2>/dev/null)"
fi

# Determine work context from the project's git origin.
dir="${CLAUDE_PROJECT_DIR:-$PWD}"
remote="$(git -C "$dir" remote get-url origin 2>/dev/null)"
is_work=0
[ -n "$WORK_ORG_MATCH" ] && case "$remote" in *"$WORK_ORG_MATCH"*) is_work=1 ;; esac

deny() {
  "$PY" -c 'import sys,json
print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":sys.argv[1]}}))' "$1"
  exit 0
}

# is_cmd <program>: true only when <program> is INVOKED (command position) in $cmd —
# at the start, after a shell separator (; & | (), or after leading VAR=val assignments.
# This deliberately does NOT match the program name appearing inside a quoted argument
# (e.g. codex exec "...firebase..." or git commit -m "fix firebase") so prose never trips
# a CLI-account check. Case-sensitive: real CLI names are lowercase.
is_cmd() {
  printf '%s' "$cmd" | grep -qE "(^|[;&|(]|&&|\|\|)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*$1([[:space:]]|$)"
}

# --- connector manifests: data-driven work/personal boundary + read-only/gated lookups (~/.claude/connectors/) ---
CONN_DIR="$HOME/.claude/connectors"
# The CURRENT project's manifest (matched by git origin), for reading this repo's own connector config.
CONN_MANIFEST="$("$HOME/.claude/bin/connectors-provision.sh" --manifest "$dir" 2>/dev/null || true)"
# A connector NAME can appear under more than one boundary (e.g. `firebase` is work in one manifest AND
# personal in another), so boundary isolation uses the SET of boundaries the name appears under
# across ALL manifests: deny only if that set is non-empty and does NOT include the current repo's boundary.
connector_boundaries() { # $1=server -> unique boundaries across all manifests, one per line
  command -v jq >/dev/null 2>&1 || return 0
  local f
  for f in "$CONN_DIR"/*.json; do
    [ -e "$f" ] || continue
    jq -r --arg n "$1" '.connectors[]? | select(.name==$n) | (.boundary // empty)' "$f" 2>/dev/null
  done | sort -u
}
connector_field() { # $1=server $2=field, from THIS project's manifest only (empty if none)
  command -v jq >/dev/null 2>&1 || return 0
  [ -n "$CONN_MANIFEST" ] && [ -f "$CONN_MANIFEST" ] || return 0
  jq -r --arg n "$1" --arg k "$2" '.connectors[]? | select(.name==$n) | (.[$k] // empty)' "$CONN_MANIFEST" 2>/dev/null | head -1
}
connector_cli_profile() { # $1=CLI name -> the profile THIS project pins for it (empty if none declared)
  command -v jq >/dev/null 2>&1 || return 0
  [ -n "$CONN_MANIFEST" ] && [ -f "$CONN_MANIFEST" ] || return 0
  jq -r --arg n "$1" '.connectors[]? | select(.kind=="cli" and ((.cli.name // "")==$n)) | (.cli.profile // empty)' "$CONN_MANIFEST" 2>/dev/null | head -1
}

# --- pal MCP tools are a WORK resource (they use the work API keys). Allow only in WORK repos. ---
case "$tool" in
  mcp__pal__*)
    [ "$is_work" -eq 1 ] && exit 0
    deny "Blocked by work/personal isolation: 'pal' holds your WORK API keys, and this is a personal/non-work repo. Work resources must not be used here. Use gstack review + your personal Codex login instead."
    ;;
esac

# --- all other MCP tools: data-driven work/personal isolation + prod read-only/gated write-guard ---
case "$tool" in
  mcp__*)
    _rest="${tool#mcp__}"; _server="${_rest%%__*}"; _mtool="${_rest#*__}"
    _cur=personal; [ "$is_work" -eq 1 ] && _cur=work
    _bs="$(connector_boundaries "$_server")"
    if [ -n "$_bs" ] && ! printf '%s\n' "$_bs" | grep -qxF "$_cur"; then
      deny "Blocked by work/personal isolation: MCP server '$_server' is not a $_cur connector (it belongs to: $(printf '%s' "$_bs" | tr '\n' ' ')). Work and personal resources must not cross."
    fi
    case "$_mtool" in
      *delete*|*set_*|*_set|*update*|*create*|*write*|*remove*|*send*)
        if [ "$(connector_field "$_server" readOnly)" = "true" ]; then
          deny "PROD is READ-ONLY: '$_server' must not run a write tool ($_mtool). To write, tell the user UP FRONT: run '/sk:setup-connectors enable-prod-write', then confirm the exact change. No prod data changes until then."
        fi
        if [ "$(connector_field "$_server" gated)" = "true" ] && [ "${CLAUDE_PROD_WRITE_OK:-0}" != "1" ]; then
          deny "GATED write on '$_server' ($_mtool): needs the user's explicit per-write confirmation. Ask FIRST, name the exact change, proceed only on an explicit yes."
        fi
        ;;
    esac
    exit 0
    ;;
esac

# --- Bash tool: enforce isolation in BOTH directions ---
# Note: `git add` is intentionally NOT gated here — normal staging must always work. Secrets are kept
# out of repos by the design (files live in ~/.claude / ~/.config), the .gitignore layers (global
# `~/.gitignore_global` ignores `.env.op`, `*serviceAccountKey*.json`, `.firebase/` so `git add .` never
# stages them), and gitleaks/pre-commit content scanning — not by blocking git commands.
if [ "$tool" = "Bash" ]; then
  # A command that ONLY drives git is exempt. The header contract above says git is allowed
  # everywhere and the guard's own contract entry says staging must always work, but the
  # NAME-based rules below matched anywhere in the command text, so a boundary name appearing
  # as a FILE PATH blocked reading the file (e.g. `git diff connectors/<other-boundary>.json`
  # denied the manifest that documents that boundary). A name in a path is a file being read,
  # not a resource being used — the same distinction crown-jewel-read-guard.py draws by asking
  # about the verb. A compound that also invokes any other CLI is NOT pure git and falls through
  # to every rule below, so `git pull && firebase --project <other> deploy` is still denied.
  if is_cmd git && \
     ! { is_cmd firebase || is_cmd gcloud || is_cmd gsutil || is_cmd bq || is_cmd aws \
         || is_cmd stripe || is_cmd codex || is_cmd gh || is_cmd npx || is_cmd node \
         || is_cmd python3 || is_cmd curl || is_cmd op || is_cmd sh || is_cmd bash; }; then
    exit 0
  fi

  if [ "$is_work" -eq 1 ]; then
    # WORK repo: block PERSONAL resources.
    # Personal cloud project id (from the overlay) used anywhere in the command.
    if [ -n "$PERSONAL_PROJECT" ]; then
      case "$cmd" in
        *"$PERSONAL_PROJECT"*) deny "Blocked by work-resource policy: '$PERSONAL_PROJECT' is your PERSONAL Firebase/GCP project. Work uses your work cloud projects only." ;;
      esac
    fi
    case "$cmd" in
      *secrets/firebase-keys*) deny "Blocked by work-resource policy: personal service-account key path. Work must use work credentials." ;;
      *personal-keys.env*)     deny "Blocked by work-resource policy: '~/.config/personal-keys.env' holds your PERSONAL API keys. Work must not read personal keys. Use pal's work-keyed models instead." ;;
      *--project-name=personal*) deny "Blocked by work-resource policy: a Stripe PERSONAL profile (--project-name=personal) in a work repo. Use your work Stripe profile." ;;
      *generativelanguage.googleapis*)
        # A direct Gemini API call is allowed in a WORK repo IF it uses the WORK Gemini key,
        # which lives in your work pal-mcp-server .env — a legit work call references that
        # path. Any other direct Gemini call (personal-keys.env is already caught above; a
        # hardcoded or otherwise-sourced key) stays blocked.
        case "$cmd" in
          *pal-mcp-server*) : ;;
          *) deny "Blocked by work-resource policy: direct Gemini API call without the WORK key. In work repos read the key from your work pal-mcp-server .env (or use pal), never a personal/hardcoded key." ;;
        esac
        ;;
    esac

    # Stripe LIVE (production) writes are gated; live reads are fine.
    if is_cmd stripe && printf '%s' "$cmd" | grep -qE -- '(--live|--project-name=work-prod)'; then
      case "$cmd" in
        *" post "*|*" delete "*|*" post"|*" delete"|*" trigger "*)
          [ "${CLAUDE_PROD_WRITE_OK:-0}" = "1" ] || deny "Blocked: Stripe LIVE/production write. Ask the user FIRST and get explicit confirmation for this exact change; live reads are fine, live writes are gated." ;;
      esac
    fi

    if is_cmd codex; then
      verdict="$(WORK_EMAIL="$WORK_EMAIL" "$PY" -c '
import json,os,base64
work_email=os.environ.get("WORK_EMAIL","")
try:
    home=os.environ.get("CODEX_HOME") or "~/.codex"
    d=json.load(open(os.path.join(os.path.expanduser(home),"auth.json")))
except Exception:
    print("BAD:no-auth"); raise SystemExit
if d.get("auth_mode")=="apikey":
    print("OK"); raise SystemExit
email=""
try:
    t=d.get("tokens",{}).get("id_token","").split(".")[1]; t+="="*(-len(t)%4)
    email=json.loads(base64.urlsafe_b64decode(t)).get("email","")
except Exception:
    pass
# No work email configured -> cannot judge -> fail open.
print("OK" if (not work_email or email==work_email) else "BAD:"+(email or "unknown"))
' 2>/dev/null)"
      case "$verdict" in
        OK) : ;;
        *) deny "Blocked by work-resource policy: the Codex CLI is authenticated as your PERSONAL ChatGPT account (${verdict#BAD:}), not work. Work must not use personal ChatGPT/Codex. Use pal's API models with the work OpenAI key (e.g. 'codereview ... with gpt-5'), or run 'codex login' with your work account / set a work OPENAI_API_KEY (auth_mode=apikey), then retry." ;;
      esac
    fi

    # Firebase CLI has a single GLOBAL active account; in a work repo it must be the work one.
    if is_cmd firebase; then
      case "$cmd" in
        *login:use*|*login:list*|*login:add*|*logout*|*--account*|*--help*|*" help"*) : ;;
        *)
          fb_active="$(firebase login:list 2>/dev/null | grep -iE 'logged in as' | head -1)"
          # Empty WORK_EMAIL, or an unreadable active account, fails open (the "" arm + a
          # match-everything glob when WORK_EMAIL is empty both land on the allow branch).
          case "$fb_active" in
            ""|*"$WORK_EMAIL"*) : ;;  # work account active, or can't determine (fail open)
            *) deny "Blocked by work-resource policy: the Firebase CLI active account is not your WORK account (${WORK_EMAIL:-your work email}), but this is a work repo. Switch first: firebase login:use ${WORK_EMAIL:-<your-work-email>}  (or pass --account ${WORK_EMAIL:-<your-work-email>})." ;;
          esac
          ;;
      esac
    fi
  else
    # PERSONAL / other repo: block WORK resources (mirror image of the above).
    case "$cmd" in
      *codex-work*)       deny "Blocked by personal-resource policy: '~/.codex-work' is your WORK Codex home (work OpenAI key). In a personal repo use your personal Codex (~/.codex) — do not point CODEX_HOME at the work home." ;;
    esac

    # The work account as an ARGUMENT to a CLI that actually switches accounts. Gated on the CLI
    # being invoked, so the address merely appearing in prose — a commit message, a quoted argument,
    # a doc being echoed — is not a block. That is the false-positive class that retired the old
    # text-matching security guard, and hooks/work-resource-guard.test.py pins it.
    if [ -n "$WORK_EMAIL" ] \
       && printf '%s' "$cmd" | grep -qF "$WORK_EMAIL" \
       && { is_cmd firebase || is_cmd gcloud || is_cmd aws || is_cmd gh || is_cmd npx; }; then
      deny "Blocked by personal-resource policy: '$WORK_EMAIL' is your WORK account. Personal repos must use ${PERSONAL_EMAIL:-your personal account}."
    fi

    # Stripe profile rules. Both are gated on is_cmd so the flag merely APPEARING in a commit message,
    # a test script or a quoted argument never trips them — the same false-positive class that retired
    # the old text-matching security guard.
    if is_cmd stripe; then
      case "$cmd" in
        *--project-name=work*) deny "Blocked by personal-resource policy: a Stripe WORK profile (--project-name=work*) in a personal repo. Use your personal Stripe profile." ;;
      esac
    fi

    # A BARE `stripe` command is the hole the rule above cannot see: with no --project-name it falls
    # through to the CLI's [default] profile, which on your machine may be the WORK account holding a
    # LIVE key. So require a profile to be pinned; the work variants are already denied just above.
    # The expected name comes from this project's manifest, so the guard stays data-driven.
    if is_cmd stripe; then
      case "$cmd" in
        *--project-name=*|*--help*|*" -h"*|*version*) : ;;
        *)
          _sp="$(connector_cli_profile stripe)"
          deny "Blocked by personal-resource policy: a bare 'stripe' command in a personal repo uses the CLI's [default] profile, which on your machine may be your WORK account (live key). Pin the personal profile explicitly: stripe --project-name=${_sp:-<your-personal-profile>} ...${_sp:+  (create it once with: stripe login --project-name=$_sp)}" ;;
      esac
    fi

    # Work Firebase/GCP project ids used with firebase/gcloud.
    if [ -n "$WORK_PROJECTS_RE" ] \
       && printf '%s' "$cmd" | grep -qiE '(firebase|gcloud)' \
       && printf '%s' "$cmd" | grep -qiE "(project[[:space:]=]+|use[[:space:]]+)($WORK_PROJECTS_RE)([^[:alnum:]-]|$)"; then
      deny "Blocked by personal-resource policy: your work cloud projects are for work repos only. Personal repos use '${PERSONAL_PROJECT:-your personal project}'."
    fi

    # Firebase CLI has a single GLOBAL active account; in a personal repo it must be personal.
    # (Skip account-management/help subcommands so the fix itself isn't blocked. If the command
    #  pins --account explicitly, trust that; an --account <work-email> is already caught above.)
    if [ -n "$WORK_EMAIL" ] && is_cmd firebase; then
      case "$cmd" in
        *login:use*|*login:list*|*login:add*|*logout*|*--account*|*--help*|*" help"*) : ;;
        *)
          fb_active="$(firebase login:list 2>/dev/null | grep -iE 'logged in as' | head -1)"
          case "$fb_active" in
            *"$WORK_EMAIL"*) deny "Blocked by personal-resource policy: the Firebase CLI active account is $WORK_EMAIL (WORK), but this is a personal repo. Switch first: firebase login:use ${PERSONAL_EMAIL:-<your-personal-email>}  (or pass --account ${PERSONAL_EMAIL:-<your-personal-email>})." ;;
          esac
          ;;
      esac
    fi
  fi
  exit 0
fi

exit 0
