# Active Context

## Current State
**v2.0.8** is the latest stable release (May 13, 2026). All three infra-TAK servers (tak-10, responder, ssdnodes) need to be updated; tak-10 already runs v2.0.8.

## Most Recent Work
A multi-release effort (v2.0.5 → v2.0.8) to fix HLS playback in two scenarios that broke after the infra-TAK deployment topology and MediaMTX v1.18.x rolled out:

1. **HLS Watch button (admin)** — broken on servers where MediaMTX is bound to `127.0.0.1:8888` and accessed only through Caddy's `/hls-proxy/` route. The web editor was generating direct `https://domain:8888/...` URLs which timed out from the browser.
2. **Share-link playback** on MediaMTX v1.18.x — broken because v1.18.0 introduced HLS session tracking with cookieCheck redirects and `?session=<uuid>` query parameters on variant manifest URLs. The share proxy was dropping query strings and (in the failed first attempts) preserving cookies in ways that broke MediaMTX's session model.

### Release Summary

| Version | Date | Fix |
|---------|------|-----|
| v2.0.5 | May 13, 2026 | `is_hls_localhost_bound()` helper; HLS URLs use `/hls-proxy/` when MediaMTX is on 127.0.0.1; `watchStream` JS skips Basic Auth `xhrSetup` for proxied URLs |
| v2.0.6 | May 13, 2026 | **Failed attempt 1** at share-link fix on v1.18.x — added query-string forwarding in `hls_fetch_for_share` (kept), switched to `requests.Session()` (mistake — preserved cookies → broke variant manifest fetch) |
| v2.0.7 | May 13, 2026 | **Failed attempt 2** — dropped `Session()` but kept `requests.get()`. Turned out `requests` uses urllib3 internally, which also preserves cookies across the redirect chain. Same broken outcome |
| v2.0.8 | May 13, 2026 | **Real fix** — replaced `requests.get()` with `urllib.request.urlopen()` in `hls_fetch_for_share`. urllib has no cookie jar by default, so MediaMTX falls back to URL-based session tracking and `?session=` survives the round-trip |

### Critical Insight: MediaMTX v1.18.x HLS Session Tracking

MediaMTX v1.18.0 introduced a dual-mode session model:

- **Cookie-based** — when the client returns the `cookieCheck` cookie on subsequent requests, manifest URLs are emitted *without* `?session=...`
- **URL-based** — when the client does *not* return the cookie, MediaMTX embeds `?session=<uuid>` in variant manifest URLs

A Flask proxy is request-stateless: cookies cannot survive between calls. So **URL-based mode is the only viable mode for a per-request proxy**. To force URL-based mode, the proxy fetcher must NOT preserve cookies during its internal redirect chain. `urllib.request.urlopen` achieves this naturally; `requests` (with or without Session) does not.

### Infra-TAK Caddyfile change (separate handoff)

Documented in `docs/INFRA-TAK-CADDY-HLS-v1.18.md`. Required on any infra-TAK server running MediaMTX v1.18.x because v1.18's `cookieCheck` 302 redirect strips the `/hls-proxy/` prefix from the `Location` header. Fix: `header_down Location ^ /hls-proxy` in the `handle_path /hls-proxy/*` block. `header_down` was chosen over `handle_response` because `handle_response` breaks `handle_path` termination and triggers `forward_auth`. This file is for the infra-TAK team to apply to their Caddyfile template — it does not live in our repo's installer.

## Recent Git Commits (latest first)
1. `b0b5985` — v2.0.8: fix shared HLS links on MediaMTX v1.18.x (the real fix)
2. `e59ce3a` — v2.0.7: fix shared HLS links on MediaMTX v1.18.x (revised)
3. `404bdf6` — v2.0.6: fix share link playback on MediaMTX v1.18.x
4. `94b4196` — docs: clarify HLS handoff doc — TL;DR + supersession + verification
5. `7cba475` — docs: correct infra-TAK Caddyfile HLS fix — use header_down instead of handle_response
6. `38baef9` — docs: add v2.0.5 release notes and infra-TAK Caddyfile HLS fix handoff
7. (v2.0.5 commit) — HLS URL generation fix, `is_hls_localhost_bound()` helper, `watchStream` JS proxied-URL handling

## Active Decisions & Considerations
- **Cookie persistence is a footgun.** The `requests` library preserves cookies across redirects even without an explicit `Session()`. Any code that proxies HLS for MediaMTX v1.18+ must use `urllib.request` or otherwise guarantee zero cookie persistence.
- **Per-token Session pooling** was considered for share links but rejected — Flask process restarts would lose sessions, and URL-based mode works without state.
- **infra-TAK overlay parity** — the LDAP overlay's `_hls_fetch` function has the same cookie/query-string bug as our pre-v2.0.8 code. Flagged for the infra-TAK team; not our code to fix.
- **The `document.write` warning** in Chrome for `hls.js@latest` is a known non-blocking deprecation. Future work item, not urgent.

## Next Steps (Known TODOs)
- [ ] Update responder and ssdnodes to v2.0.8 (Versions → Update in web editor)
- [ ] Verify HLS Watch button works on responder and ssdnodes after update
- [ ] Infra-TAK team to apply Caddyfile change from `docs/INFRA-TAK-CADDY-HLS-v1.18.md` when any infra-TAK server is upgraded to MediaMTX v1.18.x
- [ ] Infra-TAK team to fix `_hls_fetch` in `mediamtx_ldap_overlay.py` (same query-string + cookie issue we fixed in v2.0.8)
- [ ] Consider replacing `document.write` Hls.js injection with a proper `<script>` tag

## Open Questions
- Should the installer pin a specific MediaMTX version (e.g. v1.17.x) rather than always pulling the latest? v1.18.x's session tracking is now compatible with the web editor, but each major MediaMTX release is a potential breakage vector.

## Abandoned Work
- **Rocky 9 support** — scripts in `rocky-9/` are abandoned; Ubuntu 22.04 is the only supported platform.
- **`requests`-based share proxy** (v2.0.6, v2.0.7) — replaced with `urllib.request` in v2.0.8.
