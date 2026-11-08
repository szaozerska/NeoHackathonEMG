#!/bin/bash
# Fresh-clone setup. No global Python installs, account changes or pairing resets.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TASK_ROOT"
WITH_GAME=0
for argument in "$@"; do
  case "$argument" in
    --with-game) WITH_GAME=1 ;;
    --help|-h) echo 'Usage: bash scripts/setup_partner.sh [--with-game]'; exit 0 ;;
    *) echo "Unknown argument: $argument" >&2; exit 2 ;;
  esac
done
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'The packaged band bench requires an Apple Silicon Mac with macOS 14+.' >&2
  echo 'Python-only analysis can be installed separately; see HANDOFF.md.' >&2
  exit 1
fi
OS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$OS_MAJOR" -ge 14 ]] || { echo 'macOS 14 or newer is required.' >&2; exit 1; }
mkdir -p .setup/downloads .setup/bin
UV_VERSION=0.12.18
UV_ARCHIVE=".setup/downloads/uv-aarch64-apple-darwin.tar.gz"
UV_SHA256=cf40e0c6a202190ccd9e0406dcfdd5b2d6668a9a5c779b17948963df32aafe5b
if [[ ! -x .setup/bin/uv ]]; then
  echo "Downloading pinned uv ${UV_VERSION}..."
  curl --fail --location --retry 3 "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-aarch64-apple-darwin.tar.gz" -o "$UV_ARCHIVE"
  printf '%s  %s\n' "$UV_SHA256" "$UV_ARCHIVE" | shasum -a 256 -c -
  tar -xzf "$UV_ARCHIVE" -C .setup/bin --strip-components=1
fi
[[ "$(.setup/bin/uv --version)" == "uv $UV_VERSION"* ]] || { echo 'Unexpected uv version; inspect .setup/bin.' >&2; exit 1; }
export UV_CACHE_DIR="$TASK_ROOT/.setup/uv-cache"
export UV_PYTHON_INSTALL_DIR="$TASK_ROOT/.setup/python"
echo 'Preparing managed Python 3.14 and the local environment…'
.setup/bin/uv python install 3.14
if [[ ! -x .venv/bin/python ]]; then
  .setup/bin/uv venv --python 3.14 --managed-python .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,14), "Existing .venv is not Python 3.14; move it aside and rerun setup."'
.setup/bin/uv pip install --python .venv/bin/python -r requirements-lock.txt -r requirements-neural-lock.txt -e .
echo 'Checking models and preparing the bundled Kinesis app…'
.venv/bin/python scripts/prepare_partner.py
if [[ "$WITH_GAME" == 1 ]]; then
  .setup/bin/uv sync --frozen --python 3.14 --project apps/server
  .setup/bin/uv sync --frozen --python 3.14 --project apps/hand-client
fi
.venv/bin/python scripts/doctor.py
echo
echo 'Setup complete. Double-click Start Partner Bench.command to open Kinesis and the localhost test bench.'
echo 'Pair/sign in using your own account, then start a raw EMG recording at the path shown on the page.'
