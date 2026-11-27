#!/bin/bash

# MediaMTX Web Configuration Editor - Installation Script (Ubuntu / Rocky 9)
# Installs Flask-based web editor for managing MediaMTX
# v2.0 - Adds psutil, requests dependencies
# v2.1 - Python packages go in a venv, so the install works on Ubuntu 24.04+ / Debian 12
# v2.2 - Rocky/RHEL 9: the venv is built from python3.12 (the pinned packages need Python 3.10+)

set -e

# Prevent interactive prompts
export DEBIAN_FRONTEND=noninteractive

echo "=========================================="
echo "MediaMTX Web Editor Installer v2.0"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Check if MediaMTX is installed
# Look for the binary by path too: on Rocky/RHEL, sudo's secure_path leaves out
# /usr/local/bin, so `command -v` alone misses where the installers put it.
if { ! command -v mediamtx &> /dev/null && [ ! -x /usr/local/bin/mediamtx ]; } || [ ! -f /usr/local/etc/mediamtx.yml ]; then
    echo "ERROR: MediaMTX is not installed!"
    echo "Please run the MediaMTX installer first:"
    echo "  sudo ./ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh   (Ubuntu)"
    echo "  sudo ./rocky-9/Rocky_9_MediaMTX_install.sh             (Rocky/RHEL)"
    exit 1
fi

# >>> mtx_editor_version
# Version compare for the check below. CURRENT_VERSION in the editor file reads v2.1.21 on a release and
# v2.1.21-dev on the dev branch (which is OLDER than the release it is heading for).
mtx_editor_version() {
    sed -n -E "s/^CURRENT_VERSION[[:space:]]*=[[:space:]]*['\"]v?([0-9]+\.[0-9]+\.[0-9]+(-dev)?)['\"].*/\1/p" "$1" 2>/dev/null | head -n 1
}
mtx_version_key() {
    local v=${1%-dev} dev=1 a b c
    case $1 in *-dev) dev=0 ;; esac
    IFS=. read -r a b c <<< "$v"
    printf '%05d%05d%05d%d' "$((10#$a))" "$((10#$b))" "$((10#$c))" "$dev"
}
# 0 (true) when version $1 is older than version $2
mtx_version_older() {
    [ "$(mtx_version_key "$1")" -lt "$(mtx_version_key "$2")" ]
}
# <<< mtx_editor_version

# Where the editor file to install is (the same two places Step 2 looks).
EDITOR_SRC=""
if [ -f "./config-editor/mediamtx_config_editor.py" ]; then
    EDITOR_SRC="./config-editor/mediamtx_config_editor.py"
elif [ -f "./mediamtx_config_editor.py" ]; then
    EDITOR_SRC="./mediamtx_config_editor.py"
fi

# Re-running this script from an old copy of the repository must not turn a newer editor back into
# an older one (ops #1315). The check runs before anything is changed.
if [ -n "$EDITOR_SRC" ] && [ -f /opt/mediamtx-webeditor/mediamtx_config_editor.py ]; then
    INSTALLED_EDITOR_VERSION=$(mtx_editor_version /opt/mediamtx-webeditor/mediamtx_config_editor.py)
    THIS_EDITOR_VERSION=$(mtx_editor_version "$EDITOR_SRC")
    if [ -n "$INSTALLED_EDITOR_VERSION" ] && [ -n "$THIS_EDITOR_VERSION" ] \
        && mtx_version_older "$THIS_EDITOR_VERSION" "$INSTALLED_EDITOR_VERSION"; then
        echo "ERROR: this copy of the web editor (v$THIS_EDITOR_VERSION) is older than the one installed (v$INSTALLED_EDITOR_VERSION)."
        echo "Nothing was changed."
        echo "Get the newest copy first (git pull, or download the newest release), then run this script again."
        echo "To go back to an older version on purpose, use Rollback on the web editor's Versions tab."
        exit 1
    fi
fi

# ==========================================
# Unattended-Upgrade Detection
# ==========================================
if pgrep -f "/usr/bin/unattended-upgrade$" > /dev/null; then
    echo ""
    echo "************************************************************"
    echo "  YOUR OPERATING SYSTEM IS CURRENTLY DOING UPGRADES"
    echo "  We need to wait until this is done."
    echo "  The process will auto-start once updates are complete."
    echo "************************************************************"
    echo ""
    
    SECONDS=0
    while pgrep -f "/usr/bin/unattended-upgrade$" > /dev/null; do
        printf "\rWaiting... %02d:%02d elapsed" $((SECONDS/60)) $((SECONDS%60))
        sleep 2
    done
    
    echo ""
    echo ""
    echo "✓ Updates complete after $((SECONDS/60)) minutes! Starting installation..."
    echo ""
    sleep 2
