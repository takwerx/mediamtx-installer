# MediaMTX Quick Start Guide

**Fast MediaMTX streaming server deployment for experienced Linux users.**

For complete documentation, see [MEDIAMTX-DEPLOYMENT-GUIDE.md](MEDIAMTX-DEPLOYMENT-GUIDE.md)

---

## Prerequisites

- Fresh Ubuntu 22.04 VPS
- 2GB+ RAM, 2+ CPU cores
- Root access OR user account with sudo privileges
- (Optional) Domain name for HTTPS/RTSPS

---

## 1. Download Scripts

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

## 2. Install MediaMTX

```bash
sudo ./ubuntu-22.04/Ubuntu_22_04_MediaMTX_install.sh
```

**During install:**
- No prompts — fully automated
- Waits for unattended-upgrades if running

**Completion time:** ~5 minutes

**At the end, save the HLS viewer password displayed on screen!**

**Verify:**
```bash
systemctl status mediamtx
```

**Test stream (no auth required):**
```
rtsp://YOUR-IP:8554/teststream
```

---

## 3. Install Web Editor

```bash
sudo ./config-editor/Install_MediaMTX_Config_Editor.sh
```

> **Note:** The `mediamtx_config_editor.py` file must be in `./config-editor/` or the current directory.

**Access:** `http://YOUR-IP:5000`
**Default login:** admin / admin

**Change the admin password immediately after first login!**

---

## 4. Add SSL (Optional)

**Prerequisites:**
- Domain name
- DNS A record pointing to VPS IP
- MediaMTX and Web Editor installed and working

```bash
sudo ./ubuntu-22.04/Ubuntu_22_04_Install_MediaMTX_Caddy.sh
```

**During setup:**
- Enter your domain name
- Confirm domain name

**Access:** `https://yourdomain.com`

> **Note:** Caddy writes certificate paths to mediamtx.yml but does NOT enable encryption. Enable RTSPS/HLS encryption via the Web Editor when ready.

---

## 5. Enable Encryption (After Caddy)

### RTSPS
1. Web Editor → Advanced YAML
2. Change `rtspEncryption: "no"` to `rtspEncryption: "optional"`
3. Save → Restart MediaMTX

### HLS Encryption
1. Web Editor → Advanced YAML
2. Change `hlsEncryption: no` to `hlsEncryption: yes`
3. Save → Restart MediaMTX

---

## Verification Commands

**Check all services:**
```bash
systemctl status mediamtx
systemctl status mediamtx-webeditor
systemctl status caddy              # if installed
```

**View logs:**
```bash
journalctl -u mediamtx -f
journalctl -u mediamtx-webeditor -f
journalctl -u caddy -f              # if installed
```

**Test RTSP stream:**
```bash
ffplay rtsp://YOUR-IP:8554/teststream
```

---

## Quick Command Reference

### Service Management
```bash
systemctl restart mediamtx
systemctl restart mediamtx-webeditor
systemctl reload caddy
```

### Configuration
```bash
# MediaMTX config
nano /usr/local/etc/mediamtx.yml

# Caddyfile
cat /etc/caddy/Caddyfile

# Web editor
nano /opt/mediamtx-webeditor/mediamtx_config_editor.py
```

### User Management
All user management is done through the Web Editor at `http://YOUR-IP:5000` → Users & Auth tab.

---

## File Locations

| Type | Location |
|------|----------|
| MediaMTX config | `/usr/local/etc/mediamtx.yml` |
| MediaMTX binary | `/usr/local/bin/mediamtx` |
| Web editor | `/opt/mediamtx-webeditor/` |
| Web editor users | `/opt/mediamtx-webeditor/users.json` |
| Group metadata | `/opt/mediamtx-webeditor/group_names.json` |
| Config backups | `/opt/mediamtx-webeditor/backups/` |
| Recordings | `/opt/mediamtx-webeditor/recordings/` |
| Caddy certs | `/var/lib/caddy/.local/share/caddy/certificates/` |
| Caddyfile | `/etc/caddy/Caddyfile` |

---

## Default Credentials

| Item | Value |
|------|-------|
| Web editor login | admin / admin |
| HLS viewer | hlsviewer / (random, shown at install) |
| Teststream | No auth required |

---

## Streaming URLs

| Protocol | Publish | View |
|----------|---------|------|
| **RTSP** | `rtsp://user:pass@IP:8554/live/uas1` | `rtsp://user:pass@IP:8554/uas1` |
| **RTSPS** | `rtsps://user:pass@IP:8322/live/uas1` | `rtsps://user:pass@IP:8322/uas1` |
| **HLS** | (auto from RTSP) | `http://IP:8888/uas1/` |
| **SRT** | `srt://IP:8890?streamid=publish:live/uas1` | `srt://IP:8890?streamid=read:uas1` |

---

## Troubleshooting

**MediaMTX won't start:**
```bash
journalctl -u mediamtx -n 50 --no-pager
```

**Web editor won't load:**
```bash
journalctl -u mediamtx-webeditor -n 50 --no-pager
# Check: pip3 install Flask ruamel.yaml requests psutil
```

**Caddy SSL fails:**
```bash
journalctl -u caddy -n 50 --no-pager
dig yourdomain.com
caddy validate --config /etc/caddy/Caddyfile
```

**RTSPS not working:**
```bash
grep rtspEncryption /usr/local/etc/mediamtx.yml
grep rtspServerKey /usr/local/etc/mediamtx.yml
```

---

## Support

- **Repository:** [github.com/takwerx/mediamtx-installer](https://github.com/takwerx/mediamtx-installer)
- **Issues:** [Report bugs/issues](https://github.com/takwerx/mediamtx-installer/issues)
- **YouTube:** [The TAK Syndicate](https://www.youtube.com/@thetaksyndicate6234)
- **Website:** [https://www.thetaksyndicate.org/](https://www.thetaksyndicate.org/)

---

**Created by:** [The TAK Syndicate](https://www.youtube.com/@thetaksyndicate6234) | [https://www.thetaksyndicate.org/](https://www.thetaksyndicate.org/)
