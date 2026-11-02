# mediamtx-installer: platform reference

The outside contracts this product depends on. Seeded 2026-10-31 (ops #371) from the repo, its notes and upstream sources.
No box names, addresses or credentials in this file.

**Status key**
- ✅ verified `<date>` `<where>`: proven on a real box or live service.
- 📖 source-checked `<date>`: read in the official source or docs, not run on a box.
- 📝 from our notes: recorded by an earlier session, not re-run for this file.
- ⚠️ drift or risk.

Where a doc and what we saw disagree, both are kept.

---

## 1. MediaMTX (upstream: https://github.com/bluenviron/mediamtx)

### 1.1 Release download (installer script and web editor "Upgrade MediaMTX")
- Latest version comes from `https://api.github.com/repos/bluenviron/mediamtx/releases/latest` (`tag_name`, form `vX.Y.Z`).
- Binary: `https://github.com/bluenviron/mediamtx/releases/download/vX.Y.Z/mediamtx_vX.Y.Z_linux_<arch>.tar.gz`,
  `<arch>` in `amd64`, `arm64`, `armv6`, `armv7`. A `checksums.sha256` is published beside them.
- 📖 source-checked 2026-10-31: asset names above match the v1.21.3 release.
- ⚠️ We install whatever is latest, unpinned. Each upstream release can change the API or HLS behaviour (see 1.3, 1.4).

### 1.2 Control API (v3)
- Default `apiAddress: :9997` upstream. Our installer writes `apiAddress: :9997`; the editor calls `http://localhost:9997`
  as user `any` with an empty password, which works because our config's first internal user is `any` limited to
  127.0.0.1/::1 with the `api` action.
- 📝 from our notes (CLAUDE.md): infra-TAK deployments run the API on **9898**, not 9997, and overlay LDAP auth onto the
  deployed editor. Deployed file is not the repo file.
- Endpoints the editor uses: `GET /v3/config/global/get`, `GET /v3/paths/list`, `GET /v3/paths/get/{name}`,
  `GET /v3/<kind>/list` and `POST /v3/<kind>/kick/{id}` for the publisher kinds.
- 📖 source-checked 2026-10-31: the first three are in `api/openapi.yaml` at v1.21.3, and in v1.19.3.
- ⚠️ **Publisher kinds were renamed upstream in v1.21.0.** The editor still uses `rtmpconns`, `rtmpsconns`, `rtspsessions`,
  `rtspssessions`, `srtconns`, `webrtcsessions` (`PUBLISHER_LISTS`). Upstream now documents `rtmp/conns`, `rtmps/conns`,
  `rtsp/sessions`, `rtsps/sessions`, `srt/conns`, `webrtc/sessions`. openapi at v1.20.0 and older has only the old names;
  at v1.21.0 and newer (checked v1.21.0, v1.21.1, v1.21.3) only the new ones. 📖 `internal/api/api.go` at v1.21.3 still registers the old paths as aliases
  (e.g. `/rtspsessions/list`), so it works today. If upstream drops the aliases, `kick_publishers()` skips every kind
  silently and a revoked Stream Key keeps streaming. Not seen failing on a box.

### 1.3 HLS session tracking, v1.18.0 and later
- First manifest request gets a `302` to `?cookieCheck=1` with a cookie. Without the cookie MediaMTX falls back to putting
  `?session=<uuid>` in variant manifest URLs. v1.17.x does not do this.
- Behind Caddy `handle_path /hls-proxy/*` the redirect `Location` lacks the `/hls-proxy` prefix and 404s. Fix is
  `header_down Location ^ /hls-proxy` in the `reverse_proxy` block; `handle_response` does not work there.
- Our share-link proxy must not keep cookies: `urllib.request.urlopen` (no cookie jar) works, `requests` (with or
  without `Session`) keeps them across the redirect chain and breaks the variant manifest. Shipped in v2.0.8.
- 📝 from our notes (`RELEASE-v2.0.5` to `v2.0.8`, `INFRA-TAK-CADDY-HLS-v1.18.md`). 📖 upstream API shape for `hls/muxers` and
  `hls/sessions` exists at v1.21.3. The cookie behaviour itself is not in upstream docs we could find; it was learned
  on boxes.

### 1.4 Config keys the editor reads and writes (`/usr/local/etc/mediamtx.yml`)
- 📖 source-checked 2026-10-31: `apiAddress`, `authMethod`, `authInternalUsers`, `authHTTPAddress`, `hlsVariant`,
  `rtspDemuxMpegts`, `srtPublishPassphrase`, `webrtcICEUDPMuxAddress` all exist in v1.21.3 `api/openapi.yaml`.
- Default listen ports upstream (`mediamtx.yml` v1.21.3): RTSP 8554, RTSPS 8322, RTMP 1935, RTMPS 1936, HLS 8888,
  WebRTC 8889 (media on UDP 8189), SRT 8890, API 9997. 📖 source-checked 2026-10-31.
- MediaMTX hot-reloads its YAML, so config saves apply even when `systemctl restart` fails (infra-TAK boxes, see 3.2). 📝 from our notes.
- Fresh Rocky installs: MediaMTX's own default config has the API off. Our installer turns it on at `127.0.0.1:9997`. 📝 v2.1.9 release notes.

### 1.5 KLV (drone video metadata)
- KLV over RTSP needs GStreamer (`rtspclientsink`, `rtpklvpay`). FFmpeg cannot packetize KLV into RTP. SRT carries KLV natively through FFmpeg.
- 📝 from our notes (CLAUDE.md, `PLAN-v2.1.0-klv-to-cot.md`). Official GStreamer docs for `rtpklvpay` not yet linked here.

---

## 2. Distribution and updates (GitHub)

- Main-channel boxes: `https://api.github.com/repos/takwerx/mediamtx-installer/releases/latest`, then pull
  `config-editor/mediamtx_config_editor.py` from the `main` raw URL. Dev-channel boxes pull from the `dev` raw URL.
  So **a push to `dev` deploys to dev-channel boxes, and a GitHub release deploys to main-channel boxes.**
- Unauthenticated GitHub API calls are limited per IP (60 an hour, https://docs.github.com/rest/using-the-rest-api/rate-limits-for-the-rest-api).
  ✅ verified 2026-10-31 from the worker Mac: two unauthenticated calls in a row returned `403 rate limit exceeded`. The editor sends a
  `User-Agent` and does not use a token, so many boxes behind one IP can fail the update check.
- The release notes users see in the editor are the GitHub release body (`body` field), so they must be user-facing.
  PR checks now verify the version file against the newest tag and the notes (`.github/ci/release_hygiene.py`).
- `CURRENT_VERSION` in the editor file is `vX.Y.Z` on main and `vX.Y.Z-dev` on dev (release skill, steps 3 and 7).

## 3. infra-TAK integration (sibling product, not ours to change here)

### 3.1 Layout
- Editor runs as the unprivileged console user (`takwerx`), not root, with no sudo.
- HLS is bound to loopback `127.0.0.1:8888` and served through Caddy at `/hls-proxy/`; port 8888 is firewalled.
- The LDAP login overlay lives beside the editor (`mediamtx_ldap_overlay.py`) and is copied from the running infra-TAK install
  directory, newest by mtime, never replacing a newer one. 📝 from our notes.
- infra-TAK keys its editor patch on the `_INFRATAK_SSE_HEARTBEAT` marker in the editor source; do not remove it.

### 3.2 Privilege bridge
- Root actions go through the infra-TAK broker, or the root-owned `/usr/local/sbin/mediamtx-upgrade-helper` plus sudoers
  rule `/etc/sudoers.d/mediamtx-webeditor`. Without either, Upgrade and Rollback refuse with a clear message; plain `sudo` fails.
- ✅ verified 2026-07-23 on the Rocky non-root fleet box (per `HANDOFF-2026-07-23-broker-upgrade.md`): MediaMTX
  v1.19.2 to v1.19.3 from the Versions page through the helper. Earlier editor builds failed there with `[Errno 13] Permission denied`.
- ⚠️ The helper must stay root-owned and not writable by the editor user, or the sudoers rule becomes full root.

## 4. OS and packages

- Supported installer: Ubuntu 22.04. Rocky/RHEL 9: the editor installs there and uses `dnf`, `firewalld` and SELinux
  (`restorecon`); the `rocky-9/` scripts are older and one memory note calls them abandoned. Both are kept: treat Rocky as
  editor-supported, installer scripts as not maintained. 📝 from our notes.
- Caddy comes from Cloudsmith's apt repo (`https://dl.cloudsmith.io/public/caddy/stable/`), certificates from Let's Encrypt.
  📖 as written in `Ubuntu_22.04_Install_MediaMTX_Caddy.sh`; official install steps: https://caddyserver.com/docs/install#debian-ubuntu-raspbian
- Firewall: `ufw` where present, else `firewall-cmd` (runtime and permanent rule, no reload). SSH, 80, 443, 5000 and TAK ports are never closed by the editor.
- Browser player: hls.js is vendored and served from `/static/hls.min.js` so the console works air-gapped.

## 5. Open items (not contracts yet)
- Link GStreamer's `rtpklvpay` and `rtspclientsink` docs and prove KLV-over-RTSP on a box.
- Prove the cookieCheck behaviour (1.3) against a current MediaMTX on a box and record the version.
- Decide whether to move the editor to the new publisher-kind API names (1.2) before upstream drops the aliases.
