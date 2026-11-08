#!/usr/bin/env python3
"""Compile the portable Quest sender against a locally installed Unity editor, without launching it."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--editor',default='/Applications/Unity/Hub/Editor/6000.6.8f1/Unity.app')
a=p.parse_args()
root=Path(a.editor)/'Contents/Resources/Scripting'
source=Path(__file__).resolve().parents[1]/'apps/vr-client/Packages/com.neohackathon.spell-recorder'
with tempfile.TemporaryDirectory() as output:
    command=[str(root/'MonoBleedingEdge/bin/mono'),str(root/'MonoBleedingEdge/lib/mono/4.5/csc.exe'),
             '-noconfig','-nostdlib','-target:library',f'-out:{output}/SpellTraining.dll',
             '-r:'+str(root/'NetStandard/ref/2.1.0/netstandard.dll'),
             '-r:'+str(root/'Managed/UnityEngine/UnityEngine.CoreModule.dll'),
             '-r:'+str(root/'Managed/UnityEngine/UnityEngine.JSONSerializeModule.dll'),
             str(source/'Runtime/SpellTrackingSource.cs'),str(source/'Runtime/SpellQuestSender.cs')]
    subprocess.run(command,check=True)
print('Portable Unity sender compiled. This does not build an Android APK or validate device tracking.')
