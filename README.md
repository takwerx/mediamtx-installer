# MediaMTX Automated Installer

**Automated installation scripts for MediaMTX streaming server with Caddy reverse proxy and web-based configuration editor.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MediaMTX](https://img.shields.io/badge/MediaMTX-Auto--Download-blue)](https://github.com/bluenviron/mediamtx)
[![OS Support](https://img.shields.io/badge/OS-Rocky%209%20%7C%20Ubuntu%2022.04-green)]()

## ✨ Features

- 🚀 **Auto-downloads latest MediaMTX** from GitHub - no manual downloads needed!
- 🔒 **Automatic HTTPS** with Caddy and Let's Encrypt (no certbot cronjobs!)
- 🎨 **Web-based YAML editor** - manage configuration through browser interface
- 🎬 **FFmpeg pre-installed** for HLS streaming and transcoding
- 📦 **Multi-OS support** - Rocky Linux 9 and Ubuntu 22.04
- ⚡ **Zero manual downloads** - completely automated installation
- 🔧 **Version-agnostic** - always installs the latest MediaMTX release

## 📋 What is MediaMTX?

[MediaMTX](https://github.com/bluenviron/mediamtx) is a ready-to-use, zero-dependency real-time media server and media proxy that allows you to publish, read, proxy, record and playback video and audio streams. It supports multiple protocols including RTSP, RTMP, HLS, WebRTC, and SRT.

**Perfect for:**
- Live video streaming
- Security camera systems (RTSP)
- OBS Studio streaming (RTMP)
- Browser-based playback (HLS/WebRTC)
- Low-latency applications (SRT)

## 🎯 Quick Start

### Prerequisites
- Fresh VPS with Rocky Linux 9 or Ubuntu 22.04
- Root access
- (Optional) Domain name for HTTPS

### Rocky Linux 9

```bash
# Download the installer
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/rocky-9/Rocky_9_MediaMTX_install.sh

# Make executable
chmod +x Rocky_9_MediaMTX_install.sh

# Run installer
sudo ./Rocky_9_MediaMTX_install.sh
```

### Ubuntu 22.04

```bash
# Download the installer
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh

# Make executable
chmod +x Ubuntu_22.04_MediaMTX_install.sh

# Run installer
sudo ./Ubuntu_22.04_MediaMTX_install.sh
```

**Installation time:** ~5 minutes

The script will prompt for:
- MediaMTX username (default: admin)
- MediaMTX password (default: admin)

**That's it!** MediaMTX and FFmpeg are automatically installed and configured.

## 🔒 Add HTTPS with Caddy (Optional)

If you have a domain name, add automatic HTTPS:

### Rocky Linux 9
```bash
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/rocky-9/Rocky_9_Caddy_setup.sh
chmod +x Rocky_9_Caddy_setup.sh
sudo ./Rocky_9_Caddy_setup.sh
```

### Ubuntu 22.04
```bash
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/ubuntu-22.04/Ubuntu_22.04_Caddy_setup.sh
chmod +x Ubuntu_22.04_Caddy_setup.sh
sudo ./Ubuntu_22.04_Caddy_setup.sh
```

**Requirements:**
- Domain name (e.g., video.example.com)
- DNS A record pointing to your server IP
- Ports 80 and 443 accessible

## 🎨 Web Configuration Editor (Optional)

Manage MediaMTX configuration through a beautiful web interface instead of editing YAML files manually!

```bash
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/config-editor/Install_MediaMTX_Config_Editor.sh
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/config-editor/mediamtx_config_editor.py
chmod +x Install_MediaMTX_Config_Editor.sh mediamtx_config_editor.py
sudo ./Install_MediaMTX_Config_Editor.sh
```

Access at: `http://YOUR-SERVER-IP:5000`

**Features:**
- 📝 User management (add/edit users and passwords)
- 🔧 Protocol settings (RTSP, RTMP, HLS, SRT ports)
- 💾 Automatic backups before changes
- ⚡ Service control (start/stop/restart)
- ✅ YAML syntax validation
- 🎨 Clean tabbed interface

## 📡 Streaming Protocols

After installation, MediaMTX supports:

| Protocol | Port | Use Case | Example URL |
|----------|------|----------|-------------|
| **RTSP** | 8554 | Most applications, VLC, cameras | `rtsp://user:pass@IP:8554/stream` |
| **RTMP** | 1935 | OBS Studio, legacy apps | `rtmp://IP:1935/stream` |
| **HLS** | 8888 | Browser playback, iOS | `http://IP:8888/stream/index.m3u8` |
| **WebRTC** | 8889 | Low-latency browser | `http://IP:8889/stream` |
| **SRT** | 8890 | Low-latency, reliable | `srt://IP:8890?streamid=stream` |

With Caddy (HTTPS):
- **HLS:** `https://video.example.com/hls/stream/index.m3u8`
- **WebRTC:** `https://video.example.com/webrtc/?stream=stream`

## 🎬 Example: Stream with OBS Studio

### RTMP Method
1. **OBS Settings → Stream**
2. **Service:** Custom
3. **Server:** `rtmp://YOUR-IP:1935/`
4. **Stream Key:** `mystream`

### RTSP Method (Recommended)
1. **OBS Settings → Stream**
2. **Service:** Custom
3. **Server:** `rtsp://YOUR-IP:8554/mystream`
4. **Use authentication:** Yes
5. **Username:** (your username)
6. **Password:** (your password)

### SRT Method (Low Latency)
1. **OBS Settings → Stream**
2. **Service:** Custom
3. **Server:** `srt://YOUR-IP:8890?streamid=mystream`

## 📺 Example: View Stream

### VLC Media Player
```
Media → Open Network Stream
rtsp://username:password@YOUR-IP:8554/stream
```

### FFplay (Command Line)
```bash
ffplay rtsp://username:password@YOUR-IP:8554/stream
```

### Web Browser (HLS)
```html
<video controls>
    <source src="https://video.example.com/hls/stream/index.m3u8" type="application/x-mpegURL">
</video>
```

## 📁 Repository Contents

| File | Description |
|------|-------------|
| `rocky-9/Rocky_9_MediaMTX_install.sh` | Main installer for Rocky Linux 9 |
| `rocky-9/Rocky_9_Caddy_setup.sh` | Caddy HTTPS setup for Rocky Linux 9 |
| `ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh` | Main installer for Ubuntu 22.04 |
| `ubuntu-22.04/Ubuntu_22.04_Caddy_setup.sh` | Caddy HTTPS setup for Ubuntu 22.04 |
| `config-editor/mediamtx_config_editor.py` | Web-based configuration editor |
| `config-editor/Install_MediaMTX_Config_Editor.sh` | Config editor installer |
| `DEPLOYMENT_GUIDE.md` | Comprehensive deployment documentation |

## 🔧 Post-Installation

### Check Status
```bash
systemctl status mediamtx
journalctl -u mediamtx -f
```

### Edit Configuration
```bash
# Manual method
nano /usr/local/etc/mediamtx.yml

# Or use web editor
http://YOUR-IP:5000
```

### Common Commands
```bash
# Restart MediaMTX
systemctl restart mediamtx

# Stop MediaMTX
systemctl stop mediamtx

# Start MediaMTX
systemctl start mediamtx

# View logs
journalctl -u mediamtx -f
```

## 🔒 Security Best Practices

1. **Change default credentials** immediately after installation
2. **Restrict web config editor** access by IP using firewall
3. **Use HTTPS** (Caddy) for all browser-based access
4. **Enable encryption** for protocols (RTSP/RTMP/SRT)
5. **Keep MediaMTX updated** regularly

### Secure Web Config Editor

```bash
# Rocky - Allow only your IP
firewall-cmd --add-rich-rule='rule family="ipv4" source address="YOUR-IP" port port="5000" protocol="tcp" accept' --permanent
firewall-cmd --reload

# Ubuntu - Allow only your IP
ufw allow from YOUR-IP to any port 5000
```

## 📖 Documentation

- **[Full Deployment Guide](DEPLOYMENT_GUIDE.md)** - Complete documentation with examples
- **[MediaMTX Official Docs](https://github.com/bluenviron/mediamtx)** - MediaMTX documentation
- **[Caddy Documentation](https://caddyserver.com/docs/)** - Caddy web server docs

## 🆘 Troubleshooting

### MediaMTX won't start
```bash
# Check logs
journalctl -u mediamtx -n 50

# Verify config syntax
/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml --check
```

### Can't connect to stream
```bash
# Check firewall
firewall-cmd --list-all  # Rocky
ufw status               # Ubuntu

# Test locally first
ffplay rtsp://127.0.0.1:8554/test
```

### Caddy certificate fails
```bash
# Verify DNS
dig your-domain.com

# Check Caddy logs
journalctl -u caddy -n 50

# Validate Caddyfile
caddy validate --config /etc/caddy/Caddyfile
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Related Projects

- **[MediaMTX](https://github.com/bluenviron/mediamtx)** - The MediaMTX streaming server
- **[Caddy](https://github.com/caddyserver/caddy)** - The Caddy web server
- **Your TAK Server Installer** - [Link to your TAK server repo if public]

## ⭐ Star This Repo

If these scripts helped you, please consider giving this repo a star! It helps others find it.

## 📧 Support

For issues specific to these installation scripts, please open a GitHub issue.

For MediaMTX-specific questions, see the [MediaMTX repository](https://github.com/bluenviron/mediamtx/issues).

---

**Made with ❤️ for the streaming community**
