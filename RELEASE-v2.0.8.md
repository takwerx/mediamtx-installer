# MediaMTX Installer v2.0.8

## Hotfix: Shared HLS links on MediaMTX v1.18.x (the real fix)

v2.0.6 and v2.0.7 both failed to fix shared `/shared/<token>` links on
MediaMTX v1.18.x. This release fixes the root cause.

### Why v2.0.6 and v2.0.7 didn't work

MediaMTX v1.18.0 introduced HLS session tracking. On the first fetch it
issues a 302 with `Set-Cookie: cookieCheck=1` and a `?cookieCheck=1` query
parameter to validate the client. Once validated, MediaMTX picks ONE of
two session modes:

- **Cookie-based** if the client returns the cookie on subsequent requests
  → manifest URLs are emitted *without* `?session=...`
- **URL-based** if the client doesn't return the cookie → manifest URLs
  are emitted *with* `?session=<uuid>...`

The Python proxy creates a fresh fetch on every Flask call. Cookies cannot
survive between calls because Flask is request-stateless. So we **need**
URL-based session mode for the browser to round-trip the session back
through us.

- **v2.0.6** used `requests.Session()` — preserved cookies → cookie mode →
  manifest came back without `?session=...` → next call had no cookie and
  no session → 401.
- **v2.0.7** used plain `requests.get()` — but `requests` uses urllib3
  internally, which **also** preserves cookies across the redirect chain
  within a single call. Same outcome as v2.0.6.

### The real fix

Switch the share proxy to `urllib.request.urlopen`. Python's built-in
urllib has no cookie jar by default, so Set-Cookie headers are silently
dropped — even across redirects. MediaMTX never sees the cookieCheck
cookie come back, so it falls into URL-based session mode and embeds
`?session=<uuid>` in variant manifest URLs.

The browser then sends those URLs back through `/shared-hls/<token>/...`.
The query-string forwarding added in v2.0.6 (still in place) carries
`?session=...` through to MediaMTX, which validates URL-side and returns
the variant manifest and segments correctly.

### Net result

- v1.17.x share links: unchanged (no session tracking → no query strings)
- v1.18.x share links: now work end-to-end (master → variant → segments)

### Files changed

- `config-editor/mediamtx_config_editor.py`
  - `CURRENT_VERSION` → `v2.0.8`
  - `hls_fetch_for_share()` — replace `requests.get()` with
    `urllib.request.urlopen()` to eliminate cookie preservation

### Upgrade

Web Editor → Versions → **Update** (pulls v2.0.8 and restarts the service).
