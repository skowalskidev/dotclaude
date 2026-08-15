#!/usr/bin/env bash
# port-slot.sh
#
# Gives this worktree its own LANE of local dev ports, so several Claude sessions can run their
# stacks at the same time and each be reachable in a browser.
#
# A lane is a SLOT, 0..9. Slot N means `base + N*10` for every base port the project uses. Slot 1 of
# a {web 3000, api 4000} project is {3010, 4010}.
#
# Why 10 and not 100. A 100 step reads nicer (3000/3100/3200) and was the first design, but it walks
# straight into ports real projects have already spoken for — in your work monorepo, 3100 is the
# landing app's dev default and both 3100 and 3200 are in its scripts/kill_ports.sh, so four of
# the ten lanes were broken before anyone used them. A 10 step collided with nothing there. It is
# also the increment the parallel-worktree write-ups converge on, and what Conductor itself does:
# "Conductor allocates ten ports to each workspace: CONDUCTOR_PORT through CONDUCTOR_PORT+9."
#
# What this script is NOT. It does not decide which env var carries a port into which service, and it
# does not boot anything. That is judgement about a specific project, and it belongs to
# skills/sk/skills/work-isolate-environment. This script owns the deterministic half: pick a lane,
# arbitrate it, sweep what previous sessions left behind, record the run.
#
# Usage:
#   port-slot.sh                       sweep, resolve, print the lane and its URLs (does NOT claim)
#   port-slot.sh --claim               same, and claim the lane in the registry (do this at boot)
#   port-slot.sh --env                 KEY=VALUE lines: `export $(port-slot.sh --env)`
#   port-slot.sh --json                the whole resolved lane as JSON
#   port-slot.sh --release             release this worktree's lane
#   port-slot.sh --sweep               the self-heal pass alone, resolve nothing
#   port-slot.sh --base web=3000,api=4000   override discovered base ports
#   port-slot.sh --slot N              force a slot
#   port-slot.sh --quiet               suppress the human report (still logs)
#
# Claims LAZILY, sweeps EAGERLY. Resolving and printing a lane is free, so a run that never starts a
# server never adds a registry row — that is what stops rows piling up across a day of sessions. The
# sweep runs on every invocation regardless, so even a run that claims nothing still cleans up after
# a session that died without releasing.
#
# Exit codes: 0 ok · 2 usage · 3 no lane available (every slot held by a live session)
#             · 6 base ports could not be discovered (pass --base, or let the skill discover them)
#
# Env: CLAUDE_PORT_SLOT   force a slot (same as --slot)
#      PORT_SLOT_STEP     ports between lanes (default 10)
#      PORT_SLOT_COUNT    how many lanes (default 10)
set -u

REGISTRY_SH="${PORT_REGISTRY_SH:-$HOME/.claude/bin/port-registry.sh}"
LOG_FILE="${PORT_SLOT_LOG:-$HOME/.claude/logs/isolate-runs.jsonl}"
LOG_KEEP=200
SCHEMA=1
STEP="${PORT_SLOT_STEP:-10}"
SLOT_COUNT="${PORT_SLOT_COUNT:-10}"
STATE_NAME=".claude-slot.json"

QUIET=0
MODE="report"
WANT_SLOT=""
BASE_OVERRIDE=""

# --- identity ---------------------------------------------------------------------------------------
# The workspace is the git worktree root, defined exactly as port-registry.sh defines it, because the
# rows it writes store this path and the sweep compares against it. Two definitions here would mean a
# lane that can never be matched to its own worktree.
workspace_root() { git rev-parse --show-toplevel 2>/dev/null || pwd; }

WS="$(workspace_root)"
WS_NAME="${CONDUCTOR_WORKSPACE_NAME:-${WS##*/}}"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
[ "$BRANCH" = "HEAD" ] && BRANCH="$(git rev-parse --short HEAD 2>/dev/null || echo detached)"
STATE_FILE="$WS/$STATE_NAME"

# The session label is port-registry.sh's to define, so ask it rather than re-deriving it. If the two
# ever disagreed, this script would fail to recognise its own rows and would re-claim a lane it
# already held on every run.
ME="$($REGISTRY_SH whoami 2>/dev/null | awk '/^session:/ { print $2; exit }')"
[ -n "$ME" ] || ME="${WS##*/}"

