#!/usr/bin/env bash
# Runs the py runtime's S4 review lane tests (tests/test_review.py) from the repo root so
# tests/all.sh picks them up.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if (cd "$ROOT" && python3 -m unittest tests.test_review -v); then
	printf 'PASS review-py.test.sh\n'
else
	printf 'FAIL review-py.test.sh\n'
	exit 1
fi
