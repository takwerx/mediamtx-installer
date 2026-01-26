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
    aarch64)
        MEDIAMTX_ARCH="arm64v8"
        ;;
    armv7l)
        MEDIAMTX_ARCH="armv7"
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

# Install wget, tar, and firewall tools
dnf install -y wget tar firewalld

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

# Move config file
mv mediamtx.yml /usr/local/etc/

echo "MediaMTX installed to /usr/local/bin/"
echo "Configuration file: /usr/local/etc/mediamtx.yml"

echo ""
echo "=========================================="
echo "Step 6: Configuring Default Credentials"
echo "=========================================="

# Prompt for username and password
read -p "Enter MediaMTX username [default: admin]: " MTX_USER
MTX_USER=${MTX_USER:-admin}

read -sp "Enter MediaMTX password [default: admin]: " MTX_PASS
echo ""
MTX_PASS=${MTX_PASS:-admin}

# Update credentials in config file
sed -i "s/user: addusernamehere/user: $MTX_USER/" /usr/local/etc/mediamtx.yml
sed -i "s/pass: addpasswordhere/pass: $MTX_PASS/" /usr/local/etc/mediamtx.yml

echo "Credentials configured"

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
systemctl start mediamtx

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
firewall-cmd --zone=public --permanent --add-port=8889/tcp   # WebRTC HTTP
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
echo "  - Username: $MTX_USER"
echo "  - Password: $MTX_PASS"
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
echo "  - 8889/tcp  (WebRTC HTTP)"
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
echo "Test RTSP stream:"
echo "  rtsp://$MTX_USER:$MTX_PASS@<your-server-ip>:8554/mystream"
echo ""

# Cleanup
cd /
rm -rf "$TMP_DIR"
