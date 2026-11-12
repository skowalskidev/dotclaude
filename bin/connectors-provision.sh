#!/usr/bin/env bash
# connectors-provision.sh — per-project connector provisioning and native-host discovery.
#
# Reads this project's effective connector set from the ONE loader, bin/connector_registry.py (the
# registry lives outside ~/.claude, one root per boundary; see references/connectors-setup.md), and
# registers its MCP servers at LOCAL scope (claude mcp add-json -s local). Runnable by hand, by
# hooks/session-connectors.sh, or by a Conductor scripts.setup. Never hard-codes a project. Fast (no
# `claude mcp list` / no network for the registration check). Designed to be safe in a hook: never
# exits non-zero, never blocks.
#
# It does NOT fetch secrets. A local route's `secret.path` is a DECLARATION of where its key lives so
# --check can report presence, and the key is created by hand from that route's own `auth.steps` (e.g.
# `gcloud iam service-accounts keys create`). A `secret.store: vault` route points at a Supabase Vault
# secret by name; --check reports it as `vault-pointer`, and `connector_registry.py run` reads it at use.
#
# Usage:
#   connectors-provision.sh [DIR]           provision the project at DIR (default: $PWD)
#   connectors-provision.sh --check [DIR]    print a readiness report (one line per connector: the
#                                            project's routes, then shared-account routes, no writes)
#   connectors-provision.sh --manifest [DIR] print the effective manifest JSON (or nothing)
#   connectors-provision.sh --host codex [--check] [DIR] inspect the launch-time Codex projection
#
# Which capability route to TRY first is a different question: bin/connector_registry.py resolve.
#
# Adapters by connector.kind: mcp-http | mcp-stdio (registered as MCP servers); api | service-key |
# cli | env | claude-connector | codex-app (no MCP registration; readiness is reported by --check,
# setup is via the auth-gate/doctor). claude-connector is a claude.ai account-level connector loaded
# from claude.ai connector settings; codex-app is an app in the Codex ChatGPT login, reached through
# codex exec. The engine registers neither; the boundary guard matches on the route `name`.
# A new kind = add a case below. See ~/.claude/references/connectors-setup.md for the schema.
set -u

# Codex consumes the manifest at launch; there is no second MCP configuration to update.
# Keep the Claude registration path below for Claude Code's native local scope.
if [ "${1:-}" = "--host" ]; then
  host="${2:-}"; shift 2
  case "$host" in
    codex)
      [ "${1:-}" = "--check" ] && shift
      exec python3 "$HOME/.claude/bin/agent_runtime.py" doctor --cwd "${1:-$PWD}"
      ;;
    claude) ;;
    *) echo "connectors: unsupported host" >&2; exit 2 ;;
  esac
fi

REGISTRY="$(cd "$(dirname "$0")" && pwd)/connector_registry.py"
PY="$(command -v /usr/bin/python3 || command -v python3)"
CLAUDE_JSON="$HOME/.claude.json"

have() { command -v "$1" >/dev/null 2>&1; }
expand_tilde() { case "$1" in "~/"*) printf '%s' "$HOME/${1#\~/}" ;; *) printf '%s' "$1" ;; esac; }

have jq || { echo "connectors: jq not found; cannot read the registry output" >&2; exit 0; }
[ -n "$PY" ] && [ -f "$REGISTRY" ] || { echo "connectors: python3 or connector_registry.py missing" >&2; exit 0; }

# --- parse args ---
mode="provision"; dir="$PWD"
case "${1:-}" in
  --check)    mode="check";    shift ;;
  --manifest) mode="manifest"; shift ;;
  -h|--help)  sed -n '2,27p' "$0"; exit 0 ;;
esac
[ -n "${1:-}" ] && dir="$1"
[ -d "$dir" ] || dir="$PWD"