# Work vs personal boundary from the identity overlay's workOrgMatch (see identity.example.json).
_ID_FILE="${CLAUDE_IDENTITY_FILE:-$HOME/.claude/identity.local.json}"
_WORK_ORG_MATCH=""
[ -f "$_ID_FILE" ] && command -v jq >/dev/null 2>&1 && _WORK_ORG_MATCH="$(jq -r '.workOrgMatch // ""' "$_ID_FILE" 2>/dev/null)"
BOUNDARY="personal"
[ -n "$_WORK_ORG_MATCH" ] && git remote -v 2>/dev/null | grep -qiF "$_WORK_ORG_MATCH" && BOUNDARY="work"

TAB="$(printf '\t')"
say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
die() { printf 'port-slot: %s\n' "$*" >&2; exit "${2:-2}"; }

# --- base-port discovery ----------------------------------------------------------------------------
# Discovered, never hardcoded. Order: --base, then a cached map this worktree wrote earlier, then a
# mechanical scan. Anything the scan cannot see is the skill's job to find and record.
#
# The cache is REJECTED unless its `workspace` field matches this worktree. Conductor copies files
# matching `.env*` and CLAUDE.local.md into every new workspace, so inheriting a neighbour's port map
# is a real event, not a hypothetical, and a silently inherited map is how a fresh workspace boots on
# another lane's ports.
discover_from_state() {
  [ -f "$STATE_FILE" ] || return 1
  /usr/bin/python3 - "$STATE_FILE" "$WS" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
if d.get("workspace") != sys.argv[2]:
    sys.exit(1)                      # foreign copy: rediscover rather than trust
svc = d.get("services") or {}
if not svc:
    sys.exit(1)
for name, s in sorted(svc.items()):
    base = s.get("base")
    if base:
        print(f"{name}={base}\t{s.get('env','')}")
PY
}

# The mechanical half: an explicit port in a package.json dev/start script, or a host-side port in a
# compose file. It deliberately understands `-p ${PORT:-3000}` as well as `-p 3000`, because making a
# script overridable is the first thing this system asks a project to do, and a scan that then stopped
# recognising its own handiwork would rediscover nothing on the second run.
discover_mechanically() {
  /usr/bin/python3 - "$WS" <<'PY' 2>/dev/null
import json, os, re, sys

root = sys.argv[1]
SKIP = {"node_modules", ".git", ".next", "dist", "build", ".turbo", ".yarn"}
PORT_RE = re.compile(r"(?:-p|--port)[= ]+(?:\$\{[A-Za-z_][A-Za-z0-9_]*:-(\d{2,5})\}|(\d{2,5}))")
COMPOSE_RE = re.compile(r"[\"']?(?:\$\{[A-Za-z_][A-Za-z0-9_]*:-(\d{2,5})\}|(\d{2,5})):\d{2,5}[\"']?")

found = {}

def add(name, port):
    port = int(port)
    if port < 1024 or port > 65535:
        return
    found.setdefault(name, port)

def walk(depth=3):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        if rel != "." and rel.count(os.sep) + 1 > depth:
            dirnames[:] = []
            continue
        yield dirpath, filenames

for dirpath, filenames in walk():
    if "package.json" in filenames:
        try:
            pkg = json.load(open(os.path.join(dirpath, "package.json")))
        except Exception:
            pkg = {}
        name = pkg.get("name") or os.path.basename(dirpath)
        name = str(name).split("/")[-1]
        for key, val in (pkg.get("scripts") or {}).items():
            if not (key == "start" or key.startswith("dev") or key.endswith(":dev")):
                continue
            m = PORT_RE.search(str(val))
            if m:
                add(name, m.group(1) or m.group(2))
    for fn in filenames:
        low = fn.lower()
        if "compose" in low and (low.endswith(".yml") or low.endswith(".yaml")):
            try:
                text = open(os.path.join(dirpath, fn)).read()
            except Exception:
                continue
            # Track position properly instead of matching any `name:` line. Naively treating every
            # key as a service name made `ports:` itself the service, and the first scan of the
            # work monorepo duly reported a service called "ports" on 9200.
            in_services = False
            services_indent = None
            svc = None
            for line in text.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                stripped = line.strip()
                if re.match(r"^services:\s*$", stripped):
                    in_services, services_indent, svc = True, indent, None
                    continue
                if in_services and indent <= services_indent and stripped.endswith(":"):
                    in_services = False           # left the services block entirely
                if not in_services:
                    continue
                if re.match(r"^[A-Za-z0-9_.-]+:$", stripped) and indent == services_indent + 2:
                    svc = stripped[:-1]
                    continue
                if svc is None:
                    continue
                m = COMPOSE_RE.search(stripped)
                if m and (stripped.startswith("- ") or stripped.startswith('"') or stripped.startswith("'")):
                    add(svc, m.group(1) or m.group(2))

for name, port in sorted(found.items(), key=lambda kv: kv[1]):
    print(f"{name}={port}\t")
PY
}

