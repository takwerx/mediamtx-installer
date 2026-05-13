# Web Editor v2.0.6 Release Notes

**Release Date:** May 13, 2026  
**Minimum MediaMTX Version:** v1.17.0  
**Recommended MediaMTX Version:** v1.17.0 or v1.18.x (with infra-TAK Caddyfile fix)

---

## Fixes

### Fixed: Share link playback broken on MediaMTX v1.18.x

Share links (`/shared/<token>`) showed "Stream Offline" on servers running MediaMTX v1.18.0 or later. The master HLS manifest loaded correctly, but the variant manifest (`main_stream.m3u8?session=...`) returned `502 Bad Gateway` from the web editor's proxy.

**Root cause:** MediaMTX v1.18.x added session-scoped HLS URLs — the master manifest references variant URLs with a `?session=<uuid>` query parameter that MediaMTX uses to track viewers. The web editor's HLS proxy function (`hls_fetch_for_share`) only received the path portion of the URL from Flask's `<path:subpath>` route converter, dropping the query string entirely. Without the session token, MediaMTX returned `401 Unauthorized`, which Flask converted to a 502.

**Fix:**
- `hls_fetch_for_share()` now accepts the original request's query string and appends it to the upstream MediaMTX URL — preserving `?session=...` and `?cookieCheck=1` parameters
- Switched the HTTP client from `urllib.request.urlopen` to `requests.Session()` — maintains a cookie jar across the v1.18.x cookieCheck redirect cycle that happens on first fetch, so the session cookie is properly preserved on follow-up requests

This affects only the `/shared/<token>` share link feature. MediaMTX v1.17.0 has no session tokens or cookieCheck, so this code path was previously silent — the bug only became visible when servers were upgraded to v1.18.x.

---

## What still requires the infra-TAK Caddyfile fix

Share links work after this update on all MediaMTX versions (v1.17.0 and v1.18.x). The Active Streams → Watch button on infra-TAK servers running v1.18.x still requires the [Caddyfile `header_down Location ^ /hls-proxy` change](docs/INFRA-TAK-CADDY-HLS-v1.18.md) — that's a separate code path through Caddy, not Flask, and the rewrite happens at the proxy layer.

---

## Known related issue — infra-TAK LDAP overlay

The infra-TAK LDAP overlay (`mediamtx_ldap_overlay.py`) contains a parallel `_hls_fetch()` function (used by the overlay's `/watch/<stream>` admin route) with the same query-string-dropping bug. The overlay's `/hls-proxy/` route is also affected if it ever serves a request directly from Flask (rare — Caddy normally intercepts `/hls-proxy/*` before Flask sees it).

The infra-TAK team should apply the same fix pattern to `_hls_fetch()`:
- Forward `request.query_string`
- Use `requests.Session()` instead of `urllib.request.urlopen`

---

## Full changelog since v2.0.0

- **v2.0.6** — Fix share link playback on MediaMTX v1.18.x (forward query string + cookie persistence in HLS proxy)
- **v2.0.5** — Fix HLS Watch button on infra-TAK (use `/hls-proxy/` URLs when MediaMTX is localhost-bound)
- **v2.0.4** — Fix YAML corruption from v2.0.3 FFmpeg removal, no-cache headers, post-update reload polling
- **v2.0.3** — Auto-enable `rtspDemuxMpegts: true` on existing installations
- **v2.0.2** — Auto-remove FFmpeg `/live` path, backup version label fix
- **v2.0.1** — infra-TAK LDAP overlay startup fix, overlay re-sync in `apply_update()`
- **v2.0.0** — Native MPEG-TS demuxing, HLS Tuning page, HLS.js player fixes
