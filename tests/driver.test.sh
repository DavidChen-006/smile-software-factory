#!/usr/bin/env bash
# Drives the stamped driver, `smile run`, per docs/RUNTIME-CONTRACT.md section 8: the singleton
# pid file, a tick that claims and spawns, the max_parallel cap, the pause skip, reaping a closed
# bead, crash respawn and escalation, campaign completion, the work order, the worker argv and
# environment, the trust edit, and the factory directory seen from a linked worktree.
#
# bd and treehouse are real, in scratch repos under $TMP with HOME pointed at $TMP/home, so the
# real ~/.claude.json and the real treehouse pool are never touched. The pane tool is a fake tmux
# first on PATH that records every argv line and answers list-windows from a state file, so the
# real `smile mux` and mux.d/tmux run unchanged and a pane can be killed off at will. No tmux
# server is started and no session is opened.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# -P: the physical path, because the driver resolves the factory directory through git, which
# answers with symlinks resolved, and the tests compare those paths as exact strings
TMP=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smile-driver-test.XXXXXX")" && pwd -P)
export HOME="$TMP/home"
export SMILE_MUX_SESSION="s3bash-$$"
mkdir -p "$HOME"
cleanup() {
	# the fake tmux never starts a server; kill any session of our own name in case a real tmux ran
	command -v tmux >/dev/null 2>&1 && PATH="$REAL_PATH" tmux kill-session -t "=$SMILE_MUX_SESSION" >/dev/null 2>&1
	rm -rf "$TMP"
}
REAL_PATH="$PATH"
trap cleanup EXIT
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

nlines() { printf '%s' "$1" | grep -c ''; }                      # lines in a string, 0 when empty
rc_of() { "$@" >/dev/null 2>&1; printf '%s' "$?"; }
stderr_of() { "$@" 2>&1 >/dev/null; }

# ---------------------------------------------------------------- the fake tmux
FAKEBIN="$TMP/bin"; mkdir -p "$FAKEBIN"
export FAKE_TMUX_LOG="$TMP/tmux.log" FAKE_TMUX_STATE="$TMP/tmux.state"
: > "$FAKE_TMUX_LOG"; : > "$FAKE_TMUX_STATE"
cat > "$FAKEBIN/tmux" <<'PYEOF'
#!/usr/bin/env python3
"""A tmux stand-in for the driver tests. Records every argv line, keeps one row per window
("<session> <window_id> <pane_dead>") in a state file the test edits to kill a pane off, and runs
the spawned command itself so the stub worker's argv and environment can be read back."""
import os, subprocess, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_TMUX_LOG"], "a") as f:
    f.write("\t".join(argv) + "\n")
state_path = os.environ["FAKE_TMUX_STATE"]

def rows():
    if not os.path.exists(state_path):
        return []
    return [l.split() for l in open(state_path).read().splitlines() if l.strip()]

def put(rs):
    with open(state_path, "w") as f:
        f.write("".join(" ".join(r) + "\n" for r in rs))

verb = argv[0] if argv else ""
if verb in ("new-window", "new-session"):
    session = cwd = None
    command = []
    i = 1
    while i < len(argv):
        if argv[i] in ("-t", "-s"):
            session = argv[i + 1].lstrip("="); i += 2
        elif argv[i] == "-c":
            cwd = argv[i + 1]; i += 2
        elif argv[i] == "--":
            command = argv[i + 1:]; break
        else:
            i += 1
    rs = rows()
    if verb == "new-window" and not any(r[0] == session for r in rs):
        sys.stderr.write("can't find session: %s\n" % session)
        sys.exit(1)
    counter_path = state_path + ".counter"
    n = int(open(counter_path).read()) + 1 if os.path.exists(counter_path) else 1
    open(counter_path, "w").write(str(n))
    window = "@%d" % n
    rs.append([session, window, "0"])
    put(rs)
    if command:
        subprocess.call(command, cwd=cwd)
    print("%s:%s" % (session, window))
elif verb == "list-windows":
    session = None
    for i, a in enumerate(argv):
        if a == "-t":
            session = argv[i + 1].lstrip("=")
    out = ["%s %s" % (r[1], r[2]) for r in rows() if r[0] == session]
    if not out:
        sys.exit(1)
    print("\n".join(out))