# Two bugs lived in the obvious version of this, and both failed SILENTLY, which is the worst outcome
# for a function whose whole job is deciding which services get isolated:
#
#   * `printf '%s'` gives tr no trailing newline, and `while read` discards a final line that has none,
#     so `--base web=3000,api=4000,esipc=8080` allocated web and api and dropped esipc.
#   * Validating inside the emit loop cannot work. That loop is a pipeline, so it runs in a subshell,
#     and an `exit 2` there kills the subshell while the caller sees success — `--base web=3000,garbage`
#     exited 0 with a one-service lane.
#
# So: validate in THIS shell, first, then emit.
parse_base_override() {
  if printf '%s\n' "$1" | tr ',' '\n' | grep -v '^$' | grep -qvE '^[A-Za-z0-9_.-]+=[0-9]{2,5}$'; then
    return 2
  fi
  printf '%s\n' "$1" | tr ',' '\n' | while IFS= read -r pair; do
    [ -n "$pair" ] || continue
    printf '%s\t\n' "$pair"
  done
}

# --- lane arithmetic --------------------------------------------------------------------------------
hash_slot() {
  printf '%s' "$WS" | cksum | awk -v n="$SLOT_COUNT" '{ print $1 % n }'
}

# lane_ports SLOT < base_lines — emits "name<TAB>port<TAB>env" for one slot.
lane_ports() {
  awk -v slot="$1" -v step="$STEP" -F"$TAB" '
    { split($1, kv, "="); printf "%s\t%d\t%s\n", kv[1], kv[2] + slot * step, $2 }
  '
}

# --- the sweep --------------------------------------------------------------------------------------
# Reaping belongs to the registry, which owns the rows; this only handles the one case the registry
# deliberately refuses to resolve on its own. A row whose workspace has been DELETED but whose server
# is still listening is correctly kept by the registry (the port really is bound) and would therefore
# look healthy forever, so exit 5 hands it here.
#
# Killing is confined to exactly that case. Its code is gone, so nobody can be using it. Every other
# shape — including a listener nobody claimed — is reported and left alone, because killing a server
# you started yourself is worse than failing.
SWEEP_REAPED=0
SWEEP_KILLED=0
SWEEP_ORPHANS=0
SWEEP_REPORTED=0

kill_orphan_on_port() {
  port="$1"
  lp="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  [ -n "$lp" ] || return 0

  # Capture the family BEFORE signalling: a child's ppid changes the instant its parent dies, so a
  # tree collected afterwards is already wrong. Same reason bin/kill-orphan-workers.sh does this.
  family="$lp $(pgrep -P "$lp" 2>/dev/null | tr '\n' ' ')"
  for p in $family; do kill -TERM "$p" 2>/dev/null; done
  sleep 2

  # Re-check against the observable that actually matters, the port, not pid liveness: if only the
  # parent died, a surviving child still holds the bind and has just become an orphan of its own.
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    still="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | tr '\n' ' ')"
    for p in $still $family; do kill -9 "$p" 2>/dev/null; done
    sleep 1
  fi

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    say "  port $port: orphaned server SURVIVED SIGKILL — tell the user, pid $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t | head -1)"
    return 1
  fi
  SWEEP_KILLED=$((SWEEP_KILLED + 1))
  say "  port $port: orphaned server killed (its workspace no longer exists)"
  return 0
}

