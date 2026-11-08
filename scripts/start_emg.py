#!/usr/bin/env python3
"""Start the next EMG-only session without overwriting recordings."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--subject', default='player-a')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--profile', choices=('baseline','supplemental'), default='baseline')
    parser.add_argument('--dataset-role', choices=('development','test'), default='development')
    args = parser.parse_args()
    if not args.subject or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.subject):
        parser.error('Subject must contain only letters, numbers, hyphens or underscores')
    root = Path(__file__).resolve().parents[1]
    python = root / '.venv/bin/python'
    if not python.exists():
        raise SystemExit('First create .venv and install this project; see README.md')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=1) as response:
            current = json.load(response)
        print('Training dashboard already running: http://127.0.0.1:8765')
        print('Current session:', current['session']['id'])
        print('Kinesis recording path:', current['session'].get('band_file', 'see dashboard'))
        return
    except OSError:
        pass
    base = root / 'data' / args.subject
    raw = base / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    index = 1
    while (base / f'band-{index:02}').exists() or (raw / f'band-{index:02}.jsonl').exists():
        index += 1
    name = f'band-{index:02}'
    session = base / name
    capture = raw / (name + '.jsonl')
    command = [str(python), '-m', 'spelltrain', 'record', '--subject', args.subject,
               '--session', str(session), '--emg-only', '--kinesis-file', str(capture),
               '--training-profile', args.profile, '--dataset-role', args.dataset_role]
    print('EMG-only dashboard: http://127.0.0.1:8765', flush=True)
    print('In Kinesis → Readings → record…, save to:', capture, flush=True)
    print('Session:', session, flush=True)
    if not args.background:
        raise SystemExit(subprocess.call(command, cwd=root))
    log = base / f'{name}-server.log'
    with log.open('x') as output:
        child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    (base / f'{name}-server.pid').write_text(str(child.pid) + '\n')
    for _ in range(60):
        if child.poll() is not None:
            raise SystemExit('Recorder exited. See ' + str(log))
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=.5) as response:
                if json.load(response)['session']['id'] == name:
                    print('Verified running. PID:', child.pid)
                    return
        except OSError:
            time.sleep(.1)
    raise SystemExit('Recorder did not become ready; inspect ' + str(log))


if __name__ == '__main__':
    main()
