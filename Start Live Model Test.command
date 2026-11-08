#!/bin/zsh
cd "${0:A:h}"
exec .venv/bin/python scripts/start_live_test.py --background --open-browser
