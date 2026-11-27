#!/bin/bash

# Caddy Setup Script for MediaMTX (Ubuntu 22.04)
# Provides HTTPS via Let's Encrypt, web editor proxy, SSL cert paths for RTSPS/HLS,
# and automatically enables RTSPS (optional) and HLS encryption.

set -e

# >>> caddy_site_functions
# Caddyfile edits that touch only this MediaMTX site (ops #1317). Identical in the Ubuntu and
# Rocky scripts; tests/test_caddy_setup_ops1317.py runs this text and checks both copies match.

# caddy_remove_site SRC DST DOMAIN
# Copies SRC to DST without the site block whose address list is exactly DOMAIN (also
# https://DOMAIN and DOMAIN:443). The block ends where its own braces close, never at the
# first "}" in column 0 and never at the end of the file. Nothing else is touched.
# Returns 0 removed, 3 no such site, 4 DOMAIN shares a block with other addresses,
# 5 braces do not balance. On 3, 4 and 5 DST is not written.
caddy_remove_site() {
    local src="$1" dst="$2" domain="$3" rc=0
    CADDY_SITE="$domain" awk '
    function strip(s) {
        gsub(/"[^"]*"/, "", s); gsub(/`[^`]*`/, "", s)
        sub(/(^|[ \t])#.*/, "", s)
        return s
    }
    function count(s, ch,   t) { t = s; return gsub(ch, "", t) }
    BEGIN { want = tolower(ENVIRON["CADDY_SITE"]); depth = 0; skipping = 0; removed = 0; shared = 0; n = 0 }
    {
        code = strip($0)
        if (skipping) {
            depth += count(code, "\\{") - count(code, "\\}")
            if (depth <= 0) { skipping = 0; depth = 0 }
            next
        }
        if (depth == 0 && code ~ /^[ \t]*[^ \t{}][^{}]*\{[ \t]*$/) {
            head = code; sub(/\{[ \t]*$/, "", head)
            m = split(head, parts, /[ \t,]+/)
            hit = 0; others = 0
            for (i = 1; i <= m; i++) {
                a = tolower(parts[i])
                if (a == "") continue
                sub(/^https:\/\//, "", a); sub(/:443$/, "", a)
                if (a == want) hit = 1; else others = 1
            }
            if (hit && others) shared = 1
            if (hit && !others) {
                if (n > 0 && out[n] ~ /^# MediaMTX (Web Configuration Editor|Configuration)[ \t]*$/) n--
                depth = count(code, "\\{") - count(code, "\\}")
                if (depth > 0) skipping = 1; else depth = 0
                removed++
                next
            }
        }
        depth += count(code, "\\{") - count(code, "\\}")
        if (depth < 0) depth = 0
        out[++n] = $0
    }
    END {
        if (skipping) exit 5
        if (shared) exit 4
        if (!removed) exit 3
        for (i = 1; i <= n; i++) print out[i]
    }' "$src" > "$dst" || rc=$?
    if [ "$rc" -ne 0 ]; then rm -f "$dst"; fi
    return "$rc"
}

# caddy_configure_site CADDYFILE DOMAIN BLOCK
# Adds BLOCK (the site block for DOMAIN) to CADDYFILE. Backs the file up first and sets
# CADDYFILE_BACKUP to the backup. If DOMAIN already has its own block, asks before replacing
# it (answer read from stdin). Returns 0 done, 2 left as it was because the answer was no,
# 1 refused (the Caddyfile is not changed).
caddy_configure_site() {
    local cf="$1" domain="$2" block="$3" tmp rc=0 reply=""
    CADDYFILE_BACKUP=""
    if [[ ! "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
        echo "ERROR: '$domain' is not a valid domain name. Caddyfile not changed."
        return 1
    fi
    if [ ! -f "$cf" ]; then
        mkdir -p "$(dirname "$cf")"
        printf '%s\n' "$block" > "$cf"
        echo "✓ New Caddyfile created"
        return 0
    fi
    CADDYFILE_BACKUP="$cf.backup.$(date +%Y%m%d_%H%M%S)"
    cp -p "$cf" "$CADDYFILE_BACKUP"
    echo "✓ Existing Caddyfile backed up to $CADDYFILE_BACKUP"
    tmp=$(mktemp)
    caddy_remove_site "$cf" "$tmp" "$domain" || rc=$?
    case "$rc" in
        0)
            echo "WARNING: $domain already has its own site block in the Caddyfile"
            read -r -p "Replace the block for $domain? Other sites are not touched. [y/N]: " reply || true
            if [[ ! "$reply" =~ ^[Yy]$ ]]; then
                rm -f "$tmp"
                echo "Caddyfile not changed."
                return 2
            fi
            # cat, not mv: keeps the owner and mode Caddy needs to read the file
            cat "$tmp" > "$cf"
            rm -f "$tmp"
            { echo ""; echo "$block"; } >> "$cf"
            echo "✓ Replaced the block for $domain (other sites untouched)"
            ;;
        3)
            rm -f "$tmp"
            { echo ""; echo "$block"; } >> "$cf"
            echo "✓ Added $domain to the Caddyfile (other sites untouched)"
            ;;
        4)
            rm -f "$tmp"
            echo "ERROR: $domain sits in a site block together with other addresses."
            echo "This script will not edit that block. Caddyfile not changed."
            echo "Edit /etc/caddy/Caddyfile by hand, then run this script again."
            return 1
            ;;
        *)
            rm -f "$tmp"
            echo "ERROR: could not read the Caddyfile structure (braces do not balance)."
            echo "Caddyfile not changed. Backup: $CADDYFILE_BACKUP"
            return 1
            ;;
    esac
    return 0
}

# caddy_validate_or_restore CADDYFILE BACKUP
# Runs caddy validate. If it fails, puts BACKUP back and returns 1. Run it before any restart.
caddy_validate_or_restore() {
    local cf="$1" backup="$2" out
    if out=$(caddy validate --config "$cf" --adapter caddyfile 2>&1); then
        echo "✓ Caddyfile is valid"
        return 0
    fi
    echo "ERROR: Caddyfile validation failed:"
    echo "$out" | tail -n 15
    if [ -n "$backup" ] && [ -f "$backup" ]; then
        cat "$backup" > "$cf"
        echo "✓ Restored your previous Caddyfile from $backup. Caddy was not restarted."
    fi
    return 1
}
# <<< caddy_site_functions

# >>> wait_for_certs
# wait_for_certs CERT KEY: waits up to CERT_WAIT_SECONDS (default 60) for Caddy to write both
# files. Returns 0 when both exist, 1 when the time ran out. (The old loop counted with a bare
# post-increment in double parentheses. That returns 1 while the count is 0 and ends a "set -e"
# script on the first wait: ops #1317.)
wait_for_certs() {
    local waited=0 limit="${CERT_WAIT_SECONDS:-60}"
    while [ ! -f "$1" ] || [ ! -f "$2" ]; do
        if [ "$waited" -ge "$limit" ]; then
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 0
}
# <<< wait_for_certs

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

CADDYFILE_RC=0
caddy_configure_site /etc/caddy/Caddyfile "$DOMAIN" "$MEDIAMTX_CADDY_BLOCK" || CADDYFILE_RC=$?
if [ "$CADDYFILE_RC" -eq 1 ]; then
    exit 1
fi
if [ "$CADDYFILE_RC" -eq 0 ] && [ "$CADDY_EXISTING" = true ]; then
    echo "  (Existing services like TAK Server are preserved)"
fi

# Validate Caddyfile before Caddy restarts. If it fails, the previous file is put back.
echo ""
echo "Validating Caddyfile..."
if ! caddy_validate_or_restore /etc/caddy/Caddyfile "$CADDYFILE_BACKUP"; then
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
SKIP_CERTS=false
if ! wait_for_certs "$CERT_FILE" "$KEY_FILE"; then
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
fi

if [ "$SKIP_CERTS" != "true" ]; then
    echo "✓ Certificates found!"
    echo "  Key:  $KEY_FILE"
    echo "  Cert: $CERT_FILE"
    
    # Backup MediaMTX config
    cp /usr/local/etc/mediamtx.yml /usr/local/etc/mediamtx.yml.backup.$(date +%Y%m%d_%H%M%S)
    echo "✓ MediaMTX config backed up"
    
    # Update RTSP certificate paths (remove any indented continuation lines first)
    sed -i '/^rtspServerKey:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i '/^rtspServerCert:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i "s|^rtspServerKey:.*|rtspServerKey: $KEY_FILE|" /usr/local/etc/mediamtx.yml
    sed -i "s|^rtspServerCert:.*|rtspServerCert: $CERT_FILE|" /usr/local/etc/mediamtx.yml
    
    # Update HLS certificate paths
    sed -i '/^hlsServerKey:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i '/^hlsServerCert:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i "s|^hlsServerKey:.*|hlsServerKey: $KEY_FILE|" /usr/local/etc/mediamtx.yml
    sed -i "s|^hlsServerCert:.*|hlsServerCert: $CERT_FILE|" /usr/local/etc/mediamtx.yml
    
    # Update RTMP certificate paths (for RTMPS support)
    sed -i '/^rtmpServerKey:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i '/^rtmpServerCert:/{ n; /^  /d }' /usr/local/etc/mediamtx.yml
    sed -i "s|^rtmpServerKey:.*|rtmpServerKey: $KEY_FILE|" /usr/local/etc/mediamtx.yml
    sed -i "s|^rtmpServerCert:.*|rtmpServerCert: $CERT_FILE|" /usr/local/etc/mediamtx.yml
    
    # Enable encryption
    sed -i 's/^rtspEncryption: .*/rtspEncryption: "optional"/' /usr/local/etc/mediamtx.yml
    sed -i 's/^hlsEncryption: .*/hlsEncryption: yes/' /usr/local/etc/mediamtx.yml
    
    echo "✓ Certificate paths written to mediamtx.yml"
    echo "✓ RTSPS encryption enabled (optional - both RTSP and RTSPS work)"
    echo "✓ HLS encryption enabled"
    echo "✓ RTMP certificates configured (enable RTMPS via Web Editor → Protocols)"
    
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
echo "    RTMP:  rtmp://$DOMAIN:1935/[stream]"
echo "    RTMPS: rtmps://$DOMAIN:1936/[stream]  (after enabling encryption)"
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
