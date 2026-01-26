#!/bin/bash

# MediaMTX Web Config Editor Installation Script
# Works on Rocky Linux 9 and Ubuntu 22.04

set -e

echo "=========================================="
echo "MediaMTX Web Config Editor Installation"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Check if MediaMTX is installed
if [ ! -f /usr/local/etc/mediamtx.yml ]; then
    echo "ERROR: MediaMTX is not installed!"
    echo "Please run the MediaMTX installation script first."
    exit 1
fi

echo "=========================================="
echo "Step 1: Installing Python and Dependencies"
echo "=========================================="

# Detect OS
if [ -f /etc/rocky-release ]; then
    OS="rocky"
    dnf install -y python3 python3-pip
elif [ -f /etc/lsb-release ]; then
    OS="ubuntu"
    apt update
    apt install -y python3 python3-pip
else
    echo "Unsupported OS"
    exit 1
fi

# Install Python packages
pip3 install flask pyyaml

echo ""
echo "=========================================="
echo "Step 2: Installing Web Config Editor"
echo "=========================================="

# Create directory
mkdir -p /opt/mediamtx-config-editor

# Download or copy the Python script
# Note: Replace this with actual download or assume script is in current directory
if [ -f "mediamtx_config_editor.py" ]; then
    cp mediamtx_config_editor.py /opt/mediamtx-config-editor/
else
    echo "ERROR: mediamtx_config_editor.py not found in current directory"
    exit 1
fi

chmod +x /opt/mediamtx-config-editor/mediamtx_config_editor.py

echo ""
echo "=========================================="
echo "Step 3: Creating systemd Service"
echo "=========================================="

cat > /etc/systemd/system/mediamtx-config-editor.service <<EOF
[Unit]
Description=MediaMTX Configuration Web Editor
After=network.target mediamtx.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mediamtx-config-editor
ExecStart=/usr/bin/python3 /opt/mediamtx-config-editor/mediamtx_config_editor.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable mediamtx-config-editor
systemctl start mediamtx-config-editor

echo ""
echo "=========================================="
echo "Step 4: Configuring Firewall"
echo "=========================================="

if [ "$OS" = "rocky" ]; then
    firewall-cmd --zone=public --permanent --add-port=5000/tcp
    firewall-cmd --reload
else
    ufw allow 5000/tcp
fi

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "MediaMTX Config Editor is now running!"
echo ""
echo "Access the web interface:"
echo "  http://<your-server-ip>:5000"
echo ""
echo "Service Commands:"
echo "  - Status:  systemctl status mediamtx-config-editor"
echo "  - Stop:    systemctl stop mediamtx-config-editor"
echo "  - Start:   systemctl start mediamtx-config-editor"
echo "  - Restart: systemctl restart mediamtx-config-editor"
echo "  - Logs:    journalctl -u mediamtx-config-editor -f"
echo ""
echo "SECURITY NOTE:"
echo "  The config editor runs on port 5000 without authentication."
echo "  For production use, consider:"
echo "  1. Adding firewall rules to restrict access"
echo "  2. Using Caddy to add HTTPS and basic auth"
echo "  3. Only allowing access from specific IPs"
echo ""
