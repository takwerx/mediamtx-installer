#!/bin/bash

# Caddy Setup Script for MediaMTX (Ubuntu 22.04)
# Provides automatic HTTPS with Let's Encrypt for MediaMTX services

set -e

echo "=========================================="
echo "Caddy Setup for MediaMTX"
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
    echo "Please run the MediaMTX installation script first."
    exit 1
fi

echo "=========================================="
echo "Step 1: Domain Configuration"
echo "=========================================="
echo ""
echo "IMPORTANT: Before continuing, ensure:"
echo "  1. You have a domain name"
echo "  2. DNS A record points to this server's public IP"
echo "  3. Ports 80 and 443 are accessible (for Let's Encrypt)"
echo ""

read -p "Enter your domain name (e.g., video.example.com): " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo "Domain name is required!"
    exit 1
fi

echo ""
echo "Domain configured: $DOMAIN"

echo ""
echo "=========================================="
echo "Step 2: Installing Caddy"
echo "=========================================="

# Install Caddy using official repository
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy

echo "Caddy installed successfully"

echo ""
echo "=========================================="
echo "Step 3: Configuring Firewall (UFW)"
echo "=========================================="

# Open HTTP and HTTPS ports for Caddy
ufw allow 80/tcp
ufw allow 443/tcp

echo "Firewall configured (ports 80, 443 opened)"

echo ""
echo "=========================================="
echo "Step 4: Creating Caddyfile"
echo "=========================================="

# Check if Caddyfile exists
if [ -f /etc/caddy/Caddyfile ]; then
    # Backup existing Caddyfile
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.backup.$(date +%Y%m%d_%H%M%S)
    echo "Existing Caddyfile backed up"
    
    # Check if MediaMTX config already exists
    if grep -q "$DOMAIN" /etc/caddy/Caddyfile; then
        echo "WARNING: Configuration for $DOMAIN already exists in Caddyfile"
        read -p "Do you want to replace it? [y/N]: " REPLACE
        if [[ ! "$REPLACE" =~ ^[Yy]$ ]]; then
            echo "Aborted. Caddyfile not modified."
            exit 1
        fi
        # Remove old configuration
        sed -i "/$DOMAIN {/,/^}/d" /etc/caddy/Caddyfile
    fi
    
    # Append MediaMTX configuration
    cat >> /etc/caddy/Caddyfile <<EOF

# MediaMTX Configuration
$DOMAIN {
    # HLS streams
    reverse_proxy /hls/* localhost:8888
    
    # WebRTC HTTP
    reverse_proxy /webrtc/* localhost:8889
    
    # API (if enabled)
    reverse_proxy /api/* localhost:9997
    
    # Metrics (if enabled)
    reverse_proxy /metrics localhost:9998
    
    # Default page
    respond / "MediaMTX Server - Use appropriate endpoints for streaming" 200
}
EOF

else
    # Create new Caddyfile
    cat > /etc/caddy/Caddyfile <<EOF
# MediaMTX Configuration
$DOMAIN {
    # HLS streams
    reverse_proxy /hls/* localhost:8888
    
    # WebRTC HTTP
    reverse_proxy /webrtc/* localhost:8889
    
    # API (if enabled)
    reverse_proxy /api/* localhost:9997
    
    # Metrics (if enabled)
    reverse_proxy /metrics localhost:9998
    
    # Default page
    respond / "MediaMTX Server - Use appropriate endpoints for streaming" 200
}
EOF
fi

echo "Caddyfile configured for $DOMAIN"

echo ""
echo "=========================================="
echo "Step 5: Starting Caddy"
echo "=========================================="

# Enable and start Caddy
systemctl enable caddy
systemctl restart caddy

# Wait for Caddy to get certificate
echo "Waiting for Caddy to obtain Let's Encrypt certificate..."
sleep 10

# Check Caddy status
if systemctl is-active --quiet caddy; then
    echo "Caddy is running successfully"
else
    echo "ERROR: Caddy failed to start"
    echo "Check logs: journalctl -u caddy -n 50"
    exit 1
fi

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "MediaMTX is now accessible via HTTPS:"
echo "  - Domain: https://$DOMAIN"
echo ""
echo "HTTPS Endpoints:"
echo "  - HLS:     https://$DOMAIN/hls/[stream-name]/index.m3u8"
echo "  - WebRTC:  https://$DOMAIN/webrtc/?stream=[stream-name]"
echo ""
echo "Direct Streaming (no HTTPS - for apps like VLC/OBS):"
echo "  - RTSP:    rtsp://<server-ip>:8554/[stream-name]"
echo "  - RTMP:    rtmp://<server-ip>:1935/[stream-name]"
echo "  - SRT:     srt://<server-ip>:8890?streamid=[stream-name]"
echo ""
echo "Certificate Information:"
echo "  - Let's Encrypt certificate auto-renewed by Caddy"
echo "  - No cronjobs needed!"
echo "  - Certificate location: /var/lib/caddy/.local/share/caddy/certificates/"
echo ""
echo "Useful Commands:"
echo "  - Caddy status:  systemctl status caddy"
echo "  - Caddy logs:    journalctl -u caddy -f"
echo "  - Reload Caddy:  systemctl reload caddy"
echo "  - Test config:   caddy validate --config /etc/caddy/Caddyfile"
echo ""
echo "Note: RTSP/RTMP/SRT still use direct IP access (not through Caddy)"
echo "      Only HLS and WebRTC benefit from HTTPS via Caddy"
echo ""