sweep() {
  out="$($REGISTRY_SH reap 2>&1)"; rc=$?
  SWEEP_REAPED="$(printf '%s\n' "$out" | grep -c 'claim dropped' || true)"
  [ "$QUIET" -eq 1 ] || printf '%s\n' "$out" | sed 's/^/  /'

  if [ "$rc" -eq 5 ]; then
    # Re-derive the orphans from rows rather than by parsing the prose above.
    orphan_ports="$($REGISTRY_SH list --tsv 2>/dev/null | awk -F"$TAB" '{ if (system("[ -d \"" $3 "\" ]") != 0) print $1 }')"
    for p in $orphan_ports; do
      SWEEP_ORPHANS=$((SWEEP_ORPHANS + 1))
      kill_orphan_on_port "$p"
    done
    # The rows now have no listener and no existing workspace, so this drops them.
    $REGISTRY_SH reap >/dev/null 2>&1 || true
  fi

  # A listener nobody claimed is the registry's exit 4. Report only.
  SWEEP_REPORTED="$(printf '%s\n' "$out" | grep -c 'no session claimed' || true)"
}

# --- logging ----------------------------------------------------------------------------------------
# Records only. It must never block, fail, or alter a run — same standing rule as
# bin/superspeed-dispatch.sh's instrumentation. Built with jq so a branch or path containing a quote
# cannot corrupt the file, matching hooks/retro-trigger-log.sh. No jq means no log, never an error.
#
# Self-trimming, because nothing else in ~/.claude/logs/ is: security-guard.log sat at 640K long after
# the guard that wrote it was retired.
log_run() {
  command -v jq >/dev/null 2>&1 || return 0
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || return 0
  jq -n -c \
    --arg ts "$(TZ=UTC date +%Y-%m-%dT%H:%M:%SZ)" \
    --arg session "${CONDUCTOR_SESSION_ID:-${CLAUDE_SESSION_ID:-unknown}}" \
    --arg cwd "$WS" \
    --arg repo "$WS_NAME" \
    --arg boundary "$BOUNDARY" \
    --arg branch "$BRANCH" \
    --arg mode "$MODE" \
    --argjson schema "$SCHEMA" \
    --argjson slot_wanted "${1:-0}" \
    --argjson slot_granted "${2:--1}" \
    --argjson probes "${3:-0}" \
    --arg lane "${4:-}" \
    --arg discovery_source "${5:-none}" \
    --argjson discovery_ms "${6:-0}" \
    --argjson services_discovered "${7:-0}" \
    --argjson reaped "$SWEEP_REAPED" \
    --argjson killed_orphan "$SWEEP_KILLED" \
    --argjson orphans_found "$SWEEP_ORPHANS" \
    --argjson reported_unclaimed "$SWEEP_REPORTED" \
    --argjson blind_spots "${8:-[]}" \
    '{ts:$ts, schema:$schema, session:$session, cwd:$cwd, repo:$repo, boundary:$boundary,
      branch:$branch, mode:$mode, slot_wanted:$slot_wanted, slot_granted:$slot_granted,
      probes:$probes, lane:$lane, discovery_source:$discovery_source, discovery_ms:$discovery_ms,
      services_discovered:$services_discovered,
      sweep:{reaped:$reaped, killed_orphan:$killed_orphan, orphans_found:$orphans_found,
             reported_unclaimed:$reported_unclaimed},
      blind_spots:$blind_spots}' >> "$LOG_FILE" 2>/dev/null || return 0

  lines="$(wc -l < "$LOG_FILE" 2>/dev/null | tr -d ' ')"
  if [ -n "$lines" ] && [ "$lines" -gt "$LOG_KEEP" ] 2>/dev/null; then
    tail -n "$LOG_KEEP" "$LOG_FILE" > "$LOG_FILE.tmp" 2>/dev/null && mv "$LOG_FILE.tmp" "$LOG_FILE"
  fi
}

# --- state file -------------------------------------------------------------------------------------
# Lives INSIDE the worktree on purpose, ignored through ~/.gitignore_global rather than any committed
# .gitignore. Deleting the worktree therefore deletes its state, which is what makes an orphaned entry
# under ~/.claude structurally impossible.
write_state() {
  slot="$1"; lane_f="$2"
  /usr/bin/python3 - "$STATE_FILE" "$WS" "$BRANCH" "$WS_NAME" "$slot" "$lane_f" "$STEP" <<'PY' 2>/dev/null || return 0
import json, os, sys
path, ws, branch, name, slot, lane_f, step = sys.argv[1:8]
services = {}
prev = {}
if os.path.exists(path):
    try:
        prev = (json.load(open(path)) or {}).get("services") or {}
    except Exception:
        prev = {}
for line in open(lane_f):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 2 or not parts[0]:
        continue
    svc, port = parts[0], int(parts[1])
    env = parts[2] if len(parts) > 2 else ""
    if not env:
        env = (prev.get(svc) or {}).get("env", "")
    services[svc] = {"base": port - int(slot) * int(step), "port": port, "env": env}
json.dump({"schema": 1, "workspace": ws, "branch": branch, "name": name,
           "slot": int(slot), "step": int(step), "services": services},
          open(path, "w"), indent=2, sort_keys=True)
open(path, "a").write("\n")
PY
}

