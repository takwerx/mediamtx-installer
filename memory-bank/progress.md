# Progress

## What Works (Completed & Stable)

### Installation Scripts
- [x] Ubuntu 22.04 MediaMTX install — fully automated, no prompts, ~5 min
- [x] Caddy SSL installer — Let's Encrypt, HTTPS reverse proxy, RTSPS cert paths auto-configured
- [x] Web editor installer — Python/Flask, systemd service, port 5000

### Web Editor Features (v2.0.8)
- [x] Dashboard with live metrics (CPU, RAM, disk, network, stream counts, uptime)
- [x] Active Streams — view, HLS player, share links (4h token)
- [x] External Sources — RTSP/SRT/RTMP/UDP MPEG-TS pull with share links (configurable duration)
- [x] Test Streams — upload MP4, play/stop, optimize
- [x] Recordings — rules, retention, disk usage
- [x] Protocols — RTSP/RTMP/SRT/HLS toggle, ports, encryption mode; UFW auto-managed
- [x] HLS Tuning — segment count/duration, variant, always remux, write queue; LAN/Internet/Satellite presets
- [x] MPEG-TS demux toggle from UI
- [x] Users & Auth — CRUD for MediaMTX path-level users with agency/group labels
- [x] Advanced YAML editor with auto-backup
- [x] Service Control — start/stop/restart
- [x] Firewall (UFW) management
- [x] Version management — check, update (poll-until-ready), rollback
- [x] Web Users — admin/viewer roles, self-registration, email notifications
- [x] Styling/Theme — gradient header, accent color, logo, title, quick presets
- [x] Ku-band Link Simulator — per-source traffic impairment
- [x] Live Logs — real-time MediaMTX log stream

### Integrations
- [x] infra-TAK LDAP overlay compatibility (detection, skip conflicting routes, re-sync on update)
- [x] Auto-update from GitHub releases with self-healing startup migrations

### Documentation
- [x] README.md
- [x] MEDIAMTX-QUICK-START.md
- [x] MEDIAMTX-DEPLOYMENT-GUIDE.md (referenced but not yet read — verify exists)
- [x] TESTING.md — full feature test checklist
- [x] Release notes for v2.0.0 through v2.0.8
- [x] `docs/INFRA-TAK-CADDY-HLS-v1.18.md` — handoff doc for infra-TAK team (Caddyfile fix required for MediaMTX v1.18.x compat)

## What's Left / In Progress

### Rocky 9 Support (Abandoned)
- Rocky 9 scripts (`rocky-9/Rocky_9_MediaMTX_install.sh`, `rocky-9/Rocky_9_Caddy_setup.sh`) exist in the repo but have been abandoned
- Ubuntu 22.04 remains the only supported platform

### Known Gaps
- [ ] No automated test suite — testing is entirely manual per `TESTING.md`
- [ ] No CI/CD pipeline
- [ ] `MEDIAMTX-DEPLOYMENT-GUIDE.md` referenced in README but not verified complete

## Known Issues (Historical — Fixed)

### Fixed in v2.0.8
- ~~MediaMTX v1.18.x share links return black screen — variant manifest fetch 401s because `?session=` query string is dropped and cookie-based session state can't survive between Flask calls~~ — Fixed in v2.0.8 by switching `hls_fetch_for_share` to `urllib.request.urlopen` (no cookie jar → MediaMTX uses URL-based session mode → `?session=` survives end-to-end)

### Fixed in v2.0.5
- ~~HLS Watch button times out on infra-TAK servers where MediaMTX is bound to `127.0.0.1:8888`~~ — Fixed by `is_hls_localhost_bound()` helper that switches HLS URL generation to `/hls-proxy/` relative paths when localhost-bound

### Fixed in v2.0.4
- ~~v2.0.3 introduced YAML corruption from FFmpeg path removal on multi-line `runOnReady` values~~ — Fixed in v2.0.4
- ~~Stale page served after updates due to browser caching~~ — Fixed in v2.0.4 (no-cache headers)
- ~~Blind 5s delay after update before page reload~~ — Fixed in v2.0.4 (poll-until-ready)
- ~~Backup files showed "unknown" version instead of actual version~~ — Fixed in v2.0.4

## Open Known Issues
- **`document.write` for `hls.js@latest`** — Chrome flags this as parser-blocking cross-site script. Non-blocking but should be replaced with proper `<script>` tag injection.
- **LDAP overlay `_hls_fetch`** (in infra-TAK's `mediamtx_ldap_overlay.py`, not our repo) — has the same v1.18.x cookie/query-string bug we fixed in v2.0.8. Flagged to the infra-TAK team.

## Version History

| Version | Date | Key Change |
|---------|------|-----------|
| v2.0.8 | May 13, 2026 | **Real fix** for share-link playback on MediaMTX v1.18.x — `urllib.request.urlopen` in share proxy (no cookie jar → URL-based session mode) |
| v2.0.7 | May 13, 2026 | (Failed) Dropped `requests.Session()` but plain `requests.get()` still preserved cookies via urllib3 — superseded by v2.0.8 |
| v2.0.6 | May 13, 2026 | (Failed) First attempt at share-link fix — added query-string forwarding (kept) + `requests.Session()` (mistake) — superseded by v2.0.8 |
| v2.0.5 | May 13, 2026 | HLS URL generation uses `/hls-proxy/` when MediaMTX bound to localhost; `watchStream` JS skips Basic Auth `xhrSetup` for proxied URLs |
| v2.0.4 | Mar 20, 2026 | Fix YAML corruption from v2.0.3, no-cache headers, poll-until-ready reload |
| v2.0.3 | Mar 18, 2026 | Auto-enable `rtspDemuxMpegts` on existing installs |
| v2.0.2 | Mar 18, 2026 | Auto-remove legacy FFmpeg `/live` path, update reload fix, backup version labels |
| v2.0.1 | — | infra-TAK LDAP overlay startup fix, overlay re-sync on update |
| v2.0.0 | — | Native MPEG-TS demuxing, HLS Tuning page, HLS.js fixes, `rtspDemuxMpegts` toggle |
| v1.1.9 | — | (prior release) |
| v1.1.8 | — | (prior release) |
