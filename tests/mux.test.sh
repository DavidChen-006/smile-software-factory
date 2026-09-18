#!/usr/bin/env bash
# Drives the stamped smile shim's mux seam against a real tmux server, per
# docs/RUNTIME-CONTRACT.md section 7: spawn (handle shape, window name, cwd, argv with a space),
# alive (running, exited, killed), kill (idempotent), handle and usage rejections, and backend
# selection (config value, auto-detect, no backend on PATH).
#
# Every window this file opens lives in its own session, named by SMILE_MUX_SESSION, which the
# exit trap kills. It never touches a session it did not create.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smile-mux-test.XXXXXX")" && pwd)
export SMILE_MUX_SESSION="smile-test-$$"
trap 'tmux kill-session -t "=$SMILE_MUX_SESSION" >/dev/null 2>&1; rm -rf "$TMP"' EXIT
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

command -v tmux >/dev/null 2>&1 || { printf 'FAIL mux.test.sh: tmux not on PATH\n'; exit 1; }

# ---------------------------------------------------------------- scratch repo
REPO="$TMP/mux-repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" -c user.email=mux@test -c user.name=mux commit -q --allow-empty -m init
python3 "$ROOT/install.py" "$REPO" >/dev/null
SMILE="$REPO/smile/smile"
CONFIG="$REPO/smile.config.yaml"
WORK="$TMP/work"; mkdir -p "$WORK"
WORK_REAL=$(cd "$WORK" && pwd -P)
set_key() { sed -i.bak "s|^$1:.*|$1: $2|" "$CONFIG" && rm -f "$CONFIG.bak"; }

rc_of() { "$@" >/dev/null 2>&1; printf '%s' "$?"; }              # exit code of a command
stderr_of() { "$@" 2>&1 >/dev/null; }                            # its stderr alone
win_target() { printf '%s' "${1#tmux:}"; }                       # handle -> tmux <session>:<window_id>
# poll_gone <handle>: wait up to ~5s for alive to stop reporting 0
poll_gone() {
	local i=0
	while [ "$i" -lt 50 ]; do
		"$SMILE" mux alive "$1" >/dev/null 2>&1 || return 0
		sleep 0.1
		i=$((i + 1))
	done
	return 1
}

# ---------------------------------------------------------------- spawn
H=$("$SMILE" mux spawn w1 "$WORK" sleep 300); SPAWN_RC=$?
check "spawn exits 0" test "$SPAWN_RC" -eq 0
check "spawn prints a well-formed handle" grep -qE '^tmux:[^ :]+:@[0-9]+$' <<<"$H"
check "spawn prints exactly one line" test "$(wc -l <<<"$H" | tr -d ' ')" -eq 1
check "spawn names the handle's session after SMILE_MUX_SESSION" test "$H" != "${H#tmux:$SMILE_MUX_SESSION:}"
check "spawn opens the window in that session" \
	grep -qxF "$(printf '%s' "$H" | sed 's/.*://')" <<<"$(tmux list-windows -t "=$SMILE_MUX_SESSION" -F '#{window_id}')"
check "spawn labels the window with <name>" \
	test "$(tmux display -p -t "$(win_target "$H")" '#{window_name}')" = w1
check "spawn runs the command in <cwd>" \
	test "$(tmux display -p -t "$(win_target "$H")" '#{pane_current_path}')" = "$WORK_REAL"
check "spawn leaves remain-on-exit off" \
	test "$(tmux show-window-options -t "$(win_target "$H")" -v remain-on-exit)" = off

# ---------------------------------------------------------------- alive and kill
check "alive exits 0 for a running command" "$SMILE" mux alive "$H"
check "kill exits 0" "$SMILE" mux kill "$H"
check "kill removes the window" test "$(rc_of "$SMILE" mux alive "$H")" -eq 1
check "alive exits 1 after kill" test "$(rc_of "$SMILE" mux alive "$H")" -eq 1
check "a second kill on a gone handle exits 0" "$SMILE" mux kill "$H"
check "a third kill is still 0" "$SMILE" mux kill "$H"

HT=$("$SMILE" mux spawn short "$WORK" true)
check "alive exits 1 once the command has exited" poll_gone "$HT"

# ---------------------------------------------------------------- argv, not a shell string
HS=$("$SMILE" mux spawn spaced "$WORK" sh -c 'printf "%s" "$1" > out.txt' _ 'a b')
poll_gone "$HS"
check "an argument containing a space reaches the command intact" test "$(cat "$WORK/out.txt")" = 'a b'

