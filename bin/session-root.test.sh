#!/usr/bin/env bash
# Checks for session-root.sh, against a temp directory. Run: bash bin/session-root.test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SR="$HERE/session-root.sh"
TMP="$(cd -P "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_SESSION_ROOT_DIR="$TMP/state"

fails=0
check() { # $1 = name, $2 = got, $3 = want
  if [ "$2" = "$3" ]; then printf 'ok    %s\n' "$1"
  else printf 'FAIL  %s\n      got:  %s\n      want: %s\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

git init -q "$TMP/repo"
git -C "$TMP/repo" -c user.email=t@example.invalid -c user.name=t commit -q --allow-empty -m init
mkdir -p "$TMP/repo/.context" "$TMP/repo/src/deep"
git -C "$TMP/repo" worktree add -q "$TMP/repo/.context/nested" -b nested 2>/dev/null
git init -q "$TMP/other"
mkdir -p "$TMP/plain"

check "first use answers the git top level" "$(bash "$SR" s1 "$TMP/repo/src/deep")" "$TMP/repo"
check "a worktree nested under the root keeps the root" "$(bash "$SR" s1 "$TMP/repo/.context/nested")" "$TMP/repo"
check "back in the root, still the root" "$(bash "$SR" s1 "$TMP/repo")" "$TMP/repo"
check "a session that STARTS in the nested worktree owns it" "$(bash "$SR" s2 "$TMP/repo/.context/nested")" "$TMP/repo/.context/nested"
check "a move outside the root re-homes the session" "$(bash "$SR" s1 "$TMP/other")" "$TMP/other"
check "after re-homing, the old nested worktree is its own root" "$(bash "$SR" s1 "$TMP/repo/.context/nested")" "$TMP/repo/.context/nested"
check "no session id: plain git top level, nothing remembered" "$(bash "$SR" "" "$TMP/repo/.context/nested")" "$TMP/repo/.context/nested"
check "outside git: the directory itself" "$(bash "$SR" s3 "$TMP/plain")" "$TMP/plain"
[ -e "$TMP/state/s3" ]; check "outside git: nothing remembered" "$?" "1"

bash "$SR" s4 "$TMP/repo" >/dev/null
rm -rf "$TMP/gone"; printf '%s\n' "$TMP/gone" > "$TMP/state/s4"
check "a remembered root that no longer exists is replaced" "$(bash "$SR" s4 "$TMP/repo/.context/nested")" "$TMP/repo/.context/nested"

bash "$SR" s5 "$TMP/repo" >/dev/null
bash "$SR" forget s5
check "forget drops the record" "$(bash "$SR" s5 "$TMP/repo/.context/nested")" "$TMP/repo/.context/nested"

bash "$SR" "../../evil" "$TMP/repo" >/dev/null
[ -e "$TMP/evil" ]; check "a crafted session id stays inside the state directory" "$?" "1"

bash "$SR" s6 "$TMP/missing" >/dev/null 2>&1
check "a cwd that is not a directory exits 1" "$?" "1"

if [ "$fails" -eq 0 ]; then echo "ALL PASSED"; else echo "$fails FAILED"; exit 1; fi
