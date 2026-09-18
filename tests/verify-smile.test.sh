#!/usr/bin/env bash
# Exercises verify-smile up, feature install, the stub worker's PR and fix rounds, down, and a
# forced up failure, against real fixture repos. Needs gh (logged in), bd, tmux. Creates and
# disposes of private repos named smile-verify-<runid>.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VS="$ROOT/.claude/skills/verify-smile/scripts/verify-smile"
STUB_WORKER="$ROOT/.claude/skills/verify-smile/scripts/stub-worker"
EVIDENCE_ROOT="${SMILE_VERIFY_ROOT:-$HOME/.smile-verify}"
RUNIDS=""
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

mfget() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$EVIDENCE_ROOT/$1/manifest.json" "$2"; }

cleanup() {
	local r
	for r in $RUNIDS; do
		[ -f "$EVIDENCE_ROOT/$r/manifest.json" ] || continue
		if [ "$(mfget "$r" state)" != "down" ]; then
			printf 'cleanup: tearing down %s\n' "$r"
			"$VS" down "$r" >/dev/null 2>&1 || true
		fi
	done
}
trap cleanup EXIT

# ---------------------------------------------------------------- up
UP_OUT=$("$VS" up 2>&1) || { printf 'FAIL up: %s\n' "$UP_OUT"; exit 1; }
RUNID=$(printf '%s\n' "$UP_OUT" | sed -n 's/^fixture ready \([^ ]*\) .*/\1/p')
FIXTURE=$(printf '%s\n' "$UP_OUT" | sed -n 's/^fixture ready [^ ]* \(.*\)/\1/p')
[ -n "$RUNID" ] || { printf 'FAIL up: no runid in output\n%s\n' "$UP_OUT"; exit 1; }
RUNIDS="$RUNID"
printf 'run %s fixture %s\n' "$RUNID" "$FIXTURE"

check "manifest written" test -f "$EVIDENCE_ROOT/$RUNID/manifest.json"
check "manifest state up" test "$(mfget "$RUNID" state)" = "up"
check "fixture has .beads" test -d "$FIXTURE/.beads"
SESSION=$(mfget "$RUNID" tmux_session)
check "tmux session exists" tmux has-session -t "=$SESSION"
BEAD_A=$(mfget "$RUNID" bead_a)
BEAD_B=$(mfget "$RUNID" bead_b)
READY=$(cd "$FIXTURE" && bd ready --json | python3 -c 'import json,sys; print(" ".join(i["id"] for i in json.load(sys.stdin)))')
check "bd ready shows only bead A" test "$READY" = "$BEAD_A"
REPO=$(mfget "$RUNID" repo)
check "fixture repo exists on GitHub" gh repo view "$REPO"

# ---------------------------------------------------------------- feature install
FEAT_OUT=$("$VS" feature install --run "$RUNID" 2>&1); FEAT_RC=$?
printf '%s\n' "$FEAT_OUT" | tail -1
check "feature install exits 0" test "$FEAT_RC" -eq 0
check "feature install printed PASS" grep -q '^PASS install' <<<"$FEAT_OUT"
check "install.log recorded" test -f "$EVIDENCE_ROOT/$RUNID/install.log"
# a feature that has not landed yet: `loop` landed in S3 and would really drive this fixture
"$VS" feature review --run "$RUNID" >/dev/null 2>&1; RC=$?
check "unimplemented feature exits 2" test "$RC" -eq 2
"$VS" feature install --nosuch --run "$RUNID" >/dev/null 2>&1; RC=$?
check "unknown flag rejected" test "$RC" -ne 0
"$VS" feature install --backend >/dev/null 2>&1; RC=$?
check "flag without value rejected" test "$RC" -ne 0

# ---------------------------------------------------------------- stub worker, first run
run_stub() { (cd "$FIXTURE" && SMILE_BEAD="$BEAD_A" SMILE_BEAD_TITLE="bead A" SMILE_REPO="$FIXTURE" SMILE_BASE_BRANCH=main "$STUB_WORKER" /dev/null); }
STUB_OUT=$(run_stub 2>&1); STUB_RC=$?
printf '%s\n' "$STUB_OUT" | tail -1
check "stub-worker first run exits 0" test "$STUB_RC" -eq 0
PR=$(cd "$FIXTURE" && gh pr list --head "smile/$BEAD_A" --state open --json number --jq '.[0].number // empty')
check "stub-worker opened one PR" test -n "$PR"
PR_BODY=$(cd "$FIXTURE" && gh pr view "$PR" --json body --jq .body)
check "PR body ends with Bead trailer" test "$(printf '%s' "$PR_BODY" | tail -1)" = "Bead: $BEAD_A"

