#!/bin/sh
# Installs TiQR as a service from this folder: sudo ./install.sh [tiqr install options]
# The folder is copied to /opt/tiqr (data and settings there survive an upgrade), then
# `tiqr install` sets up the address, database, first admin, firewall and systemd unit.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
target=${TIQR_INSTALL_DIR:-/opt/tiqr}

if [ "$(id -u)" -ne 0 ]; then
    echo "Needs root; running again with sudo." >&2
    exec sudo "$0" "$@"
fi

exe="$here/tiqr"
[ -f "$exe" ] || { echo "No tiqr executable in $here" >&2; exit 1; }

# An upgrade replaces the program under a running service; stop it first.
systemctl stop tiqr.service 2>/dev/null || true

mkdir -p "$target"
cp "$exe" "$target/tiqr"
chmod 755 "$target/tiqr"
for file in THIRD-PARTY-NOTICES.txt INSTALL.txt; do
    if [ -f "$here/$file" ]; then cp "$here/$file" "$target/$file"; fi
done
# A reinstall keeps the branding the site has already edited.
if [ ! -f "$target/tiqr_brand.jsonc" ]; then
    [ -f "$here/tiqr_brand.jsonc" ] || { echo "tiqr_brand.jsonc is missing" >&2; exit 1; }
    cp "$here/tiqr_brand.jsonc" "$target/tiqr_brand.jsonc"
fi

cd "$target"
exec ./tiqr install "$@"
