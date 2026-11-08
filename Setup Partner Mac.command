#!/bin/bash
cd "$(dirname "$0")"
bash scripts/setup_partner.sh
result=$?
echo
read -r -p 'Press Enter to close…' _
exit "$result"