# ---------------------------------------------------------------- stub worker, fix round
run_stub >/dev/null 2>&1; RC=$?
check "fix round with no review issue exits 4" test "$RC" -eq 4
(cd "$FIXTURE" && gh label create review --force >/dev/null 2>&1)
ISSUE=$(cd "$FIXTURE" && gh issue create --label review --title "stub finding on PR #$PR" \
	--body "$(printf 'stub finding: add a line to the file\n\nPR: #%s' "$PR")" | grep -oE '[0-9]+$')
check "review issue created" test -n "$ISSUE"
FIX_OUT=$(run_stub 2>&1); FIX_RC=$?
printf '%s\n' "$FIX_OUT" | tail -1
check "fix round exits 0" test "$FIX_RC" -eq 0
# the PR's commit list lags the push by a few seconds on GitHub; poll until the fix commit shows
LAST_MSG=""
for _ in 1 2 3 4 5 6; do
	LAST_MSG=$(cd "$FIXTURE" && gh pr view "$PR" --json commits --jq '.commits[-1] | .messageHeadline + "\n" + .messageBody')
	grep -q '^fix: address review' <<<"$LAST_MSG" && break
	sleep 3
done
check "fix commit headline is fix: address review" grep -q '^fix: address review' <<<"$LAST_MSG"
check "fix commit body addresses the issue" grep -q "^addresses #$ISSUE" <<<"$LAST_MSG"

# ---------------------------------------------------------------- down
TMP=$(mfget "$RUNID" tmp)
DOWN_OUT=$("$VS" down "$RUNID" 2>&1); DOWN_RC=$?
printf '%s\n' "$DOWN_OUT" | tail -1
check "down exits 0" test "$DOWN_RC" -eq 0
check "manifest state down" test "$(mfget "$RUNID" state)" = "down"
check "tmux session gone" bash -c "! tmux has-session -t '=$SESSION' 2>/dev/null"
check "temp dir gone" test ! -d "$TMP"
DISPOSAL=$(mfget "$RUNID" disposal)
# gh repo view follows rename redirects, so resolve the name instead of trusting the exit code
disposed() { local a; a=$(gh repo view "$1" --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true); [ -z "$a" ] || [ "$a" = "$1-trash" ]; }
check "repo no longer resolves to its original name" disposed "$REPO"
if [ "$DISPOSAL" = "archived-renamed" ]; then
	check "trash repo is archived" test "$(gh repo view "$REPO-trash" --json isArchived --jq .isArchived 2>/dev/null)" = "true"
else
	check "disposal is deleted" test "$DISPOSAL" = "deleted"
fi
for f in manifest.json beads.json prs.json install.log; do
	check "evidence has $f" test -f "$EVIDENCE_ROOT/$RUNID/$f"
done
check "beads.json lists bead A" grep -q "\"$BEAD_A\"" "$EVIDENCE_ROOT/$RUNID/beads.json"
check "beads.json lists bead B" grep -q "\"$BEAD_B\"" "$EVIDENCE_ROOT/$RUNID/beads.json"
check "prs.json lists the stub PR" grep -q "\"number\": *$PR" "$EVIDENCE_ROOT/$RUNID/prs.json"

"$VS" down "$RUNID" >/dev/null 2>&1; check "second down exits 0" test $? -eq 0
"$VS" down no-such-run >/dev/null 2>&1; check "down without manifest refuses" test $? -ne 0

# ---------------------------------------------------------------- forced failure during up
FAIL_OUT=$(SMILE_VERIFY_FAIL_AFTER=clone "$VS" up 2>&1); FAIL_RC=$?
check "forced up failure exits non-zero" test "$FAIL_RC" -ne 0
FRUN=$("$VS" list | tail -1 | cut -f1)
RUNIDS="$RUNIDS $FRUN"
check "failed run is newer than the main run" test "$FRUN" != "$RUNID"
check "failed run manifest state down" test "$(mfget "$FRUN" state)" = "down"
check "failed run stopped at stage clone" test "$(mfget "$FRUN" stage)" = "clone"
FREPO=$(mfget "$FRUN" repo)
check "failed run repo disposed" disposed "$FREPO"
check "failed run temp dir gone" test ! -d "$(mfget "$FRUN" tmp)"
printf 'forced-failure run %s disposal=%s\n' "$FRUN" "$(mfget "$FRUN" disposal)"

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS verify-smile.test.sh (%s, %s)\n' "$RUNID" "$FRUN"
else
	printf 'FAIL verify-smile.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
