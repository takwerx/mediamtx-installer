#!/bin/bash

# Caddy Setup Script for MediaMTX (Ubuntu 22.04)
# Provides HTTPS via Let's Encrypt, web editor proxy, and SSL cert paths for RTSPS/HLS
# v2.0 - Single domain, TAK Server coexistence, cert path injection
#
# NOTE: This script fills in certificate paths in mediamtx.yml but does NOT
# enable encryption. Enable RTSPS/HLS encryption via the Web Editor when ready.

set -e

echo "=========================================="
echo "Caddy Setup for MediaMTX v2.0"
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
    echo "Please run the MediaMTX installer first."
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

# ==========================================
# Step 1: Domain Configuration
# ==========================================
echo "=========================================="
echo "Step 1: Domain Configuration"
echo "=========================================="
echo ""
echo "Enter the domain name for your MediaMTX server."
echo "This will be used for:"
echo "  - HTTPS access to the Web Editor"
echo "  - SSL certificates for RTSPS and HLS encryption"
echo ""
echo "Make sure DNS A record points to this server's IP!"
echo ""

# Domain input with confirmation
DOMAIN=""
DOMAIN_CONFIRM=""

while [ "$DOMAIN" != "$DOMAIN_CONFIRM" ] || [ -z "$DOMAIN" ]; do
    read -p "Enter domain (e.g., video.yourdomain.com): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo "Domain cannot be empty!"
        continue
    fi
    read -p "Confirm domain: " DOMAIN_CONFIRM
    if [ "$DOMAIN" != "$DOMAIN_CONFIRM" ]; then
        echo "Domains do not match! Try again."
        echo ""
    fi
done

echo ""
echo "✓ Domain: $DOMAIN"

# ==========================================
# Step 2: Install Caddy
# ==========================================
echo ""
echo "=========================================="
echo "Step 2: Installing Caddy"
echo "=========================================="

# Check if Caddy is already installed (e.g., for TAK Server)
if command -v caddy &> /dev/null; then
    echo "✓ Caddy is already installed"
    CADDY_EXISTING=true
    
    # Check if it's running
    if systemctl is-active --quiet caddy; then
        echo "  Caddy service is running (may be serving TAK Server or other services)"
    fi
else
    CADDY_EXISTING=false
    
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl > /dev/null 2>&1
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq > /dev/null 2>&1
    apt-get install -y caddy > /dev/null 2>&1
    echo "✓ Caddy installed"
fi

# ==========================================
# Step 3: Configure Firewall
# ==========================================
echo ""
echo "=========================================="
echo "Step 3: Configuring Firewall"
echo "=========================================="

ufw allow 80/tcp > /dev/null 2>&1
ufw allow 443/tcp > /dev/null 2>&1
echo "✓ Ports 80 and 443 opened"

# ==========================================
# Step 4: Configure Caddyfile
# ==========================================
echo ""
echo "=========================================="
echo "Step 4: Configuring Caddyfile"
echo "=========================================="

MEDIAMTX_CADDY_BLOCK="# MediaMTX Web Configuration Editor
$DOMAIN {
    # Reverse proxy to MediaMTX Config Editor
    reverse_proxy localhost:5000
}"

if [ -f /etc/caddy/Caddyfile ]; then
    # Backup existing Caddyfile
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.backup.$(date +%Y%m%d_%H%M%S)
    echo "✓ Existing Caddyfile backed up"
    
    # Check if this domain already exists in the Caddyfile
    if grep -q "$DOMAIN" /etc/caddy/Caddyfile; then
        echo "WARNING: $DOMAIN already exists in Caddyfile"
        read -p "Replace existing config for this domain? [y/N]: " REPLACE
        if [[ ! "$REPLACE" =~ ^[Yy]$ ]]; then
            echo "Skipping Caddyfile modification."
        else
            # Remove old block for this domain
            # Use awk to remove the domain block
            awk -v domain="$DOMAIN" '
                $0 ~ domain " {" { skip=1; next }
                skip && /^}/ { skip=0; next }
                skip { next }
                { print }
            ' /etc/caddy/Caddyfile > /tmp/Caddyfile.tmp
            mv /tmp/Caddyfile.tmp /etc/caddy/Caddyfile
            
            # Append new config
            echo "" >> /etc/caddy/Caddyfile
            echo "$MEDIAMTX_CADDY_BLOCK" >> /etc/caddy/Caddyfile
            echo "✓ Replaced existing config for $DOMAIN"
        fi
    else
        # Append MediaMTX config to existing Caddyfile (TAK Server coexistence)
        echo "" >> /etc/caddy/Caddyfile
        echo "$MEDIAMTX_CADDY_BLOCK" >> /etc/caddy/Caddyfile
        echo "✓ MediaMTX config appended to existing Caddyfile"
        
        if [ "$CADDY_EXISTING" = true ]; then
            echo "  (Existing services like TAK Server are preserved)"
        fi
    fi
else
    # Create new Caddyfile
    echo "$MEDIAMTX_CADDY_BLOCK" > /etc/caddy/Caddyfile
    echo "✓ New Caddyfile created"
fi

# Validate Caddyfile
echo ""
echo "Validating Caddyfile..."
if caddy validate --config /etc/caddy/Caddyfile 2>/dev/null; then
    echo "✓ Caddyfile is valid"