elif verb == "kill-window":
    target = ""
    for i, a in enumerate(argv):
        if a == "-t":
            target = argv[i + 1].lstrip("=")
    session, _, window = target.rpartition(":")
    put([r for r in rows() if not (r[0] == session and r[1] == window)])
elif verb in ("set-window-option", "set-option"):
    pass
else:
    sys.exit(1)
PYEOF
chmod +x "$FAKEBIN/tmux"
export PATH="$FAKEBIN:$PATH"

# pane_kill <handle>: mark the pane dead, as a worker exiting would
pane_kill() { sed -i.bak "s|^\(.* ${1##*:} \)0$|\11|" "$FAKE_TMUX_STATE" && rm -f "$FAKE_TMUX_STATE.bak"; }

# ---------------------------------------------------------------- the stub worker
WORKER="$TMP/stub-worker"
cat > "$WORKER" <<'SHEOF'
#!/bin/sh
{
	printf 'argv:'; for a in "$@"; do printf ' [%s]' "$a"; done; printf '\n'
	printf 'bead=%s title=%s repo=%s base=%s\n' \
		"${SMILE_BEAD:-}" "${SMILE_BEAD_TITLE:-}" "${SMILE_REPO:-}" "${SMILE_BASE_BRANCH:-}"
	printf 'cwd=%s\n' "$(pwd)"
} >> "$WORKER_LOG"
exit 0
SHEOF
chmod +x "$WORKER"
export SMILE_WORKER_CMD="$WORKER"

# ---------------------------------------------------------------- scratch repos
# new_repo <name> <bead title>...: a stamped repo with bd, treehouse, a spec, and one bead per
# title. Sets REPO, SMILE, FACTORY, and BEADS (ids in creation order).
new_repo() {
	local name="$1" title; shift
	REPO="$TMP/$name"; SMILE="$REPO/smile/smile"; FACTORY="$REPO/.factory"
	mkdir -p "$REPO/docs"
	git -C "$REPO" init -q
	git -C "$REPO" config user.email driver@test
	git -C "$REPO" config user.name driver
	printf '# spec\n' > "$REPO/docs/SPEC.md"
	git -C "$REPO" add -A
	git -C "$REPO" commit -q -m init
	python3 "$ROOT/install.py" "$REPO" >/dev/null
	SMILE_ROOT="$REPO" "$SMILE" init >/dev/null
	BEADS=""
	for title in "$@"; do
		BEADS="$BEADS $(cd "$REPO" && BD_NON_INTERACTIVE=1 bd create "$title" -d "do $title" --silent)"
	done
	BEADS="${BEADS# }"
	git -C "$REPO" add -A
	git -C "$REPO" commit -q -m stamp
	export WORKER_LOG="$TMP/$name.worker.log"
	: > "$WORKER_LOG"
}

