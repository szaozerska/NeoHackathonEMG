#!/bin/bash
# Run in a Terminal with GitHub access and permission to update .git.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../../../.." && pwd)"
git_safe() { git -c core.hooksPath=/dev/null -C "$repo" "$@"; }

origin="$(git_safe remote get-url origin)"
case "$origin" in
  git@github.com:mbrncik07/NeoHackathonEMG.git|https://github.com/mbrncik07/NeoHackathonEMG.git) ;;
  *) echo 'Unexpected origin; inspect the remote before publishing.' >&2; exit 1 ;;
esac
if [ "$(git_safe branch --show-current)" != main ]; then
  echo 'Expected main; inspect the current branch before publishing.' >&2; exit 1
fi
if ! git_safe diff --cached --quiet; then
  echo 'Existing staged changes found; review them before publishing.' >&2; exit 1
fi
git_safe add -- Product/Micah/Codex/Unity Product/Micah/Unity
git_safe diff --cached --stat
if ! git_safe diff --cached --quiet; then
  git_safe commit -m 'Add Unity starter project and scoped CLI workflow'
fi
git_safe push origin main
git_safe status --short --branch
