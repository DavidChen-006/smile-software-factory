#!/usr/bin/env bash
# Exercises the verify-smile primitives against one real fixture: up, stamp, seed, tick, events,
# runs, panes, prs, issues, trust, close-bead, kill-pane, time, evidence, down (dry-run then real),
# plus a forced up failure. Needs uv, gh (logged in), bd, treehouse, tmux. Creates and disposes of
# private repos named smile-verify-<runid>.
#
# It tests the lever, not a behaviour of SMILE: what a given behaviour's proof looks like lives in
# .claude/skills/verify-smile/features/, and a verifier composes these verbs to produce it.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VS="$ROOT/.claude/skills/verify-smile/scripts/verify-smile"
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

eq() {   # eq <description> <got> <want>
	local desc="$1" got="$2" want="$3"
	if [ "$got" = "$want" ]; then
		printf 'ok   %s\n' "$desc"
	else
		printf 'FAIL %s: got [%s] want [%s]\n' "$desc" "$got" "$want"
		FAILS=$((FAILS + 1))
	fi
}

mfget() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$EVIDENCE_ROOT/$1/manifest.json" "$2"; }

# jq_ <expression over `d`> [arg]: read one JSON object from stdin as `d`, print the expression.
# A second argument is available to the expression as `a`.
jq_() { python3 -c 'import json,sys; d=json.load(sys.stdin); a=sys.argv[2] if len(sys.argv)>2 else None; print(eval(sys.argv[1]))' "$@"; }
# jl <expression over `rows`> [arg]: the same for a JSON-per-line listing
jl() { python3 -c 'import json,sys; rows=[json.loads(l) for l in sys.stdin if l.strip()]; a=sys.argv[2] if len(sys.argv)>2 else None; print(eval(sys.argv[1]))' "$@"; }
# nev <json object> <event name>: how many of that event the object's `events` array holds
nev() { printf '%s' "$1" | jq_ 'sum(1 for e in d["events"] if e["event"]==a)' "$2"; }

cleanup() {
	local r
	for r in $RUNIDS; do
		[ -f "$EVIDENCE_ROOT/$r/manifest.json" ] || continue
		if [ "$(mfget "$r" state)" != "down" ]; then
			printf 'cleanup: tearing down %s\n' "$r"
			"$VS" down --run "$r" >/dev/null 2>&1 || true
		fi
	done
}
trap cleanup EXIT

# ---------------------------------------------------------------- up
UP_OUT=$("$VS" up 2>/dev/null) || { printf 'FAIL up: %s\n' "$UP_OUT"; exit 1; }
RUNID=$(printf '%s' "$UP_OUT" | jq_ 'd["runid"]')
FIXTURE=$(printf '%s' "$UP_OUT" | jq_ 'd["fixture"]')
SESSION=$(printf '%s' "$UP_OUT" | jq_ 'd["session"]')
REPO=$(printf '%s' "$UP_OUT" | jq_ 'd["repo"]')
[ -n "$RUNID" ] || { printf 'FAIL up: no runid in %s\n' "$UP_OUT"; exit 1; }
RUNIDS="$RUNID"
printf 'run %s fixture %s\n' "$RUNID" "$FIXTURE"

check "manifest written" test -f "$EVIDENCE_ROOT/$RUNID/manifest.json"
eq "manifest state up" "$(mfget "$RUNID" state)" "up"
check "fixture has .beads" test -d "$FIXTURE/.beads"
check "tmux session exists" tmux has-session -t "=$SESSION"
check "fixture repo exists on GitHub" gh repo view "$REPO"
eq "list shows the run as up" "$("$VS" list | jl '[r["state"] for r in rows if r["runid"]==a][0]' "$RUNID")" "up"

# ---------------------------------------------------------------- help and error grammar
check "verb --help exits 0" "$VS" tick --help
check "unknown verb exits non-zero" test "$("$VS" nosuchverb >/dev/null 2>&1; echo $?)" -ne 0
check "unknown flag rejected" test "$("$VS" seed --nosuch >/dev/null 2>&1; echo $?)" -ne 0
check "flag without value rejected" test "$("$VS" seed --beads >/dev/null 2>&1; echo $?)" -ne 0
check "unknown run refused" test "$("$VS" events --run no-such-run >/dev/null 2>&1; echo $?)" -ne 0

