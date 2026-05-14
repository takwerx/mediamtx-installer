# Tech Context

## Languages & Runtimes

| Component | Language | Runtime |
|-----------|----------|---------|
| MediaMTX install script | Bash | zsh/bash on Ubuntu 22.04 |
| Caddy SSL script | Bash | zsh/bash on Ubuntu 22.04 |
| Web editor installer | Bash | zsh/bash |
| Web editor application | Python 3 | CPython 3.x (system Python on Ubuntu 22.04) |
| Ku-band simulator | Python 3 + Bash | CPython + tc (iproute2) |

## Key Dependencies

### Web Editor (Python)
| Package | Purpose |
|---------|---------|
| `flask` | Web framework — routing, sessions, JSON responses |
| `ruamel.yaml` | Comment-preserving YAML read/write for `mediamtx.yml` |
| `psutil` | System metrics (CPU, RAM, disk, network) for dashboard |
| `requests` | HTTP calls to GitHub API for version checks and update downloads. **Not used for HLS proxy fetches** — see `hls_fetch_for_share()` which uses `urllib.request` to avoid cookie persistence (see `systemPatterns.md`) |
| `secrets` | Secure random token generation (share links, app secret key) |

All installed via `pip3` by `Install_MediaMTX_Config_Editor.sh`.

### Infrastructure (Target Server)
| Tool | Purpose |
|------|---------|
| `mediamtx` | The core media server binary (auto-downloaded from GitHub releases) |
| `systemd` | Service management for mediamtx and mediamtx-webeditor |
| `ufw` | Firewall — managed automatically by protocol enable/disable |
| `caddy` | HTTPS reverse proxy + Let's Encrypt TLS certificates |
| `tc` (iproute2) | Traffic control for Ku-band simulator |

### MediaMTX Version Requirement
Minimum: **v1.17.0** (required for `rtspDemuxMpegts` support)
The install script always downloads the **latest release** from GitHub.

**v1.18.x compatibility notes:**
- v1.18.0 introduced HLS session tracking (cookieCheck redirects, `?session=<uuid>` query parameters on variant manifests). The web editor handles this transparently as of v2.0.8.
- For **infra-TAK servers running MediaMTX v1.18.x**, the Caddyfile must include `header_down Location ^ /hls-proxy` inside the `handle_path /hls-proxy/*` block, otherwise the `cookieCheck` redirect strips the `/hls-proxy/` prefix and breaks playback. See `docs/INFRA-TAK-CADDY-HLS-v1.18.md`.

## Target Platform
- **OS:** Ubuntu 22.04 LTS (Jammy)
- **Architecture:** x86_64 (standard VPS)
- **Minimum hardware:** 2GB RAM, 2 CPU cores; 4GB RAM+ recommended for HLS transcoding

## Key File Locations (Runtime)

| File | Path |
|------|------|
| MediaMTX binary | `/usr/local/bin/mediamtx` |
| MediaMTX config | `/usr/local/etc/mediamtx.yml` |
| Config backups | `/usr/local/etc/mediamtx_backups/` |
| Web editor | `/opt/mediamtx-webeditor/mediamtx_config_editor.py` |
| Web editor auth | `/opt/mediamtx-webeditor/.auth/credentials` |
| Theme config | `/opt/mediamtx-webeditor/theme_config.json` |
| Share links | `/opt/mediamtx-webeditor/share_links.json` |
| Recordings | `/opt/mediamtx-webeditor/recordings/` |
| Caddyfile | `/etc/caddy/Caddyfile` |
| TLS certs | `/var/lib/caddy/.local/share/caddy/certificates/` |
| Simulator dir | `/opt/mediamtx-webeditor/ku-band-simulator/` (overridable via `MEDIAMTX_SIMULATOR_DIR` env var) |

## Source of Truth URLs
- GitHub repo: `https://github.com/takwerx/mediamtx-installer`
- Raw editor script: `https://raw.githubusercontent.com/takwerx/mediamtx-installer/main/config-editor/mediamtx_config_editor.py`
- GitHub releases API: `https://api.github.com/repos/takwerx/mediamtx-installer/releases/latest`

## Development Notes
- The web editor is a **single large Python file** — there is no build step, no bundler, no transpilation
- HTML/CSS/JS are embedded as strings inside Python via `render_template_string`
- Testing is manual — see `TESTING.md` for the full feature test checklist
- No automated test suite exists currently
- The `truck_60.ts` file in `config-editor/` appears to be a test MPEG-TS sample file
