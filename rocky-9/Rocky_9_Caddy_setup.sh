#!/bin/bash

# Caddy Setup Script for MediaMTX (Rocky Linux 9)
# Provides automatic HTTPS with Let's Encrypt for MediaMTX services

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

# Install Caddy using DNF (official Caddy repo), but only when there is none (ops #1354, same as the Ubuntu script).
# A Caddy that is already here may serve TAK Server or other sites, and has saved certificates. "dnf install caddy" on it
# would upgrade it and restart the service, and could replace a build that came from another source.
# >>> caddy_install_guard
if command -v caddy > /dev/null 2>&1 || rpm -q caddy > /dev/null 2>&1; then
    echo "Caddy is already installed ($(caddy version 2>/dev/null | head -1)), so it is left as it is."
else
    dnf install -y 'dnf-command(copr)'
    dnf copr enable -y @caddy/caddy
    dnf install -y caddy
    echo "Caddy installed successfully"
fi
# <<< caddy_install_guard

echo ""
echo "=========================================="
echo "Step 3: Configuring Firewall"
echo "=========================================="

# Open HTTP and HTTPS ports for Caddy. Runtime + permanent, no --reload: a
# reload kills local multicast senders.
for port in 80/tcp 443/tcp; do
    firewall-cmd --zone=public --add-port=$port
    firewall-cmd --zone=public --permanent --add-port=$port
done

echo "Firewall configured (ports 80, 443 opened)"

echo ""
echo "=========================================="
echo "Step 4: Creating Caddyfile"
echo "=========================================="

MEDIAMTX_CADDY_BLOCK="# MediaMTX Configuration
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
    respond / \"MediaMTX Server - Use appropriate endpoints for streaming\" 200
}"

# Only this domain's block is added or replaced. The old file is backed up and put back if
# the new one does not validate (ops #1317).
CADDYFILE_RC=0
caddy_configure_site /etc/caddy/Caddyfile "$DOMAIN" "$MEDIAMTX_CADDY_BLOCK" || CADDYFILE_RC=$?
if [ "$CADDYFILE_RC" -eq 2 ]; then
    echo "Aborted. Caddyfile not modified."
    exit 1
elif [ "$CADDYFILE_RC" -ne 0 ]; then
    exit 1
fi

if ! caddy_validate_or_restore /etc/caddy/Caddyfile "$CADDYFILE_BACKUP"; then
    echo "Check: caddy validate --config /etc/caddy/Caddyfile"
    exit 1
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
