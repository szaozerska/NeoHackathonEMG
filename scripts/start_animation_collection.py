#!/usr/bin/env python3
"""Run a separate Space-held Animation Gesture collector without restarting other benches."""
import argparse
from pathlib import Path
import signal
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from spelltrain.live_test import LiveTester
from spelltrain.models import load_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8795)
    parser.add_argument('--condition', choices=['static','dynamic'], default='static')
    parser.add_argument('--steps', action='store_true', help='Map isolated components and manually reported sequence phases')
    parser.add_argument('--validation', action='store_true', help='Reserved static/dynamic validation collector')
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--source-state', type=Path, help='Reuse a local feed URL file without displaying it')
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535')
    tester = LiveTester(load_artifact(ROOT/'models/gestures-v4/model.joblib'),
                        ROOT/'data/player-a/raw/animation-live.jsonl', auto_source=True)
    output=(args.output_root or ROOT/('Micah contributed data/validation' if args.validation else 'Micah contributed data/animation')).resolve()
    if args.validation:tester.validation_root=output
    else:tester.animation_root=output
    if args.source_state and args.source_state.exists():
        from spelltrain.live_source import validate_stream_url
        tester.live_input.url = validate_stream_url(args.source_state.read_text().strip())
    signal.signal(signal.SIGINT, lambda *_: tester.stop.set())
    signal.signal(signal.SIGTERM, lambda *_: tester.stop.set())
    try:
        port = tester.start(args.port)
        url = f'http://127.0.0.1:{port}/'+('validation' if args.validation else 'animation-steps' if args.steps else 'animation')+f'?mode={args.condition}'
        print('Animation Gesture collection: '+url, flush=True)
        print('Capture folder: '+str(output), flush=True)
        if args.open_browser:
            webbrowser.open(url)
        while not tester.stop.wait(.25):
            pass
    finally:
        tester.close()


if __name__ == '__main__':
    main()