else
    echo "Checking for system upgrades in progress..."
    echo "✓ No system upgrades in progress, continuing..."
    echo ""
fi

echo "=========================================="
echo "Step 1: Installing Python Dependencies"
echo "=========================================="

# >>> install_python
# Installs Python and sets VENV_PYTHON, the interpreter the web editor's venv is built from.
# The pinned packages (urllib3 2.8.0, requests 2.34.2) need Python 3.10 or newer. Ubuntu 22.04 and
# newer have that. Rocky/RHEL 9 ships Python 3.9, so it also gets python3.12 from its own AppStream
# repo, and the venv uses that one (ops #1030). The system python3 stays as it is: dnf itself and
# the KLV sidecar run on it.
VENV_PYTHON=python3
install_python() {
    if command -v apt-get > /dev/null 2>&1; then
        apt-get update -qq > /dev/null 2>&1
        apt-get install -y python3 python3-pip python3-venv python3-psutil > /dev/null 2>&1 || apt-get install -y python3 python3-pip python3-venv python3-psutil
    elif command -v dnf > /dev/null 2>&1; then
        # Rocky/RHEL: venv is part of python3 there; psutil comes from pip below.
        dnf install -y -q python3 python3-pip > /dev/null 2>&1 || dnf install -y python3 python3-pip
        dnf install -y -q python3.12 python3.12-pip > /dev/null 2>&1 || dnf install -y python3.12 python3.12-pip
        if ! command -v python3.12 > /dev/null 2>&1; then
            echo ""
            echo "ERROR: python3.12 is not available from this server's dnf repositories."
            echo "The web editor needs Python 3.10 or newer, and this server has Python 3.9."
            echo "Enable the AppStream repository (dnf repolist) or install python3.12 yourself, then re-run this script."
            exit 1
        fi
        VENV_PYTHON=python3.12
    else
        echo ""
        echo "ERROR: Neither apt-get nor dnf found. Install python3 (3.10 or newer) and python3-pip yourself and re-run this script."
        exit 1
    fi
    if ! "$VENV_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' > /dev/null 2>&1; then
        echo ""
        echo "ERROR: $VENV_PYTHON is older than Python 3.10 (or missing). The web editor's pinned packages need 3.10 or newer."
        exit 1
    fi
}
# <<< install_python
install_python
echo "✓ Python and pip installed ($("$VENV_PYTHON" --version 2>&1))"

# Install required Python packages into a venv that the service runs from.
# Ubuntu 23.04+ and Debian 12 mark the system Python as externally managed
# (PEP 668) and refuse a system-wide `pip3 install`. This used to be
# `pip3 install ... || true`, which swallowed that refusal, printed ✓ anyway,
# and left the service crash-looping on `import flask`.
# --system-site-packages lets the venv use apt's python3-psutil, so boards with
# no psutil wheel (armv7) don't need a compiler.
# The new venv is built NEXT TO the running one (venv.new) and only replaces it when it imports
# everything the editor needs. The old one is kept as venv.prev. It used to be rebuilt in place with
# --clear, so a pip that failed halfway left the editor with no Flask at its next restart (ops #1315).
# A rebuild on every run also repairs a venv still pointing at the Python from before a release upgrade.
WEB_EDITOR_DIR="/opt/mediamtx-webeditor"
VENV_DIR="$WEB_EDITOR_DIR/venv"
VENV_NEW="$WEB_EDITOR_DIR/venv.new"
VENV_PREV="$WEB_EDITOR_DIR/venv.prev"
mkdir -p "$WEB_EDITOR_DIR"
venv_failed() {
    rm -rf "$VENV_NEW"
    echo ""
    echo "ERROR: $1"
    if [ -d "$VENV_DIR" ]; then
        echo "The web editor's current Python packages were not changed."
    fi
    echo "$2"
    exit 1
}
echo "Installing Flask and dependencies into a new venv ($VENV_NEW), next to the current one..."
rm -rf "$VENV_NEW"
if ! "$VENV_PYTHON" -m venv --system-site-packages "$VENV_NEW"; then
    venv_failed "Could not create a Python virtual environment at $VENV_NEW" \
        "Install python3-venv (apt-get install python3-venv) and re-run this script."
