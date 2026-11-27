#!/bin/bash

# MediaMTX Installation Script for Rocky Linux 9
# Auto-detects latest version and optionally installs FFmpeg for HLS

set -e

echo "=========================================="
echo "MediaMTX Installation for Rocky Linux 9"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        MEDIAMTX_ARCH="amd64"
        ;;
    aarch64|arm64)
        # arm64, NOT arm64v8 — upstream renamed the asset and the old name now
        # 404s, so this download failed on every aarch64 install.
        MEDIAMTX_ARCH="arm64"
        ;;
    armv7l)
        MEDIAMTX_ARCH="armv7"
        ;;
    armv6l)
        MEDIAMTX_ARCH="armv6"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "Detected architecture: $ARCH (MediaMTX: $MEDIAMTX_ARCH)"
echo ""

echo "=========================================="
echo "Step 1: Installing Dependencies"
echo "=========================================="

# Update system
dnf update -y

# Install wget, tar, openssl (random password) and firewall tools
dnf install -y wget tar openssl firewalld

# Install FFmpeg (for HLS support and transcoding)
echo ""
echo "Installing FFmpeg for HLS support and transcoding..."
# No EL release packages FFmpeg in BaseOS/AppStream, and neither does EPEL on
# EL8 or EL9 -- it comes from RPM Fusion free, which in turn needs EPEL and the
# CRB repo (called PowerTools on EL8, codeready-builder on RHEL). The old
# "epel-release + crb + dnf install ffmpeg" failed on every clean EL9 box, and
# on EL8 died even earlier because there is no repo named crb there.
EL_MAJOR=$(rpm -E '%rhel')
# >>> dnf_retry
# RPM Fusion's mirrors fall out of sync for a few minutes at a time (every mirror
# answers 404 for the repodata files; seen Nov 10, 2026, ops #640 and #693). Clean the
# cache and try again before giving up, so a fresh install does not fail on that.
dnf_retry() {
    local tries=${DNF_RETRIES:-5} delay=${DNF_RETRY_DELAY:-60} n=1
    while ! dnf "$@"; do
        [ "$n" -lt "$tries" ] || return 1
        echo "dnf $* failed (try $n of $tries). Cleaning the cache, waiting ${delay}s, trying again..."
        dnf clean all >/dev/null 2>&1 || true
        sleep "$delay"
        n=$((n + 1))
    done
}
# <<< dnf_retry
ffmpeg_failed() {
    echo ""
    echo "ERROR: Could not install FFmpeg: $1"
    echo "FFmpeg on Rocky/RHEL $EL_MAJOR comes from RPM Fusion free, which needs EPEL"
    echo "and the CRB/PowerTools repo. Enable them and install FFmpeg by hand:"
    echo "  dnf install -y epel-release"
    echo "  dnf config-manager --set-enabled crb   # powertools on EL8"
    echo "  dnf install -y https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-${EL_MAJOR}.noarch.rpm"
    echo "  dnf install -y ffmpeg"
    echo "then re-run this script. MediaMTX has not been installed yet."
    exit 1
}
if command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg already installed: $(ffmpeg -version 2>/dev/null | head -1)"
else
    # config-manager comes from dnf-plugins-core, which minimal images lack.
    dnf install -y dnf-plugins-core || ffmpeg_failed "could not install dnf-plugins-core"
    if ! rpm -q epel-release >/dev/null 2>&1; then
        # Rocky/Alma ship epel-release in their own repos; RHEL does not.
        dnf install -y epel-release \
            || dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${EL_MAJOR}.noarch.rpm" \
            || ffmpeg_failed "could not enable EPEL"
    fi
    dnf config-manager --set-enabled crb 2>/dev/null \
        || dnf config-manager --set-enabled powertools 2>/dev/null \
        || subscription-manager repos --enable "codeready-builder-for-rhel-${EL_MAJOR}-$(uname -m)-rpms" \
        || ffmpeg_failed "could not enable the CRB/PowerTools repo"
    if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
        dnf_retry install -y "https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-${EL_MAJOR}.noarch.rpm" \
            || ffmpeg_failed "could not enable RPM Fusion free"
    fi
    dnf_retry install -y ffmpeg || ffmpeg_failed "dnf install ffmpeg failed"
    echo "FFmpeg installed successfully: $(ffmpeg -version 2>/dev/null | head -1)"
