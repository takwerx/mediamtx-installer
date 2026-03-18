# MediaMTX Streaming Server Installer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MediaMTX](https://img.shields.io/badge/MediaMTX-Auto--Download-blue)](https://github.com/bluenviron/mediamtx)
[![OS Support](https://img.shields.io/badge/OS-Ubuntu%2022.04-green)]()

**Production-ready MediaMTX streaming server deployment with HTTPS, RTSPS encryption, and web-based configuration editor. Now with native MPEG-TS demuxing — no FFmpeg required for HLS from ATAK/TAKICU/UAS feeds.**

Automated installation, SSL configuration, and streaming management for emergency services and live video operations. Created and maintained by [The TAK Syndicate](https://www.thetaksyndicate.org).

---

## 🚀 Quick Start

**Three scripts to deploy a complete streaming server:**

```bash
# 1. Download scripts
git clone https://github.com/takwerx/mediamtx-installer.git
cd mediamtx-installer
chmod +x ubuntu-22.04/*.sh config-editor/*.sh

# 2. Install MediaMTX
sudo ./ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh

# 3. Install Web Configuration Editor
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh

# 4. (Optional) Add HTTPS and RTSPS certificates
sudo ./ubuntu-22.04/Ubuntu_22.04_Install_MediaMTX_Caddy.sh
```

**That's it!** MediaMTX is streaming at `rtsp://YOUR-IP:8554`

📖 **[Read the complete deployment guide](MEDIAMTX-DEPLOYMENT-GUIDE.md)** for detailed instructions.
⚡ **[Quick start for experienced users](MEDIAMTX-QUICK-START.md)**

---

## 🔧 infra-TAK Users — Read This First

If MediaMTX was deployed through [infra-TAK](https://github.com/takwerx/infra-TAK), the web editor runs with an LDAP overlay for Authentik integration.

**Web editor not loading after an update?** The LDAP overlay can become stale after the editor auto-updates. To fix:

1. Open your **infra-TAK console** — either `https://infratak.yourdomain.com` or `https://tak.yourdomain.com` (or the backdoor at `https://<VPS-IP>:5001`)
2. Go to the **MediaMTX** page
3. Click **Patch web editor**

This re-syncs the LDAP overlay and restarts the editor. **v2.0.1** fixes this at startup by skipping conflicting route registration when the overlay is detected, and auto re-syncs the overlay during future updates. The manual patch always works as a fallback.

---

## ✨ Features

### 🔧 MediaMTX Installation Script
- ✅ Auto-downloads latest MediaMTX from GitHub
- ✅ Ships with proven production YAML configuration
- ✅ **MPEG-TS demuxing enabled by default** — RTSP sources (TAKICU, ATAK UAS, ISR cameras) work with HLS natively
- ✅ No FFmpeg transcoding required for MPEG-TS over RTSP sources
- ✅ Random HLS viewer password generation
- ✅ Unattended-upgrade detection (waits for system updates)
- ✅ Firewall configuration (UFW)
- ✅ systemd service with auto-start

### 🎨 Web Configuration Editor (v2.0.1)
- ✅ **HLS Tuning page** — Segment count, duration, variant, always remux, write queue — all from the browser
- ✅ **HLS presets** — One-click LAN, Internet, and Satellite (KU/KA) profiles
- ✅ **MPEG-TS demux toggle** — Enable/disable RTSP MPEG-TS unwrapping from the UI (no YAML editing)
- ✅ User management with agency/group labels
- ✅ Recording management with retention periods
- ✅ Public access toggle
- ✅ Theme/styling customization
- ✅ Advanced YAML editor
- ✅ Service control (start/stop/restart)
- ✅ Automatic backups before changes
- ✅ Auto-update from GitHub releases
- ✅ **Ku-band link simulator** — One-click “Simulate link” per external source to impair incoming traffic (delay/jitter/loss) for HLS testing without flying
- ✅ **Share links** — Token-based share links (Active Streams: 4h; External Sources: configurable duration)

### 🔒 Caddy SSL Script (Optional)
- ✅ Let's Encrypt SSL certificates (automatic)
- ✅ HTTPS reverse proxy for web editor
- ✅ Certificate paths auto-configured for RTSPS/HLS
- ✅ TAK Server Caddy coexistence (appends, doesn't overwrite)
- ✅ No manual certificate management

---

## 📋 What You Need

### Required
- Fresh VPS with Ubuntu 22.04
- 2GB RAM minimum (4GB+ recommended for HLS)
- 2+ CPU cores recommended
- Root/sudo access
- High bandwidth (video streaming intensive)

### Optional (for SSL/RTSPS)
- Domain name
- DNS A record pointing to your VPS

---

## 📂 Repository Structure

```
mediamtx-installer/
├── ubuntu-22.04/
│   ├── Ubuntu_22.04_MediaMTX_install.sh          # MediaMTX installation
│   └── Ubuntu_22.04_Install_MediaMTX_Caddy.sh    # SSL/Let's Encrypt setup
├── config-editor/
│   ├── Install_MediaMTX_Config_Editor.sh          # Web editor installer (universal)
│   └── mediamtx_config_editor.py                  # Web editor application (v2.0.1)
├── scripts/
│   └── ku-band-simulator/                         # Ku-band link simulator (delay/jitter/loss)
├── MEDIAMTX-DEPLOYMENT-GUIDE.md                   # Complete deployment guide
├── MEDIAMTX-QUICK-START.md                        # Fast deployment instructions
├── RELEASE-v2.0.0.md                               # Web Editor v2.0.0 release notes
├── RELEASE-v2.0.1.md                               # v2.0.1 infra-TAK overlay fix
└── README.md                                      # This file
```

---

## 🎯 Installation Overview

### Step 1: Install MediaMTX

Installs MediaMTX, deploys custom YAML configuration with MPEG-TS demuxing, configures firewall.

```bash
sudo ./ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh
```

**What it does:**
- Downloads latest MediaMTX binary
- Deploys production YAML with MPEG-TS demuxing and 3 built-in users
- Generates random HLS viewer password
- Creates systemd service
- Configures UFW firewall

**Access:** `rtsp://YOUR-IP:8554/teststream` (no auth required for teststream)

---

### Step 2: Install Web Editor

Web-based configuration management — no more manual YAML editing.

```bash
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh
```

**What it does:**
- Installs Python3, Flask, and dependencies
- Deploys web editor to /opt/mediamtx-webeditor/
- Creates systemd service on port 5000

**Access:** `http://YOUR-IP:5000`
**Default login:** admin / admin (change immediately!)

---

### Step 3: Add SSL (Optional)

Adds HTTPS for web editor and certificate paths for RTSPS/HLS encryption.

```bash
sudo ./ubuntu-22.04/Ubuntu_22.04_Install_MediaMTX_Caddy.sh
```

**What it does:**
- Installs Caddy
- Obtains Let's Encrypt certificate
- Configures HTTPS reverse proxy for web editor
- Writes certificate paths to MediaMTX YAML
- Enables RTSPS and HLS encryption automatically

**Access:** `https://yourdomain.com`

---

## 📡 Streaming Protocols

| Protocol | Port | Use Case |
|----------|------|----------|
| **RTSP** | 8554/tcp | Most apps, VLC, cameras, ATAK |
| **RTSPS** | 8322/tcp | Encrypted RTSP (after enabling) |
| **HLS** | 8888/tcp | Browser playback |
| **SRT** | 8890/udp | Low-latency, reliable |

### MPEG-TS Demuxing (v2.0.0+)

RTSP sources that wrap H264/AAC inside MPEG-TS (TAKICU, ATAK UAS Tool, ISR cameras) are automatically unwrapped into native tracks. HLS playback works natively — no FFmpeg transcoding step required. KLV metadata tracks are preserved for RTSP readers and skipped by HLS.

Requires MediaMTX v1.17.0+. Enable/disable from **Configuration > HLS Tuning** in the web editor.

---

## 🔐 Built-in Users

The installer creates 3 users (no prompts during install):

| User | Purpose | Auth |
|------|---------|------|
| FFmpeg localhost | Internal transcoding | No auth (127.0.0.1 only) |
| HLS viewer | Browser HLS playback | Random password (shown at install) |
| Public teststream | Test stream viewing | No auth (teststream path only) |

All additional users are managed through the Web Editor → Users & Auth tab.

---

## 📚 Documentation

- **[Complete Deployment Guide](MEDIAMTX-DEPLOYMENT-GUIDE.md)** - Step-by-step instructions with troubleshooting
- **[Quick Start Guide](MEDIAMTX-QUICK-START.md)** - Fast deployment for experienced users
- **[MediaMTX Official Docs](https://github.com/bluenviron/mediamtx)** - MediaMTX documentation

---

## 🔒 Security Notes

### Default Credentials
- **Web Editor:** admin / admin (change immediately!)
- **HLS Viewer:** hlsviewer / (random, shown at install)
- **Teststream:** No auth required (read-only, teststream path only)

### Firewall Ports
The scripts automatically configure these ports:
- **8554/tcp** - RTSP
- **8322/tcp** - RTSPS (after enabling encryption)
- **8888/tcp** - HLS
- **8890/udp** - SRT
- **8000/udp** - RTP
- **8001/udp** - RTCP
- **5000/tcp** - Web editor
- **80/tcp** - HTTP (only if using Caddy)
- **443/tcp** - HTTPS (only if using Caddy)

---

## 🎓 Support

Created by **[The TAK Syndicate](https://www.youtube.com/@thetaksyndicate6234)**

- 🌐 Website: [https://www.thetaksyndicate.org](https://www.thetaksyndicate.org)
- 📺 YouTube: [@TheTAKSyndicate](https://www.youtube.com/@thetaksyndicate6234)
- 📧 Email: thetaksyndicate@gmail.com

### Getting Help
1. Check the [Deployment Guide](MEDIAMTX-DEPLOYMENT-GUIDE.md)
2. Review [Troubleshooting](MEDIAMTX-DEPLOYMENT-GUIDE.md#troubleshooting)
3. Search existing [GitHub Issues](https://github.com/takwerx/mediamtx-installer/issues)
4. Open a new issue if needed

---

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details.

Free to use, modify, and distribute. Attribution appreciated!

---

## 🙏 Credits

- **MediaMTX** by [bluenviron](https://github.com/bluenviron/mediamtx)
- **Scripts** by [The TAK Syndicate](https://www.thetaksyndicate.org)
- **Community contributions** welcome!

---

## ⭐ Star This Repo!

If these scripts helped you deploy a streaming server, please star this repository!

**[⭐ Star on GitHub](https://github.com/takwerx/mediamtx-installer)**

---

**Latest Update:** March 2026  
**Web Editor:** v2.0.1  
**Script Version:** 2.0  
**Compatible with:** MediaMTX v1.17.0+ (auto-downloads latest)  
**Tested on:** Ubuntu 22.04 LTS