else
    echo "ERROR: Caddyfile validation failed!"
    echo "Check: caddy validate --config /etc/caddy/Caddyfile"
    exit 1
fi

# ==========================================
# Step 5: Start/Restart Caddy
# ==========================================
echo ""
echo "=========================================="
echo "Step 5: Starting Caddy"
echo "=========================================="

systemctl enable caddy > /dev/null 2>&1
systemctl restart caddy

echo "Waiting for Caddy to obtain Let's Encrypt certificate..."
sleep 15

if systemctl is-active --quiet caddy; then
    echo "✓ Caddy is running"
else
    echo "ERROR: Caddy failed to start"
    echo "Check logs: journalctl -u caddy -n 50"
    exit 1
fi

# ==========================================
# Step 6: Configure MediaMTX Certificate Paths
# ==========================================
echo ""
echo "=========================================="
echo "Step 6: Configuring Certificate Paths"
echo "=========================================="

CERT_BASE="/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory"
CERT_DIR="$CERT_BASE/$DOMAIN"
CERT_FILE="$CERT_DIR/$DOMAIN.crt"
KEY_FILE="$CERT_DIR/$DOMAIN.key"

# Wait up to 60 seconds for certificates
echo "Looking for Let's Encrypt certificates..."
WAIT_COUNT=0
while [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; do
    if [ $WAIT_COUNT -ge 60 ]; then
        echo ""
        echo "WARNING: Certificates not found after 60 seconds."
        echo "This might be due to:"
        echo "  - Let's Encrypt rate limiting"
        echo "  - DNS not pointing to this server"
        echo "  - Ports 80/443 not accessible"
        echo ""
        echo "Certificate paths (add manually later):"
        echo "  Key:  $KEY_FILE"
        echo "  Cert: $CERT_FILE"
        echo ""
        echo "You can re-run this script after fixing the issue."
        SKIP_CERTS=true
        break
    fi
    sleep 1
    ((WAIT_COUNT++))
done

if [ "$SKIP_CERTS" != "true" ]; then
    echo "✓ Certificates found!"
    echo "  Key:  $KEY_FILE"
    echo "  Cert: $CERT_FILE"
    
    # Backup MediaMTX config
    cp /usr/local/etc/mediamtx.yml /usr/local/etc/mediamtx.yml.backup.$(date +%Y%m%d_%H%M%S)
    echo "✓ MediaMTX config backed up"
    
    # Update RTSP certificate paths
    sed -i "s|^rtspServerKey:.*|rtspServerKey: $KEY_FILE|" /usr/local/etc/mediamtx.yml
    sed -i "s|^rtspServerCert:.*|rtspServerCert: $CERT_FILE|" /usr/local/etc/mediamtx.yml
    
    # Update HLS certificate paths
    sed -i "s|^hlsServerKey:.*|hlsServerKey: $KEY_FILE|" /usr/local/etc/mediamtx.yml
    sed -i "s|^hlsServerCert:.*|hlsServerCert: $CERT_FILE|" /usr/local/etc/mediamtx.yml
    
    # Enable encryption
    sed -i 's/^rtspEncryption: .*/rtspEncryption: "optional"/' /usr/local/etc/mediamtx.yml
    sed -i 's/^hlsEncryption: .*/hlsEncryption: yes/' /usr/local/etc/mediamtx.yml
    
    echo "✓ Certificate paths written to mediamtx.yml"
    echo "✓ RTSPS encryption enabled (optional - both RTSP and RTSPS work)"
    echo "✓ HLS encryption enabled"
    
    # Restart MediaMTX to pick up config changes
    systemctl restart mediamtx
    sleep 3
    
    if systemctl is-active --quiet mediamtx; then
        echo "✓ MediaMTX restarted successfully"
    else
        echo "WARNING: MediaMTX may have issues. Check: journalctl -u mediamtx -n 50"
    fi
fi

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "  Web Editor: https://$DOMAIN"
echo "  (Caddy provides HTTPS automatically)"
echo ""
echo "  Streaming (direct, no Caddy):"
echo "    RTSP:  rtsp://$DOMAIN:8554/[stream]"
echo "    RTSPS: rtsps://$DOMAIN:8322/[stream]  (after enabling encryption)"
echo "    HLS:   https://$DOMAIN:8888/[stream]/  (after enabling encryption)"
echo "    SRT:   srt://$DOMAIN:8890?streamid=[stream]"
echo ""
echo "  To enable RTSPS encryption:"
echo "    1. Open Web Editor → Advanced YAML"
echo "    2. Search for rtspEncryption"
echo "    3. Change to: rtspEncryption: \"optional\""
echo "    4. Save and restart MediaMTX"
echo ""
echo "  To enable HLS encryption:"
echo "    1. Open Web Editor → Advanced YAML"
echo "    2. Search for hlsEncryption"
echo "    3. Change to: hlsEncryption: yes"
echo "    4. Save and restart MediaMTX"
echo ""
echo "  Caddy Commands:"
echo "    Status:  systemctl status caddy"
echo "    Logs:    journalctl -u caddy -f"
echo "    Reload:  systemctl reload caddy"
echo ""
