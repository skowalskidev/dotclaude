#!/usr/bin/env bash
# connectors-provision.sh — generic, idempotent connector provisioner (harness-independent).
#
# Reads the per-project manifest ~/.claude/connectors/<project>.json chosen by matching the current
# git origin, and registers that project's MCP servers at LOCAL scope (claude mcp add-json -s local).
# Runnable by hand, by hooks/session-connectors.sh, or by a Conductor scripts.setup. Never hard-codes a
# project. Fast (no `claude mcp list` / no network for the registration check). Designed to be safe in a
# hook: never exits non-zero, never blocks.
#
# It does NOT fetch secrets. There is no secret store in this setup: a connector's `secret.path` is a
# DECLARATION of where its key lives so --check can report presence, and the key is created by hand from
# that connector's own `auth.steps` (e.g. `gcloud iam service-accounts keys create`). GCP/Stripe/Firebase
# IAM is the source of truth, and a key is regenerated on demand rather than mirrored into a vault.
#
# Usage:
#   connectors-provision.sh [DIR]           provision the project at DIR (default: $PWD)
#   connectors-provision.sh --check [DIR]    print a readiness report (one line per connector), no writes
#   connectors-provision.sh --manifest [DIR] print the resolved manifest path (or nothing)
#
# Adapters by connector.kind: mcp-http | mcp-stdio (registered as MCP servers); api | service-key |
# cli | env | claude-connector (no MCP registration — readiness is reported by --check, setup is via the
# auth-gate/doctor). claude-connector is a claude.ai account-level connector loaded from claude.ai
# connector settings, NOT via `claude mcp add-json` — the engine never registers it; the boundary guard
# matches on its live server-id `name`.
# A new kind = add a case below. See ~/.claude/references/connectors-setup.md for the schema.
set -u

CONN_DIR="$HOME/.claude/connectors"
CLAUDE_JSON="$HOME/.claude.json"

have() { command -v "$1" >/dev/null 2>&1; }
expand_tilde() { case "$1" in "~/"*) printf '%s' "$HOME/${1#\~/}" ;; *) printf '%s' "$1" ;; esac; }

[ -d "$CONN_DIR" ] || { echo "connectors: no ~/.claude/connectors dir; nothing to do" >&2; exit 0; }
have jq || { echo "connectors: jq not found; cannot read manifests" >&2; exit 0; }

# --- parse args ---
mode="provision"; dir="$PWD"
case "${1:-}" in
  --check)    mode="check";    shift ;;
  --manifest) mode="manifest"; shift ;;
  -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
esac
[ -n "${1:-}" ] && dir="$1"
[ -d "$dir" ] || dir="$PWD"

