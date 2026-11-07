#!/bin/bash
# Build only. This script never opens a serial port or writes to a board.
set -euo pipefail
cd "$(dirname "$0")/.."

bridge_cli="${ARDUINO_CLI:-}"
if [ -z "$bridge_cli" ]; then
    bridge_cli=$(command -v arduino-cli || true)
fi
if [ -z "$bridge_cli" ]; then
    bridge_cli='/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli'
fi
[ -x "$bridge_cli" ] || { printf '%s\n' 'Install Arduino CLI or set ARDUINO_CLI to its executable.' >&2; exit 1; }

"$bridge_cli" core list --format json | python3 -c '
import json, sys
platforms = json.load(sys.stdin).get("platforms", [])
if not any(p.get("id") == "esp32:esp32" and p.get("installed_version") == "3.3.11" for p in platforms):
    sys.exit("This adapter build requires Espressif Arduino core esp32:esp32 version 3.3.11.")
'

mkdir -p dist/phone-bridge
"$bridge_cli" compile \
    --fqbn 'esp32:esp32:esp32:FlashMode=dio,FlashSize=4M,PartitionScheme=no_fs,PSRAM=disabled' \
    --warnings all \
    --build-path "$PWD/dist/phone-bridge-build" \
    --output-dir "$PWD/dist/phone-bridge" \
    firmware/axo-phone-bridge 2>&1 | tee dist/phone-bridge-build.log

(cd dist/phone-bridge && shasum -a 256 ./*.bin > SHA256SUMS)
printf '\nBuilt firmware for the original ESP32 with 4 MB flash:\n%s\n' "$PWD/dist/phone-bridge"
