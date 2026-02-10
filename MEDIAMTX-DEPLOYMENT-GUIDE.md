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

Unlike TAK Server scripts (where you must manually download the TAK Server package), these MediaMTX scripts **automatically download the latest version from GitHub**. Just run the script and it handles everything!

This deployment suite provides automated installation scripts for MediaMTX streaming server with:
- ✅ MediaMTX with custom production YAML (not the default config)
- ✅ FFmpeg for HLS transcoding with live/ path support
- ✅ Web-based configuration editor with user management
- ✅ Caddy reverse proxy with auto-HTTPS
- ✅ RTSPS and HLS encryption via Caddy's Let's Encrypt certificates
- ✅ Unattended-upgrade detection (waits for system updates)
- ✅ TAK Server Caddy coexistence (appends, doesn't overwrite)

**Why separate VPS for video?**
- Video streaming requires high bandwidth
- Prevents impact on TAK Server reliability
- Easier to scale independently
- Better cost optimization (use cheaper high-bandwidth VPS for video)

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

### Recommended VPS Providers
- **DigitalOcean** - Excellent bandwidth
- **Vultr** - Good price/performance for video
- **Linode** - Reliable bandwidth allocation
- **Hetzner** - European locations with great bandwidth

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

### Components
1. **MediaMTX** - Core streaming server (native install, auto-downloaded)
2. **FFmpeg** - HLS transcoding (installed automatically)
3. **Web Config Editor** - Python Flask app for configuration management
4. **Caddy** - Reverse proxy for HTTPS and certificate provider (optional)

**Key:** Caddy does NOT reverse proxy streams. It only:
1. Proxies the web editor (port 5000)
2. Obtains Let's Encrypt certificates
3. MediaMTX uses those certificate files directly for RTSPS/HLS

---

## Installation

### Download Scripts

> **Note:** If not running as root, your user account must have sudo privileges. All installation commands require root access.

```bash
git clone https://github.com/takwerx/mediamtx-installer.git
cd mediamtx-installer
```

**Make scripts executable:**
```bash
chmod +x ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
chmod +x config-editor/Install_MediaMTX_Config_Editor.sh
chmod +x ubuntu-22.04/Ubuntu_22_04_Install_MediaMTX_Caddy.sh
```

---

### Step 1: Install MediaMTX

```bash
sudo ./ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
```

**During install:**
- No prompts — fully automated
- Waits for unattended-upgrades if running
- Detects architecture (amd64, arm64, armv7)

**Completion time:** ~5 minutes

**What it installs:**
- Latest MediaMTX binary from GitHub
- FFmpeg for HLS transcoding
- Custom production YAML with:
  - FFmpeg localhost user (127.0.0.1 only, no auth)
  - HLS viewer user with random 16-character password
  - Public teststream user (no auth, teststream path only)
  - live/ path FFmpeg transcoding
  - Recording OFF by default
  - All encryption OFF (enable after Caddy)
- systemd service (auto-start on boot)
- UFW firewall rules

**⚠️ Save the HLS viewer password displayed at the end of installation!**

**Verify installation:**
```bash
systemctl status mediamtx
```

**Test stream (no auth required):**
```bash
ffplay rtsp://YOUR-IP:8554/teststream
# Or open in VLC: rtsp://YOUR-IP:8554/teststream
```

---

### Step 2: Install Web Configuration Editor

```bash
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh
```

> **Important:** The `mediamtx_config_editor.py` file must be in `./config-editor/` or the current directory.

**What it installs:**
- Python3, pip, Flask, ruamel.yaml, requests, psutil
- Web editor application at /opt/mediamtx-webeditor/
- systemd service on port 5000
- UFW rule for port 5000

**Access:** `http://YOUR-IP:5000`
**Default login:** admin / admin

**⚠️ Change the admin password immediately after first login!**

---

### Step 3: Install Caddy SSL (Optional)

**Prerequisites:**
- Domain name (e.g., video.example.com)
- DNS A record pointing to your server IP
- Ports 80 and 443 accessible
- MediaMTX and Web Editor installed and working

```bash
sudo ./ubuntu-22.04/Ubuntu_22_04_Install_MediaMTX_Caddy.sh
```

**During setup:**
- Enter your domain name
- Confirm domain name

**What it does:**
- Installs Caddy (or detects existing installation)
- Appends MediaMTX config to Caddyfile (preserves TAK Server config if present)
- Creates HTTPS reverse proxy for web editor
- Waits for Let's Encrypt certificates
- Writes certificate paths into mediamtx.yml:
  - `rtspServerKey` / `rtspServerCert`
  - `hlsServerKey` / `hlsServerCert`
- Does NOT enable encryption (you do that in Web Editor when ready)
- Restarts MediaMTX to pick up config changes

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
3. **Add streaming users** for your agencies/teams via Users & Auth tab
4. **Test streaming** — publish to `rtsp://IP:8554/teststream` and view in VLC
5. **Enable encryption** when ready (see below)

---

## Web Config Editor

### Access
```
http://YOUR-SERVER-IP:5000
```
Or after Caddy: `https://yourdomain.com`

### Tabs

- **Dashboard** — System stats, active streams, bandwidth, disk usage
- **Users & Auth** — Add/edit/revoke MediaMTX streaming users, public access toggle
- **Protocols** — RTSP, HLS, SRT, WebRTC settings
- **Recording** — Enable/disable recording, set retention period
- **Styling** — Custom theme colors, agency logo, header text
- **Advanced YAML** — Direct YAML editing with search
- **Service Control** — Start/stop/restart, backups, restore

### Two Separate Auth Systems

The web editor manages two independent login systems:

1. **Web Editor Login** (users.json) — who can access the web editor
   - Default: admin / admin
   - Change in web editor settings

2. **MediaMTX Streaming Users** (mediamtx.yml authInternalUsers) — who can publish/read streams
   - Managed in Users & Auth tab
   - Add users with agency/group labels
   - Set permissions (read, publish, playback)

### Built-in Users (do not delete)

| User | Purpose | Notes |
|------|---------|-------|
| FFmpeg localhost | Internal transcoding | Locked to 127.0.0.1, no auth |
| HLS viewer | Browser HLS playback | Password edit only |
| Public teststream | Test stream viewing | No auth, teststream path only |

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
netstat -tlnp | grep 8554
```

### Web Editor Won't Load
```bash
journalctl -u mediamtx-webeditor -n 50 --no-pager

# Common causes:
# - Missing Python packages
pip3 install Flask ruamel.yaml requests psutil
# - Port 5000 blocked by firewall
ufw status
# - mediamtx_config_editor.py not found
ls -la /opt/mediamtx-webeditor/
```

### Can't Connect to Stream
```bash
# 1. Check service is running
systemctl status mediamtx

# 2. Check firewall
ufw status

# 3. Test locally first
ffplay rtsp://127.0.0.1:8554/teststream

# 4. Check credentials
grep -A 10 "authInternalUsers" /usr/local/etc/mediamtx.yml
```

### Caddy Certificate Issues
```bash
journalctl -u caddy -n 50 --no-pager

# Verify DNS is correct
dig YOUR-DOMAIN.com

# Check ports 80/443 are open
ufw status

# Test Caddy config
caddy validate --config /etc/caddy/Caddyfile
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

### 1. Change Default Credentials
- Change web editor admin password immediately after install
- Change HLS viewer password via Users & Auth tab
- Use strong passwords for streaming users

### 2. Restrict Web Editor Access
```bash
# Allow only your IP to access web editor
ufw allow from YOUR-IP to any port 5000
ufw deny 5000
```

### 3. Enable Encryption
- Enable RTSPS for encrypted RTSP connections
- Enable HLS encryption for browser playback
- Add SRT passphrases for encrypted SRT streams

### 4. Use HTTPS
Always use Caddy for production deployments — provides HTTPS for the web editor automatically.

### 5. Firewall Configuration
```bash
# Review current rules
ufw status numbered

# Remove unused ports
ufw delete [number]
```

### 6. Keep Updated
The web editor has auto-update functionality from GitHub releases. Check for MediaMTX updates:
```bash
curl -s https://api.github.com/repos/bluenviron/mediamtx/releases/latest | grep tag_name
```

---

## Backup and Recovery

### Automatic Backups
The web editor creates automatic backups before every configuration change in:
```
/opt/mediamtx-webeditor/backups/
```

### Manual Backup
```bash
sudo cp /usr/local/etc/mediamtx.yml ~/mediamtx_backup_$(date +%Y%m%d).yml
```

### Restore from Web Editor
Service Control tab → Select backup → Restore

### Restore from Command Line
```bash
sudo cp ~/mediamtx_backup.yml /usr/local/etc/mediamtx.yml
sudo systemctl restart mediamtx
```

---

## File Locations

| Type | Location |
|------|----------|
| MediaMTX config | `/usr/local/etc/mediamtx.yml` |
| MediaMTX binary | `/usr/local/bin/mediamtx` |
| Web editor app | `/opt/mediamtx-webeditor/mediamtx_config_editor.py` |
| Web editor users | `/opt/mediamtx-webeditor/users.json` |
| Group metadata | `/opt/mediamtx-webeditor/group_names.json` |
| Config backups | `/opt/mediamtx-webeditor/backups/` |
| Recordings | `/opt/mediamtx-webeditor/recordings/` |
| Caddyfile | `/etc/caddy/Caddyfile` |
| Caddy certificates | `/var/lib/caddy/.local/share/caddy/certificates/` |

---

## Support

Created by **[The TAK Syndicate](https://www.youtube.com/@thetaksyndicate6234)**

- 🌐 Website: [https://www.thetaksyndicate.org](https://www.thetaksyndicate.org)
- 📺 YouTube: [@TheTAKSyndicate](https://www.youtube.com/@thetaksyndicate6234)
- 📧 Email: thetaksyndicate@gmail.com

### Getting Help
1. Check the troubleshooting section above
2. Search existing [GitHub Issues](https://github.com/takwerx/mediamtx-installer/issues)
3. Open a new issue if needed
4. Check MediaMTX GitHub: https://github.com/bluenviron/mediamtx/issues

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

These installation scripts are provided as-is for deployment assistance.
MediaMTX is licensed under MIT License.
Caddy is licensed under Apache License 2.0.

---

**Last Updated:** February 2026
**Script Version:** 2.0
**Compatible MediaMTX Versions:** All (auto-downloads latest)
**Tested on:** Ubuntu 22.04 LTS
