#!/bin/bash
# Privileged helper for the MediaMTX web editor's binary upgrade/rollback.
#
# The editor may run as an unprivileged user (hardened installs). Replacing
# /usr/local/bin/mediamtx and stopping/starting the service need root, so
# such boxes provision this helper ONCE, as root:
#
#   install -o root -g root -m 0755 mediamtx-upgrade-helper.sh /usr/local/sbin/mediamtx-upgrade-helper
#   echo '<editor-user> ALL=(root) NOPASSWD: /usr/local/sbin/mediamtx-upgrade-helper' > /etc/sudoers.d/mediamtx-webeditor
#   chmod 0440 /etc/sudoers.d/mediamtx-webeditor
#
# This intentionally grants the editor user exactly one capability: replace
# the MediaMTX binary and control its service. Keep the file root-owned and
# never writable by the editor user, or the grant becomes full root.
set -euo pipefail

BIN=/usr/local/bin/mediamtx

case "${1:-}" in
    check)
        exit 0
        ;;
    stop|start|restart)
        exec systemctl "$1" mediamtx
        ;;
    install)
        SRC="${2:?usage: mediamtx-upgrade-helper install <path-to-binary>}"
        [ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 1; }
        "$SRC" --version >/dev/null 2>&1 || { echo "not a runnable mediamtx binary: $SRC" >&2; exit 1; }
        if [ -f "$BIN" ]; then
            TS=$(date +%Y%m%d_%H%M%S)
            cp -p "$BIN" "$BIN.backup_$TS"
            echo "BACKUP=$BIN.backup_$TS"
        fi
        cp "$SRC" "$BIN"
        chmod 755 "$BIN"
        command -v restorecon >/dev/null 2>&1 && restorecon "$BIN" || true
        echo "INSTALLED=$("$BIN" --version 2>/dev/null | head -1)"
        ;;
    *)
        echo "usage: mediamtx-upgrade-helper check|stop|start|restart|install <path>" >&2
        exit 2
        ;;
esac
