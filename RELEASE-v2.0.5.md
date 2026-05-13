# Web Editor v2.0.5 Release Notes

**Release Date:** May 13, 2026  
**Minimum MediaMTX Version:** v1.17.0  
**Recommended MediaMTX Version:** v1.17.0 (see note on v1.18.x below)

---

## Fixes

### Fixed: HLS Watch button broken on infra-TAK servers

On infra-TAK deployments, port 8888 is firewalled externally (`8888/tcp DENY`) and MediaMTX is configured to bind to `127.0.0.1:8888`. The web editor was generating direct `https://domain:8888/...` HLS URLs that the browser could never reach, causing `ERR_CONNECTION_TIMED_OUT` in the Watch popup.

**Root cause:** The web editor's HLS URL generation did not account for localhost-bound MediaMTX. It always constructed direct port-8888 URLs, which are inaccessible when the server is behind Caddy with firewall hardening.

**Fix:** A new `is_hls_localhost_bound()` helper reads `hlsAddress` from `mediamtx.yml`. When it detects `127.0.0.1:8888`, all HLS URLs are generated as `/hls-proxy/<stream>/index.m3u8` — a relative path that Caddy routes internally to MediaMTX without touching the firewall.

Standalone deployments (where `hlsAddress` is `:8888` or `0.0.0.0:8888`) are completely unaffected — they continue to use direct port-8888 URLs with Basic Auth as before.

**Affected areas fixed:**
- Active Streams → Watch button
- Test Streams → Watch button
- Share link player page (`/watch/<stream>`)

**watchStream JS updated:** When using the `/hls-proxy/` path, the browser-side Basic Auth (`xhrSetup`) is now skipped. Authentication is handled server-side — Caddy proxies to MediaMTX on localhost, which allows all requests from `127.0.0.1` via the `user: any` rule.

---

## MediaMTX v1.18.x — infra-TAK Caddyfile update required

MediaMTX v1.18.0 introduced **HLS session tracking**. On first manifest request, MediaMTX issues a `302` redirect to `?cookieCheck=1` to verify the client can store cookies.

The current infra-TAK Caddyfile's `handle_path /hls-proxy/*` block strips the `/hls-proxy/` prefix before proxying to MediaMTX. When MediaMTX issues the cookie-check redirect, the `Location` header no longer contains the `/hls-proxy/` prefix. The browser follows the redirect to a path Caddy has no handler for — resulting in a 404.

**This is an infra-TAK Caddyfile issue, not a web editor issue.** MediaMTX v1.17.0 does not have this redirect, so servers staying on v1.17.0 are unaffected.

**Recommendation:** Stay on MediaMTX v1.17.0 until the infra-TAK Caddyfile template is updated. See [`docs/INFRA-TAK-CADDY-HLS-v1.18.md`](docs/INFRA-TAK-CADDY-HLS-v1.18.md) for the required Caddyfile change to hand off to the infra-TAK team.

---

## Full changelog since v2.0.0

- **v2.0.5** — Fix HLS Watch button on infra-TAK (use `/hls-proxy/` URLs when MediaMTX is localhost-bound)
- **v2.0.4** — Fix YAML corruption from v2.0.3 FFmpeg removal, no-cache headers, post-update reload polling
- **v2.0.3** — Auto-enable `rtspDemuxMpegts: true` on existing installations
- **v2.0.2** — Auto-remove FFmpeg `/live` path, backup version label fix
- **v2.0.1** — infra-TAK LDAP overlay startup fix, overlay re-sync in `apply_update()`
- **v2.0.0** — Native MPEG-TS demuxing, HLS Tuning page, HLS.js player fixes
