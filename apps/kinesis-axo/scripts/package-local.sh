#!/bin/bash
# Archive an existing local app and the current source tree. Never builds,
# launches, installs, signs, or accesses the app's runtime data or credentials.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { printf '%s\n' "$*" >&2; exit 1; }
if [ "$#" -gt 1 ]; then fail 'usage: scripts/package-local.sh [path/to/Kinesis.app]'; fi

app_path="${1:-$PWD/dist/Kinesis.app}"
case "$app_path" in /*) ;; *) app_path="$PWD/$app_path" ;; esac
[ -d "$app_path/Contents" ] || fail "app bundle not found: $app_path"
app_info="$app_path/Contents/Info.plist"
/usr/bin/plutil -lint "$app_info" >/dev/null
/usr/bin/codesign --verify --deep --strict "$app_path"

plist_value() { /usr/libexec/PlistBuddy -c "Print :$2" "$1"; }
bundle_id=$(plist_value "$app_info" CFBundleIdentifier)
expected_id=$(plist_value Packaging/Info.plist CFBundleIdentifier)
[ "$bundle_id" = "$expected_id" ] || fail 'app bundle identifier does not match Packaging/Info.plist'
version=$(plist_value "$app_info" CFBundleShortVersionString)
build=$(plist_value "$app_info" CFBundleVersion)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'app version must have three numeric components'
[[ "$build" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || fail 'app build must have one to three numeric components'
[ "$version" = "$(plist_value Packaging/Info.plist CFBundleShortVersionString)" ] &&
    [ "$build" = "$(plist_value Packaging/Info.plist CFBundleVersion)" ] ||
    fail 'source Packaging/Info.plist version/build must match the app being packaged'
executable=$(plist_value "$app_info" CFBundleExecutable)
case "$executable" in ''|*/*|.|..) fail 'app executable must be a filename within Contents/MacOS' ;; esac
binary="$app_path/Contents/MacOS/$executable"
[ -f "$binary" ] || fail 'app executable is missing'
architectures=$(/usr/bin/lipo -archs "$binary")
case "$architectures" in
    arm64) arch=arm64; platform='Apple silicon (arm64)' ;;
    x86_64) arch=x86_64; platform='Intel (x86_64)' ;;
    'arm64 x86_64'|'x86_64 arm64') arch=universal; platform='Apple silicon and Intel (arm64, x86_64)' ;;
    *) fail "unsupported app architectures: $architectures" ;;
esac
signature_details=$(/usr/bin/codesign -d --verbose=2 "$app_path" 2>&1)
case "$signature_details" in
    *'Signature=adhoc'*) signing_note='This app is ad-hoc signed, not Developer ID signed or notarized.' ;;
    *) signing_note='The existing code signature is preserved; this tool performs no signing or notarization assessment.' ;;
esac

release_root="$PWD/dist/release-local"
release_path="$release_root/$version-build$build-$arch"
[ ! -e "$release_path" ] && [ ! -L "$release_path" ] || fail "output already exists: $release_path"
mkdir -p "$release_root"
lock_path="$release_path.lock"
stage_dir=''
lock_owned=false
cleanup() {
    if [ -n "$stage_dir" ] && [ -d "$stage_dir" ]; then rm -rf "$stage_dir"; fi
    if $lock_owned; then rmdir "$lock_path" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$lock_path" 2>/dev/null || fail "packaging is already reserved: $lock_path"
lock_owned=true
[ ! -e "$release_path" ] && [ ! -L "$release_path" ] || fail "output already exists: $release_path"
stage_dir=$(mktemp -d "$PWD/dist/.package-local.XXXXXX")
source_name="kinesis-$version-build$build-source"
source_dir="$stage_dir/$source_name"
output_dir="$stage_dir/output"
mkdir -p "$source_dir/design" "$output_dir"

# Copy only release inputs, including uncommitted source changes. In particular,
# never copy the repository root, user settings, recordings, or previous builds.
for directory in Sources Tests Packaging scripts docs Tools firmware; do
    [ -d "$directory" ] && [ ! -L "$directory" ] || fail "missing source directory: $directory"
    /usr/bin/rsync -a --exclude='.DS_Store' --exclude='.git/' --exclude='.build/' --exclude='build/' \
        --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.pyo' \
        --exclude='.native/' --exclude='dist/' --exclude='local/' --exclude='.runtime/' \
        --exclude='recordings/' --exclude='AGENT_HANDOFF*' "$directory" "$source_dir/"
done
for file in README.md Package.swift LICENSE .gitignore; do
    [ -f "$file" ] && [ ! -L "$file" ] || fail "missing source file: $file"
    cp "$file" "$source_dir/"
done
for file in design/kinesis-links*.svg; do
    [ -e "$file" ] || continue
    [ -f "$file" ] && [ ! -L "$file" ] || fail "invalid design asset: $file"
    cp "$file" "$source_dir/design/"
done
# Do not ship links that could resolve outside the allowlisted source tree.
source_link=$(/usr/bin/find "$source_dir" -type l -print -quit)
[ -z "$source_link" ] || fail 'source archive contains a symbolic link; remove it before packaging'

source_zip="$source_name.zip"
app_zip="Kinesis-$version-build$build-$arch-local.zip"
/usr/bin/ditto -c -k --norsrc --noextattr --keepParent "$source_dir" "$output_dir/$source_zip"
/usr/bin/ditto -c -k --norsrc --noextattr --keepParent "$app_path" "$output_dir/$app_zip"

# Verify that archive extraction preserves the existing signature. This does not
# execute the app or run tests, and it does not change the input app bundle.
verify_dir="$stage_dir/verify"
mkdir "$verify_dir"
/usr/bin/ditto -x -k "$output_dir/$app_zip" "$verify_dir"
app_name=$(basename "$app_path")
/usr/bin/codesign --verify --deep --strict "$verify_dir/$app_name"
cmp "$binary" "$verify_dir/$app_name/Contents/MacOS/$executable" >/dev/null ||
    fail 'the archived executable differs from the input app'

cat > "$output_dir/README-local.txt" <<EOF
Kinesis $version — local build $build
Architecture: $platform
Bundle identifier: $bundle_id

$signing_note
This is a local package, not an official notarized upstream release. macOS may
require the user's approval to open it and grant Bluetooth/Accessibility access.
The app is archived as supplied, without rebuilding, re-signing or installation.

The source ZIP includes current working-tree changes from the allowlisted source
and documentation directories. It excludes runtime data, recordings, system/app
preferences, pairing/Keychain material, personal profiles and saved Dot links.

Kinesis's MIT notice and the hand asset's MIT notice are retained. The band image
is separately attributed in Band-image-source.txt and excluded from Kinesis's
MIT licence; do not assume every asset is covered by that licence.

Verify these files from this directory with: shasum -a 256 -c SHA256SUMS
EOF
(
    cd "$output_dir"
    /usr/bin/shasum -a 256 "$source_zip" "$app_zip" README-local.txt > SHA256SUMS
    /usr/bin/shasum -a 256 -c SHA256SUMS
)
[ ! -e "$release_path" ] && [ ! -L "$release_path" ] || fail "output already exists: $release_path"
mv "$output_dir" "$release_path"
printf '\nPackaged local release:\n%s\n%s\n%s\n%s\n' \
    "$release_path/$source_zip" "$release_path/$app_zip" \
    "$release_path/README-local.txt" "$release_path/SHA256SUMS"