# ---------------------------------------------------------------- stamp
STAMP_OUT=$("$VS" stamp --run "$RUNID" 2>/dev/null) || { printf 'FAIL stamp\n'; exit 1; }
printf 'stamp: %s\n' "$STAMP_OUT"
eq "manifest install stamped" "$(mfget "$RUNID" install)" "stamped"
check "shim is executable" test -x "$FIXTURE/smile/smile"
check "config stamped" test -f "$FIXTURE/smile.config.yaml"
eq "init created .factory" "$(printf '%s' "$STAMP_OUT" | jq_ '"created .factory" in d["init"]')" "True"
check "install transcript kept" test -s "$EVIDENCE_ROOT/$RUNID/install-stamp.log"

# ---------------------------------------------------------------- doctor
DOC_OUT=$("$VS" doctor --run "$RUNID" 2>/dev/null); DOC_RC=$?
eq "doctor exits 0 on a fresh fixture" "$DOC_RC" "0"
eq "doctor reports ok" "$(printf '%s' "$DOC_OUT" | jq_ 'd["ok"]')" "True"
eq "doctor ran smile doctor through the shim" \
	"$(printf '%s' "$DOC_OUT" | jq_ 'sum(1 for c in d["checks"] if c["name"]=="smile.doctor" and c["detail"].count("ok ")==8)')" "1"

# ---------------------------------------------------------------- seed
SEED_OUT=$("$VS" seed --beads 2 --run "$RUNID" 2>/dev/null) || { printf 'FAIL seed\n'; exit 1; }
BEAD_A=$(printf '%s' "$SEED_OUT" | jq_ 'd["beads"][0]')
BEAD_B=$(printf '%s' "$SEED_OUT" | jq_ 'd["beads"][1]')
printf 'beads %s %s\n' "$BEAD_A" "$BEAD_B"
eq "seed created two beads" "$(printf '%s' "$SEED_OUT" | jq_ 'len(d["beads"])')" "2"
eq "both beads are ready" "$(printf '%s' "$SEED_OUT" | jq_ 'sorted(d["ready"]) == sorted(d["beads"])')" "True"

# ---------------------------------------------------------------- tick: claim
TICK1=$("$VS" tick --run "$RUNID" 2>/dev/null)
printf 'claim tick: %s\n' "$(printf '%s' "$TICK1" | jq_ '" ".join(e["event"] for e in d["events"])')"
eq "claim tick exits 0" "$(printf '%s' "$TICK1" | jq_ 'd["exit"]')" "0"
for n in bead.claimed worktree.acquired pane.spawned; do
	eq "claim tick logged two $n" "$(nev "$TICK1" "$n")" "2"
done

eq "runs lists two live run files" "$("$VS" runs --run "$RUNID" | jq_ 'len(d["live"])')" "2"
eq "runs live entries carry a handle" "$("$VS" runs --run "$RUNID" | jq_ 'all(r["handle"] for r in d["live"])')" "True"
eq "trust marked both worktrees" "$("$VS" trust --run "$RUNID" | jq_ 'sum(1 for v in d["projects"].values() if v is True)')" "2"
check "trust lives under the scratch home" test -f "$EVIDENCE_ROOT/$RUNID/home/.claude.json"
check "panes lists the session windows" test -n "$("$VS" panes --run "$RUNID")"

EV_A=$("$VS" events --bead "$BEAD_A" --run "$RUNID" | jl '" ".join(r["event"] for r in rows)')
eq "bead A's first three events are the claim sequence" "$EV_A" "bead.claimed worktree.acquired pane.spawned"
eq "events --since skips the head of the log" \
	"$("$VS" events --since 1 --run "$RUNID" | jl 'rows[0]["event"]')" "bead.claimed"