drive() { SMILE_ROOT="$REPO" "$SMILE" run "$@"; }   # run the driver against the current repo
set_key() { sed -i.bak "s|^$1:.*|$1: $2|" "$REPO/smile.config.yaml" && rm -f "$REPO/smile.config.yaml.bak"; }
bead_n() { printf '%s\n' "$BEADS" | cut -d' ' -f"$1"; }
close_bead() { (cd "$REPO" && BD_NON_INTERACTIVE=1 bd close "$1" >/dev/null 2>&1); }
status_of() { (cd "$REPO" && BD_NON_INTERACTIVE=1 bd list --all --json) | python3 -c '
import json, sys
print(next((b["status"] for b in json.load(sys.stdin) if b["id"] == sys.argv[1]), "?"))' "$1"; }

count_ev() { grep -c "\"event\":\"$1\"" "$FACTORY/events.jsonl" 2>/dev/null || true; }
# events_for <bead>: that bead's event names, in order, space separated
events_for() { python3 -c '
import json, sys
names = []
for line in open(sys.argv[1]):
    o = json.loads(line)
    if o["bead"] == sys.argv[2]:
        names.append(o["event"])
print(" ".join(names))' "$FACTORY/events.jsonl" "$1"; }
# detail_of <bead> <event> [<nth>]: the detail field of the nth (default 1) such event
detail_of() { python3 -c '
import json, sys
hits = [o["detail"] for o in map(json.loads, open(sys.argv[1]))
        if o["bead"] == sys.argv[2] and o["event"] == sys.argv[3]]
print(hits[int(sys.argv[4]) - 1] if len(hits) >= int(sys.argv[4]) else "")' \
	"$FACTORY/events.jsonl" "$1" "$2" "${3:-1}"; }
run_field() { python3 -c '
import json, sys
print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }
run_keys() { python3 -c '
import json, sys
print(" ".join(sorted(json.load(open(sys.argv[1])))))' "$1"; }
trust_of() { python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("projects", {}).get(sys.argv[2], {}).get("hasTrustDialogAccepted"))' "$HOME/.claude.json" "$1"; }

# ---------------------------------------------------------------- usage
new_repo usage "bead one"
check "an unknown flag exits 2" test "$(rc_of drive --wiggle)" -eq 2
check "--interval without a value exits 2" test "$(rc_of drive --interval)" -eq 2
check "a non-numeric interval exits 2" test "$(rc_of drive --interval soon)" -eq 2
check "a rejected run appends nothing" test "$(count_ev campaign.start)" -eq 0

# ---------------------------------------------------------------- singleton
mkdir -p "$FACTORY"
printf '%s\n' "$$" > "$FACTORY/driver.pid"
check "a second driver exits 1" test "$(rc_of drive --once)" -eq 1
check "it names the running pid on stderr" \
	test "$(stderr_of drive --once)" = "driver already running (pid $$)"
check "it is one stderr line" test "$(nlines "$(stderr_of drive --once)")" -eq 1
check "it claimed nothing" test "$(count_ev bead.claimed)" -eq 0
check "it left the pid file alone" test "$(cat "$FACTORY/driver.pid")" = "$$"

printf '999999\n' > "$FACTORY/driver.pid"          # a pid no process holds
check "a stale pid file is overwritten" drive --once
check "the pid file is removed on exit" test ! -e "$FACTORY/driver.pid"
check "the stale run claimed its bead" test "$(count_ev bead.claimed)" -eq 1

# ---------------------------------------------------------------- one tick, two beads
printf '{"numStartups":7,"projects":{"/somewhere/else":{"hasTrustDialogAccepted":true}}}\n' > "$HOME/.claude.json"
new_repo two "bead A" "bead B"
A=$(bead_n 1); B=$(bead_n 2)
check "a tick with two ready beads exits 0" drive --once

check "it appended campaign.start" test "$(count_ev campaign.start)" -eq 1
check "campaign.start carries the interval" \
	test "$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).readline())["detail"])' "$FACTORY/events.jsonl")" = "interval 60"
check "two beads were claimed" test "$(count_ev bead.claimed)" -eq 2
check "two worktrees were acquired" test "$(count_ev worktree.acquired)" -eq 2
check "two panes were spawned" test "$(count_ev pane.spawned)" -eq 2
check "the events for bead A are claimed, worktree, spawned" \
	test "$(events_for "$A")" = 'bead.claimed worktree.acquired pane.spawned'
check "the events for bead B are claimed, worktree, spawned" \
	test "$(events_for "$B")" = 'bead.claimed worktree.acquired pane.spawned'
check "both beads are in_progress in bd" \
	test "$(status_of "$A")$(status_of "$B")" = in_progressin_progress

WT_A=$(detail_of "$A" worktree.acquired)
HANDLE_A=$(detail_of "$A" pane.spawned)
check "worktree.acquired carries the worktree path" test -d "$WT_A"
check "pane.spawned carries the mux handle" \
	test -n "$(printf '%s' "$HANDLE_A" | grep -E "^tmux:$SMILE_MUX_SESSION:@[0-9]+$")"
check "the pane is alive through the seam" env SMILE_ROOT="$REPO" "$SMILE" mux alive "$HANDLE_A"

check "two run state files are live" test "$(ls "$FACTORY/runs"/*.json | grep -c '')" -eq 2
check "the run file carries the six keys" \
	test "$(run_keys "$FACTORY/runs/$A.json")" = 'attempts bead handle order spawned_at worktree'
check "the run file names the bead" test "$(run_field "$FACTORY/runs/$A.json" bead)" = "$A"
check "the run file names the worktree" test "$(run_field "$FACTORY/runs/$A.json" worktree)" = "$WT_A"
check "the run file names the handle" test "$(run_field "$FACTORY/runs/$A.json" handle)" = "$HANDLE_A"
check "the run file starts at attempt 1" test "$(run_field "$FACTORY/runs/$A.json" attempts)" = 1
check "the run file names the order" test "$(run_field "$FACTORY/runs/$A.json" order)" = "$FACTORY/orders/$A.md"

# ---------------------------------------------------------------- the work order
ORDER=$(cat "$FACTORY/orders/$A.md")
check "the order file exists" test -f "$FACTORY/orders/$A.md"
check "every placeholder was substituted" test -z "$(printf '%s' "$ORDER" | grep '{{')"
check "the order names the bead id" test -n "$(printf '%s' "$ORDER" | grep -F "$A")"
check "the order names the bead title" test -n "$(printf '%s' "$ORDER" | grep -F 'bead A')"
check "the order carries the description" test -n "$(printf '%s' "$ORDER" | grep -F 'do bead A')"
check "the order names the spec" test -n "$(printf '%s' "$ORDER" | grep -F 'docs/SPEC.md')"
check "the order names the base branch" test -n "$(printf '%s' "$ORDER" | grep -F 'bead/'"$A")"

# ---------------------------------------------------------------- worker argv, env, cwd
check "the worker ran twice" test "$(grep -c '^argv:' "$WORKER_LOG")" -eq 2
check "the worker's last argument is its order path" \
	test -n "$(grep -F "argv: [$FACTORY/orders/$A.md]" "$WORKER_LOG")"
check "the worker environment carries the four variables" \
	test -n "$(grep -F "bead=$A title=bead A repo=$REPO base=main" "$WORKER_LOG")"
check "the worker ran in its worktree" test -n "$(grep -F "cwd=$WT_A" "$WORKER_LOG")"
check "the pane was opened through the mux seam, with remain-on-exit off" \
	test "$(grep -c 'set-window-option' "$FAKE_TMUX_LOG")" -ge 2

# ---------------------------------------------------------------- trust
check "the worktree is trusted in ~/.claude.json" test "$(trust_of "$WT_A")" = True
check "the other project entry survived" test "$(trust_of /somewhere/else)" = True
check "the other keys survived" \
	test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["numStartups"])' "$HOME/.claude.json")" = 7

# ---------------------------------------------------------------- reap
close_bead "$A"
pane_kill "$HANDLE_A"
KILLS_BEFORE=$(grep -c 'kill-window' "$FAKE_TMUX_LOG")
check "the reaping tick exits 0" drive --once
check "the closed bead's pane was reaped" test "$(count_ev pane.reaped)" -eq 1
check "pane.reaped carries the handle" test "$(detail_of "$A" pane.reaped)" = "$HANDLE_A"
check "the seam was asked to kill the window" \
	test "$(grep -c 'kill-window' "$FAKE_TMUX_LOG")" -gt "$KILLS_BEFORE"
check "the run file moved to runs/done" test -f "$FACTORY/runs/done/$A.json"
check "it is no longer live" test ! -e "$FACTORY/runs/$A.json"
check "the worktree lease was returned" \
	test -z "$( (cd "$REPO" && treehouse status 2>/dev/null) | grep -F "held by $A")"
check "the open bead's pane was left alone" test ! -e "$FACTORY/runs/done/$B.json"
check "the campaign is not complete while bead B is open" test "$(count_ev campaign.complete)" -eq 0

# ---------------------------------------------------------------- campaign.complete
HANDLE_B=$(detail_of "$B" pane.spawned)
close_bead "$B"
pane_kill "$HANDLE_B"
check "the last tick exits 0" drive --once
check "campaign.complete was appended" test "$(count_ev campaign.complete)" -eq 1
check "both run files are done" test "$(ls "$FACTORY/runs/done"/*.json | grep -c '')" -eq 2
check "no run file is live" test -z "$(ls "$FACTORY/runs"/*.json 2>/dev/null)"
check "the pid file is gone" test ! -e "$FACTORY/driver.pid"

# ---------------------------------------------------------------- max_parallel
new_repo capped "bead A" "bead B"
set_key max_parallel 1
check "a capped tick exits 0" drive --once
check "max_parallel 1 claims one bead" test "$(count_ev bead.claimed)" -eq 1
check "max_parallel 1 spawns one pane" test "$(count_ev pane.spawned)" -eq 1
check "max_parallel 1 leaves one live run" test "$(ls "$FACTORY/runs"/*.json | grep -c '')" -eq 1

# ---------------------------------------------------------------- pause
new_repo paused "bead A" "bead B"
mkdir -p "$FACTORY"
: > "$FACTORY/pause"
check "a paused tick exits 0" drive --once
check "a paused driver claims nothing" test "$(count_ev bead.claimed)" -eq 0
check "a paused driver spawns nothing" test "$(count_ev pane.spawned)" -eq 0
check "a paused driver logs nothing about pausing" test "$(count_ev driver.paused)" -eq 0
check "a paused tick appends campaign.start and nothing else" \
	test "$(nlines "$(cat "$FACTORY/events.jsonl")")" -eq 1
check "no bead was claimed in bd" test "$(status_of "$(bead_n 1)")" = open
rm -f "$FACTORY/pause"
check "the tick after resuming claims" drive --once
check "it claimed two beads" test "$(count_ev bead.claimed)" -eq 2

# ---------------------------------------------------------------- crash, respawn, escalate
new_repo crashy "bead A"
C=$(bead_n 1)
check "the first tick exits 0" drive --once
H1=$(detail_of "$C" pane.spawned)
pane_kill "$H1"
check "the crash tick exits 0" drive --once
check "one crash was logged" test "$(count_ev worker.crashed)" -eq 1
check "the crash names the attempt" test "$(detail_of "$C" worker.crashed)" = 'attempt 1'
check "the worker was respawned" test "$(count_ev pane.spawned)" -eq 2
check "the run file counts attempt 2" test "$(run_field "$FACTORY/runs/$C.json" attempts)" = 2
check "the bead is still claimed" test "$(status_of "$C")" = in_progress
H2=$(detail_of "$C" pane.spawned 2)
check "the respawn got a new handle" test "$H2" != "$H1"

pane_kill "$H2"
check "the escalating tick exits 0" drive --once
check "the second crash is logged" test "$(detail_of "$C" worker.crashed 2)" = 'attempt 2'
check "the escalation is logged" test "$(detail_of "$C" worker.crashed 3)" = escalated
check "there are three crash events" test "$(count_ev worker.crashed)" -eq 3
check "the run file moved to runs/crashed" test -f "$FACTORY/runs/crashed/$C.json"
check "it is no longer live" test ! -e "$FACTORY/runs/$C.json"
check "the escalated bead stays claimed" test "$(status_of "$C")" = in_progress
check "no third pane was spawned" test "$(count_ev pane.spawned)" -eq 2
check "the escalated campaign is not complete" test "$(count_ev campaign.complete)" -eq 0

# ---------------------------------------------------------------- from a linked worktree
new_repo linked "bead A"
LINK="$TMP/linked-wt"
git -C "$REPO" worktree add -q -b side "$LINK" >/dev/null 2>&1
check "smile event from a worktree writes the main checkout's log" \
	env SMILE_ROOT="$LINK" "$LINK/smile/smile" event bead.closed "bead=$(bead_n 1)" actor=worker detail=fromwt
check "the line landed in the main checkout" test "$(count_ev bead.closed)" -eq 1
check "the worktree has no .factory of its own" test ! -e "$LINK/.factory"
check "smile status from a worktree reads that log" \
	test -n "$(SMILE_ROOT="$LINK" "$LINK/smile/smile" status 2>/dev/null | grep -F 'bead.closed')"
check "smile pause from a worktree pauses the main checkout" \
	env SMILE_ROOT="$LINK" "$LINK/smile/smile" pause
check "the pause file is the main checkout's" test -f "$FACTORY/pause"
check "smile resume from a worktree clears it" \
	env SMILE_ROOT="$LINK" "$LINK/smile/smile" resume
check "the pause file is gone" test ! -e "$FACTORY/pause"
check "the driver run from a worktree drives the main checkout" \
	env SMILE_ROOT="$LINK" "$LINK/smile/smile" run --once
check "its run state landed in the main checkout" test "$(ls "$FACTORY/runs"/*.json | grep -c '')" -eq 1

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS driver.test.sh\n'
else
	printf 'FAIL driver.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
