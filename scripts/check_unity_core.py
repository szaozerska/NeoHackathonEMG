#!/usr/bin/env python3
"""Compile the current Unity game with its actual installed Editor and packages."""
import argparse
import os
from pathlib import Path
import re
import subprocess


def main():
    workspace=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=workspace/'apps/vr-client')
    parser.add_argument('--editor',type=Path,help='Unity executable or Unity.app; defaults to UNITY_EDITOR or the pinned macOS installation')
    parser.add_argument('--log',type=Path,default=workspace/'.local/unity-compile.log')
    parser.add_argument('--build-target',choices=['Android','StandaloneOSX'])
    args=parser.parse_args()
    project=args.project.resolve()
    version_file=project/'ProjectSettings/ProjectVersion.txt'
    if not version_file.is_file():parser.error('Not a Unity project: '+str(project))
    version=re.search(r'^m_EditorVersion:\s*(\S+)',version_file.read_text(),re.M)
    if version is None:parser.error('ProjectVersion.txt has no Editor version')
    editor=args.editor or Path(os.environ.get('UNITY_EDITOR',f'/Applications/Unity/Hub/Editor/{version[1]}/Unity.app'))
    executable=editor/'Contents/MacOS/Unity' if editor.suffix=='.app' else editor
    if not executable.is_file():parser.error('Unity Editor not found; use --editor or UNITY_EDITOR: '+str(executable))
    log=args.log.resolve();log.parent.mkdir(parents=True,exist_ok=True)
    command=[str(executable),'-batchmode','-nographics','-quit','-projectPath',str(project),'-logFile',str(log)]
    if args.build_target:command.extend(['-buildTarget',args.build_target])
    print('Compiling Unity project:',project,flush=True)
    result=subprocess.run(command)
    messages=log.read_text(errors='replace') if log.exists() else ''
    errors=[line for line in messages.splitlines() if re.search(r'error CS\d+|Scripts have compiler errors|Compilation failed',line)]
    if result.returncode or errors:
        for line in errors[-30:]:print(line)
        raise SystemExit(f'Unity compilation failed (exit {result.returncode}); see {log}')
    print('Unity game and Editor assemblies compiled successfully. Log:',log)
    print('This check does not build an APK or validate headset tracking.')


if __name__=='__main__':main()