# the GitHub API lags the worker's `gh pr create`, so poll rather than read once
for _ in 1 2 3 4 5 6 7 8; do
	NPR=$("$VS" prs --run "$RUNID" | jl 'sum(1 for r in rows if r["bead"])')
	[ "$NPR" -ge 2 ] && break
	sleep 5
done
eq "two pull requests carry a Bead trailer" "$NPR" "2"
eq "both pull requests are open" "$("$VS" prs --run "$RUNID" | jl 'sum(1 for r in rows if r["state"]=="OPEN")')" "2"

# ---------------------------------------------------------------- tick: review, merge, reap
TICK2=$("$VS" tick --run "$RUNID" 2>/dev/null)
printf 'review tick: %s\n' "$(printf '%s' "$TICK2" | jq_ '" ".join(e["event"] for e in d["events"])')"
eq "review tick merged both pull requests" "$(nev "$TICK2" pr.merged)" "2"
eq "GitHub reports both pull requests merged" \
	"$("$VS" prs --run "$RUNID" | jl 'sum(1 for r in rows if r["state"]=="MERGED" and r["mergedAt"])')" "2"
eq "no review issue is open" "$("$VS" issues --run "$RUNID" | jl 'sum(1 for r in rows if r["state"]=="OPEN")')" "0"

TICK3=$("$VS" tick --run "$RUNID" 2>/dev/null)
printf 'reap tick: %s\n' "$(printf '%s' "$TICK3" | jq_ '" ".join(e["event"] for e in d["events"])')"
eq "reap tick logged two pane.reaped" "$(nev "$TICK3" pane.reaped)" "2"
eq "reap tick logged campaign.complete" "$(nev "$TICK3" campaign.complete)" "1"
eq "runs moved both files to done" "$("$VS" runs --run "$RUNID" | jq_ 'len(d["done"])')" "2"
eq "runs has nothing live" "$("$VS" runs --run "$RUNID" | jq_ 'len(d["live"])')" "0"
eq "bead A's events end with pane.reaped" \
	"$("$VS" events --bead "$BEAD_A" --run "$RUNID" | jl 'rows[-1]["event"]')" "pane.reaped"
check "the driver pid file is gone" test ! -e "$FIXTURE/.factory/driver.pid"

# ---------------------------------------------------------------- kill-pane on a live pane
BASE_PANES=$("$VS" panes --run "$RUNID" | jl 'len(rows)')
BEAD_C=$("$VS" seed --beads 1 --run "$RUNID" 2>/dev/null | jq_ 'd["beads"][0]')
"$VS" tick --worker-sleep 90 --run "$RUNID" >/dev/null 2>&1
eq "the slow worker's bead is live" "$("$VS" runs --run "$RUNID" | jq_ 'len(d["live"])')" "1"
eq "its pane is a new window" "$("$VS" panes --run "$RUNID" | jl 'len(rows)')" "$((BASE_PANES + 1))"
sleep 20   # the stub worker finishes in seconds; a pane still up after this really did sleep
eq "--worker-sleep kept the pane alive well past the tick" \
	"$("$VS" panes --run "$RUNID" | jl 'len(rows)')" "$((BASE_PANES + 1))"
KP=$("$VS" kill-pane "$BEAD_C" --run "$RUNID" 2>/dev/null)
printf 'kill-pane: %s\n' "$KP"
eq "kill-pane exits 0" "$(printf '%s' "$KP" | jq_ 'd["exit"]')" "0"
eq "kill-pane used the run file's handle" \
	"$(printf '%s' "$KP" | jq_ 'd["handle"].startswith("tmux:")')" "True"
eq "a second kill of the same pane still exits 0" \
	"$("$VS" kill-pane "$BEAD_C" --run "$RUNID" 2>/dev/null | jq_ 'd["exit"]')" "0"
eq "the window count is back" "$("$VS" panes --run "$RUNID" | jl 'len(rows)')" "$BASE_PANES"

