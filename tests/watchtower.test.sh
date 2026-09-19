#!/usr/bin/env bash
# Runs the py runtime's S5 watchtower tests (tests/test_watchtower.py) from the repo root so
# tests/all.sh picks them up.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && uv run python -m unittest tests.test_watchtower -v); then
	printf 'PASS watchtower.test.sh\n'
else
	printf 'FAIL watchtower.test.sh\n'
	exit 1
fi
