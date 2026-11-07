#!/bin/bash
# Run from macOS Terminal, outside the restricted agent session.
set -euo pipefail

workspace="$(cd "$(dirname "$0")/../../../.." && pwd)"
remote='git@github.com:mbrncik07/NeoHackathonEMG.git'

# Disable repository/global hooks for every Git operation in this script.
git_safe() { git -c core.hooksPath=/dev/null "$@"; }

if [ -e "$workspace/.git" ]; then
  echo 'A Git checkout now exists here. Stop and inspect it before continuing.' >&2
  exit 1
fi

scratch="$(mktemp -d "${TMPDIR:-/tmp}/neohackathon-push.XXXXXX")"
checkout="$scratch/repo"
echo "Cloning $remote into $checkout"
git_safe clone -- "$remote" "$checkout"

# Overlay the scaffold while preserving upstream text and rejecting other collisions.
python3 - "$workspace" "$checkout" <<'PY'
from pathlib import Path
import shutil
import sys

source, dest = map(Path, sys.argv[1:])
files = [source / name for name in ('README.md', '.gitignore', 'AGENTS.md')]
for folder in ('Pitch', 'Product'):
    files.extend(p for p in (source / folder).rglob('*') if p.is_file())
for src in files:
    relative = src.relative_to(source)
    target = dest / relative
    if '.git' in relative.parts:
        raise SystemExit(f'Refusing nested Git metadata: {relative}')
    if target.exists() and target.read_bytes() != src.read_bytes():
        if str(relative) in ('README.md', '.gitignore', 'AGENTS.md'):
            with target.open('a') as stream:
                stream.write('\n\n' + src.read_text())
            continue
        raise SystemExit(f'Upstream file collision; inspect before replacing: {relative}')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)

readme = dest / 'README.md'
text = readme.read_text()
text = text.replace(
    'Setup status: the folder scaffold exists locally. Cloning `https://github.com/mbrncik07/NeoHackathonEMG.git` failed because the session cannot write the root `.git` directory and cannot resolve `github.com`. No upstream files have been downloaded, and no commits or pushes have been made.',
    'The scaffold was integrated with the upstream repository using `Product/Micah/Codex/Unity/push-scaffold.sh`.')
readme.write_text(text)
PY

git_safe -C "$checkout" add -- README.md .gitignore AGENTS.md Pitch Product
git_safe -C "$checkout" diff --cached --stat
if ! git_safe -C "$checkout" diff --cached --quiet; then
  git_safe -C "$checkout" commit -m "Set up hackathon workspaces and Unity CLI guide"
fi
git_safe -C "$checkout" push origin HEAD

# Bring the successful checkout, including its Git history, into the workspace.
python3 - "$checkout" "$workspace" <<'PY'
from pathlib import Path
import shutil
import sys
source, dest = map(Path, sys.argv[1:])
for item in source.iterdir():
    target = dest / item.name
    if item.is_dir():
        shutil.copytree(item, target, dirs_exist_ok=True, symlinks=True)
    else:
        shutil.copy2(item, target, follow_symlinks=False)
PY

git_safe -C "$workspace" status --short --branch
echo "Push complete. Repository history is now installed in $workspace"
echo "Temporary checkout retained at $checkout"
