#!/bin/bash

# MediaMTX Web Configuration Editor - Installation Script (Ubuntu 22.04)
# Installs Flask-based web editor for managing MediaMTX
# v2.0 - Adds psutil, requests dependencies

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
if ! command -v mediamtx &> /dev/null || [ ! -f /usr/local/etc/mediamtx.yml ]; then
    echo "ERROR: MediaMTX is not installed!"
    echo "Please run the MediaMTX installer first:"
    echo "  sudo ./Ubuntu_22_04_MediaMTX_install.sh"
    exit 1
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

apt-get update -qq > /dev/null 2>&1
apt-get install -y python3 python3-pip python3-psutil > /dev/null 2>&1 || apt-get install -y python3 python3-pip python3-psutil
echo "✓ Python3 and pip installed"

# Install required Python packages
echo "Installing Flask and dependencies..."
pip3 install Flask ruamel.yaml requests psutil 2>&1 | grep -v "already satisfied" || true
echo "✓ Python packages installed (Flask, ruamel.yaml, requests, psutil)"

echo ""
echo "=========================================="
echo "Step 2: Installing Web Editor Files"
echo "=========================================="

# Create web editor directory
WEB_EDITOR_DIR="/opt/mediamtx-webeditor"
mkdir -p "$WEB_EDITOR_DIR"
mkdir -p "$WEB_EDITOR_DIR/backups"
mkdir -p "$WEB_EDITOR_DIR/recordings"
mkdir -p "$WEB_EDITOR_DIR/test_videos"

# Find the Python file
if [ -f "./config-editor/mediamtx_config_editor.py" ]; then
    cp ./config-editor/mediamtx_config_editor.py "$WEB_EDITOR_DIR/"
    echo "✓ Web editor copied from config-editor/"
elif [ -f "./mediamtx_config_editor.py" ]; then
    cp ./mediamtx_config_editor.py "$WEB_EDITOR_DIR/"
    echo "✓ Web editor copied from current directory"
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

echo ""
echo "=========================================="
echo "Step 3: Creating systemd Service"
echo "=========================================="

cat > /etc/systemd/system/mediamtx-webeditor.service <<EOF
[Unit]
Description=MediaMTX Web Configuration Editor
After=network.target mediamtx.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/mediamtx-webeditor/mediamtx_config_editor.py
WorkingDirectory=/opt/mediamtx-webeditor
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mediamtx-webeditor
systemctl start mediamtx-webeditor

echo "✓ Web editor service created and started"

echo ""
echo "=========================================="
echo "Step 4: Configuring Firewall"
echo "=========================================="

# Open web editor port
ufw allow 5000/tcp > /dev/null 2>&1
echo "✓ Port 5000 opened for web editor"

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
    echo "  Default Login:"
    echo "    Username: admin"
    echo "    Password: admin"
    echo "    (Change after first login!)"
    echo ""
    echo "  Service Commands:"
    echo "    Status:  systemctl status mediamtx-webeditor"
    echo "    Logs:    journalctl -u mediamtx-webeditor -f"
    echo "    Restart: systemctl restart mediamtx-webeditor"
    echo ""
    echo "  Next Steps:"
    echo "    1. Login and change default password"
    echo "    2. Configure streaming users in Users & Auth tab"
    echo "    3. Install Caddy for HTTPS (optional)"
    echo ""
else
    echo ""
    echo "WARNING: Web editor service may not have started correctly."
    echo "Check logs: journalctl -u mediamtx-webeditor -n 50"
    echo ""
fi