top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$dir")"
# In a linked git worktree (a Conductor workspace), `claude mcp ... -s local` records the server under the
# MAIN worktree's path in ~/.claude.json, not the linked worktree's. Reading only "$top" therefore reports
# every already-registered server as "missing" forever, and the SessionStart precheck cries "NOT SET UP"
# about connectors that are loaded and working. Resolve the main worktree root so the read side matches the
# write side. Equals "$top" outside a worktree, and when git is absent.
top_main="$top"
gitcommon="$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
[ -n "$gitcommon" ] && [ -d "$gitcommon" ] && top_main="$(dirname "$gitcommon")"

# The effective connector set: the matched project's routes first, then shared-account routes of the
# same boundary (a project route wins a name clash). Matching and layering live in the loader only.
effective="$("$PY" "$REGISTRY" manifest --cwd "$dir" 2>/dev/null || true)"
count="$(printf '%s' "$effective" | jq -r '(.connectors // []) | length' 2>/dev/null || echo 0)"

if [ "$mode" = "manifest" ]; then
  [ "${count:-0}" -gt 0 ] || [ "$(printf '%s' "$effective" | jq -r '.project // empty' 2>/dev/null)" != "" ] \
    && printf '%s\n' "$effective"
  exit 0
fi
if [ "${count:-0}" -eq 0 ]; then
  echo "connectors: no registry project or shared route matches this repo ($dir)" >&2
  exit 0
fi

proj="$(printf '%s' "$effective" | jq -r '.project // "(shared-only)"')"

# Servers AVAILABLE this session, across ALL scopes Claude Code loads (fast, no network): local (keyed by
# BOTH this worktree and the main worktree — see top_main above) + user scope in ~/.claude.json, PLUS the
# committed project .mcp.json. A server present in ANY of these is usable now — so it must NOT be reported
# "missing" or "provision + restart" (that was the bug that told Claude a working `linear-server` wasn't
# loaded). Only genuinely-absent servers get provisioned/flagged.
registered=""
if [ -f "$CLAUDE_JSON" ]; then
  registered="$(jq -r --arg p "$top" --arg pm "$top_main" '((.projects[$p].mcpServers // {}) + (.projects[$pm].mcpServers // {}) + (.mcpServers // {})) | keys[]?' "$CLAUDE_JSON" 2>/dev/null)"
fi
if [ -f "$top/.mcp.json" ]; then
  registered="$registered
$(jq -r '(.mcpServers // {}) | keys[]?' "$top/.mcp.json" 2>/dev/null)"
fi
is_registered() { printf '%s\n' "$registered" | grep -qxF "$1"; }

# status for one connector record (as compact JSON on stdin arg $1) -> "name<TAB>kind<TAB>env<TAB>status"
check_line() {
  c="$1"
  name="$(printf '%s' "$c" | jq -r '.name')"
  kind="$(printf '%s' "$c" | jq -r '.kind')"
  env="$(printf '%s' "$c" | jq -r '.env // ""')"
  ond="$(printf '%s' "$c" | jq -r '.enabledOnDemand // false')"
  spath="$(printf '%s' "$c" | jq -r '.secret.path // ""')"
  store="$(printf '%s' "$c" | jq -r '.secret.store // "local"')"
  status="unknown"
  case "$kind" in
    *) [ "$store" = vault ] && { printf '%s\t%s\t%s\t%s%s\n' "$name" "$kind" "$env" "vault-pointer" "$2"; return; } ;;
  esac
  case "$kind" in
    mcp-*) if [ "$ond" = "true" ]; then status="on-demand"; elif is_registered "$name"; then status="registered"; else status="missing"; fi ;;
    api|service-key) if [ -n "$spath" ] && [ -f "$(expand_tilde "$spath")" ]; then status="key-present"; else status="key-missing"; fi ;;
    cli) status="cli" ;;
    env) status="env" ;;
    claude-connector) status="account" ;;   # claude.ai account-level connector; loaded from claude.ai settings, not registered here
    codex-app) status="codex-app" ;;        # an app in the Codex ChatGPT login; reached through codex exec
  esac
  if [ -n "$spath" ] && [ "$kind" != api ] && [ "$kind" != service-key ]; then
    [ -f "$(expand_tilde "$spath")" ] || status="$status,key-missing"
  fi
  printf '%s\t%s\t%s\t%s%s\n' "$name" "$kind" "$env" "$status" "$2"
}