# --- argument parsing -------------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --env) MODE="env" ;;
    --json) MODE="json" ;;
    --claim) MODE="claim" ;;
    --release) MODE="release" ;;
    --sweep) MODE="sweep" ;;
    --quiet | -q) QUIET=1 ;;
    --slot) shift; WANT_SLOT="${1:-}" ;;
    --slot=*) WANT_SLOT="${1#--slot=}" ;;
    --base) shift; BASE_OVERRIDE="${1:-}" ;;
    --base=*) BASE_OVERRIDE="${1#--base=}" ;;
    --help | -h) sed -n '/^# Usage:/,/^# Env:/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done
# Machine-readable modes must emit nothing but their payload. Written as a case rather than
# `[ a ] || [ b ] && c`, which parses as `(a || b) && c` and is a trap waiting for the next edit.
case "$MODE" in
  env | json) QUIET=1 ;;
esac

# --- run --------------------------------------------------------------------------------------------
TMP="$(mktemp -d "${TMPDIR:-/tmp}/port-slot.XXXXXX")"
trap 'rc__=$?; rm -rf "$TMP" 2>/dev/null; exit $rc__' EXIT

say "port-slot: workspace '$WS_NAME' ($BRANCH, $BOUNDARY)"
say "sweep:"
sweep

if [ "$MODE" = "sweep" ]; then
  log_run 0 -1 0 "" none 0 0 '[]'
  exit 0
fi

if [ "$MODE" = "release" ]; then
  out="$($REGISTRY_SH release 2>&1)"; rc=$?
  say "$out"
  log_run 0 -1 0 "" none 0 0 '[]'
  exit $rc
fi

# Base ports.
BASES="$TMP/bases"
start_ms="$(/usr/bin/python3 -c 'import time; print(int(time.time()*1000))')"
DISCOVERY="none"
if [ -n "$BASE_OVERRIDE" ]; then
  parse_base_override "$BASE_OVERRIDE" > "$BASES" || die "--base wants name=port pairs, e.g. web=3000,api=4000"
  DISCOVERY="flag"
elif discover_from_state > "$BASES" 2>/dev/null && [ -s "$BASES" ]; then
  DISCOVERY="cache"
else
  discover_mechanically > "$BASES" 2>/dev/null || true
  if [ -s "$BASES" ]; then
    DISCOVERY="scan"
    [ -f "$STATE_FILE" ] && DISCOVERY="scan-after-foreign-state"
  else
    [ -f "$STATE_FILE" ] && DISCOVERY="foreign-state-rejected"
    log_run 0 -1 0 "" "$DISCOVERY" 0 0 '["base ports: nothing discoverable, no --base given"]'
    die "no base ports discovered in '$WS'. Pass --base web=3000,api=4000, or let
       /sk:work-isolate-environment discover them and record them in $STATE_NAME." 6
  fi
fi
end_ms="$(/usr/bin/python3 -c 'import time; print(int(time.time()*1000))')"
DISCOVERY_MS=$((end_ms - start_ms))
NSERVICES="$(wc -l < "$BASES" | tr -d ' ')"
say "base ports ($DISCOVERY): $(awk -F"$TAB" '{ printf "%s ", $1 }' "$BASES")"

# Slot.
WANTED="${WANT_SLOT:-${CLAUDE_PORT_SLOT:-$(hash_slot)}}"
case "$WANTED" in ''|*[!0-9]*) die "--slot wants a number 0..$((SLOT_COUNT - 1))" ;; esac

GRANTED=-1
PROBES=0
LANE="$TMP/lane"
i=0
while [ "$i" -lt "$SLOT_COUNT" ]; do
  cand=$(( (WANTED + i) % SLOT_COUNT ))
  lane_ports "$cand" < "$BASES" > "$LANE"
  ports="$(awk -F"$TAB" '{ printf "%s ", $2 }' "$LANE")"
  PROBES=$((PROBES + 1))
  # shellcheck disable=SC2086 # deliberately word-split
  if $REGISTRY_SH check $ports >/dev/null 2>&1; then
    GRANTED="$cand"
    break
  fi
  i=$((i + 1))
