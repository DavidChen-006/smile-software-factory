#!/usr/bin/env bash
# The unit suite: every tests/*.test.sh in order, one line per file with its wall time.
# Offline by rule (docs/PROCESS.md, "Unit suite rules"). Live drives live in tests/live.sh.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FAILS=0
# The offline switch: git refuses http/https/ssh remotes, so any test that grew a real fetch, clone
# or push fails here instead of costing minutes when GitHub is slow. Scratch repos talk to local
# bare origins, which `file` still allows.
export GIT_ALLOW_PROTOCOL=file
# a per-run log directory: two worktrees running this at once must not clobber each other's logs
LOGS=$(mktemp -d "${TMPDIR:-/tmp}/smile-tests.XXXXXX")
printf 'logs: %s\n' "$LOGS"
SUITE_START=$SECONDS
for t in "$ROOT"/tests/*.test.sh; do
	name=$(basename "$t")
	start=$SECONDS
	if bash "$t" > "$LOGS/$name.log" 2>&1; then
		printf 'ok   %s %ss\n' "$name" "$((SECONDS - start))"
	else
		printf 'FAIL %s %ss (log: %s/%s.log)\n' "$name" "$((SECONDS - start))" "$LOGS" "$name"
		FAILS=$((FAILS + 1))
	fi
done
printf 'total %ss\n' "$((SECONDS - SUITE_START))"
[ "$FAILS" -eq 0 ] && printf 'all tests passed\n' || { printf '%s test file(s) failed\n' "$FAILS"; exit 1; }
