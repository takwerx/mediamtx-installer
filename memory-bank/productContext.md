# Product Context

## Why This Project Exists
Emergency services and tactical operations (ATAK, drone ISR, UAS) need reliable RTSP/HLS video streaming infrastructure that is:
- Fast to deploy (minutes, not hours)
- Manageable without deep Linux expertise
- Secure (HTTPS, RTSPS, user authentication)
- Compatible with TAKICU / ATAK UAS Tool / ISR cameras that push MPEG-TS–wrapped H264 over RTSP

MediaMTX (formerly rtsp-simple-server) is the ideal engine, but raw deployment requires manual YAML editing, firewall setup, systemd configuration, and certificate management. This project automates all of that.

## Problems It Solves

| Problem | Solution |
|---------|----------|
| Manual YAML editing to configure MediaMTX | Web editor UI manages every setting |
| Complex SSL/certificate setup | One-script Caddy installer with Let's Encrypt |
| MPEG-TS RTSP sources failing HLS playback | `rtspDemuxMpegts: true` enabled by default — no FFmpeg transcoding |
| infra-TAK LDAP overlay conflicts on update | LDAP overlay detection at startup; overlay re-sync on update |
| Stale YAML from migration bugs (v2.0.3) | Self-healing startup passes in v2.0.4 |

## How It Works (User Journey)

1. Clone repo on fresh Ubuntu 22.04 VPS
2. Run `Ubuntu_22.04_MediaMTX_install.sh` → MediaMTX running with production YAML in ~5 min
3. Run `Install_MediaMTX_Config_Editor.sh` → Web editor at `http://IP:5000`
4. (Optional) Run `Ubuntu_22.04_Install_MediaMTX_Caddy.sh` → HTTPS + RTSPS via Let's Encrypt
5. All ongoing management through the web editor (users, protocols, recordings, streams, logs)

## Key User-Facing Features (Web Editor v2.0.4)

- **Dashboard** — live system metrics (CPU, RAM, disk, network), stream counts, uptime
- **Active Streams** — view, watch (HLS player), share (token-based links, 4h active streams / configurable external)
- **External Sources** — pull RTSP/SRT/RTMP/UDP MPEG-TS streams into MediaMTX
- **Test Streams** — upload MP4, play/stop, optimize for streaming
- **Recordings** — manage recording rules, retention, disk usage
- **Protocols** — toggle RTSP/RTMP/SRT/HLS, set ports, encryption mode
- **HLS Tuning** — segment count/duration, variant, always remux, write queue; presets for LAN/Internet/Satellite
- **MPEG-TS demux toggle** — enable/disable from UI without YAML editing
- **Users & Auth** — CRUD for MediaMTX path-level users with agency/group labels
- **Advanced YAML** — raw editor with automatic backup before save
- **Service Control** — start/stop/restart MediaMTX and webeditor
- **Firewall (UFW)** — view/add/remove rules; protocol toggles automatically manage ports
- **Version Management** — check for updates, apply update (with poll-until-ready reload), rollback
- **Web Users** — admin/viewer roles, self-registration, email notifications
- **Styling/Theme** — gradient header, accent color, logo, title; quick presets (Blue, Red, Tactical Green, Blackout, etc.)
- **Ku-band Link Simulator** — one-click traffic impairment (delay/jitter/loss) per external source for HLS satellite testing
- **Live Logs** — real-time MediaMTX log stream in browser

## infra-TAK Integration
When deployed via infra-TAK, an LDAP overlay (`mediamtx_ldap_overlay.py`) wraps the web editor for Authentik authentication. The editor detects this overlay at startup and skips conflicting route registration. Updates automatically re-sync the overlay.
