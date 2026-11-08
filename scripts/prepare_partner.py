"""Verify distributed files and prepare a local Kinesis copy, preserving installed apps."""
from pathlib import Path
import hashlib
import json
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify_bundle(root=ROOT):
    manifest = json.loads((root/'models/manifest.json').read_text())
    files = {str(Path('models')/name): value['sha256'] for name, value in manifest['models'].items()}
    files[manifest['kinesis']['archive']] = manifest['kinesis']['sha256']
    for name, expected in files.items():
        path = root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Missing or changed packaged file: '+name)
    return manifest


def main():
    manifest = verify_bundle()
    target = ROOT/'.local/apps/Kinesis.app'
    marker = target.parent/'kinesis-archive.sha256'
    wanted = manifest['kinesis']['sha256']
    if target.exists() and (not marker.exists() or marker.read_text().strip() != wanted):
        raise SystemExit('A different local Kinesis copy exists. Move .local/apps aside and rerun; installed apps are untouched.')
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(ROOT/manifest['kinesis']['archive']), str(target.parent)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(target)], check=True)
        marker.write_text(wanted+'\n')
    with (target/'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if info.get('CFBundleIdentifier') != 'local.callbacked.kinesis':
        raise SystemExit('Unexpected Kinesis bundle identifier')
    print('Verified Kinesis '+str(info['CFBundleVersion'])+': '+str(target))
    print('Prepared original v4 test model and experimental neural weights.')


if __name__ == '__main__':
    main()
