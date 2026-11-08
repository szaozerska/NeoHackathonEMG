#!/usr/bin/env python3
"""Launch the latest EMG tester without changing any training session."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--background',action='store_true')
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--kinesis-file')
    parser.add_argument('--model', help='Override the fallback model path')
    parser.add_argument('--port',type=int,help='Use a specific localhost port for a separate bench')
    args=parser.parse_args()
    if args.port is not None and not 1024<=args.port<=65535:parser.error('Port must be between 1024 and 65535')
    root=Path(__file__).resolve().parents[1]
    local=root/'artifacts/player-a/gestures-v4/model.joblib'
    model=Path(args.model).resolve() if args.model else local if local.exists() else root/'models/gestures-v4/model.joblib'
    if not model.exists():raise SystemExit('The updated model is missing: '+str(model))
    port=None
    candidates=(args.port,) if args.port is not None else (8765,8766)
    for candidate in candidates:
        url=f'http://127.0.0.1:{candidate}'
        try:
            status=json.load(urllib.request.urlopen(url+'/api/status',timeout=.5))
            if status.get('app')=='live-model-tester':
                print('Live model tester already running: '+url)
                print('Kinesis recording path: '+status['band_file'])
                if args.open_browser:subprocess.run(['open',url],check=True)
                return
        except (OSError,ValueError):pass
    for candidate in candidates:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:probe.bind(('127.0.0.1',candidate))
            except OSError:continue
        port=candidate;break
    if port is None:raise SystemExit('Requested localhost ports are in use; existing apps were left running.')
    raw=root/'data/player-a/raw';raw.mkdir(parents=True,exist_ok=True)
    if args.kinesis_file:capture=Path(args.kinesis_file).resolve()
    else:
        index=1
        while (raw/f'live-test-{index:02}.jsonl').exists():index+=1
        capture=raw/f'live-test-{index:02}.jsonl'
    command=[str(root/'.venv/bin/python'),'-m','spelltrain','live-test','--model',str(model),
             '--kinesis-file',str(capture),'--web-port',str(port)]
    if not args.kinesis_file:command.append('--auto-source')
    url=f'http://127.0.0.1:{port}'
    print('Live model tester: '+url,flush=True)
    if args.kinesis_file:
        print('Following Kinesis raw recording: '+str(capture),flush=True)
    else:
        print('Automatically following Kinesis active recording or the saved local feed.',flush=True)
    if not args.background:
        if args.open_browser:subprocess.run(['open',url],check=True)
        raise SystemExit(subprocess.call(command,cwd=root))
    support=root/'data/player-a'
    with (support/'live-tester.log').open('a') as log:
        child=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=log,
                               stderr=subprocess.STDOUT,start_new_session=True)
    (support/('live-tester.pid' if args.port is None else f'live-tester-{port}.pid')).write_text(str(child.pid)+'\n')
    for _ in range(100):
        if child.poll() is not None:raise SystemExit('Tester exited; see data/player-a/live-tester.log')
        try:
            status=json.load(urllib.request.urlopen(url+'/api/status',timeout=.5))
            if status.get('app')=='live-model-tester':
                print('Verified running. PID: '+str(child.pid))
                if args.open_browser:subprocess.run(['open',url],check=True)
                return
        except OSError:pass
        time.sleep(.1)
    raise SystemExit('Tester is still starting; inspect its log.')


if __name__=='__main__':main()
