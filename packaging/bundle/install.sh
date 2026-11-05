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

# An existing installation (units, program or data) is asked about before anything is stopped or copied.
# The first question is reinstall or update. An update keeps the database, settings and license and
# replaces only the program; a reinstall deletes it all, database included, and starts from scratch.
data=/var/lib/tiqr
if [ -e /etc/systemd/system/tiqr.service ] || [ -e /etc/systemd/system/tiqr-health.service ] || [ -e /etc/systemd/system/tiqr-health.timer ] || [ -e "$target/tiqr" ] || [ -e "$data" ]; then
    [ -t 0 ] || { echo "TiQR is already installed. Run this from a terminal to confirm a reinstall; nothing was changed." >&2; exit 1; }
    printf 'TiQR is already installed. Is this a reinstall or an update?\n  update    keeps the database, users, settings and license; only the program is replaced\n  reinstall deletes the program and all its data, including the database and users\nType update, reinstall, or anything else to cancel [update/reinstall/N] ' >&2
    read -r answer || answer=
    case "$answer" in
        update|Update|UPDATE|u|U) export TIQR_UPDATE_CONFIRMED=1 ;;
        reinstall|Reinstall|REINSTALL|r|R)
            printf 'This deletes all data, including the database and users. Continue? [y/N] ' >&2
            read -r sure || sure=
            case "$sure" in
                y|Y|yes|YES|Yes) export TIQR_REINSTALL_CONFIRMED=1 ;;
                *) echo "Install cancelled; nothing was changed." >&2; exit 1 ;;
            esac ;;
        *) echo "Install cancelled; nothing was changed." >&2; exit 1 ;;
    esac
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
# The bundle's branding is copied to the program folder; `tiqr install` then applies it to the data folder.
[ -f "$here/tiqr_brand.jsonc" ] || { echo "tiqr_brand.jsonc is missing" >&2; exit 1; }
cp "$here/tiqr_brand.jsonc" "$target/tiqr_brand.jsonc"

cd "$target"
exec ./tiqr install "$@"