# --- CHECK mode: emit "name<TAB>kind<TAB>env<TAB>status[<TAB>(shared)]" per connector and exit ---
if [ "$mode" = "check" ]; then
  printf '%s' "$effective" | jq -c '.connectors[]?' 2>/dev/null | while IFS= read -r c; do
    if [ "$(printf '%s' "$c" | jq -r '.scope // ""')" = "shared-account" ]; then
      check_line "$c" "	(shared)"
    else
      check_line "$c" ""
    fi
  done
  exit 0
fi

# --- PROVISION mode ---
added=0; skipped=0
echo "connectors: provisioning '$proj' from the connector registry" >&2

provision_connector() { # $1=connector JSON (the loader already resolved name clashes)
  c="$1"
  name="$(printf '%s' "$c" | jq -r '.name')"
  kind="$(printf '%s' "$c" | jq -r '.kind')"
  ond="$(printf '%s' "$c" | jq -r '.enabledOnDemand // false')"
  [ "$ond" = "true" ] && return                # on-demand capabilities (e.g. prod-write) are NOT auto-provisioned

  # A connector bound to a key file declares it in .secret.path so --check can report presence. Nothing
  # is fetched here: if it is absent, the doctor surfaces the connector's own auth.steps and you run
  # them. Warn rather than fail, so a missing key never blocks the rest of the provisioning run.
  spath="$(printf '%s' "$c" | jq -r '.secret.path // ""')"
  if [ -n "$spath" ] && [ ! -f "$(expand_tilde "$spath")" ]; then
    echo "  ! $name: key $spath is missing — run /sk:setup-connectors for its auth.steps" >&2
  fi

  case "$kind" in
    mcp-http|mcp-stdio)
      if is_registered "$name"; then skipped=$((skipped+1)); return; fi
      # build the add-json payload from .mcp, expanding ~ in env values and args
      json="$(printf '%s' "$c" | jq -c --arg home "$HOME" '
        .mcp
        | (if .env then .env |= with_entries(.value |= (gsub("^~/"; $home + "/"))) else . end)
        | (if .args then .args |= map(gsub("^~/"; $home + "/")) else . end)')"
      [ "$json" = "null" ] || [ -z "$json" ] && { echo "  ! $name: no .mcp block, skipping" >&2; return; }
      if have claude; then
        ( cd "$top" 2>/dev/null && claude mcp add-json "$name" "$json" -s local >/dev/null 2>&1 ) \
          && { echo "  + registered $name (local)" >&2; added=$((added+1)); } \
          || echo "  ! failed to register $name" >&2
      else
        echo "  ! 'claude' CLI not on PATH; cannot register $name" >&2
      fi
      ;;
    api|service-key|cli|env|claude-connector|codex-app) : ;;   # no MCP registration; readiness is via --check and the auth-gate/doctor
    *) echo "  ? unknown kind '$kind' for $name (add an adapter in connectors-provision.sh)" >&2 ;;
  esac
}

# register MCP servers for every connector NOT enabledOnDemand, in the loader's order
while IFS= read -r c; do [ -n "$c" ] && provision_connector "$c"; done < <(printf '%s' "$effective" | jq -c '.connectors[]?' 2>/dev/null)

echo "connectors: done ($added added, $skipped already present)." >&2
if [ "$added" -gt 0 ]; then
  echo "connectors: NEW MCP servers were registered; they load on the NEXT session — restart to use them." >&2
fi
exit 0
