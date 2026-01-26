# MediaMTX Streaming Server - Complete Deployment Guide

## 📋 Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Installation Options](#installation-options)
5. [Quick Start Guide](#quick-start-guide)
6. [Post-Installation](#post-installation)
7. [Web Config Editor](#web-config-editor)
8. [Streaming Protocols](#streaming-protocols)
9. [Troubleshooting](#troubleshooting)
10. [Security Best Practices](#security-best-practices)

---

## Overview

**⚡ IMPORTANT: No Manual Downloads Required!**

Unlike TAK Server scripts (where you must manually download the TAK Server zip file), these MediaMTX scripts **automatically download the latest version from GitHub**. Just run the script and it handles everything!

This deployment suite provides automated installation scripts for MediaMTX streaming server with:
- ✅ **Version-agnostic installation** - Auto-detects and downloads latest MediaMTX release from GitHub
- ✅ **Caddy reverse proxy** - Automatic HTTPS with Let's Encrypt
- ✅ **Web-based config editor** - No more manual YAML editing
- ✅ **FFmpeg pre-installed** - HLS and transcoding ready out of the box
- ✅ **Multi-OS support** - Rocky Linux 9 and Ubuntu 22.04
- ✅ **Zero manual downloads** - Scripts handle everything automatically

**Why separate VPS for video?**
- Video streaming requires high bandwidth
- Prevents impact on TAK Server reliability
- Easier to scale independently
- Better cost optimization (use cheaper high-bandwidth VPS for video)

---

## Prerequisites

### Server Requirements
- **OS**: Rocky Linux 9 or Ubuntu 22.04
- **RAM**: Minimum 2GB (4GB+ recommended for HLS)
- **CPU**: 2+ cores recommended
- **Bandwidth**: High bandwidth VPS (video streaming intensive)
- **Storage**: 20GB+ (depends on recording needs)

### Before Installation
- ✅ Fresh VPS with root access
- ✅ Public IP address
- ✅ (Optional) Domain name with A record pointing to server IP
- ✅ Ports 80, 443 accessible for Let's Encrypt (if using Caddy)

### Recommended VPS Providers
- **DigitalOcean** - Excellent bandwidth
- **Vultr** - Good price/performance for video
- **Linode** - Reliable bandwidth allocation
- **Hetzner** - European locations with great bandwidth

---

## Architecture

### Deployment Diagram
```
Internet Users
    ↓
[Caddy (443/80)] ← Let's Encrypt SSL
    ↓
    ├─→ HLS Streams (port 8888)
    ├─→ WebRTC HTTP (port 8889)
    └─→ API/Metrics (ports 9997/9998)

Direct Streaming (no HTTPS):
    → RTSP (port 8554)
    → RTMP (port 1935)
    → SRT (port 8890)
    → RTP/RTCP (ports 8000/8001)
```

### Components
1. **MediaMTX** - Core streaming server (native install)
2. **Caddy** - Reverse proxy for HTTPS (native install)
3. **FFmpeg** - Optional transcoding for HLS
4. **Web Config Editor** - Python Flask app for YAML management

---

## Installation Options

### Scripts Available

#### Rocky Linux 9
- `Rocky_9_MediaMTX_install.sh` - Main MediaMTX installation
- `Rocky_9_MediaMTX_Caddy_setup.sh` - Caddy reverse proxy setup
- `Install_MediaMTX_Config_Editor.sh` - Web configuration interface

#### Ubuntu 22.04
- `Ubuntu_22_04_MediaMTX_install.sh` - Main MediaMTX installation
- `Ubuntu_22_04_MediaMTX_Caddy_setup.sh` - Caddy reverse proxy setup
- `Install_MediaMTX_Config_Editor.sh` - Web configuration interface (same for both OS)

---

## Quick Start Guide

### Option A: Basic Installation (No Domain/HTTPS)

Perfect for testing or private network use.

```bash
# 1. Download installation script
wget https://your-site.com/Rocky_9_MediaMTX_install.sh
# OR for Ubuntu:
# wget https://your-site.com/Ubuntu_22_04_MediaMTX_install.sh

# 2. Make executable
chmod +x Rocky_9_MediaMTX_install.sh

# 3. Run installer
sudo ./Rocky_9_MediaMTX_install.sh

# Follow prompts:
# - Username: (enter desired username)
# - Password: (enter desired password)
# Note: FFmpeg is installed automatically for HLS support

# 4. Installation complete!
# Test with: rtsp://username:password@YOUR-IP:8554/test
```

**Installation time:** ~5 minutes

---

### Option B: Production Installation (With HTTPS Domain)

Best for production deployments with public access.

```bash
# Step 1: Run basic installation first
chmod +x Rocky_9_MediaMTX_install.sh
sudo ./Rocky_9_MediaMTX_install.sh

# Step 2: Setup domain DNS
# Point your A record to your server's public IP
# Example: video.example.com → 123.45.67.89

# Step 3: Run Caddy setup
wget https://your-site.com/Rocky_9_MediaMTX_Caddy_setup.sh
chmod +x Rocky_9_MediaMTX_Caddy_setup.sh
sudo ./Rocky_9_MediaMTX_Caddy_setup.sh

# Follow prompts:
# - Enter domain: video.example.com

# Step 4: Install Web Config Editor (Optional but Recommended)
wget https://your-site.com/Install_MediaMTX_Config_Editor.sh
wget https://your-site.com/mediamtx_config_editor.py
chmod +x Install_MediaMTX_Config_Editor.sh
chmod +x mediamtx_config_editor.py
sudo ./Install_MediaMTX_Config_Editor.sh

# Done! Access:
# - HLS: https://video.example.com/hls/stream/index.m3u8
# - Config Editor: http://YOUR-IP:5000
```

**Installation time:** ~10 minutes

---

## Post-Installation

### Verify Installation

```bash
# Check MediaMTX status
systemctl status mediamtx

# Check logs
journalctl -u mediamtx -f

# Test RTSP stream
ffplay rtsp://username:password@YOUR-IP:8554/test
# OR with VLC: rtsp://username:password@YOUR-IP:8554/test
```

### Common First Steps

1. **Change default credentials**
   - Edit `/usr/local/etc/mediamtx.yml`
   - Or use Web Config Editor

2. **Configure firewall for your network**
   ```bash
   # Rocky:
   firewall-cmd --list-all
   
   # Ubuntu:
   ufw status
   ```

3. **Test streaming**
   - Publish test stream with OBS/FFmpeg
   - View with VLC or web player

---

## Web Config Editor

### Features
- 📝 Edit credentials without YAML knowledge
- 🔐 Manage users and permissions
- 🔧 Configure protocol settings (RTSP, RTMP, HLS, SRT)
- 💾 Automatic configuration backups
- ⚡ Restart MediaMTX service from web UI
- 🎯 Syntax validation before saving

### Access
```
http://YOUR-SERVER-IP:5000
```

### Usage

#### Basic Settings Tab
- Change log level (error/warn/info/debug)
- Adjust timeouts
- Modify write queue size

#### Users & Auth Tab
- Add/update users
- Set passwords
- Configure permissions (publish, read, playback, api)
- View all current users

#### Protocols Tab
- Change RTSP/RTMP/HLS/SRT ports
- Enable/disable encryption
- Configure protocol-specific settings

#### Advanced YAML Tab
- Direct YAML editing for power users
- Syntax validation before saving
- Full configuration control

#### Service Control Tab
- View service status
- Start/stop/restart MediaMTX
- Create manual backups
- Restore previous configurations

### Security Warning
⚠️ The config editor has no authentication by default!

**Recommended security measures:**
```bash
# Option 1: Firewall restriction (allow only your IP)
# Rocky:
firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="YOUR-IP" port port="5000" protocol="tcp" accept' --permanent
firewall-cmd --reload

# Ubuntu:
ufw allow from YOUR-IP to any port 5000

# Option 2: Add to Caddy with basic auth
# Add to Caddyfile:
config.video.example.com {
    reverse_proxy localhost:5000
    basicauth {
        admin $2a$14$encrypted_password_hash
    }
}
```

---

## Streaming Protocols

### RTSP (Recommended for most use cases)

**Publish:**
```bash
# With FFmpeg
ffmpeg -re -i input.mp4 -c copy -f rtsp rtsp://username:password@YOUR-IP:8554/stream

# With OBS
Server: rtsp://YOUR-IP:8554/stream
Username: username
Password: password
```

**View:**
```bash
# VLC
rtsp://username:password@YOUR-IP:8554/stream

# FFplay
ffplay rtsp://username:password@YOUR-IP:8554/stream
```

**Ports:** 8554 (TCP)

---

### RTMP (Good for legacy systems/OBS)

**Publish:**
```bash
# OBS Settings
Server: rtmp://YOUR-IP:1935/
Stream Key: stream

# FFmpeg
ffmpeg -re -i input.mp4 -c copy -f flv rtmp://YOUR-IP:1935/stream
```

**View:**
```bash
ffplay rtmp://YOUR-IP:1935/stream
```

**Ports:** 1935 (TCP)

---

### HLS (Best for web browsers)

**Requirements:** FFmpeg must be installed (choose 'y' during installation)

**Publish:**
```bash
# Publish to RTSP first (triggers HLS conversion)
ffmpeg -re -i input.mp4 -c copy -f rtsp rtsp://username:password@YOUR-IP:8554/live/stream
```

**View:**
```html
<!-- With Caddy HTTPS domain -->
https://video.example.com/hls/stream/index.m3u8

<!-- Direct (no HTTPS) -->
http://YOUR-IP:8888/stream/index.m3u8
```

**Ports:** 8888 (TCP)

**Configuration Note:**
The default config includes FFmpeg path mapping for HLS:
```yaml
paths:
  "~^live/(.+)$":
    runOnReady: ffmpeg -i rtsp://localhost:8554/live/$G1 -c:v copy -map 0:0 -f rtsp rtsp://localhost:8554/hls/$G1
    runOnReadyRestart: yes
```

---

### SRT (Low-latency, reliable)

**Publish:**
```bash
# FFmpeg
ffmpeg -re -i input.mp4 -c copy -f mpegts srt://YOUR-IP:8890?streamid=stream

# OBS
Server: srt://YOUR-IP:8890
Stream ID: stream
```

**View:**
```bash
ffplay srt://YOUR-IP:8890?streamid=stream
```

**Ports:** 8890 (UDP)

**Add passphrase:**
Edit `/usr/local/etc/mediamtx.yml`:
```yaml
srtEncryption: aes128
```

---

### WebRTC (Browser-based, low latency)

**View:**
```
https://video.example.com/webrtc/?stream=stream
```

**Ports:** 8889 (TCP), 8189 (UDP)

---

## Troubleshooting

### MediaMTX Won't Start
```bash
# Check logs
journalctl -u mediamtx -n 50

# Common issues:
# 1. Port already in use
netstat -tlnp | grep 8554

# 2. Config syntax error
/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml --check

# 3. Permissions
ls -la /usr/local/etc/mediamtx.yml
```

### Can't Connect to Stream
```bash
# 1. Check service is running
systemctl status mediamtx

# 2. Check firewall
# Rocky:
firewall-cmd --list-all

# Ubuntu:
ufw status

# 3. Test locally first
ffplay rtsp://127.0.0.1:8554/test

# 4. Check credentials
grep -A 10 "authInternalUsers" /usr/local/etc/mediamtx.yml
```

### Caddy Certificate Issues
```bash
# Check Caddy logs
journalctl -u caddy -n 50

# Verify DNS is correct
dig YOUR-DOMAIN.com

# Test Caddy config
caddy validate --config /etc/caddy/Caddyfile

# Force certificate renewal
systemctl restart caddy
```

### HLS Not Working
```bash
# 1. Check FFmpeg is installed
ffmpeg -version

# 2. Check HLS config in mediamtx.yml
grep -A 5 "paths:" /usr/local/etc/mediamtx.yml

# 3. Check HLS logs
journalctl -u mediamtx | grep hls

# 4. Verify stream path
# Publish to: rtsp://IP:8554/live/mystream
# View at: http://IP:8888/hls/mystream/index.m3u8
```

### High CPU Usage
```bash
# Check processes
top -u root

# If FFmpeg is using too much:
# 1. Reduce HLS segment size
# 2. Use hardware encoding if available
# 3. Limit concurrent streams
```

---

## Security Best Practices

### 1. Change Default Credentials
```bash
# Use Web Config Editor OR edit manually:
sudo nano /usr/local/etc/mediamtx.yml

# Find authInternalUsers section
# Change username and password
```

### 2. Enable Encryption
```yaml
# In mediamtx.yml
rtspEncryption: strict
rtmpEncryption: strict
srtEncryption: aes128
```

### 3. Restrict Access by IP
```yaml
authInternalUsers:
- user: publisher
  pass: strongpassword
  ips: ['1.2.3.4', '5.6.7.8']  # Only these IPs can use this user
```

### 4. Use HTTPS for Web Access
```bash
# Always use Caddy for HLS/WebRTC in production
# Never expose HTTP ports (8888, 8889) directly to internet
```

### 5. Firewall Configuration
```bash
# Rocky - Only allow necessary ports
firewall-cmd --zone=public --list-all

# Remove unused ports
firewall-cmd --zone=public --remove-port=XXXX/tcp --permanent

# Ubuntu - Same principle
ufw status numbered
ufw delete [number]
```

### 6. Regular Updates
```bash
# Check for MediaMTX updates
curl -s https://api.github.com/repos/bluenviron/mediamtx/releases/latest | grep tag_name

# Update if needed (backup first!)
systemctl stop mediamtx
# Download new version
# Replace /usr/local/bin/mediamtx
systemctl start mediamtx
```

### 7. Enable API Authentication
```yaml
api: yes
apiAddress: :9997
# Add authentication or use Caddy proxy with basic auth
```

### 8. Monitor Logs
```bash
# Setup log rotation
sudo nano /etc/logrotate.d/mediamtx

# Add:
/usr/local/etc/mediamtx.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 root root
    postrotate
        systemctl reload mediamtx
    endscript
}
```

---

## Performance Tuning

### For High-Traffic Deployments

```yaml
# Increase write queue
writeQueueSize: 2048

# Adjust UDP buffer
udpMaxPayloadSize: 1472

# For HLS
hlsSegmentCount: 7
hlsSegmentDuration: 1s
```

### Hardware Acceleration (if available)

```yaml
# For Raspberry Pi or systems with GPU
rpiCameraCodec: hardwareH264
```

---

## Backup and Recovery

### Manual Backup
```bash
# Backup config
sudo cp /usr/local/etc/mediamtx.yml ~/mediamtx_backup_$(date +%Y%m%d).yml

# Backup using Web Config Editor
# Service Control tab → Create Backup Now
```

### Automated Backup
```bash
# Create backup script
sudo nano /usr/local/bin/backup-mediamtx.sh

#!/bin/bash
cp /usr/local/etc/mediamtx.yml /backup/mediamtx_$(date +%Y%m%d_%H%M%S).yml

# Make executable
sudo chmod +x /usr/local/bin/backup-mediamtx.sh

# Add to crontab (daily backup)
crontab -e
0 2 * * * /usr/local/bin/backup-mediamtx.sh
```

### Restore from Backup
```bash
# Manual restore
sudo cp ~/mediamtx_backup.yml /usr/local/etc/mediamtx.yml
sudo systemctl restart mediamtx

# OR use Web Config Editor
# Service Control tab → Select backup → Restore
```

---

## Integration Examples

### OBS Studio Setup

1. **RTMP Publishing:**
   - Settings → Stream
   - Service: Custom
   - Server: `rtmp://YOUR-IP:1935/`
   - Stream Key: `mystream`

2. **RTSP Publishing:**
   - Settings → Stream
   - Service: Custom
   - Server: `rtsp://YOUR-IP:8554/mystream`
   - Use authentication: Yes
   - Username: (your username)
   - Password: (your password)

3. **SRT Publishing:**
   - Settings → Stream
   - Service: Custom
   - Server: `srt://YOUR-IP:8890?streamid=mystream`

### VLC Player Viewing

```
Media → Open Network Stream
rtsp://username:password@YOUR-IP:8554/stream
```

### Web Player (HLS)

```html
<!DOCTYPE html>
<html>
<head>
    <link href="https://vjs.zencdn.net/7.20.3/video-js.css" rel="stylesheet" />
</head>
<body>
    <video id="my-video" class="video-js" controls preload="auto" width="640" height="360">
        <source src="https://video.example.com/hls/stream/index.m3u8" type="application/x-mpegURL">
    </video>
    
    <script src="https://vjs.zencdn.net/7.20.3/video.min.js"></script>
    <script>
        var player = videojs('my-video');
    </script>
</body>
</html>
```

---

## Additional Resources

- **MediaMTX Documentation:** https://github.com/bluenviron/mediamtx
- **Caddy Documentation:** https://caddyserver.com/docs/
- **FFmpeg Documentation:** https://ffmpeg.org/documentation.html
- **RTSP Specification:** https://tools.ietf.org/html/rfc2326
- **HLS Specification:** https://tools.ietf.org/html/rfc8216

---

## Support

For issues or questions:
1. Check logs: `journalctl -u mediamtx -f`
2. Verify config: `/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml --check`
3. Review this guide's troubleshooting section
4. Check MediaMTX GitHub issues: https://github.com/bluenviron/mediamtx/issues

---

## License

These installation scripts are provided as-is for deployment assistance.
MediaMTX is licensed under MIT License.
Caddy is licensed under Apache License 2.0.

---

**Last Updated:** January 2025
**Script Version:** 1.0
**Compatible MediaMTX Versions:** All versions (auto-detects latest)