# ---------------------------------------------------------------- close-bead
CB=$("$VS" close-bead "$BEAD_C" --run "$RUNID" 2>/dev/null)
eq "close-bead reads the status back as closed" "$(printf '%s' "$CB" | jq_ 'd["status"]')" "closed"
check "close-bead refuses an unknown bead" test "$("$VS" close-bead sv-nope --run "$RUNID" >/dev/null 2>&1; echo $?)" -ne 0

# ---------------------------------------------------------------- no secret under the evidence dir
TOKEN=$(gh auth token 2>/dev/null || printf 'no-token-available')
eq "the gh token is nowhere under the evidence directory" \
	"$(grep -rlF "$TOKEN" "$EVIDENCE_ROOT/$RUNID" 2>/dev/null | wc -l | tr -d ' ')" "0"
eq "the wrapper files name no token variable" \
	"$(grep -lE 'GH_TOKEN' "$EVIDENCE_ROOT/$RUNID/home/worker-env" "$EVIDENCE_ROOT/$RUNID/home/reviewer-env" 2>/dev/null | wc -l | tr -d ' ')" "0"
eq "the token rides the fixture session's environment instead" \
	"$(tmux show-environment -t "=$SESSION" GH_TOKEN >/dev/null 2>&1 && printf yes || printf no)" "yes"

# ---------------------------------------------------------------- kill-pane with no run file
KPE=$("$VS" kill-pane sv-nosuch --run "$RUNID" 2>/dev/null); KPE_RC=$?
eq "kill-pane without a run file exits 1" "$KPE_RC" "1"
eq "kill-pane without a run file prints an error object on stdout" \
	"$(printf '%s' "$KPE" | jq_ '"error" in d')" "True"

# ---------------------------------------------------------------- crash and escalation
BEAD_D=$("$VS" seed --beads 1 --run "$RUNID" 2>/dev/null | jq_ 'd["beads"][0]')
"$VS" tick --worker-crash "$BEAD_D" --run "$RUNID" >/dev/null 2>&1
CRASH1=$("$VS" tick --worker-crash "$BEAD_D" --run "$RUNID" 2>/dev/null)
eq "--worker-crash makes the driver see a crash" \
	"$(printf '%s' "$CRASH1" | jq_ 'sum(1 for e in d["events"] if e["event"]=="worker.crashed" and e["detail"]=="attempt 1" and e["bead"]==a)' "$BEAD_D")" "1"
eq "the crash is respawned, not reclaimed" \
	"$(printf '%s' "$CRASH1" | jq_ 'sum(1 for e in d["events"] if e["event"]=="bead.claimed" and e["bead"]==a)' "$BEAD_D")" "0"
CRASH2=$("$VS" tick --worker-crash "$BEAD_D" --run "$RUNID" 2>/dev/null)
eq "the second crash escalates" \
	"$(printf '%s' "$CRASH2" | jq_ 'sum(1 for e in d["events"] if e["event"]=="worker.crashed" and e["detail"]=="escalated" and e["bead"]==a)' "$BEAD_D")" "1"
eq "the escalated run file is filed under crashed" \
	"$("$VS" runs --run "$RUNID" | jq_ 'sum(1 for r in d["crashed"] if r.get("bead")==a)' "$BEAD_D")" "1"

# ---------------------------------------------------------------- review: lock, cap, hand merge
BEAD_E=$("$VS" seed --beads 1 --run "$RUNID" 2>/dev/null | jq_ 'd["beads"][0]')
"$VS" tick --run "$RUNID" >/dev/null 2>&1
PR_E=""
for _ in 1 2 3 4 5 6 7 8; do
	PR_E=$("$VS" prs --run "$RUNID" | jl '([str(r["number"]) for r in rows if r["bead"]==a and r["state"]=="OPEN"] or [""])[0]' "$BEAD_E")
	[ -n "$PR_E" ] && break
	sleep 5
done
eq "the new bead opened a pull request" "$(test -n "$PR_E" && printf yes || printf no)" "yes"