fi

echo ""
echo "=========================================="
echo "Step 2: Detecting Latest MediaMTX Version"
echo "=========================================="

# Get latest version from GitHub
LATEST_VERSION=$(curl -s https://api.github.com/repos/bluenviron/mediamtx/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to detect latest version. Please check your internet connection."
    exit 1
fi

echo "Latest MediaMTX version: $LATEST_VERSION"
echo ""

# >>> keep_newer_binary
# ops #1354: re-running this script is how people update MediaMTX, and it installs the newest release. A box that already runs
# a NEWER build (a pre-release put there by hand, a release MediaMTX pulled) must not be moved back: an older binary can refuse
# a config that the newer one wrote. Prints x.y.z of the installed binary $1, or nothing when there is none or it prints no version.
mtx_installed_version() {
    local bin="${1:-/usr/local/bin/mediamtx}" out
    [ -x "$bin" ] || return 0
    out=$("$bin" --version 2>&1 | head -1) || true
    printf '%s\n' "$out" | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' | head -1 | sed 's/^v//'
}
# True when version $1 is strictly newer than version $2. Anything that is not x.y.z counts as "not newer" (the old behavior).
mtx_is_newer() {
    [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$2" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}
# <<< keep_newer_binary

INSTALLED_VERSION=$(mtx_installed_version /usr/local/bin/mediamtx)
KEEP_BINARY=0
FINAL_VERSION="$LATEST_VERSION"
if mtx_is_newer "$INSTALLED_VERSION" "$LATEST_VERSION"; then
    KEEP_BINARY=1
    FINAL_VERSION="$INSTALLED_VERSION"
    echo "MediaMTX $INSTALLED_VERSION is installed here and is newer than the newest release ($LATEST_VERSION)."
    echo "The installed binary is kept (an older one could refuse the config the newer one wrote)."
fi

# Construct download URL
DOWNLOAD_URL="https://github.com/bluenviron/mediamtx/releases/download/v${LATEST_VERSION}/mediamtx_v${LATEST_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"

echo "=========================================="
echo "Step 3: Downloading MediaMTX"
echo "=========================================="
echo "URL: $DOWNLOAD_URL"
echo ""

# Create temporary directory
TMP_DIR=$(mktemp -d)
cd "$TMP_DIR"

# Download MediaMTX
wget -O mediamtx.tar.gz "$DOWNLOAD_URL"

if [ $? -ne 0 ]; then
    echo "Failed to download MediaMTX"
    exit 1
fi

# Check the download against the SHA-256 that MediaMTX publishes with the release (ops #623).
# Fail closed: no checksum, no match, no install. The tarball is not unpacked before this passes.
TARBALL_NAME="mediamtx_v${LATEST_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"
CHECKSUMS_URL="https://github.com/bluenviron/mediamtx/releases/download/v${LATEST_VERSION}/checksums.sha256"
if ! wget -q -O checksums.sha256 "$CHECKSUMS_URL"; then
    echo "Could not download the MediaMTX checksum list ($CHECKSUMS_URL). Nothing was installed."
    exit 1
fi
EXPECTED_SHA=$(awk -v f="$TARBALL_NAME" '{n=$2; sub(/^\*/, "", n)} n==f {print $1}' checksums.sha256)
ACTUAL_SHA=$(sha256sum mediamtx.tar.gz | awk '{print $1}')
if [ -z "$EXPECTED_SHA" ]; then
    echo "The MediaMTX checksum list has no entry for $TARBALL_NAME. Nothing was installed."
    exit 1
fi
if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
    echo "Checksum mismatch for $TARBALL_NAME (expected $EXPECTED_SHA, got $ACTUAL_SHA). Nothing was installed."
    exit 1
fi
echo "✓ Checksum verified (SHA-256 $ACTUAL_SHA)"

echo ""
echo "=========================================="
echo "Step 4: Extracting MediaMTX"
echo "=========================================="

tar -xzf mediamtx.tar.gz

echo ""
echo "=========================================="
echo "Step 5: Installing MediaMTX"
echo "=========================================="

# >>> mtx_install_binary
# Re-running this script is how people update MediaMTX. Keep the binary it replaces, next to it as
# mediamtx.backup_<time> (the web editor's Rollback looks for that name), so a new version that will
# not start can be taken out again (ops #1315). The new binary goes in under a temporary name and is
# renamed, so a killed run never leaves half a binary at the real name.
MTX_BIN=/usr/local/bin/mediamtx
MTX_BIN_BACKUP=""
mtx_install_binary() {
    local new=$1 dest=$2
    MTX_BIN_BACKUP=""
    if [ -f "$dest" ]; then
        MTX_BIN_BACKUP="$dest.backup_$(date +%Y%m%d_%H%M%S)"
        cp -p "$dest" "$MTX_BIN_BACKUP" || return 1
    fi
    cp "$new" "$dest.new" && chmod 755 "$dest.new" && mv -f "$dest.new" "$dest" || return 1
    # SELinux (Rocky/RHEL): the file keeps the label of the folder it came from until it is relabelled.
    if command -v restorecon > /dev/null 2>&1; then restorecon "$dest" > /dev/null 2>&1 || true; fi
}
# <<< mtx_install_binary
if [ "$KEEP_BINARY" = "1" ]; then
    echo "Keeping the installed MediaMTX $INSTALLED_VERSION in /usr/local/bin/ (see keep_newer_binary above)"
else
    mtx_install_binary mediamtx "$MTX_BIN"
fi

# Create config directory
mkdir -p /usr/local/etc

# Install upstream's config only on a fresh install. Re-running this script is
# how people update MediaMTX, so an existing config is the operator's (streams,
# users, passwords, certs) and is never replaced. It is backed up into the web
# editor's backup folder (shows up under Restore) and kept as-is. To start over
# from upstream's config, move the file away and re-run.
CONFIG_FILE=/usr/local/etc/mediamtx.yml
# A fresh config is built under this name (CFG) through the credentials step and renamed into place
# at the end of Step 6, so a run that is stopped half way (Ctrl-C at the username prompt, a lost
# connection) never leaves upstream's open config for the next run to keep (ops #1315).
rm -f "$CONFIG_FILE.new"
KEEP_CONFIG=0
if [ -s "$CONFIG_FILE" ]; then
    KEEP_CONFIG=1
    CFG="$CONFIG_FILE"
    CONFIG_BACKUP_DIR=/usr/local/etc/mediamtx_backups
    mkdir -p "$CONFIG_BACKUP_DIR"
    CONFIG_BACKUP="$CONFIG_BACKUP_DIR/mediamtx.yml.$(date +%Y%m%d_%H%M%S)"
    cp -p "$CONFIG_FILE" "$CONFIG_BACKUP"
    echo "Existing configuration kept: $CONFIG_FILE (backup: $CONFIG_BACKUP)"
else
    CFG="$CONFIG_FILE.new"
    cp mediamtx.yml "$CFG"
fi

# >>> mtx_moq
# Small edits to a configuration that is kept. Each one writes a copy and renames it over the
# original, so the file is never half written. They return 1 and change nothing when there is
# nothing to do.
#
# MoQ: MediaMTX turns MoQ on when the key is missing, which opens port 8892. A config that has the
# key (yes or no) is the operator's choice and is left alone; one that lacks it gets moq: no.
mtx_ensure_moq_off() {
    local cfg=$1
    if grep -qE '^moq[[:space:]]*:' "$cfg"; then
        return 1
    fi
    cp -p "$cfg" "$cfg.new" || return 1
    if ! printf '\n# Added by the MediaMTX installer: newer MediaMTX turns MoQ on when this key is missing,\n# which opens port 8892. Set it to yes if you want MoQ.\nmoq: no\n' >> "$cfg.new"; then
        rm -f "$cfg.new"
        return 1
    fi
    mv -f "$cfg.new" "$cfg"
}
# True when the configuration turns MoQ on (yes or true). The installer leaves that as it is and says so.
mtx_moq_is_on() {
    grep -qE '^moq[[:space:]]*:[[:space:]]*(yes|true)[[:space:]]*(#.*)?$' "$1"
}
# <<< mtx_moq

# Disable MoQ. Unlike the Ubuntu script this one keeps upstream's shipped config, so a fresh install
# inherits `moq: true` — relative cert paths (auto.key/auto.crt) written into the service's working
# directory, which is / for the unit below. As root that write succeeds and litters the filesystem
# root while opening 8892 (and 8893 since v1.20.0), unfirewalled.
if [ "$KEEP_CONFIG" = "1" ]; then
    # The operator's file: add the key only when it is missing, never change a value they set.
    if mtx_ensure_moq_off "$CFG"; then
        echo "Added 'moq: no' (this configuration had no MoQ setting; MediaMTX would turn MoQ on and open port 8892)"
    elif mtx_moq_is_on "$CFG"; then
        echo "NOTE: MoQ is on in this configuration (moq: yes, port 8892). It was left as it is."
        echo "      To turn it off, set 'moq: no' in $CONFIG_FILE and run: systemctl restart mediamtx"
    fi
elif grep -qE '^[[:space:]]*moq:' "$CFG"; then
    # Upstream's own file: rewrite the key it ships.
    sed -i -E 's/^([[:space:]]*)moq:[[:space:]]*(yes|true)[[:space:]]*$/\1moq: no/' "$CFG"
else
    mtx_ensure_moq_off "$CFG" || true
fi

echo "MediaMTX installed to /usr/local/bin/"
echo "Configuration file: /usr/local/etc/mediamtx.yml"

echo ""
echo "=========================================="
echo "Step 6: Configuring Credentials"
echo "=========================================="

# Characters MediaMTX accepts in a username/password; anything else stops it from starting.
MTX_CREDENTIAL_RE='^[]A-Za-z0-9!$()*+.;<=>^_@#&{}[-]+$'
MTX_CREDENTIAL_CHARS='letters, digits and ! $ ( ) * + . ; < = > [ ] ^ _ - { } @ # &'

# True if a `user: any` entry (anonymous) may publish from any IP, as in upstream's
# shipped mediamtx.yml.
anyone_can_publish() {
    awk '
        function check() { if (is_any && open_ips && can_publish) found = 1 }
        /^authInternalUsers:/ { in_users = 1; next }
        in_users && /^[^[:space:]#-]/ { check(); in_users = 0 }
        !in_users { next }
        /^[[:space:]]*- user:/ { check(); u = $3; gsub(/["\047]/, "", u); is_any = (u == "any"); open_ips = 1; can_publish = 0; next }
        /^[[:space:]]*ips:/ { open_ips = ($0 ~ /ips:[[:space:]]*(\[[[:space:]]*\])?[[:space:]]*$/) }
        /^[[:space:]]*- action:[[:space:]]*publish/ { can_publish = 1 }
        END { if (in_users) check(); exit !found }
    ' "$1"
}

if [ "$KEEP_CONFIG" = "1" ]; then
    echo "Skipped: existing configuration keeps its users and passwords"
    if anyone_can_publish "$CONFIG_FILE"; then
        echo ""
        echo "WARNING: this configuration lets ANYONE publish streams without a password"
        echo "         (a 'user: any' entry with publish rights and no IP limit)."
        echo "         Remove publish from that entry in $CONFIG_FILE (or in the web"
        echo "         editor's Users tab) and add a named user instead, then:"
        echo "         systemctl restart mediamtx"
        echo "         To start over with this installer's secure default, move"
        echo "         $CONFIG_FILE away and re-run this script."
        echo ""
    fi
    if grep -qE '^api:[[:space:]]*(no|false)[[:space:]]*$' "$CONFIG_FILE"; then
        echo ""
        echo "NOTE: the MediaMTX API is off in this configuration, so the web editor's"
        echo "      Active Streams can't list streams. To turn it on for this server"
        echo "      only, set these in $CONFIG_FILE:"
        echo "        api: true"
        echo "        apiAddress: 127.0.0.1:9997"
        echo "      then: systemctl restart mediamtx"
        echo ""
    fi
else
    # Prompt for username and password
    while true; do
        read -p "Enter MediaMTX username [default: admin]: " MTX_USER || true
        MTX_USER=${MTX_USER:-admin}
        if [ "$MTX_USER" = "any" ]; then
            echo "'any' means anonymous in MediaMTX; pick another username"
        elif [[ ! "$MTX_USER" =~ $MTX_CREDENTIAL_RE ]]; then
            echo "Username can only contain $MTX_CREDENTIAL_CHARS"
        else
            break
        fi
    done

    while true; do
        read -sp "Enter MediaMTX password [default: random]: " MTX_PASS || true
        echo ""
        if [ -z "$MTX_PASS" ]; then
            MTX_PASS=$(openssl rand -base64 16 | tr -d '/+=\n' | head -c 16)
            break
        elif [[ ! "$MTX_PASS" =~ $MTX_CREDENTIAL_RE ]]; then
            echo "Password can only contain $MTX_CREDENTIAL_CHARS"
        else
            break
        fi
    done

    # Replace upstream's authInternalUsers list with our own (same layout as the
    # Ubuntu template):
    #   - localhost (internal FFmpeg, web editor test stream): read, publish, API, metrics
    #   - the user entered above: publish and read from anywhere
    #   - anyone: read the teststream path only
    MTX_USER="$MTX_USER" MTX_PASS="$MTX_PASS" awk '
        /^authInternalUsers:/ {
            print "authInternalUsers:"
            print "# Internal FFmpeg - localhost only"
            print "- user: any"
            print "  ips: [\"127.0.0.1\", \"::1\"]"
            print "  permissions:"
            print "  - action: read"
            print "  - action: publish"
            print "  - action: api"
            print "  - action: metrics"
            print "  - action: pprof"
            print "# Installer user - publish and read"
            print "- user: \"" ENVIRON["MTX_USER"] "\""
            print "  pass: \"" ENVIRON["MTX_PASS"] "\""
            print "  ips: []"
            print "  permissions:"
            print "  - action: publish"
            print "  - action: read"
            print "  - action: playback"
            print "# Public test stream - no auth, teststream only"
            print "- user: any"
            print "  pass: \047\047"
            print "  ips: []"
            print "  permissions:"
            print "  - action: read"
            print "    path: teststream"
            print ""
            skipping = 1
            next
        }
        # Upstream indents the list and its comments; the next column-0 line ends it.
        skipping && (/^[[:space:]]/ || /^-/ || /^$/) { next }
        { skipping = 0; print }
    ' "$CFG" > "$CFG.tmp"
    if ! grep -qxF -- "- user: \"$MTX_USER\"" "$CFG.tmp" || anyone_can_publish "$CFG.tmp"; then
        rm -f "$CFG.tmp"
        echo "ERROR: could not replace the users in $CFG; credentials NOT configured"
        exit 1
    fi
    mv "$CFG.tmp" "$CFG"

    # Requests through the Caddy reverse proxy (HLS, WebRTC, API, metrics) arrive from
    # localhost. Trust Caddy's X-Forwarded-For so they are checked as the real client,
    # not as the localhost user above.
    sed -i -E 's/^(hls|webrtc|api|metrics|pprof|playback)TrustedProxies:.*/\1TrustedProxies: ["127.0.0.1", "::1"]/' "$CFG"
    # Browsers may not call the Control API from other origins (CSRF).
    sed -i -E 's/^apiAllowOrigins:.*/apiAllowOrigins: []/' "$CFG"
    # The web editor's Active Streams reads the Control API, which upstream ships
    # off. Turn it on for localhost only: the firewall doesn't open 9997 and the
    # Caddy /api/ proxy reaches it on localhost.
    sed -i -E 's/^api:.*/api: true/; s/^apiAddress:.*/apiAddress: 127.0.0.1:9997/' "$CFG"
    if ! grep -qx 'api: true' "$CFG" || ! grep -qx 'apiAddress: 127.0.0.1:9997' "$CFG"; then
        echo "WARNING: could not enable the MediaMTX API; the web editor's Active Streams won't work"
    fi

    echo "Credentials configured: anonymous publishing is off, '$MTX_USER' can publish and read"

    # The configuration is finished: only now does it get its real name (ops #1315).
    sync
    mv -f "$CFG" "$CONFIG_FILE"
    # Same SELinux relabel as the binary (the file was made in a temp folder).
    if command -v restorecon > /dev/null 2>&1; then
        restorecon -v "$CONFIG_FILE" || true
    fi
fi

echo ""
echo "=========================================="
echo "Step 7: Creating systemd Service"
echo "=========================================="

cat > "$TMP_DIR/mediamtx.service" <<EOF
[Unit]
Description=MediaMTX RTSP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml
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
mtx_write_unit /etc/systemd/system/mediamtx.service "$TMP_DIR/mediamtx.service" ExecStart

# >>> mtx_health
# systemctl restart returns as soon as the process is started, so "restart worked" says nothing about
# a MediaMTX that exits one second later (a kept config with a key the new version does not know:
# "unknown field"). Systemd then retries every 5 seconds and the service flips between "activating" and
# "active". Count it healthy only after it has been active for several checks in a row (ops #1315).
mtx_wait_active() {
    local limit=${MTX_HEALTH_SECONDS:-25} stable=${MTX_HEALTH_STABLE:-6} step=${MTX_HEALTH_STEP:-1} i=0 ok=0
    while [ "$i" -lt "$limit" ]; do
        if systemctl is-active --quiet mediamtx; then
            ok=$((ok + 1))
            if [ "$ok" -ge "$stable" ]; then return 0; fi
        else
            ok=0
        fi
        sleep "$step"
        i=$((i + 1))
    done
    return 1
}
# The last error line MediaMTX wrote, for the message to the operator.
mtx_last_error() {
    journalctl -u mediamtx -n 30 --no-pager -o cat 2>/dev/null | grep -iE 'ERR|fatal|invalid|unknown' | tail -n 1 || true
}
# The new MediaMTX did not stay up. Put the previous binary and the previous configuration back,
# start it, say so in plain words, and stop the install with an error.
# Needs: MTX_BIN, MTX_BIN_BACKUP, KEEP_CONFIG, CONFIG_FILE, CONFIG_BACKUP (set by this script).
mtx_start_failed() {
    local version=$1 reason
    reason=$(mtx_last_error)
    echo ""
    echo "ERROR: MediaMTX v$version did not stay running."
    if [ -n "$reason" ]; then echo "  What MediaMTX said: $reason"; fi
    if [ -n "$MTX_BIN_BACKUP" ] && [ -f "$MTX_BIN_BACKUP" ]; then
        echo "  Putting your previous MediaMTX back..."
        cp -p "$MTX_BIN_BACKUP" "$MTX_BIN.new" && mv -f "$MTX_BIN.new" "$MTX_BIN"
        if command -v restorecon > /dev/null 2>&1; then restorecon "$MTX_BIN" > /dev/null 2>&1 || true; fi
        if [ "$KEEP_CONFIG" = "1" ] && [ -f "$CONFIG_BACKUP" ]; then
            cp -p "$CONFIG_BACKUP" "$CONFIG_FILE"
        fi
        systemctl restart mediamtx || true
        if mtx_wait_active; then
            echo "  Your previous MediaMTX is back and running. Your settings are as they were."
            echo "  The new version did not run with your current settings or on this system. Nothing else was changed."
            echo "  Read what MediaMTX said above, fix that (settings are in $CONFIG_FILE), then run this script again."
        else
            echo "  The previous MediaMTX does not stay running either. Your settings are as they were."
            echo "  Look at the log: journalctl -u mediamtx -n 50"
        fi
    else
        echo "  There was no earlier MediaMTX to go back to."
        echo "  Look at the log: journalctl -u mediamtx -n 50"
    fi
    exit 1
}
# <<< mtx_health

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable mediamtx
# restart, not start: on a re-run MediaMTX is already running, and `start` would
# leave the old binary serving.
systemctl restart mediamtx || true
if ! mtx_wait_active; then
    mtx_start_failed "$LATEST_VERSION"
fi

echo "MediaMTX service created and started"

echo ""
echo "=========================================="
echo "Step 8: Configuring Firewall"
echo "=========================================="

# Start and enable firewalld
systemctl enable --now firewalld

# Common MediaMTX ports: RTSP, RTMP, HLS, WebRTC UDP, RTP, RTCP, SRT.
# Runtime + permanent, no --reload: a reload briefly drops outbound traffic and
# kills local senders (e.g. ffmpeg to a multicast group) on a re-run.
for port in 8554/tcp 1935/tcp 8888/tcp 8189/udp 8000/udp 8001/udp 8890/udp; do
    firewall-cmd --zone=public --add-port=$port
    firewall-cmd --zone=public --permanent --add-port=$port
done

echo "Firewall configured"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "MediaMTX Information:"
echo "  - Version: $FINAL_VERSION"
echo "  - Config: /usr/local/etc/mediamtx.yml"
if [ "$KEEP_CONFIG" = "1" ]; then
    echo "  - Existing configuration kept (backup: $CONFIG_BACKUP)"
else
    echo "  - Username: $MTX_USER"
    echo "  - Password: $MTX_PASS"
fi
echo "  - FFmpeg: Installed (HLS and transcoding enabled)"
echo ""
echo "Service Commands:"
echo "  - Status:  systemctl status mediamtx"
echo "  - Stop:    systemctl stop mediamtx"
echo "  - Start:   systemctl start mediamtx"
echo "  - Restart: systemctl restart mediamtx"
echo "  - Logs:    journalctl -u mediamtx -f"
echo ""
echo "Ports Opened:"
echo "  - 8554/tcp  (RTSP)"
echo "  - 1935/tcp  (RTMP)"
echo "  - 8888/tcp  (HLS)"
echo "  - 8189/udp  (WebRTC UDP)"
echo "  - 8000/udp  (RTP)"
echo "  - 8001/udp  (RTCP)"
echo "  - 8890/udp  (SRT)"
echo ""
echo "Next Steps:"
echo "  1. Run the Caddy setup script for HTTPS/domain support"
echo "  2. Edit /usr/local/etc/mediamtx.yml for advanced configuration"
echo "  3. Or use the MediaMTX Config Editor web interface"
echo ""
if [ "$KEEP_CONFIG" != "1" ]; then
    echo "Test RTSP stream:"
    echo "  rtsp://$MTX_USER:$MTX_PASS@<your-server-ip>:8554/mystream"
    echo ""
fi

# Cleanup
cd /
rm -rf "$TMP_DIR"
