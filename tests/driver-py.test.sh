#!/usr/bin/env bash
# Runs the py runtime's S3 driver tests (tests/test_driver.py) from the repo root so tests/all.sh picks them up.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && uv run python -m unittest tests.test_driver -v); then
	printf 'PASS driver-py.test.sh\n'
else
	printf 'FAIL driver-py.test.sh\n'
	exit 1
fi