# --- resolve the manifest for this project via git origin (fallback: repo path) ---
origin="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$dir")"
# In a linked git worktree (a Conductor workspace), `claude mcp ... -s local` records the server under the
# MAIN worktree's path in ~/.claude.json, not the linked worktree's. Reading only "$top" therefore reports
# every already-registered server as "missing" forever, and the SessionStart precheck cries "NOT SET UP"
# about connectors that are loaded and working. Resolve the main worktree root so the read side matches the
# write side. Equals "$top" outside a worktree, and when git is absent.
top_main="$top"
gitcommon="$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
[ -n "$gitcommon" ] && [ -d "$gitcommon" ] && top_main="$(dirname "$gitcommon")"
manifest=""
for f in "$CONN_DIR"/*.json; do
  [ -e "$f" ] || continue
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    case "$origin$top" in *"$m"*) manifest="$f"; break ;; esac
  done < <(jq -r '.match[]? // empty' "$f" 2>/dev/null)
  [ -n "$manifest" ] && break
done

if [ "$mode" = "manifest" ]; then [ -n "$manifest" ] && printf '%s\n' "$manifest"; exit 0; fi
[ -n "$manifest" ] || { echo "connectors: no manifest matches this project (origin: ${origin:-none})" >&2; exit 0; }

proj="$(jq -r '.project // "?"' "$manifest")"

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

# --- CHECK mode: emit "name<TAB>kind<TAB>env<TAB>status" and exit ---
if [ "$mode" = "check" ]; then
  jq -c '.connectors[]?' "$manifest" 2>/dev/null | while IFS= read -r c; do
    name="$(printf '%s' "$c" | jq -r '.name')"
    kind="$(printf '%s' "$c" | jq -r '.kind')"
    env="$(printf '%s' "$c" | jq -r '.env // ""')"
    ond="$(printf '%s' "$c" | jq -r '.enabledOnDemand // false')"
    spath="$(printf '%s' "$c" | jq -r '.secret.path // ""')"
    status="unknown"
    case "$kind" in
      mcp-*) if [ "$ond" = "true" ]; then status="on-demand"; elif is_registered "$name"; then status="registered"; else status="missing"; fi ;;
      api|service-key) if [ -n "$spath" ] && [ -f "$(expand_tilde "$spath")" ]; then status="key-present"; else status="key-missing"; fi ;;
      cli) status="cli" ;;
      env) status="env" ;;
      claude-connector) status="account" ;;   # claude.ai account-level connector; loaded from claude.ai settings, not registered here
    esac
    if [ -n "$spath" ] && [ "$kind" != api ] && [ "$kind" != service-key ]; then
      [ -f "$(expand_tilde "$spath")" ] || status="$status,key-missing"
    fi
    printf '%s\t%s\t%s\t%s\n' "$name" "$kind" "$env" "$status"
  done
  exit 0
fi

# --- PROVISION mode ---
added=0; skipped=0
echo "connectors: provisioning '$proj' (manifest: $(basename "$manifest"))" >&2

# register MCP servers for every connector NOT enabledOnDemand
while IFS= read -r c; do
  [ -n "$c" ] || continue
  name="$(printf '%s' "$c" | jq -r '.name')"
  kind="$(printf '%s' "$c" | jq -r '.kind')"
  ond="$(printf '%s' "$c" | jq -r '.enabledOnDemand // false')"
  [ "$ond" = "true" ] && continue                # on-demand capabilities (e.g. prod-write) are NOT auto-provisioned

  # A connector bound to a key file declares it in .secret.path so --check can report presence. Nothing
  # is fetched here: if it is absent, the doctor surfaces the connector's own auth.steps and you run
  # them. Warn rather than fail, so a missing key never blocks the rest of the provisioning run.
  spath="$(printf '%s' "$c" | jq -r '.secret.path // ""')"
  if [ -n "$spath" ] && [ ! -f "$(expand_tilde "$spath")" ]; then
    echo "  ! $name: key $spath is missing — run /sk:setup-connectors for its auth.steps" >&2
  fi

  case "$kind" in
    mcp-http|mcp-stdio)
      if is_registered "$name"; then skipped=$((skipped+1)); continue; fi
      # build the add-json payload from .mcp, expanding ~ in env values and args
      json="$(printf '%s' "$c" | jq -c --arg home "$HOME" '
        .mcp
        | (if .env then .env |= with_entries(.value |= (gsub("^~/"; $home + "/"))) else . end)
        | (if .args then .args |= map(gsub("^~/"; $home + "/")) else . end)')"
      [ "$json" = "null" ] || [ -z "$json" ] && { echo "  ! $name: no .mcp block, skipping" >&2; continue; }
      if have claude; then
        ( cd "$top" 2>/dev/null && claude mcp add-json "$name" "$json" -s local >/dev/null 2>&1 ) \
          && { echo "  + registered $name (local)" >&2; added=$((added+1)); } \
          || echo "  ! failed to register $name" >&2
      else
        echo "  ! 'claude' CLI not on PATH; cannot register $name" >&2
      fi
      ;;
    api|service-key|cli|env|claude-connector) : ;;   # no MCP registration; readiness is via --check and the auth-gate/doctor
    *) echo "  ? unknown kind '$kind' for $name (add an adapter in connectors-provision.sh)" >&2 ;;
  esac
done < <(jq -c '.connectors[]?' "$manifest" 2>/dev/null)

echo "connectors: done ($added added, $skipped already present)." >&2
if [ "$added" -gt 0 ]; then
  echo "connectors: NEW MCP servers were registered; they load on the NEXT session — restart to use them." >&2
fi
exit 0
