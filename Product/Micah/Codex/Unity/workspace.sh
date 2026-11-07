#!/bin/bash
set -euo pipefail

tools_dir="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$tools_dir/../../../.." && pwd)"
project="$repo/Product/Micah/Unity/HackathonEMG"

usage() {
  cat <<'EOF'
Usage: bash Product/Micah/Codex/Unity/workspace.sh <action> [arguments]

  setup       Import the project, install Pipeline, open the Editor, wait for ready
  import      Import/compile in batch mode (close this project's Editor first)
  open        Open this project's Editor
  status      Inspect only this project's connected Editor
  commands    Discover the commands this Editor actually supports
  command ... Run a discovered Editor command against this project
  recompile   Compile scripts in the connected Editor
  verify      Check project integrity without launching an Editor
  build       Build WebGL under Micah's workspace (close the Editor first)

Requires Unity CLI and Editor 6000.6.8f1. Setup needs network access for
packages, a valid Unity license, and permission to use local sockets.
EOF
}

action="${1:-help}"
if [ "$#" -gt 0 ]; then shift; fi
case "$action" in help|-h|--help) usage; exit 0 ;; esac
command -v unity >/dev/null || { echo 'Unity CLI is not on PATH.' >&2; exit 1; }
test -f "$project/ProjectSettings/ProjectVersion.txt" || {
  echo "Missing Unity project: $project" >&2; exit 1;
}
# All Editor operations use this exact project; never borrow another Editor.
export UNITY_PROJECT_PATH="$project"
case "$action" in
  setup)
    bash "$tools_dir/workspace.sh" import
    unity pipeline install --project-path "$project" --non-interactive --format json
    unity open "$project"
    unity status --project-path "$project" --until-ready --timeout 300 --format json
    unity command --project-path "$project" --format json
    ;;
  import)
    mkdir -p "$project/Logs"
    unity run "$project" --timeout 300 --log-file "$project/Logs/import.log" -- -nographics
    ;;
  open) unity open "$project" "$@" ;;
  status) unity status --project-path "$project" --format json "$@" ;;
  commands) unity command --project-path "$project" --format json "$@" ;;
  command)
    if [ "$#" -eq 0 ]; then echo 'Supply a discovered command name.' >&2; exit 2; fi
    # Do not accept options that could retarget another workspace/runtime.
    for arg in "$@"; do
      case "$arg" in
        --project-path*|--runtime*) echo 'Target overrides are not allowed.' >&2; exit 2 ;;
      esac
    done
    unity command --project-path "$project" "$@"
    ;;
  recompile) unity recompile --project-path "$project" --timeout 120 --format json ;;
  verify) unity projects verify "$project" --format json ;;
  build)
    mkdir -p "$tools_dir/Builds"
    unity build "$project" --target WebGL --output-path "$tools_dir/Builds/WebGL" --timeout 600
    ;;
  *) usage >&2; exit 2 ;;
esac
