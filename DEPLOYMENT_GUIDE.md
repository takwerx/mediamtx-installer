# MediaMTX Streaming Server - Complete Deployment Guide

## 📋 Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Installation](#installation)
5. [Post-Installation](#post-installation)
6. [Web Config Editor](#web-config-editor)
7. [Enabling Encryption](#enabling-encryption)
8. [Streaming Protocols](#streaming-protocols)
9. [Troubleshooting](#troubleshooting)
10. [Security Best Practices](#security-best-practices)

---

## Overview

**⚡ No Manual Downloads Required!**

These scripts automatically download the latest MediaMTX from GitHub and deploy a proven production configuration. No manual YAML editing needed — manage everything through the web editor.

**What you get:**
- ✅ MediaMTX with custom production YAML (not the default config)
- ✅ FFmpeg for HLS transcoding with live/ path support
- ✅ Web-based configuration editor with user management
- ✅ Caddy reverse proxy with auto-HTTPS
- ✅ RTSPS and HLS encryption via Caddy's Let's Encrypt certificates
- ✅ Unattended-upgrade detection (waits for system updates)
- ✅ TAK Server Caddy coexistence (appends, doesn't overwrite)

---

## Prerequisites

### Server Requirements
- **OS**: Ubuntu 22.04
- **RAM**: Minimum 2GB (4GB+ recommended for HLS)
- **CPU**: 2+ cores recommended
- **Bandwidth**: High bandwidth VPS (video streaming intensive)
- **Storage**: 20GB+ (depends on recording needs)

### Before Installation
- ✅ Fresh VPS with root access
- ✅ Public IP address
- ✅ (Optional) Domain name with DNS A record pointing to server IP
- ✅ Ports 80, 443 accessible for Let's Encrypt (if using Caddy)

---

## Architecture

```
Internet Users
    ↓
[Caddy (443)] ← Let's Encrypt SSL → Web Editor (port 5000)
                                   ← Cert files used by MediaMTX

Direct Streaming (DNS resolves to server IP):
    → RTSP  (port 8554)  - unencrypted
    → RTSPS (port 8322)  - encrypted (after enabling)
    → HLS   (port 8888)  - encrypted (after enabling)
    → SRT   (port 8890)  - UDP, optional passphrase
```

**Key:** Caddy does NOT reverse proxy streams. It only:
1. Proxies the web editor (port 5000)
2. Obtains Let's Encrypt certificates
3. MediaMTX uses those certificate files directly for RTSPS/HLS

---

## Installation

### Three Scripts, Run in Order

#### Step 1: Install MediaMTX

```bash
git clone https://github.com/takwerx/mediamtx-installer.git
cd mediamtx-installer

chmod +x ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
sudo ./ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
```

**What it does:**
- Waits for unattended-upgrades if running
- Detects architecture (amd64, arm64, armv7)
- Downloads latest MediaMTX from GitHub
- Installs FFmpeg
- Deploys custom YAML with:
  - FFmpeg localhost user (127.0.0.1 only)
  - HLS viewer user with random 16-char password
  - Public teststream (no auth, teststream path only)
  - live/ path FFmpeg transcoding
  - Recording OFF by default
  - All encryption OFF (enable after Caddy)
- Creates systemd service
- Configures UFW firewall

**At the end, it displays the generated HLS viewer password. Save it!**

#### Step 2: Install Web Configuration Editor

```bash
chmod +x config-editor/Install_MediaMTX_Config_Editor.sh
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh
```

**What it does:**
- Installs Python3, pip, Flask, ruamel.yaml, requests, psutil
- Copies web editor to /opt/mediamtx-webeditor/
- Creates systemd service on port 5000
- Opens port 5000 in UFW

**Access:** `http://YOUR-SERVER-IP:5000`
**Default login:** admin / admin (change immediately!)

#### Step 3: Install Caddy (Optional - requires domain)

```bash
chmod +x ubuntu-22.04/Install_MediaMTX_Caddy.sh
sudo ./ubuntu-22.04/Install_MediaMTX_Caddy.sh
```

**What it does:**
- Asks for domain name (with confirmation)
- Installs Caddy (or detects existing installation)
- Appends MediaMTX config to Caddyfile (preserves TAK Server config)
- Creates HTTPS reverse proxy for web editor
- Waits for Let's Encrypt certificates
- Writes certificate paths into mediamtx.yml:
  - `rtspServerKey` / `rtspServerCert`
  - `hlsServerKey` / `hlsServerCert`
- Does NOT enable encryption (you do that in web editor)
- Restarts MediaMTX

**After Caddy:** Access web editor at `https://yourdomain.com`

---

## Post-Installation

### Verify Everything is Running

```bash
# MediaMTX
systemctl status mediamtx

# Web Editor
systemctl status mediamtx-webeditor

# Caddy (if installed)
systemctl status caddy
```

### First Steps

1. **Login to Web Editor** at `http://YOUR-IP:5000` (or `https://domain`)
2. **Change admin password** immediately
3. **Change HLS viewer password** in Users & Auth tab (or keep the auto-generated one)
4. **Add streaming users** for your agencies/teams via Users & Auth tab
5. **Test streaming** — publish to `rtsp://IP:8554/teststream` and view in VLC
6. **Enable encryption** when ready (see below)

---

## Web Config Editor

### Tabs

- **Dashboard** — System stats, active streams, bandwidth, disk usage
- **Users & Auth** — Add/edit/revoke MediaMTX streaming users, public access toggle
- **Protocols** — RTSP, HLS, SRT, WebRTC settings
- **Recording** — Enable/disable recording, set retention period
- **Styling** — Custom theme colors, agency logo, header text
- **Advanced YAML** — Direct YAML editing with search
- **Service Control** — Start/stop/restart, backups, restore

### User Management

The web editor manages two separate auth systems:

1. **Web Editor Login** (users.json) — who can access the web editor
   - Default: admin / admin
   - Change in web editor settings

2. **MediaMTX Streaming Users** (mediamtx.yml authInternalUsers) — who can publish/read streams
   - Managed in Users & Auth tab
   - Add users with agency/group labels
   - Set permissions (read, publish, playback)

### Built-in Users (do not delete)

- **FFmpeg localhost** — Internal user for FFmpeg transcoding (locked to 127.0.0.1)
- **HLS viewer** — Read-only user for browser HLS playback (password edit only)
- **Public teststream** — Anyone can view teststream path without auth

---

## Enabling Encryption

After Caddy installs certificates, enable encryption via the Web Editor:

### RTSPS (Encrypted RTSP on port 8322)

1. Web Editor → Advanced YAML
2. Search for `rtspEncryption`
3. Change `rtspEncryption: "no"` to `rtspEncryption: "optional"`
4. Save → Restart MediaMTX

**"optional"** means both RTSP (8554) and RTSPS (8322) work simultaneously.
**"strict"** means only RTSPS (8322) works.

### HLS Encryption (HTTPS on port 8888)

1. Web Editor → Advanced YAML
2. Search for `hlsEncryption`
3. Change `hlsEncryption: no` to `hlsEncryption: yes`
4. Save → Restart MediaMTX

After enabling, HLS is accessed at `https://domain:8888/streamname/`

---

## Streaming Protocols

### RTSP / RTSPS

**Publish (from drone or camera):**
```
rtsp://username:password@YOUR-IP:8554/live/uas1
```

The `live/` prefix triggers FFmpeg transcoding — creates a clean stream at:
```
rtsp://YOUR-IP:8554/uas1
```

**View in ATAK/VLC:**
```
rtsp://username:password@YOUR-IP:8554/uas1
rtsps://username:password@YOUR-IP:8322/uas1  (after enabling encryption)
```

### HLS (Browser Playback)

**View in browser:**
```
http://YOUR-IP:8888/uas1/
https://YOUR-DOMAIN:8888/uas1/  (after enabling HLS encryption)
```

HLS requires the `hlsviewer` credentials for authentication.

### SRT (Low Latency)

**Publish:**
```
srt://YOUR-IP:8890?streamid=publish:live/uas1
```

**View:**
```
srt://YOUR-IP:8890?streamid=read:uas1
```

SRT passphrase can be configured per-path via Web Editor → Advanced YAML.

---

## Troubleshooting

### MediaMTX Won't Start
```bash
journalctl -u mediamtx -n 50 --no-pager

# Common causes:
# - YAML syntax error (check Advanced YAML tab)
# - Encryption enabled but cert paths missing/wrong
# - Port conflict with another service
```

### Web Editor Won't Load
```bash
journalctl -u mediamtx-webeditor -n 50 --no-pager

# Common causes:
# - Missing Python packages (pip3 install Flask ruamel.yaml requests psutil)
# - Port 5000 blocked by firewall
# - mediamtx_config_editor.py not found
```

### Caddy Certificate Issues
```bash
journalctl -u caddy -n 50 --no-pager

# Common causes:
# - DNS not pointing to server
# - Ports 80/443 blocked
# - Let's Encrypt rate limit (wait 1 hour)
```

### RTSPS Not Working
```bash
# Check encryption setting
grep rtspEncryption /usr/local/etc/mediamtx.yml

# Check cert paths are filled in
grep rtspServerKey /usr/local/etc/mediamtx.yml
grep rtspServerCert /usr/local/etc/mediamtx.yml

# Verify cert files exist
ls -la /var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/
```

### FFmpeg Transcoding Not Working
```bash
# Check FFmpeg is installed
which ffmpeg

# Check the live/ path config exists
grep -A 3 "live/" /usr/local/etc/mediamtx.yml

# Check FFmpeg localhost user exists
grep -A 5 "127.0.0.1" /usr/local/etc/mediamtx.yml
```

---

## Security Best Practices

1. **Change web editor default password** immediately after install
2. **Change HLS viewer password** via Users & Auth tab
3. **Add SRT passphrases** for encrypted SRT streams
4. **Enable RTSPS** for encrypted RTSP connections
5. **Restrict web editor** by IP if not using Caddy:
   ```bash
   ufw allow from YOUR-IP to any port 5000
   ```
6. **Keep MediaMTX updated** — web editor has auto-update from GitHub releases

---

## Useful Commands

```bash
# Services
systemctl status mediamtx
systemctl status mediamtx-webeditor
systemctl status caddy

# Logs
journalctl -u mediamtx -f
journalctl -u mediamtx-webeditor -f
journalctl -u caddy -f

# Config
nano /usr/local/etc/mediamtx.yml
cat /etc/caddy/Caddyfile

# Restart
systemctl restart mediamtx
systemctl restart mediamtx-webeditor
systemctl reload caddy
```

---

**Last Updated:** February 2026
**Script Version:** 2.0
**Compatible MediaMTX Versions:** All (auto-detects latest)