fi
# Exact versions with a SHA-256 for every file (requirements*.txt), so pip refuses a swapped or
# tampered package (ops #623). They sit beside this script (the same place the editor file is
# looked for below).
REQ_DIR=""
for d in "$(dirname "$0")" "./config-editor" "."; do
    if [ -f "$d/requirements.txt" ]; then REQ_DIR="$d"; break; fi
done
if [ -z "$REQ_DIR" ]; then
    venv_failed "requirements.txt (the pinned Python packages) was not found next to this script." \
        "Get the whole repository (git clone, or the release zip) and re-run this script."
fi
PIP_INSTALL=("$VENV_NEW/bin/python3" -m pip install --quiet --disable-pip-version-check --require-hashes)
if ! "${PIP_INSTALL[@]}" -r "$REQ_DIR/requirements.txt"; then
    venv_failed "Could not install the web editor's Python packages (see pip's output above)." \
        "If pip reports a hash mismatch, do not work around it: the download does not match what we pinned. Fix that and re-run this script."
fi
# psutil: apt's python3-psutil is already visible in the venv on Ubuntu/Debian, so only pip-install
# it when it is missing (Rocky). Keeps armv7 boards, which have no psutil wheel, working.
if ! "$VENV_NEW/bin/python3" -c 'import psutil' > /dev/null 2>&1; then
    if ! "${PIP_INSTALL[@]}" -r "$REQ_DIR/requirements-psutil.txt"; then
        venv_failed "Could not install psutil (see pip's output above)." "Fix that and re-run this script."
    fi
fi
if ! "$VENV_NEW/bin/python3" -c 'import flask, ruamel.yaml, requests, psutil' > /dev/null 2>&1; then
    venv_failed "The new Python environment cannot import what the web editor needs (flask, ruamel.yaml, requests, psutil)." \
        "Re-run this script. If it happens again, see pip's output above."