# a review killed mid-run leaves this path registered; the lane must reclaim it, not wedge
git -C "$FIXTURE" worktree add --detach "$FIXTURE/.factory/review/$PR_E" HEAD >/dev/null 2>&1
REV1=$("$VS" review "$PR_E" --reviewer /usr/bin/false --run "$RUNID" 2>/dev/null)
eq "a failing reviewer is exit 1" "$(printf '%s' "$REV1" | jq_ 'd["exit"]')" "1"
eq "the stale review worktree did not wedge the pull request" \
	"$(printf '%s' "$REV1" | jq_ 'sum(1 for e in d["events"] if e["event"]=="review.started")')" "1"
eq "a failed review is kept under reviews/ as .failed.md" \
	"$(printf '%s' "$REV1" | jq_ 'd["review"].endswith(".failed.md")')" "True"
"$VS" review "$PR_E" --reviewer /usr/bin/false --run "$RUNID" >/dev/null 2>&1
"$VS" review "$PR_E" --reviewer /usr/bin/false --run "$RUNID" >/dev/null 2>&1
CAP=$("$VS" tick --run "$RUNID" 2>/dev/null)
eq "three failed reviews stop the driver reviewing that head" \
	"$(printf '%s' "$CAP" | jq_ 'sum(1 for e in d["events"] if e["event"]=="review.started")')" "0"
eq "the capped head is escalated once" \
	"$(printf '%s' "$CAP" | jq_ 'sum(1 for e in d["events"] if e["event"]=="watch.escalation" and e["detail"]=="review failed 3 times")')" "1"
eq "ticking again does not escalate twice" \
	"$("$VS" tick --run "$RUNID" 2>/dev/null | jq_ 'sum(1 for e in d["events"] if e["event"]=="watch.escalation")')" "0"

(cd "$FIXTURE" && gh pr merge "$PR_E" --squash --delete-branch >/dev/null 2>&1)
MERGED=$("$VS" tick --run "$RUNID" 2>/dev/null)
eq "a hand-merged pull request closes its bead" \
	"$(printf '%s' "$MERGED" | jq_ 'sum(1 for e in d["events"] if e["event"]=="bead.closed" and e["bead"]==a)' "$BEAD_E")" "1"
eq "a hand-merged pull request is never a crash" \
	"$(printf '%s' "$MERGED" | jq_ 'sum(1 for e in d["events"] if e["event"]=="worker.crashed" and e["bead"]==a)' "$BEAD_E")" "0"
eq "pr.merged names the merge commit GitHub reports" \
	"$(printf '%s' "$MERGED" | jq_ '([e["sha"] for e in d["events"] if e["event"]=="pr.merged"] or [""])[0]')" \
	"$("$VS" prs --run "$RUNID" | jl '([r["mergeCommit"] for r in rows if str(r["number"])==a] or [""])[0]' "$PR_E")"

REVC=$("$VS" review "$PR_E" --run "$RUNID" 2>/dev/null); REVC_RC=$?
eq "review refuses a pull request that is not open" "$REVC_RC" "1"
eq "a refused review logs nothing" "$(printf '%s' "$REVC" | jq_ 'len(d["events"])')" "0"

# ---------------------------------------------------------------- gate and time
eq "gate status prints the mode" \
	"$("$VS" gate status --run "$RUNID" 2>/dev/null | jq_ 'd["stdout"][0]')" "mode auto"
TIME_OUT=$("$VS" time status --n 2 --run "$RUNID" 2>/dev/null)
printf 'time: %s\n' "$TIME_OUT"
eq "time ran the command twice" "$(printf '%s' "$TIME_OUT" | jq_ 'len(d["samples_ms"])')" "2"
eq "time reports a median" "$(printf '%s' "$TIME_OUT" | jq_ 'isinstance(d["median_ms"], int)')" "True"

# ---------------------------------------------------------------- evidence before down
eq "evidence names the run directory" \
	"$("$VS" evidence --run "$RUNID" | jq_ 'd["dir"]')" "$EVIDENCE_ROOT/$RUNID"

