# infra-TAK Caddyfile Update — MediaMTX HLS v1.18.x Compatibility

**Affects:** All infra-TAK servers running MediaMTX v1.18.0 or later  
**Status:** Required for HLS Watch playback to work on v1.18.x  
**infra-TAK change:** Caddyfile template — `stream.DOMAIN` block only  

---

## Background

MediaMTX v1.18.0 introduced **HLS session tracking**. On the first manifest request, MediaMTX returns a `302` redirect to `?cookieCheck=1` with a session cookie. The browser follows the redirect, MediaMTX verifies the cookie, then redirects back to the original manifest URL. This is a one-time handshake per browser session.

The current infra-TAK Caddyfile handles HLS via:

```caddy
handle_path /hls-proxy/* {
    reverse_proxy https://127.0.0.1:8888 {
        transport http {
            tls_server_name <stream-domain>
        }
    }
}
```

`handle_path` strips the `/hls-proxy/` prefix before forwarding to MediaMTX. When MediaMTX issues the cookie-check redirect, its `Location` header is relative to its own path (e.g. `/teststream/index.m3u8?cookieCheck=1`) — without the `/hls-proxy/` prefix. The browser follows the redirect to `/teststream/index.m3u8?cookieCheck=1`, which has no Caddy handler, and gets a 404. HLS playback fails.

MediaMTX v1.17.0 does **not** issue this redirect, so servers staying on v1.17.0 are unaffected.

---

## Required Caddyfile Change

In the `stream.DOMAIN` block, update the `/hls-proxy/` handler to intercept `3xx` responses from MediaMTX and rewrite the `Location` header to add the `/hls-proxy` prefix back before returning to the browser.

### Before

```caddy
handle_path /hls-proxy/* {
    reverse_proxy https://127.0.0.1:8888 {
        transport http {
            tls_server_name <stream-domain>
        }
    }
}
```

### After

```caddy
handle_path /hls-proxy/* {
    reverse_proxy https://127.0.0.1:8888 {
        transport http {
            tls_server_name <stream-domain>
        }
        @mtx_redirect status 3xx
        handle_response @mtx_redirect {
            header +Set-Cookie {http.reverse_proxy.header.Set-Cookie}
            redir /hls-proxy{http.reverse_proxy.header.Location} 302
        }
    }
}
```

`<stream-domain>` stays as-is — replace with whatever value is already in the template (e.g. `stream.{base_domain}`).

---

## What the change does

| Line | Purpose |
|------|---------|
| `@mtx_redirect status 3xx` | Matches any redirect response from MediaMTX |
| `header +Set-Cookie ...` | Copies the `mediamtx_session` cookie from MediaMTX's response to the browser, so the cookie check can complete |
| `redir /hls-proxy{...Location} 302` | Rewrites the redirect destination to add `/hls-proxy` back, so the browser's follow-up request lands in the correct Caddy handler |

---

## Cookie check flow after the fix

1. Browser → `https://stream.domain/hls-proxy/teststream/index.m3u8`
2. Caddy strips prefix → MediaMTX gets `GET /teststream/index.m3u8`
3. MediaMTX (v1.18.x): `302 /teststream/index.m3u8?cookieCheck=1` + `Set-Cookie: mediamtx_session=X`
4. Caddy intercepts, rewrites: `302 /hls-proxy/teststream/index.m3u8?cookieCheck=1` + forwards cookie ✓
5. Browser follows → `/hls-proxy/teststream/index.m3u8?cookieCheck=1` → Caddy handles ✓
6. Caddy strips prefix → MediaMTX gets `GET /teststream/index.m3u8?cookieCheck=1` with cookie
7. MediaMTX validates cookie: `302 /teststream/index.m3u8`
8. Caddy rewrites: `302 /hls-proxy/teststream/index.m3u8` ✓
9. Browser follows → manifest served, HLS plays ✓

---

## Compatibility

- **MediaMTX v1.17.0:** No `3xx` redirects for HLS — `@mtx_redirect` never matches. Zero impact.
- **MediaMTX v1.18.0+:** Cookie check completes correctly. HLS plays.

This change is backwards-compatible and safe to deploy to all infra-TAK servers regardless of their current MediaMTX version.