fi
# A venv remembers its own folder name in pyvenv.cfg and in the first line of its scripts (pip, flask).
# It was built as venv.new, so point those at venv before the folder is renamed.
for f in "$VENV_NEW/pyvenv.cfg" "$VENV_NEW"/bin/*; do
    if [ -f "$f" ] && [ ! -L "$f" ] && grep -Iq '/venv\.new' "$f" 2>/dev/null; then
        sed -i 's#/venv\.new#/venv#g' "$f"
    fi
done
rm -rf "$VENV_PREV"
if [ -e "$VENV_DIR" ]; then mv "$VENV_DIR" "$VENV_PREV"; fi
if ! mv "$VENV_NEW" "$VENV_DIR"; then
    if [ -e "$VENV_PREV" ]; then mv "$VENV_PREV" "$VENV_DIR"; fi
    venv_failed "Could not put the new Python environment in place." "Re-run this script."
fi
echo "✓ Python packages installed (Flask, ruamel.yaml, requests, psutil), versions and hashes pinned"

echo ""
echo "=========================================="
echo "Step 2: Installing Web Editor Files"
echo "=========================================="

# Create web editor directories
mkdir -p "$WEB_EDITOR_DIR/backups"
mkdir -p "$WEB_EDITOR_DIR/recordings"
mkdir -p "$WEB_EDITOR_DIR/test_videos"

# Find the Python file (EDITOR_SRC was set at the top). The file it replaces is kept as
# mediamtx_config_editor.py.backup_<time>, the name the editor's Versions tab lists for Rollback,
# unless it is the same file (ops #1315).
if [ -n "$EDITOR_SRC" ]; then
    EDITOR_DEST="$WEB_EDITOR_DIR/mediamtx_config_editor.py"
    if [ -f "$EDITOR_DEST" ] && ! cmp -s "$EDITOR_SRC" "$EDITOR_DEST"; then
        cp -p "$EDITOR_DEST" "$EDITOR_DEST.backup_$(date +%Y%m%d_%H%M%S)"
    fi
    cp "$EDITOR_SRC" "$EDITOR_DEST.new" && mv -f "$EDITOR_DEST.new" "$EDITOR_DEST"
    echo "✓ Web editor copied from $(dirname "$EDITOR_SRC")/"
else
    echo ""
    echo "ERROR: mediamtx_config_editor.py not found!"
    echo ""
    echo "Expected in one of:"
    echo "  ./config-editor/mediamtx_config_editor.py"
    echo "  ./mediamtx_config_editor.py"
    echo ""
    echo "Please place the file and re-run this script."
    exit 1
fi

chmod 755 "$WEB_EDITOR_DIR/mediamtx_config_editor.py"

# Copy KLV->CoT sidecar (v2.1.0) if present
if [ -f "./config-editor/klv-to-cot.py" ]; then
    cp ./config-editor/klv-to-cot.py "$WEB_EDITOR_DIR/"
    chmod 755 "$WEB_EDITOR_DIR/klv-to-cot.py"
    echo "✓ KLV->CoT sidecar (klv-to-cot.py) installed"
elif [ -f "./klv-to-cot.py" ]; then
    cp ./klv-to-cot.py "$WEB_EDITOR_DIR/"
    chmod 755 "$WEB_EDITOR_DIR/klv-to-cot.py"
    echo "✓ KLV->CoT sidecar (klv-to-cot.py) installed"
else
    echo "ℹ  No KLV->CoT sidecar found (KLV extraction unavailable until present)"
fi

# Copy test video file if present
if [ -f "./config-editor/truck_60.ts" ]; then
    cp ./config-editor/truck_60.ts "$WEB_EDITOR_DIR/test_videos/"
    echo "✓ Test video (truck_60.ts) installed"
elif [ -f "./truck_60.ts" ]; then
    cp ./truck_60.ts "$WEB_EDITOR_DIR/test_videos/"
    echo "✓ Test video (truck_60.ts) installed"
else
    echo "ℹ  No test video found (optional - upload via web editor later)"
fi

# First login: a random admin password, made now and shown once at the end. A box that
# already has a users.json keeps its logins (the editor itself retires a leftover
# admin/admin when it starts).
ADMIN_PW=""
if [ ! -f "$WEB_EDITOR_DIR/users.json" ]; then
    ADMIN_PW="$("$VENV_DIR/bin/python3" -c 'import secrets; print(secrets.token_urlsafe(12))')"
    (umask 077; ADMIN_PW="$ADMIN_PW" WEB_EDITOR_DIR="$WEB_EDITOR_DIR" "$VENV_DIR/bin/python3" - <<'PYEOF'
import json, os
d = os.environ['WEB_EDITOR_DIR']
pw = os.environ['ADMIN_PW']
with open(os.path.join(d, 'users.json'), 'w') as f:
    json.dump([{'username': 'admin', 'password': pw, 'role': 'admin'}], f, indent=2)
with open(os.path.join(d, 'initial_admin_password.txt'), 'w') as f:
    f.write('# MediaMTX web editor: first login. Sign in, then change this password (Account tab).\n')
    f.write('# This file is deleted when the password is changed.\n')
    f.write('admin: ' + pw + '\n')
PYEOF
    )
    chmod 600 "$WEB_EDITOR_DIR/users.json" "$WEB_EDITOR_DIR/initial_admin_password.txt"
    echo "✓ Admin login created"
fi

echo ""
echo "=========================================="
echo "Step 3: Creating systemd Service"
echo "=========================================="

# A box that already has the unit is a re-run. It may have been hardened by hand (another User=,
# sandbox settings, port 5000 closed on purpose), and the installer keeps that (ops #1315).
EDITOR_UNIT=/etc/systemd/system/mediamtx-webeditor.service
RERUN=0
if [ -s "$EDITOR_UNIT" ]; then RERUN=1; fi
UNIT_TMP=$(mktemp)
cat > "$UNIT_TMP" <<EOF
[Unit]
Description=MediaMTX Web Configuration Editor
After=network.target mediamtx.service

[Service]
Type=simple
ExecStart=/opt/mediamtx-webeditor/venv/bin/python3 /opt/mediamtx-webeditor/mediamtx_config_editor.py
WorkingDirectory=/opt/mediamtx-webeditor
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

# >>> mtx_write_unit
# Writes a systemd unit but keeps what the operator changed in it (a hardened User=, Group=, sandbox
# settings). Only the lines named in KEY... are set to the installer's value: the ones the installer
# needs. A box with no unit gets the installer's unit as it is. The unit it replaces is kept as
# UNIT.backup_<time> (systemd ignores that name) (ops #1315).
# usage: mtx_write_unit UNIT_FILE INSTALLER_UNIT_FILE KEY...
mtx_write_unit() {
    local unit=$1 fresh=$2 key line have
    shift 2
    if [ ! -s "$unit" ] || ! grep -q '^\[Service\]' "$unit"; then
        if [ -s "$unit" ]; then cp -p "$unit" "$unit.backup_$(date +%Y%m%d_%H%M%S)"; fi
        cp "$fresh" "$unit.new" && mv -f "$unit.new" "$unit"
        return 0
    fi
    cp -p "$unit" "$unit.new" || return 1
    for key in "$@"; do
        line=$(grep -m1 "^$key=" "$fresh") || continue
        have=0
        if grep -q "^$key=" "$unit.new"; then have=1; fi
        awk -v key="$key" -v line="$line" -v have="$have" '
            index($0, key "=") == 1 { if (!done) { print line; done = 1 }; next }
            $0 == "[Service]" { print; if (!have) { print line; done = 1 }; next }
            { print }
        ' "$unit.new" > "$unit.new2" && mv -f "$unit.new2" "$unit.new"
    done
    if cmp -s "$unit" "$unit.new"; then
        rm -f "$unit.new"
    else
        cp -p "$unit" "$unit.backup_$(date +%Y%m%d_%H%M%S)"
        mv -f "$unit.new" "$unit"
    fi
}
# <<< mtx_write_unit
mtx_write_unit "$EDITOR_UNIT" "$UNIT_TMP" ExecStart WorkingDirectory
rm -f "$UNIT_TMP"

systemctl daemon-reload
systemctl enable mediamtx-webeditor
# restart, not start: on a re-run the editor is usually already running, and
# `start` would leave it on the old unit (system python3) and the old editor file.
systemctl restart mediamtx-webeditor

echo "✓ Web editor service created and started"

echo ""
echo "=========================================="
echo "Step 4: Configuring Firewall"
echo "=========================================="

# Open web editor port. Rocky/RHEL run firewalld, Ubuntu ufw; some boxes have
# neither (e.g. cloud images that rely on a security group).
# Only on the first install: a re-run leaves the firewall as the operator has it (ops #1315).
if [ "$RERUN" = "1" ]; then
    echo "ℹ  Re-run: the firewall was left as it is. If port 5000 should be open, open it yourself (ufw allow 5000/tcp, or firewall-cmd)."
elif command -v firewall-cmd > /dev/null 2>&1 && firewall-cmd --state > /dev/null 2>&1; then
    # Runtime + permanent, no --reload (a reload kills local multicast senders).
    firewall-cmd --zone=public --add-port=5000/tcp > /dev/null
    firewall-cmd --zone=public --permanent --add-port=5000/tcp > /dev/null
    echo "✓ Port 5000 opened for web editor (firewalld)"
elif command -v ufw > /dev/null 2>&1; then
    ufw allow 5000/tcp > /dev/null 2>&1
    echo "✓ Port 5000 opened for web editor"
else
    echo "ℹ  No running firewall found (firewalld or ufw), so no port was opened."
    echo "   If this server is behind another firewall, allow 5000/tcp there."
fi

# Wait for service to start
sleep 3

# Check if running
if systemctl is-active --quiet mediamtx-webeditor; then
    echo ""
    echo "=========================================="
    echo "Installation Complete!"
    echo "=========================================="
    echo ""
    echo "  Web Editor: http://<your-server-ip>:5000"
    echo ""
    if [ -n "$ADMIN_PW" ]; then
        echo "  First Login (shown once, write it down):"
        echo "    Username: admin"
        echo "    Password: $ADMIN_PW"
        echo "    Also saved, root only, in $WEB_EDITOR_DIR/initial_admin_password.txt"
        echo "    (it is deleted when you change the password)"
    else
        echo "  Login: your existing web editor logins are unchanged."
        echo "    If the old admin / admin login was still in use, the editor replaced it with a"
        echo "    random password: see $WEB_EDITOR_DIR/initial_admin_password.txt (root only)."
    fi
    echo ""
    echo "  Service Commands:"
    echo "    Status:  systemctl status mediamtx-webeditor"
    echo "    Logs:    journalctl -u mediamtx-webeditor -f"
    echo "    Restart: systemctl restart mediamtx-webeditor"
    echo ""
    echo "  Next Steps:"
    echo "    1. Login and change the password"
    echo "    2. Configure streaming users in Users & Auth tab"
    echo "    3. Install Caddy for HTTPS (optional)"
    echo ""
else
    echo ""
    echo "WARNING: Web editor service may not have started correctly."
    echo "Check logs: journalctl -u mediamtx-webeditor -n 50"
    echo ""
fi
