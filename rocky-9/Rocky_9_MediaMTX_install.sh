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
dnf install -y epel-release
dnf config-manager --set-enabled crb
dnf install -y ffmpeg ffmpeg-devel
echo "FFmpeg installed successfully"

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

echo ""
echo "=========================================="
echo "Step 4: Extracting MediaMTX"
echo "=========================================="

tar -xzf mediamtx.tar.gz

echo ""
echo "=========================================="
echo "Step 5: Installing MediaMTX"
echo "=========================================="

# Move executable to /usr/local/bin
mv mediamtx /usr/local/bin/
chmod +x /usr/local/bin/mediamtx

# Create config directory
mkdir -p /usr/local/etc

# Install upstream's config only on a fresh install. Re-running this script is
# how people update MediaMTX, so an existing config is the operator's (streams,
# users, passwords, certs) and is never replaced. It is backed up into the web
# editor's backup folder (shows up under Restore) and kept as-is. To start over
# from upstream's config, move the file away and re-run.
CONFIG_FILE=/usr/local/etc/mediamtx.yml
KEEP_CONFIG=0
if [ -s "$CONFIG_FILE" ]; then
    KEEP_CONFIG=1
    CONFIG_BACKUP_DIR=/usr/local/etc/mediamtx_backups
    mkdir -p "$CONFIG_BACKUP_DIR"
    CONFIG_BACKUP="$CONFIG_BACKUP_DIR/mediamtx.yml.$(date +%Y%m%d_%H%M%S)"
    cp -p "$CONFIG_FILE" "$CONFIG_BACKUP"
    echo "Existing configuration kept: $CONFIG_FILE (backup: $CONFIG_BACKUP)"
else
    mv mediamtx.yml "$CONFIG_FILE"
fi

# Disable MoQ. Unlike the Ubuntu script this one keeps upstream's shipped config, so
# it inherits `moq: true` — relative cert paths (auto.key/auto.crt) written into the
# service's working directory, which is / for the unit below. As root that write
# succeeds and litters the filesystem root while opening 8892 (and 8893 since
# v1.20.0), unfirewalled. Handle both shapes: rewrite the key if upstream ships one,
# append it if not.
if grep -qE '^[[:space:]]*moq:' /usr/local/etc/mediamtx.yml; then
    sed -i -E 's/^([[:space:]]*)moq:[[:space:]]*(yes|true)[[:space:]]*$/\1moq: no/' /usr/local/etc/mediamtx.yml
else
    printf '\n# Disabled by the infra-TAK MediaMTX installer - see notes in the Ubuntu script.\nmoq: no\n' >> /usr/local/etc/mediamtx.yml
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
    ' "$CONFIG_FILE" > "$CONFIG_FILE.new"
    if ! grep -qxF -- "- user: \"$MTX_USER\"" "$CONFIG_FILE.new" || anyone_can_publish "$CONFIG_FILE.new"; then
        rm -f "$CONFIG_FILE.new"
        echo "ERROR: could not replace the users in $CONFIG_FILE; credentials NOT configured"
        exit 1
    fi
    mv "$CONFIG_FILE.new" "$CONFIG_FILE"

    # Requests through the Caddy reverse proxy (HLS, WebRTC, API, metrics) arrive from
    # localhost. Trust Caddy's X-Forwarded-For so they are checked as the real client,
    # not as the localhost user above.
    sed -i -E 's/^(hls|webrtc|api|metrics|pprof|playback)TrustedProxies:.*/\1TrustedProxies: ["127.0.0.1", "::1"]/' "$CONFIG_FILE"
    # Browsers may not call the Control API from other origins (CSRF).
    sed -i -E 's/^apiAllowOrigins:.*/apiAllowOrigins: []/' "$CONFIG_FILE"

    echo "Credentials configured: anonymous publishing is off, '$MTX_USER' can publish and read"
fi

echo ""
echo "=========================================="
echo "Step 7: Creating systemd Service"
echo "=========================================="

cat > /etc/systemd/system/mediamtx.service <<EOF
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

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable mediamtx
# restart, not start: on a re-run MediaMTX is already running, and `start` would
# leave the old binary serving.
systemctl restart mediamtx

echo "MediaMTX service created and started"

echo ""
echo "=========================================="
echo "Step 8: Configuring Firewall"
echo "=========================================="

# Start and enable firewalld
systemctl enable --now firewalld

# Common MediaMTX ports
firewall-cmd --zone=public --permanent --add-port=8554/tcp   # RTSP
firewall-cmd --zone=public --permanent --add-port=1935/tcp   # RTMP
firewall-cmd --zone=public --permanent --add-port=8888/tcp   # HLS
firewall-cmd --zone=public --permanent --add-port=8189/udp   # WebRTC UDP
firewall-cmd --zone=public --permanent --add-port=8000/udp   # RTP
firewall-cmd --zone=public --permanent --add-port=8001/udp   # RTCP
firewall-cmd --zone=public --permanent --add-port=8890/udp   # SRT

# Reload firewall
firewall-cmd --reload

echo "Firewall configured"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "MediaMTX Information:"
echo "  - Version: $LATEST_VERSION"
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
