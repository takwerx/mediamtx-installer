# infra-TAK Caddyfile Update — MediaMTX HLS v1.18.x Compatibility

**Affects:** All infra-TAK servers running MediaMTX v1.18.0 or later  
**Status:** Required for HLS Watch playback to work on v1.18.x  
**infra-TAK change:** Caddyfile template — `stream.DOMAIN` block only  
**Scope:** One added line inside the existing `reverse_proxy` block  
**Doc revision:** 2026-05-13 (rev 2 — supersedes any earlier draft using `handle_response`)

---

## TL;DR — The change

In the `stream.DOMAIN` Caddyfile block, inside the existing `handle_path /hls-proxy/*` → `reverse_proxy https://127.0.0.1:8888` block, add this single line:

```caddy
header_down Location ^ /hls-proxy
```

That's the entire fix. No other directives need to be added or modified.

**Do NOT use `handle_response` + `redir` for this fix.** An earlier draft of this doc proposed that approach — it does not work in this Caddyfile because the catch-all `forward_auth` directive still fires after `handle_response` and redirects HLS traffic to Authentik. See the "Why not use `handle_response`?" section below for details.

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

In the `stream.DOMAIN` block, add a single `header_down` directive inside the `reverse_proxy` block to prepend `/hls-proxy` to any `Location` header coming back from MediaMTX.

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
        header_down Location ^ /hls-proxy
    }
}
```

`<stream-domain>` stays as-is — replace with whatever value is already in the template (e.g. `stream.{base_domain}`).

---

## What the change does

`header_down Location ^ /hls-proxy` is a regex replacement on the upstream response's `Location` header:

- `Location` — the header to modify
- `^` — regex anchor matching the start of the value
- `/hls-proxy` — the replacement (prepended to whatever Location MediaMTX returns)

So MediaMTX's `Location: /teststream/index.m3u8?cookieCheck=1` becomes `Location: /hls-proxy/teststream/index.m3u8?cookieCheck=1` before reaching the browser. `Set-Cookie` and all other headers pass through unmodified — no other changes required.

When MediaMTX returns a non-redirect response (e.g. `200 OK` with the manifest), there is no `Location` header to modify, and `header_down` is a no-op. Safe for all response types.

---

## Why not use `handle_response`?

An earlier draft of this fix used `handle_response @mtx_redirect { redir ... }` to intercept 3xx responses. That approach **does not work** in this Caddyfile because the `stream.DOMAIN` block also has a catch-all `route {}` with `forward_auth` for the web editor. When `handle_response` issues `redir`, the route chain does not terminate cleanly, and the catch-all `forward_auth` directive still fires — redirecting the request to Authentik authorize instead of serving the rewritten redirect to the browser.

`header_down` modifies the upstream response in-place without generating a new response, so the route chain terminates correctly and `forward_auth` never runs on `/hls-proxy/*` paths.

---

## Cookie check flow after the fix

1. Browser → `https://stream.domain/hls-proxy/teststream/index.m3u8`
2. Caddy strips prefix → MediaMTX gets `GET /teststream/index.m3u8`
3. MediaMTX (v1.18.x): `302 /teststream/index.m3u8?cookieCheck=1` + `Set-Cookie: cookieCheck=1`
4. Caddy rewrites Location: `302 /hls-proxy/teststream/index.m3u8?cookieCheck=1` + cookie passes through ✓
5. Browser follows → `/hls-proxy/teststream/index.m3u8?cookieCheck=1` → Caddy handles ✓
6. Caddy strips prefix → MediaMTX gets `GET /teststream/index.m3u8?cookieCheck=1` with cookie
7. MediaMTX validates cookie: `302 /teststream/index.m3u8`
8. Caddy rewrites: `302 /hls-proxy/teststream/index.m3u8` ✓
9. Browser follows → MediaMTX returns `200 OK` manifest → HLS plays ✓

---

## Compatibility

- **MediaMTX v1.17.0:** No `Location` header on HLS manifest requests — `header_down` is a no-op. Zero impact.
- **MediaMTX v1.18.0+:** Cookie check completes correctly. HLS plays.

This change is backwards-compatible and safe to deploy to all infra-TAK servers regardless of their current MediaMTX version.

---

## Verification after deploy

After regenerating the Caddyfile and reloading Caddy, run these checks on the target server:

**1. Confirm the new line is in the Caddyfile:**

```bash
grep -A 6 "handle_path /hls-proxy" /etc/caddy/Caddyfile
```

Expected output should include `header_down Location ^ /hls-proxy` and **must not** include `handle_response` or `redir /hls-proxy`.

**2. Confirm Caddy reloaded cleanly:**

```bash
caddy validate --config /etc/caddy/Caddyfile && systemctl is-active caddy
```

Expected: `Valid configuration` and `active`.

**3. Confirm the redirect rewrite is working end-to-end** (use `<stream-domain>` for the actual stream hostname; this requires a publishing test stream named `teststream`):

```bash
curl -ski "https://<stream-domain>/hls-proxy/teststream/index.m3u8" 2>&1 | grep -iE "^(HTTP|location|set-cookie)"
```

**Expected (MediaMTX v1.18.x with the fix correctly applied):**

```
HTTP/2 302
location: /hls-proxy/teststream/index.m3u8?cookieCheck=1
set-cookie: cookieCheck=1; HttpOnly; Secure; ...
```

The `location` header MUST start with `/hls-proxy/`. If it starts with `/teststream/` (no `/hls-proxy` prefix), the `header_down` line is missing or wrong.

**Failure indicator:** If the response is `302` with a `location:` pointing to `https://tak.<domain>/application/o/authorize/...` (Authentik authorize URL), the `handle_response` approach from the earlier doc draft is still in place. Remove it and use only the single `header_down Location ^ /hls-proxy` line.
