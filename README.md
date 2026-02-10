# MediaMTX Automated Installer

**Automated installation scripts for MediaMTX streaming server with Caddy HTTPS, RTSPS/HLS encryption, and web-based configuration editor.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MediaMTX](https://img.shields.io/badge/MediaMTX-Auto--Download-blue)](https://github.com/bluenviron/mediamtx)
[![OS Support](https://img.shields.io/badge/OS-Ubuntu%2022.04-green)]()

## ✨ Features

- 🚀 **Auto-downloads latest MediaMTX** from GitHub - no manual downloads needed!
- 📦 **Ships with production YAML** - proven custom configuration, not the default
- 🔒 **Automatic HTTPS** with Caddy and Let's Encrypt (no certbot cronjobs!)
- 🔐 **RTSPS/HLS encryption** - Caddy certificates auto-configured for MediaMTX
- 🎨 **Web-based configuration editor** - manage users, encryption, recording, and more
- 🎬 **FFmpeg pre-installed** for HLS streaming and live/ path transcoding
- ⚡ **Zero manual downloads** - completely automated installation
- 🛡️ **Unattended-upgrade detection** - waits for system updates before installing

## 📋 What is MediaMTX?

[MediaMTX](https://github.com/bluenviron/mediamtx) is a ready-to-use, zero-dependency real-time media server that supports RTSP, RTMP, HLS, WebRTC, and SRT protocols.

**Perfect for:**
- Live drone video streaming (DJI → ATAK/TAK)
- Security camera systems (RTSP)
- Emergency services video distribution
- Browser-based playback (HLS)
- Low-latency applications (SRT)

## 🎯 Quick Start

### Prerequisites
- Fresh VPS with Ubuntu 22.04
- Root access
- (Optional) Domain name for HTTPS/RTSPS

### Installation (3 Scripts, Run in Order)

```bash
# Clone the repo
git clone https://github.com/takwerx/mediamtx-installer.git
cd mediamtx-installer

# Step 1: Install MediaMTX
chmod +x ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
sudo ./ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh

# Step 2: Install Web Configuration Editor
chmod +x config-editor/Install_MediaMTX_Config_Editor.sh
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh

# Step 3 (Optional): Install Caddy for HTTPS + RTSPS certs
chmod +x ubuntu-22.04/Install_MediaMTX_Caddy.sh
sudo ./ubuntu-22.04/Install_MediaMTX_Caddy.sh
```

**Installation time:** ~5-10 minutes

**No username/password prompts!** The installer ships with a secure configuration:
- FFmpeg localhost user (internal, no auth needed)
- HLS viewer user with auto-generated random password
- Public teststream (no auth required for testing)
- All other users managed through the Web Editor

## 📡 What Each Script Does

### Script 1: MediaMTX Installer
- Downloads and installs latest MediaMTX binary
- Installs FFmpeg for HLS transcoding
- Deploys custom production YAML configuration
- Creates systemd service
- Configures firewall (UFW)
- Generates random HLS viewer password

### Script 2: Web Editor Installer
- Installs Python3, Flask, and dependencies (psutil, requests, ruamel.yaml)
- Deploys web-based configuration editor
- Creates systemd service on port 5000
- Default login: admin / admin (change after first login!)

### Script 3: Caddy Installer
- Installs Caddy web server
- Creates HTTPS reverse proxy for Web Editor
- Obtains Let's Encrypt SSL certificates
- Writes certificate paths to MediaMTX YAML (for RTSPS/HLS)
- **Does NOT enable encryption** — you do that via Web Editor when ready
- Safely appends to existing Caddyfile (TAK Server coexistence)

## 🔐 Enabling Encryption (After Caddy Install)

Caddy fills in the certificate paths but leaves encryption disabled. Enable when ready:

**RTSPS (encrypted RTSP):**
1. Open Web Editor → Advanced YAML
2. Search for `rtspEncryption`
3. Change to: `rtspEncryption: "optional"`
4. Save and restart MediaMTX

**HLS encryption:**
1. Open Web Editor → Advanced YAML
2. Search for `hlsEncryption`
3. Change to: `hlsEncryption: yes`
4. Save and restart MediaMTX

## 📡 Streaming Protocols

| Protocol | Port | Use Case |
|----------|------|----------|
| **RTSP** | 8554 | Most apps, VLC, cameras, ATAK |
| **RTSPS** | 8322 | Encrypted RTSP (after enabling) |
| **HLS** | 8888 | Browser playback |
| **SRT** | 8890 | Low-latency, reliable |

**FFmpeg live/ path transcoding:** Publish to `rtsp://server:8554/live/uas1` and it automatically creates a clean `rtsp://server:8554/uas1` stream.

## 🎨 Web Configuration Editor

Access at `http://YOUR-IP:5000` (or `https://yourdomain.com` after Caddy)

**Default login:** admin / admin

**Features:**
- 📊 Dashboard with system stats and active streams
- 👥 User management (add/edit/revoke streaming users)
- 🔧 Protocol settings
- 🎥 Recording management
- 🎨 Theme/styling customization
- 📝 Advanced YAML editor
- ⚡ Service control (start/stop/restart)
- 💾 Automatic backups
- 🔄 Auto-update from GitHub releases

## 📂 Repository Contents

```
mediamtx-installer/
├── README.md
├── DEPLOYMENT_GUIDE.md
├── LICENSE
├── ubuntu-22.04/
│   ├── Ubuntu_22_04_MediaMTX_install.sh    ← MediaMTX + FFmpeg + custom YAML
│   └── Install_MediaMTX_Caddy.sh           ← Caddy + HTTPS + cert paths
└── config-editor/
    ├── Install_MediaMTX_Config_Editor.sh    ← Web editor installer
    └── mediamtx_config_editor.py            ← Web editor application
```

## 🔒 Security

- HLS viewer password is auto-generated (16 random characters)
- FFmpeg internal user locked to localhost only (127.0.0.1)
- Web editor has its own login system (separate from MediaMTX users)
- Encryption disabled by default — enable after Caddy provides certificates
- All user management done through web editor (no plaintext passwords in scripts)

## 🆘 Troubleshooting

```bash
# Check MediaMTX
systemctl status mediamtx
journalctl -u mediamtx -f

# Check Web Editor
systemctl status mediamtx-webeditor
journalctl -u mediamtx-webeditor -f

# Check Caddy
systemctl status caddy
journalctl -u caddy -f
```

## 📖 Documentation

- **[Full Deployment Guide](DEPLOYMENT_GUIDE.md)**
- **[MediaMTX Official Docs](https://github.com/bluenviron/mediamtx)**
- **[Caddy Documentation](https://caddyserver.com/docs/)**

## 📜 License

MIT License - see [LICENSE](LICENSE)

---

**Made for emergency services and the streaming community**
