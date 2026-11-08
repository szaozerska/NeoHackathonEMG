#!/bin/zsh
cd "${0:A:h}"
exec .venv/bin/python scripts/start_emg.py --profile supplemental
