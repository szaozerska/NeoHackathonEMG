"""Open the packaged Kinesis and original localhost feedback bench."""
from pathlib import Path
import subprocess
import sys
from prepare_partner import verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def main():
    verify_bundle()
    app = ROOT/'.local/apps/Kinesis.app'
    if not app.exists():
        raise SystemExit('Run Setup Partner Mac.command first.')
    subprocess.run(['open', str(app)], check=True)
    raise SystemExit(subprocess.call([sys.executable, str(ROOT/'scripts/start_live_test.py'),
                                      '--model', str(ROOT/'models/gestures-v4/model.joblib'),
                                      '--background', '--open-browser'], cwd=ROOT))


if __name__ == '__main__':
    main()
