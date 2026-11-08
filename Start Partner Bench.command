#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run Setup Partner Mac.command first.'
  read -r -p 'Press Enter to close…' _
  exit 1
fi
.venv/bin/python scripts/start_partner_bench.py
result=$?
if [[ "$result" != 0 ]]; then read -r -p 'Press Enter to close…' _; fi
exit "$result"
