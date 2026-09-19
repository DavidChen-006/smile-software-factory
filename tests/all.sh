#!/usr/bin/env bash
# Run every tests/*.test.sh in order and report one line per file.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FAILS=0
# a per-run log directory: two worktrees running this at once must not clobber each other's logs
LOGS=$(mktemp -d "${TMPDIR:-/tmp}/smile-tests.XXXXXX")
printf 'logs: %s\n' "$LOGS"
for t in "$ROOT"/tests/*.test.sh; do
	name=$(basename "$t")
	if bash "$t" > "$LOGS/$name.log" 2>&1; then
		printf 'ok   %s\n' "$name"
	else
		printf 'FAIL %s (log: %s/%s.log)\n' "$name" "$LOGS" "$name"
		FAILS=$((FAILS + 1))
	fi
done
[ "$FAILS" -eq 0 ] && printf 'all tests passed\n' || { printf '%s test file(s) failed\n' "$FAILS"; exit 1; }
