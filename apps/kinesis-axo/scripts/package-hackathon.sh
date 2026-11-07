#!/bin/bash
# Builds Kinesis for this Mac and replaces the hackathon build tracked in git,
# release/Kinesis-haptics-arm64.zip, so teammates can run it without building.
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/build.sh --local
architectures=$(/usr/bin/lipo -archs dist/Kinesis.app/Contents/MacOS/Kinesis)
[ "$architectures" = arm64 ] || { echo "expected an arm64 build, got: $architectures" >&2; exit 1; }
mkdir -p release
rm -f release/Kinesis-haptics-arm64.zip
/usr/bin/ditto -c -k --keepParent dist/Kinesis.app release/Kinesis-haptics-arm64.zip
echo "Wrote release/Kinesis-haptics-arm64.zip"
