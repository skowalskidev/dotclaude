#!/usr/bin/env bash
# test-browser.sh
#
# Resolves and launches the dedicated TEST browser: Chrome for Testing, the build Playwright caches
# under ~/Library/Caches/ms-playwright. It carries a visible "Chrome for Testing" mark, so Simon can
# tell it from his own Chrome at a glance. The chrome-devtools MCP is wired with
# `--browser-url=http://127.0.0.1:9222`, so the launcher is what decides which browser that port is.
#
# The versioned path is resolved at run time (highest chromium-<n> wins), never hard-coded, so a
# Playwright upgrade cannot leave a stale path behind.
#
# Usage:
#   test-browser.sh path                       print the newest Chrome for Testing binary
#   test-browser.sh launch [options] [url]     start it with remote debugging, or reuse the one on the port
#     --port N       debugging port (default 9222)
#     --profile DIR  user-data-dir (default ~/.chrome-for-testing-debug; sign-in persists across runs)
#     --size WxH     window size, e.g. 390x844 for a phone, 1280x800 for desktop
#     --pos X,Y      window position, so several viewport windows sit side by side
#   test-browser.sh stop [--port N] [--profile DIR]
#                                              stop the Chrome for Testing that owns the port, then wait for it to close
#
# Exit codes: 0 ok (stop: also when nothing listens) · 2 usage
#             · 4 no Chrome for Testing installed (run: npx playwright install chromium)
#             · 5 the port answers but is not Chrome for Testing (stop: or not on --profile); nothing is signalled
#             · 6 launched but the port never opened · 7 stop signalled but the port stayed open
set -euo pipefail

root="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

resolve() {
  local best="" n best_n=-1 bin
  for bin in "$root"/chromium-*/chrome-mac*/"Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"; do
    [ -x "$bin" ] || continue
    n="${bin#"$root"/chromium-}"; n="${n%%/*}"
    case "$n" in ''|*[!0-9]*) continue ;; esac
    if [ "$n" -gt "$best_n" ]; then best_n="$n"; best="$bin"; fi
  done
  if [ -z "$best" ]; then
    echo "test-browser: no Chrome for Testing under $root. Run: npx playwright install chromium" >&2
    exit 4
  fi
  printf '%s\n' "$best"
}

cmd="${1:-}"
case "$cmd" in
  path) resolve ;;
  launch)
    shift
    port=9222; profile="$HOME/.chrome-for-testing-debug"; size=""; pos=""; url="about:blank"
    while [ $# -gt 0 ]; do
      case "$1" in
        --port) port="$2"; shift 2 ;;
        --profile) profile="$2"; shift 2 ;;
        --size) size="$2"; shift 2 ;;
        --pos) pos="$2"; shift 2 ;;
        -*) echo "test-browser: unknown option $1" >&2; exit 2 ;;
        *) url="$1"; shift ;;
      esac
    done
    if curl -s --max-time 2 "http://127.0.0.1:$port/json/version" >/dev/null 2>&1; then
      # /json/version reports a plain "Chrome/<v>" for every Chrome, so identify the listener by its process.
      pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
      if [ -z "$pid" ] || ! ps -o command= -p "$pid" | grep -q 'Google Chrome for Testing'; then
        echo "test-browser: port $port answers but is not Chrome for Testing. Pick another --port." >&2
        exit 5
      fi
      echo "test-browser: reusing Chrome for Testing on port $port"
      exit 0
    fi
    bin="$(resolve)"
    mkdir -p "$profile"
    args=(--remote-debugging-port="$port" --user-data-dir="$profile" --no-first-run --no-default-browser-check)
    [ -n "$size" ] && args+=(--window-size="${size/x/,}")
    [ -n "$pos" ] && args+=(--window-position="$pos")
    nohup "$bin" "${args[@]}" "$url" >"$profile/launch.log" 2>&1 &
    for _ in $(seq 1 30); do
      if curl -s --max-time 1 "http://127.0.0.1:$port/json/version" >/dev/null 2>&1; then
        echo "test-browser: Chrome for Testing on port $port (profile $profile)"
        exit 0
      fi
      sleep 0.5
    done
    echo "test-browser: launched but port $port never opened; see $profile/launch.log" >&2
    exit 6
    ;;
  stop)
    shift
    port=9222; profile=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --port) port="$2"; shift 2 ;;
        --profile) profile="$2"; shift 2 ;;
        *) echo "test-browser: unknown stop argument $1" >&2; exit 2 ;;
      esac
    done
    # The listener on the debugging port is the browser's main process; its exit takes every helper with it.
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
    if [ -z "$pid" ]; then
      echo "test-browser: nothing listens on port $port"
      exit 0
    fi
    command="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    if ! printf '%s' "$command" | grep -q 'Google Chrome for Testing'; then
      echo "test-browser: port $port belongs to another program; not stopping it." >&2
      exit 5
    fi
    if [ -n "$profile" ] && ! printf '%s' "$command" | grep -qF -- "--user-data-dir=$profile"; then
      echo "test-browser: Chrome for Testing on port $port uses another profile; not stopping it." >&2
      exit 5
    fi
    kill "$pid"
    for _ in $(seq 1 20); do
      if ! lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "test-browser: stopped Chrome for Testing on port $port"
        exit 0
      fi
      sleep 0.5
    done
    echo "test-browser: signalled pid $pid but port $port is still open" >&2
    exit 7
    ;;
  *) echo "usage: test-browser.sh path | launch [--port N] [--profile DIR] [--size WxH] [--pos X,Y] [url] | stop [--port N] [--profile DIR]" >&2; exit 2 ;;
esac