# ---------------------------------------------------------------- handle rejections
for h in nope tmux: cmux:x:y; do
	check "alive rejects the handle '$h' with exit 2" test "$(rc_of "$SMILE" mux alive "$h")" -eq 2
	check "kill rejects the handle '$h' with exit 2" test "$(rc_of "$SMILE" mux kill "$h")" -eq 2
	check "the rejection of '$h' is one stderr line" \
		test "$(stderr_of "$SMILE" mux alive "$h" | wc -l | tr -d ' ')" -eq 1
done
check "an S8 backend with no file says 'unknown backend'" \
	grep -q 'unknown backend cmux' <<<"$(stderr_of "$SMILE" mux alive cmux:x:y)"
check "a malformed handle says so" grep -q 'malformed handle' <<<"$(stderr_of "$SMILE" mux alive nope)"
check "alive rejects a handle with a space" test "$(rc_of "$SMILE" mux alive 'tmux:a b')" -eq 2

# ---------------------------------------------------------------- spawn failures
check "spawn with a missing cwd exits 1" test "$(rc_of "$SMILE" mux spawn w "$TMP/absent" true)" -eq 1
check "spawn with a missing cwd prints one stderr line" \
	test "$(stderr_of "$SMILE" mux spawn w "$TMP/absent" true | wc -l | tr -d ' ')" -eq 1

# ---------------------------------------------------------------- backend selection
H2=$("$SMILE" mux spawn auto "$WORK" sleep 300)
check "auto-detect picks tmux when backend is empty" grep -q '^tmux:' <<<"$H2"
"$SMILE" mux kill "$H2" >/dev/null 2>&1

set_key backend screen
check "a backend outside the three names exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 2
check "it names the unknown backend" grep -q 'unknown backend screen' <<<"$(stderr_of "$SMILE" mux spawn w "$WORK" true)"
set_key backend cmux
check "a config backend whose file has not landed exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 2
set_key backend tmux
H3=$("$SMILE" mux spawn named "$WORK" sleep 300)
check "an explicit tmux backend spawns" grep -q '^tmux:' <<<"$H3"
"$SMILE" mux kill "$H3" >/dev/null 2>&1
set_key backend ""

# A PATH holding only what the shim and mux need, and no multiplexer.
BIN="$TMP/bin-no-tmux"; mkdir -p "$BIN"
for t in bash sed dirname basename grep; do ln -sf "$(command -v "$t")" "$BIN/$t"; done
check "no backend on PATH makes spawn exit 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 1
check "no backend on PATH says 'missing'" \
	grep -q missing <<<"$(PATH="$BIN"; stderr_of "$SMILE" mux spawn w "$WORK" true)"
set_key backend tmux
check "a named backend missing from PATH makes spawn exit 1" test "$(PATH="$BIN"; rc_of "$SMILE" mux spawn w "$WORK" true)" -eq 1
check "a named backend missing from PATH says 'missing'" \
	grep -q missing <<<"$(PATH="$BIN"; stderr_of "$SMILE" mux spawn w "$WORK" true)"
set_key backend ""

# ---------------------------------------------------------------- usage
check "no verb exits 2" test "$(rc_of "$SMILE" mux)" -eq 2
check "an unknown verb exits 2" test "$(rc_of "$SMILE" mux wiggle)" -eq 2
check "spawn without a command exits 2" test "$(rc_of "$SMILE" mux spawn w "$WORK")" -eq 2
check "alive without a handle exits 2" test "$(rc_of "$SMILE" mux alive)" -eq 2
check "alive with two handles exits 2" test "$(rc_of "$SMILE" mux alive a b)" -eq 2
check "kill without a handle exits 2" test "$(rc_of "$SMILE" mux kill)" -eq 2

# ---------------------------------------------------------------- session default
unset SMILE_MUX_SESSION
H4=$(SMILE_MUX_SESSION= "$SMILE" mux spawn dflt "$WORK" sleep 300)
export SMILE_MUX_SESSION="smile-test-$$"
check "an empty SMILE_MUX_SESSION falls back to smile-<basename of SMILE_ROOT>" \
	grep -qE '^tmux:smile-mux-repo:@[0-9]+$' <<<"$H4"
"$SMILE" mux kill "$H4" >/dev/null 2>&1
tmux kill-session -t "=smile-mux-repo" >/dev/null 2>&1

if [ "$FAILS" -eq 0 ]; then
	printf 'PASS mux.test.sh\n'
else
	printf 'FAIL mux.test.sh: %s failure(s)\n' "$FAILS"
	exit 1
fi