done

# Every pretty lane is held. Conductor already reserved ten ports for this workspace and guarantees
# they are unique across workspaces, so it is a sound last resort — just an ugly bookmark, which is
# why it is not the primary.
if [ "$GRANTED" -lt 0 ] && [ -n "${CONDUCTOR_PORT:-}" ]; then
  awk -F"$TAB" -v base="$CONDUCTOR_PORT" '{ split($1, kv, "="); printf "%s\t%d\t%s\n", kv[1], base + NR - 1, $2 }' "$BASES" > "$LANE"
  ports="$(awk -F"$TAB" '{ printf "%s ", $2 }' "$LANE")"
  # shellcheck disable=SC2086
  if $REGISTRY_SH check $ports >/dev/null 2>&1; then
    GRANTED=99
    say "every slot 0..$((SLOT_COUNT - 1)) is held; using Conductor's reserved range from $CONDUCTOR_PORT"
  fi
fi

if [ "$GRANTED" -lt 0 ]; then
  say "no lane available. Who holds what:"
  [ "$QUIET" -eq 1 ] || $REGISTRY_SH list | sed 's/^/  /'
  log_run "$WANTED" -1 "$PROBES" "" "$DISCOVERY" "$DISCOVERY_MS" "$NSERVICES" '["no lane available: every slot held"]'
  exit 3
fi

write_state "$GRANTED" "$LANE"

# Claim. Release any lane this workspace held on a DIFFERENT slot first, so a slot change can never
# leave a second lane claimed — that is what would otherwise make rows accumulate.
if [ "$MODE" = "claim" ]; then
  newports=" $(awk -F"$TAB" '{ printf "%s ", $2 }' "$LANE")"
  stale="$($REGISTRY_SH list --tsv 2>/dev/null | awk -F"$TAB" -v me="$ME" -v keep="$newports" \
    '$2 == me && index(keep, " " $1 " ") == 0 { printf "%s ", $1 }')"
  if [ -n "$stale" ]; then
    say "releasing this workspace's previous lane:$stale"
    # shellcheck disable=SC2086
    $REGISTRY_SH release $stale >/dev/null 2>&1 || true
  fi
  ports="$(awk -F"$TAB" '{ printf "%s ", $2 }' "$LANE")"
  # shellcheck disable=SC2086
  $REGISTRY_SH claim $ports --for "slot $GRANTED · $BRANCH · $WS_NAME" >/dev/null 2>&1 \
    || die "the lane was taken between check and claim; re-run" 3
  say "claimed slot $GRANTED for '$WS_NAME'"
fi

log_run "$WANTED" "$GRANTED" "$PROBES" "$(awk -F"$TAB" '{ printf "%s ", $2 }' "$LANE" | sed 's/ $//')" \
  "$DISCOVERY" "$DISCOVERY_MS" "$NSERVICES" '[]'

# --- output -----------------------------------------------------------------------------------------
case "$MODE" in
  env)
    echo "CLAUDE_PORT_SLOT=$GRANTED"
    # A service with no recorded env var still gets one, so a port is never silently lost between
    # here and the thing that needs it.
    awk -F"$TAB" '{ key = ($3 == "" ? "SLOT_" toupper($1) "_PORT" : $3); gsub(/[^A-Za-z0-9_]/, "_", key); printf "%s=%s\n", key, $2 }' "$LANE"
    ;;
  json)
    /usr/bin/python3 -c 'import json,sys; print(open(sys.argv[1]).read().strip())' "$STATE_FILE" 2>/dev/null \
      || cat "$STATE_FILE"
    ;;
  *)
    say ""
    say "slot $GRANTED  (wanted $WANTED, $PROBES probe$([ "$PROBES" -eq 1 ] || echo s))"
    awk -F"$TAB" '{ printf "  %-14s %s   http://localhost:%s\n", $1, $2, $2 }' "$LANE" | while IFS= read -r l; do say "$l"; done
    [ "$MODE" = "claim" ] || say ""
    [ "$MODE" = "claim" ] || say "Not claimed yet (claiming is lazy). Run with --claim at boot."
    ;;
esac
