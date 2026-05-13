# MediaMTX Installer v2.0.7

## Hotfix: Shared HLS links on MediaMTX v1.18.x (revised)

v2.0.6 attempted to fix shared `/shared/<token>` links on MediaMTX v1.18.x by
switching the proxy fetcher to `requests.Session()` to persist cookies across
the `cookieCheck=1` redirect cycle. That fix worked for the **first** fetch
(the master manifest), but broke the **second** fetch (the variant manifest):

- With a persistent cookie jar, MediaMTX uses **cookie-based** session
  tracking and omits `?session=` from the manifest URLs.
- Each Flask call creates its own fresh upstream fetch, so the cookie is
  destroyed between calls. The second-level variant fetch arrives at
  MediaMTX with neither a session cookie nor a `?session=` query — and
  MediaMTX returns `401 Unauthorized`.

### The fix

Remove `requests.Session()` from `hls_fetch_for_share()` and use a plain
`requests.get()`. Cookies are intentionally **not** preserved across the
internal redirect cycle, which forces MediaMTX to fall back to **URL-based**
session tracking. The master manifest now contains URLs like:

```
main_stream.m3u8?session=c4ba7f9a-8fc9-4b13-9987-317b45f150ce
```

The browser sends those URLs back through `/shared-hls/<token>/...`. The
v2.0.6 query-string forwarding (still in place) carries `?session=...`
through to MediaMTX, which validates the session URL-side and returns the
variant manifest and segments correctly.

### Net result

- v1.17.x share links: unchanged (no session tracking, query string is empty)
- v1.18.x share links: now work end-to-end (master → variant → segments)

### Files changed

- `config-editor/mediamtx_config_editor.py`
  - `CURRENT_VERSION` → `v2.0.7`
  - `hls_fetch_for_share()` — drop `requests.Session()`, use plain `requests.get()`

### Upgrade

Web Editor → Versions → **Update** (pulls v2.0.7 and restarts the service).
