#!/bin/sh
# Installs TiQR as a service from this folder: sudo ./install.sh [tiqr install options]
# The program is copied to /opt/tiqr. Its data (database, settings, branding) lives in /var/lib/tiqr,
# which upgrades leave alone. Then `tiqr install` sets up the address, database, first admin,
# firewall, service and health timer.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
target=${TIQR_INSTALL_DIR:-/opt/tiqr}

if [ "$(id -u)" -ne 0 ]; then
    echo "Needs root; running again with sudo." >&2
    exec sudo "$0" "$@"
fi

exe="$here/tiqr"
[ -f "$exe" ] || { echo "No tiqr executable in $here" >&2; exit 1; }

# An existing installation (units, program or data) is asked about before anything is stopped or copied;
# a no changes nothing. A yes deletes it all, database included, and installs from scratch.
data=/var/lib/tiqr
if [ -e /etc/systemd/system/tiqr.service ] || [ -e /etc/systemd/system/tiqr-health.service ] || [ -e /etc/systemd/system/tiqr-health.timer ] || [ -e "$target/tiqr" ] || [ -e "$data" ]; then
    [ -t 0 ] || { echo "TiQR is already installed. Run this from a terminal to confirm a reinstall; nothing was changed." >&2; exit 1; }
    printf 'TiQR is already installed. Reinstalling deletes the program and all its data, including the database and users, and starts from scratch. Reinstall it? [y/N] ' >&2
    read -r answer || answer=
    case "$answer" in
        y|Y|yes|YES|Yes) ;;
        *) echo "Install cancelled; nothing was changed." >&2; exit 1 ;;
    esac
    export TIQR_REINSTALL_CONFIRMED=1
fi

# An upgrade replaces the program under a running service; stop it first.
systemctl stop tiqr.service 2>/dev/null || true
if [ "${TIQR_REINSTALL_CONFIRMED:-}" = 1 ]; then
    [ "$here" = "$target" ] || rm -rf "$target"
    rm -rf "$data"
fi

mkdir -p "$target"
cp "$exe" "$target/tiqr"
chmod 755 "$target/tiqr"
for file in THIRD-PARTY-NOTICES.txt INSTALL.txt; do
    if [ -f "$here/$file" ]; then cp "$here/$file" "$target/$file"; fi
done
cp "$here/tiqr-health.sh" "$target/tiqr-health.sh"
chmod 755 "$target/tiqr-health.sh"
# The bundle's branding is only the default for a first install; the data folder keeps its own.
[ -f "$here/tiqr_brand.jsonc" ] || { echo "tiqr_brand.jsonc is missing" >&2; exit 1; }
cp "$here/tiqr_brand.jsonc" "$target/tiqr_brand.jsonc"

cd "$target"
exec ./tiqr install "$@"
