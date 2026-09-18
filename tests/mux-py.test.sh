#!/usr/bin/env bash
# Runs the py runtime's S2 mux tests (tests/test_mux.py) from the repo root so tests/all.sh picks them up.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && python3 -m unittest tests.test_mux -v); then
	printf 'PASS mux-py.test.sh\n'
else
	printf 'FAIL mux-py.test.sh\n'
	exit 1
fi
