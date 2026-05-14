# System Patterns

## Repository Structure

```
mediamtx-installer/
├── ubuntu-22.04/
│   ├── Ubuntu_22.04_MediaMTX_install.sh          # Step 1: MediaMTX core install
│   └── Ubuntu_22.04_Install_MediaMTX_Caddy.sh    # Step 3: SSL/Let's Encrypt (optional)
├── config-editor/
│   ├── Install_MediaMTX_Config_Editor.sh          # Step 2: Web editor installer
│   ├── mediamtx_config_editor.py                  # Web editor app (Flask, ~12k lines)
│   └── SERVICE-COMMANDS.md                        # Quick service command reference
├── scripts/
│   └── ku-band-simulator/                         # Link impairment scripts
│       ├── simulator_controller.py
│       ├── ku_band_simulator_on.sh
│       ├── ku_band_simulator_off.sh
│       └── ku_band_simulator.conf.example
├── memory-bank/                                   # Cursor Memory Bank (this folder)
├── MEDIAMTX-DEPLOYMENT-GUIDE.md
├── MEDIAMTX-QUICK-START.md
├── TESTING.md
├── RELEASE-v2.0.x.md                             # Release notes per version
└── README.md
```

## Deployment Architecture (Runtime)

```
Ubuntu 22.04 VPS
├── /usr/local/bin/mediamtx                       # MediaMTX binary (auto-downloaded latest)
├── /usr/local/etc/mediamtx.yml                   # MediaMTX config (managed by web editor)
├── /usr/local/etc/mediamtx_backups/              # Auto-backups before each save
├── /opt/mediamtx-webeditor/
│   ├── mediamtx_config_editor.py                 # Web editor (auto-updates from GitHub)
│   ├── .auth/credentials                         # Web editor user credentials (hashed)
│   ├── users.json                                # (legacy) web editor users
│   ├── group_names.json                          # Agency/group label metadata
│   ├── theme_config.json                         # UI theme settings
│   ├── agency_logo                               # Uploaded logo file
│   ├── share_links.json                          # Token-based share links
│   ├── share_mode.json                           # Share link mode config
│   ├── srt_passphrase_backup.json
│   ├── recordings/                               # MediaMTX recordings
│   ├── backups/                                  # Web editor script backups
│   └── ku-band-simulator/                        # Simulator scripts
├── /etc/caddy/Caddyfile                          # Caddy reverse proxy config (if SSL)
└── /var/lib/caddy/.local/share/caddy/certificates/  # Let's Encrypt certs

Systemd services:
  mediamtx              → MediaMTX core server
  mediamtx-webeditor    → Flask web editor on :5000
  caddy                 → HTTPS reverse proxy (optional)
```

## Key Design Patterns

### Single-File Web Application
The entire web editor is a single Python file (`mediamtx_config_editor.py`, ~12k lines). HTML, CSS, JavaScript, and Python backend are all in one file using Flask's `render_template_string`. This is intentional — simplifies deployment and self-update (just replace the .py file and restart).

### Self-Update Pattern
The web editor checks GitHub releases API for newer versions. When an update is available:
1. Downloads new `.py` from `raw.githubusercontent.com`
2. Creates a backup of current version
3. Overwrites itself
4. Restarts the systemd service
5. Polls service until healthy (not blind delay)
6. Reloads browser page

### YAML Mutation Pattern
MediaMTX config is managed via `ruamel.yaml` (comment-preserving YAML library). Before every save:
- A timestamped backup is written to `/usr/local/etc/mediamtx_backups/`
- The in-memory YAML object is modified
- Written back to disk
- MediaMTX auto-reloads via inotify/signal

### Startup Migration Passes
On startup, the editor runs sequential migration/healing passes:
1. Check for `rtspDemuxMpegts` in YAML — add if missing (v2.0.3)
2. Remove legacy `~^live/(.+)$` FFmpeg re-publish path using indentation-based block detection (v2.0.2, fixed in v2.0.4)
3. Clean orphaned `rtsp://localhost:8554/$G1` and `runOnReadyRestart: true` lines left by v2.0.3 bug (v2.0.4)

