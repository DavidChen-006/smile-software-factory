#!/usr/bin/env bash
# Exercises verify-smile up, feature install, and down against a real fixture repo.
# Needs gh (logged in), bd, tmux. Creates and removes a private repo named smile-verify-<runid>.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VS="$ROOT/.claude/skills/verify-smile/scripts/verify-smile"
EVIDENCE_ROOT="${SMILE_VERIFY_ROOT:-$HOME/.smile-verify}"
RUNID=""
FAILS=0

check() {   # check <description> <command...>
	local desc="$1"; shift
	if "$@" >/dev/null 2>&1; then
		printf 'ok   %s\n' "$desc"
	else
		printf 'FAIL %s\n' "$desc"
		FAILS=$((FAILS + 1))
	fi
}

cleanup() {
	if [ -n "$RUNID" ] && [ -f "$EVIDENCE_ROOT/$RUNID/manifest.json" ]; then
		state=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["state"])' "$EVIDENCE_ROOT/$RUNID/manifest.json")
		if [ "$state" != "down" ]; then
			printf 'cleanup: tearing down %s\n' "$RUNID"
			"$VS" down "$RUNID" >/dev/null 2>&1 || true
		fi
	fi
}
trap cleanup EXIT

# --- up
UP_OUT=$("$VS" up 2>&1) || { printf 'FAIL up: %s\n' "$UP_OUT"; exit 1; }
RUNID=$(printf '%s\n' "$UP_OUT" | sed -n 's/^fixture ready \([^ ]*\) .*/\1/p')
FIXTURE=$(printf '%s\n' "$UP_OUT" | sed -n 's/^fixture ready [^ ]* \(.*\)/\1/p')
[ -n "$RUNID" ] || { printf 'FAIL up: no runid in output\n%s\n' "$UP_OUT"; exit 1; }
printf 'run %s fixture %s\n' "$RUNID" "$FIXTURE"

M="$EVIDENCE_ROOT/$RUNID/manifest.json"
mfget() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$M" "$1"; }

check "manifest written" test -f "$M"
check "fixture has .beads" test -d "$FIXTURE/.beads"
check "tmux session exists" tmux has-session -t "$(mfget tmux_session)"
BEAD_A=$(mfget bead_a)
READY=$(cd "$FIXTURE" && bd ready --json | python3 -c 'import json,sys; print(" ".join(i["id"] for i in json.load(sys.stdin)))')
check "bd ready shows only bead A" test "$READY" = "$BEAD_A"
check "fixture repo exists on GitHub" gh repo view "$(mfget repo)"

# --- feature install
FEAT_OUT=$("$VS" feature install --runtime bash --run "$RUNID" 2>&1); FEAT_RC=$?
printf '%s\n' "$FEAT_OUT" | tail -1
check "feature install exits 0" test "$FEAT_RC" -eq 0
check "feature install printed PASS" grep -q '^PASS install' <<<"$FEAT_OUT"
check "install.log recorded" test -f "$EVIDENCE_ROOT/$RUNID/install.log"

# --- unknown feature
"$VS" feature loop --run "$RUNID" >/dev/null 2>&1; RC=$?
check "unimplemented feature exits 2" test "$RC" -eq 2

# --- down
REPO=$(mfget repo)
TMP=$(mfget tmp)
SESSION=$(mfget tmux_session)
DOWN_OUT=$("$VS" down "$RUNID" 2>&1); DOWN_RC=$?
printf '%s\n' "$DOWN_OUT" | tail -1
check "down exits 0" test "$DOWN_RC" -eq 0
check "tmux session gone" bash -c "! tmux has-session -t '$SESSION' 2>/dev/null"
check "temp dir gone" test ! -d "$TMP"
DISPOSAL=$(mfget disposal)
if [ "$DISPOSAL" = "deleted" ]; then
	check "repo deleted on GitHub" bash -c "! gh repo view '$REPO' >/dev/null 2>&1"
else
	check "repo archived and renamed" gh repo view "$REPO-trash" --json isArchived --jq '.isArchived'
fi
for f in manifest.json beads.json prs.json install.log; do
	check "evidence has $f" test -f "$EVIDENCE_ROOT/$RUNID/$f"
done

# --- down twice must refuse nothing but stay idempotent
"$VS" down "$RUNID" >/dev/null 2>&1; check "second down exits 0" test $? -eq 0
"$VS" down no-such-run >/dev/null 2>&1; check "down without manifest refuses" test $? -ne 0

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS verify-smile.test.sh (%s)\n' "$RUNID"
else
	printf 'FAIL verify-smile.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
