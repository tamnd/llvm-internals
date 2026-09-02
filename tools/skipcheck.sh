#!/usr/bin/env bash
# A skipped test looks exactly like a passing one in a log, so CI reads the log
# and fails on a skip. Pass it the output of a verbose unittest run.
#
# One skip is allowed, and it is temporary. Alive2 is not in any distribution
# and building it takes hours, so the tests that need a real alive-tv skip until
# the `alive` bundle is published and CI can download it. That is issue #3.
# Delete this whole allowance when the issue closes.
set -euo pipefail

log=${1:?usage: skipcheck.sh <unittest output>}

# The per test lines say "... skipped 'reason'". The last line of a run says
# "OK (skipped=5)", which is a count rather than a skip, so it is dropped here
# instead of being read as a reason nobody recognises.
unexplained=$(grep "skipped" "$log" | grep -v "^OK (skipped=" | grep -cv IRX_ALIVE_BIN || true)

if [ "$unexplained" -gt 0 ]; then
  echo "$unexplained test(s) skipped for a reason that is not the Alive2 one."
  grep "skipped" "$log" | grep -v "^OK (skipped=" | grep -v IRX_ALIVE_BIN
  echo "A skip here means a tool the job installed is not really there."
  exit 1
fi

if grep -q IRX_ALIVE_BIN "$log"; then
  echo "Note: the Alive2 tests skipped, which is expected until #3 ships the bundle."
fi
