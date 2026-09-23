#!/bin/sh
set -eu
umask 022

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=$(tr -d '\n' < "$root/VERSION")
case "$version" in
    ''|*[!0-9a-zA-Z.+~-]*)
        echo "Invalid VERSION: $version" >&2
        exit 1
        ;;
esac

if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
    SOURCE_DATE_EPOCH=$(git -C "$root" log -1 --format=%ct 2>/dev/null || date +%s)
fi
export SOURCE_DATE_EPOCH

output=${1:-"$root/dist"}
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
staging=$(mktemp -d "${TMPDIR:-/tmp}/opencode-pet-deb.XXXXXX")
trap 'rm -rf "$staging"' EXIT HUP INT TERM
chmod 755 "$staging"

mkdir -p "$staging/DEBIAN" "$staging/usr/bin" \
    "$staging/usr/share/opencode-pet/plugin" \
    "$staging/usr/share/applications" \
    "$staging/usr/share/icons/hicolor/scalable/apps" \
    "$staging/usr/share/doc/opencode-pet"

install -m 644 "$root/pet.py" "$staging/usr/share/opencode-pet/pet.py"
install -m 644 "$root/plugin/pet.js" "$staging/usr/share/opencode-pet/plugin/pet.js"
install -m 755 "$root/packaging/opencode-pet" "$staging/usr/bin/opencode-pet"
install -m 644 "$root/packaging/opencode-pet.desktop" "$staging/usr/share/applications/opencode-pet.desktop"
install -m 644 "$root/packaging/opencode-pet.svg" "$staging/usr/share/icons/hicolor/scalable/apps/opencode-pet.svg"
install -m 644 "$root/LICENSE" "$staging/usr/share/doc/opencode-pet/LICENSE"

cat > "$staging/DEBIAN/control" <<EOF
Package: opencode-pet
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: OpenCode Pet Contributors <opensource@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0, librsvg2-common
Homepage: https://github.com/binaryTob/opencode-pet
Description: Floating animated companion for OpenCode
 Displays Codex-compatible pet sprites and lets you follow and start
 OpenCode chats using your existing models and provider configuration.
EOF

package="$output/opencode-pet_${version}_all.deb"
dpkg-deb --build --root-owner-group "$staging" "$package"
echo "$package"