# ---------------------------------------------------------------- down
TMP=$(mfget "$RUNID" tmp)
DRY=$("$VS" down --dry-run --run "$RUNID" 2>/dev/null)
printf 'down --dry-run: %s\n' "$DRY"
eq "dry run says it would delete the repo" "$(printf '%s' "$DRY" | jq_ 'd["would_delete_repo"]')" "True"
eq "dry run left the state up" "$(mfget "$RUNID" state)" "up"
check "dry run left the tmux session" tmux has-session -t "=$SESSION"
check "dry run left the repo" gh repo view "$REPO"

DOWN_OUT=$("$VS" down --run "$RUNID" 2>/dev/null); DOWN_RC=$?
printf 'down: %s\n' "$DOWN_OUT"
eq "down exits 0" "$DOWN_RC" "0"
eq "manifest state down" "$(mfget "$RUNID" state)" "down"
eq "down killed the session it opened" "$(printf '%s' "$DOWN_OUT" | jq_ 'd["session_killed"]')" "True"
check "tmux session gone" test "$(tmux has-session -t "=$SESSION" 2>/dev/null && echo live)" != "live"
check "temp dir gone" test ! -d "$TMP"

DISPOSAL=$(mfget "$RUNID" disposal)
# gh repo view follows rename redirects, so resolve the name instead of trusting the exit code
disposed() { local a; a=$(gh repo view "$1" --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true); [ -z "$a" ] || [ "$a" = "$1-trash" ]; }
check "repo no longer resolves to its original name" disposed "$REPO"
if [ "$DISPOSAL" = "archived-renamed" ]; then
	check "trash repo is archived" test "$(gh repo view "$REPO-trash" --json isArchived --jq .isArchived 2>/dev/null)" = "true"
else
	eq "disposal is deleted" "$DISPOSAL" "deleted"
fi

for f in manifest.json beads.json prs.json install-stamp.log; do
	check "evidence has $f" test -f "$EVIDENCE_ROOT/$RUNID/$f"
done
check "evidence has the fixture's .factory" test -f "$EVIDENCE_ROOT/$RUNID/factory/events.jsonl"
check "beads.json lists bead A" grep -q "\"$BEAD_A\"" "$EVIDENCE_ROOT/$RUNID/beads.json"
check "beads.json lists bead B" grep -q "\"$BEAD_B\"" "$EVIDENCE_ROOT/$RUNID/beads.json"
eq "evidence survives down" \
	"$("$VS" evidence --run "$RUNID" | jq_ 'len(d["files"]) > 3')" "True"
eq "events still readable from the kept factory copy" \
	"$(python3 -c 'import json,sys; print(sum(1 for l in open(sys.argv[1]) if json.loads(l)["event"]=="campaign.complete"))' "$EVIDENCE_ROOT/$RUNID/factory/events.jsonl")" "1"

"$VS" down --run "$RUNID" >/dev/null 2>&1; check "second down exits 0" test $? -eq 0
"$VS" down --run no-such-run >/dev/null 2>&1; check "down without manifest refuses" test $? -ne 0
"$VS" gc --dry-run >/dev/null 2>&1; check "gc --dry-run exits 0" test $? -eq 0

# ---------------------------------------------------------------- forced failure during up
FAIL_OUT=$(SMILE_VERIFY_FAIL_AFTER=clone "$VS" up 2>&1); FAIL_RC=$?
check "forced up failure exits non-zero" test "$FAIL_RC" -ne 0
FRUN=$("$VS" list | tail -1 | jq_ 'd["runid"]')
RUNIDS="$RUNIDS $FRUN"
check "failed run is newer than the main run" test "$FRUN" != "$RUNID"
eq "failed run manifest state down" "$(mfget "$FRUN" state)" "down"
eq "failed run stopped at stage clone" "$(mfget "$FRUN" stage)" "clone"
check "failed run repo disposed" disposed "$(mfget "$FRUN" repo)"
check "failed run temp dir gone" test ! -d "$(mfget "$FRUN" tmp)"
printf 'forced-failure run %s disposal=%s\n' "$FRUN" "$(mfget "$FRUN" disposal)"

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS verify-smile.test.sh (%s, %s)\n' "$RUNID" "$FRUN"
else
	printf 'FAIL verify-smile.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