### Deployment Topology Detection
Two topologies are supported and auto-detected from `mediamtx.yml`:

- **Standalone** — MediaMTX binds to `0.0.0.0:8888` (or all interfaces). HLS is reachable directly from the browser. UFW is opened for port 8888.
- **Infra-TAK / Caddy-proxied** — MediaMTX binds to `127.0.0.1:8888`. UFW blocks 8888 externally. Caddy's `handle_path /hls-proxy/*` block routes browser traffic to MediaMTX internally. HLS URLs must be generated as `/hls-proxy/...` relative paths.

`is_hls_localhost_bound()` is the runtime check that gates this behavior in HLS URL generation.

### LDAP Overlay Detection
At startup, checks for `/opt/mediamtx-webeditor/mediamtx_ldap_overlay.py`. If present, skips route registration that would conflict with the overlay. This is a flag-based pattern — no dynamic loading.

### Token-Based Share Links
Active streams can generate 4-hour share links. External sources can generate configurable-duration links. Tokens are stored in `share_links.json`. Expired or revoked links show "Link Expired or Revoked." The `/shared/<token>` route renders a self-contained HTML5 player that fetches the manifest via `/shared-hls/<token>/<path:subpath>`, which proxies to MediaMTX on `127.0.0.1:8888` with the `hlsviewer` credential.

### HLS URL Generation: Localhost-Bound vs Direct (v2.0.5+)
The web editor checks `hlsAddress` in `mediamtx.yml` via `is_hls_localhost_bound()`. If MediaMTX is bound to `127.0.0.1` / `localhost` (infra-TAK / Caddy-proxy topology), HLS URLs for the admin Watch button and Active Streams panel are generated as **relative `/hls-proxy/<path>/index.m3u8` URLs** so Caddy routes them internally. Otherwise the editor generates **absolute `https://domain:8888/<path>/index.m3u8` URLs** for direct browser-to-MediaMTX playback. The `watchStream` JS detects the `/hls-proxy/` prefix and skips the Basic Auth `xhrSetup` (Caddy injects auth on the upstream side).

### Share-Link HLS Proxy: No Cookie Persistence (v2.0.8+)
The `hls_fetch_for_share()` function deliberately uses `urllib.request.urlopen` (NOT the `requests` library) because urllib has no cookie jar by default. This forces MediaMTX v1.18.x into **URL-based** HLS session tracking — `?session=<uuid>` is embedded in variant manifest URLs that the browser then sends back through `/shared-hls/<token>/...`. The Flask route forwards `request.query_string` to MediaMTX so the session is recognized end-to-end. **Critical:** `requests.get()` (even without an explicit `Session`) preserves cookies via urllib3's internal redirect handler and breaks this pattern by pushing MediaMTX into cookie-based session mode — cookies then die between Flask calls and the variant fetch 401s. Any future HLS-proxy code must follow the urllib pattern.

### Ku-band Simulator
Shell scripts (`tc` / traffic control) run on the receiver side to impair incoming stream traffic with delay, jitter, and packet loss. Controlled via `simulator_controller.py` and surfaced in the web editor per-source.

## Protocol Port Map

| Protocol | Port | Transport |
|----------|------|-----------|
| RTSP | 8554 | TCP |
| RTSPS | 8322 | TCP |
| HLS | 8888 | TCP |
| SRT | 8890 | UDP |
| RTP | 8000 | UDP |
| RTCP | 8001 | UDP |
| RTMP | 1935 | TCP |
| RTMPS | 1936 | TCP |
| Web Editor | 5000 | TCP |
| HTTP (Caddy) | 80 | TCP |
| HTTPS (Caddy) | 443 | TCP |

## Built-in MediaMTX Users (Post-Install)

| User | Purpose | Restriction |
|------|---------|-------------|
| FFmpeg localhost | Internal transcoding | 127.0.0.1 only, no auth |
| hlsviewer | HLS browser playback | Random password (shown at install) |
| (anonymous) | teststream path | No auth, read-only on `/teststream` |
