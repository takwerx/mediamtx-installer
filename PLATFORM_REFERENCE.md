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
- MISB ST 0601 local set (what `klv-to-cot.py` reads): each item is a tag, a BER length and a value. Tags 128 and up are BER-OID, two bytes (`0x81 0x03` is tag 131), so a reader that takes every tag as one byte falls out of step on an ST 0601.19 stream. The set ends with tag 1: `01 02` plus a 16-bit checksum, a running sum over the whole packet (16-byte key and length included) up to the checksum, bytes at even offsets as the high byte. ⚠️ The MISB standard text is not linked here and was not read for this entry; the two rules below come from the PR author and were checked against data only.
- ✅ verified 2026-11-20 (ops #1011) on two public files: the Kitware KWIVER `h264_klv.ts` sample has 30 sets, tags up to 142, every checksum valid by the rule above (checked with a second, independent parser), longitude 128.426759. A reader with one-byte tags gives 1.39e23 degrees on every set. `config-editor/truck_60.ts` has 288 sets, tags up to 72, every checksum valid.
- ✅ verified 2026-11-20 on a throwaway Ubuntu 22.04 box with MediaMTX v1.21.4: an SRT source with KLV, added through the editor's External Source with KLV to CoT, starts the sidecar from `runOnReady`. The old reader sent 1.39e23 on every sample (130 of 130); the fixed reader sent 128.4235 to 128.4267 (129 of 129).
- A test publisher that copies a file with `ffmpeg -c copy -f mpegts` leaves data streams out unless you add `-map 0`: MediaMTX then shows one track (H264) and the sidecar's `ffmpeg -map 0:d` finds nothing. ✅ verified 2026-11-20 on the same box.
- ffmpeg 6.1.1 (Ubuntu 24.04, package `6.1.1-3ubuntu5`) hands over every KLV packet with the first 5 bytes of the ST 0601 key missing (`06 0e 2b 34 02`), so the data starts `0b 01 01 0e 01 03 01 01 00 00 00`. It happens when ffmpeg reads the `.ts` file directly, over SRT, and over RTSP (`-f data`), so it is in ffmpeg and not in MediaMTX. ffmpeg 4.4.2 (Ubuntu 22.04), 5.1.9 (Debian 12) and 7.1.1 / 7.1.5 (Ubuntu 25.10, Debian 13, same as Rocky 9) give the whole key. `klv-to-cot.py` finds the set by the last 11 bytes of the key and puts the 5 bytes back before it checks the checksum. ✅ verified 2026-11-23 on `ubuntu:24.04`, `ubuntu:22.04` and `debian:13` containers (real ffmpeg, real MediaMTX v1.21.4, SRT source with the Kitware `h264_klv.ts`): the old sidecar sent 0 samples on 24.04, the fixed one 191 in 25 s. ⚠️ Not checked: other 6.x ffmpeg builds (6.0, 6.1.x from other sources), so "6.1.1 only" is what was seen, not what is known. ops #1128.

### 1.6 MediaMTX v1.21.4 (released 2026-11-15; checked 2026-11-16, ops #818)
- ✅ verified 2026-11-16 on a throwaway Ubuntu 22.04 box and a throwaway Rocky 9.9 box (SELinux Enforcing), both x86_64, installer from `dev`:
  - A fresh install gets v1.21.4 (the installer reads `releases/latest`). The service, the web editor and the test stream pass.
  - The editor's Upgrade (v1.21.3 to v1.21.4), Rollback (back to v1.21.3) and Upgrade again all succeed over HTTP with a real sign-in. The binary keeps the `bin_t` SELinux label on Rocky and no AVC denial is logged.
  - RTSP, HLS and SRT work on both versions: RTSP read by a viewer with no password on the `teststream` path, HLS, and an SRT stream with a KLV data track (timestamps offset by 5000 s on purpose, since v1.21.4 stops rebasing MPEG-TS timestamps to zero) read back over SRT, RTSP and HLS with the KLV track intact.
  - A taken SRT UDP port (8890): the service exits at start and systemd retries every 5 s (`Restart=always`, `RestartUSec=5s`); it starts by itself once the port is free. Same as v1.21.3. A fatal UDP read error while running (the new gortsplib behaviour) was not forced on a box.
- ✅ verified 2026-11-16: v1.21.4 adds two config keys, `udpWriteBufferSize` and `srtMinLatency`. The Rocky installer copies upstream's default config, so a fresh Rocky install on v1.21.4 holds both, and v1.21.3 refuses them (`unknown field`). Rollback's unknown-field fixer removed both (`fields_removed` lists them) and v1.21.3 came back. The Ubuntu installer writes its own config with neither key.
- ✅ verified 2026-11-16 on a fleet box with CloudTAK (non-root console, editor Upgrade through the broker, v1.20.0 to v1.21.4, then Rollback to v1.20.0): a stream with KLV published to MediaMTX played through CloudTAK's video wall and marker lease both before and after the Upgrade, and after the Rollback (`video-check`: `VIDEO PASS`).
- 📖 source-checked 2026-11-16: `internal/api/api.go` at v1.21.4 still registers both the old (`/rtspsessions/list`) and the new (`/rtsp/sessions/list`) publisher paths, so the open risk in 1.2 is unchanged. ✅ verified on the Ubuntu box: both names answer 200, and a kick by the old name ends the publisher.
- 📖 Upstream v1.21.4 notes: RTSP-over-WebSocket messages are capped at 1 MiB (an unauthenticated client could make the server buffer without limit), request bodies with passwords and tokens are no longer written to the debug log, and the API redacts more secrets. No GHSA at release time.

### 1.7 Re-running the installers on a box that has MediaMTX (ops #1315)
Re-running an installer is how people update MediaMTX: the script fetches `releases/latest`, swaps the binary, keeps the configuration and restarts. All of this was seen on throwaway AWS boxes (Ubuntu 22.04, Ubuntu 24.04, Rocky 9.9 with SELinux Enforcing), each box built the way a customer's was: the old tag's own installer plus the MediaMTX release that was newest on that tag's date (the install script was told that version through a `curl` stand-in; the release tarballs are the real ones).
- ✅ verified 2026-11-26: a kept configuration with a key the newest MediaMTX does not know makes it exit at start (`ERR: json: unknown field "srtMinLatency"`) and systemd retries every 5 seconds. `systemctl restart` still returns 0, so the old installers printed "is running!" (Ubuntu) or "Installation Complete!" (Rocky) with MediaMTX down. Real case: a v1.21.4 box (its config holds `srtMinLatency` and `udpWriteBufferSize`) re-run while v1.21.3 was the newest: `dev` left the service in `activating (auto-restart)` under two success lines on both Ubuntu boxes and one on Rocky; the fixed installer printed the error and the log line, put the old binary and the config back byte for byte, exited 1, and a stream played.
- ✅ verified 2026-11-26: the service counts as running only after it has been `active` for 6 checks in a row (1 s apart, up to 25 s). One `is-active` right after the restart is not enough: a crashing MediaMTX is `active` for a moment between restarts. Tested with a fake binary that is active for one check and then dies (unit test), and with the real v1.21.3 above.
- ✅ verified 2026-11-26: the binary it replaces is kept as `/usr/local/bin/mediamtx.backup_<time>`, the same name the web editor's Upgrade and Rollback use (`mediamtx-upgrade-helper.sh` too).
- ✅ verified 2026-11-26: five customer starting points per platform, each built by the old tag's own installer on that day's MediaMTX (installer v1.0.0 + MediaMTX v1.16.1, v2.0.0 + v1.17.0, v2.0.9 + v1.19.0, v2.1.0 + v1.19.3, v2.1.14 + v1.21.3), then the fixed installer re-run over each: all succeeded on v1.21.4, the service stayed active, a stream published to the server was read back by a viewer with no password, the old binary was kept. The same re-runs with `dev` also succeeded; the differences are the MoQ findings below.
- ✅ verified 2026-11-26: **MoQ on old Ubuntu configs.** A config written by an Ubuntu installer older than the MoQ fix has no `moq:` key, and newer MediaMTX turns MoQ on when it is missing: the UDP port 8892 listens (`ss -lnup`). Not on at v1.16.1 and v1.17.0, on from v1.19.0. Seen on the installer v2.0.9 and v2.1.0 boxes (MediaMTX v1.19.0, v1.19.3) before any re-run, and on the v1.0.0, v2.0.0, v2.0.9 and v2.1.0 boxes after a `dev` re-run (v2.1.14's config already has `moq: no`). The fixed installer adds `moq: no` when the key is missing and the port closes. The installers' firewalls never open 8892, so it listens on the server only.
- ✅ verified 2026-11-26 on Rocky 9.9: installer v2.0.9 and v2.1.0 left upstream's `moq: true`. A value that is there is never changed by the fixed installer (a person may have chosen it); it prints a note with the one line that turns it off, and the port keeps listening. `dev` rewrote `true` and `yes` to `no`. Design choice put to the Tools lead (ops #1315).
- ✅ verified 2026-11-26 on Rocky 9.9 (SELinux Enforcing): the Rocky installers of v1.0.0, v2.0.0, v2.0.9 and v2.1.0 leave a box whose service never starts (`status=203/EXEC`, the binary keeps the temp folder's SELinux label; later installers run `restorecon`). A re-run of the fixed installer repairs it (0 AVC denials after the re-run).
- ✅ verified 2026-11-26: a run stopped at the config step (a `kill -9` at the first `sed -i` of the config; on Rocky the same, before the credentials step) left, with `dev`, a config under the real name: Ubuntu with the placeholder HLS viewer password `changeme` (the next run kept it and printed "Existing configuration kept"), Rocky with upstream's open config (no named user). With the fixed installers the config is written under `mediamtx.yml.new` and renamed when complete; the next run installs fresh (random 16 character HLS password on Ubuntu, the named user on Rocky).
- ✅ verified 2026-11-26: the web editor installer rebuilt the venv in place (`venv --clear`) and ran pip after. With PyPI unreachable (a `/etc/hosts` line for `pypi.org` and `files.pythonhosted.org`), `dev` left a venv with no Flask: after the next editor restart `import flask` failed, the service sat in `activating` and the login page gave no answer. The fixed installer builds `venv.new` beside the running one, checks it imports `flask, ruamel.yaml, requests, psutil`, then swaps (`venv` becomes `venv.prev`); on a pip failure the editor keeps running on its old packages and the script says "The web editor's current Python packages were not changed." The editor itself does the same at start (see 4, ops #1129), with the same folder names.
- ✅ verified 2026-11-26: a service file changed by hand (`User=mtxed`, `NoNewPrivileges=true`, `ProtectHome=true`) went back to `User=root` with `dev` on every re-run of the editor installer (seen on all three boxes). The fixed installers set only the lines they need (`ExecStart`, and `WorkingDirectory` for the editor) and keep the rest; the changed file is kept as `UNIT.backup_<time>` (systemd ignores that name). The editor ran as `mtxed` after the re-run and served the login page. ⚠️ The MediaMTX unit uses the same function but its hand-edited case was covered by unit tests only, not on a box.
- ✅ verified 2026-11-26: port 5000 closed by hand (ufw rule deleted, or the firewalld port removed) was opened again by every `dev` editor re-run. The fixed installer opens it only when the editor's service file did not exist yet (first install).
- ✅ verified 2026-11-26: an installed editor that says `v2.1.99` is not replaced by a checkout that says `v2.1.21-dev`; the script stops before it changes anything. `v2.1.21-dev` counts as older than `v2.1.21`. This protects against a future old checkout only: a script that is already old has no check.
- ✅ verified 2026-11-26, checked and found safe (no change): `pip install --require-hashes` stops on a changed hash (`THESE PACKAGES DO NOT MATCH THE HASHES`; every hash of the file was changed, because pip accepts any one hash listed for a package) and the running venv is untouched (Ubuntu 22.04, Rocky 9.9). The installers refuse a MediaMTX tarball whose SHA-256 does not match `checksums.sha256` (`Checksum mismatch ... Nothing was installed`, binary unchanged, Ubuntu 22.04 and Rocky 9.9). `mediamtx-upgrade-helper.sh install` refuses a file that is not an ELF binary (`not an ELF binary`, checked on both). The vendored `libgstrtspclientsink.so` for EL9 has the SHA-256 that `GST_RTSPSINK_SO_SHA256['9']` pins (`b1f4b5a5...c9c8518`, checked by hand; `tests/test_download_pins.py` fails if they drift). ⚠️ Not covered: the distribution GStreamer packages the Ubuntu installer installs with apt are not pinned (they come from Ubuntu's own repositories).
- ✅ verified 2026-11-27 (ops #1354): **the installer only moves forward.** `releases/latest` can be older than the MediaMTX a box already runs (a pre-release put there by hand, a release MediaMTX pulled). A v1.21.4 box with its own keys, told v1.21.3 is the newest, was moved BACK by the old script: v1.21.3 refused `srtMinLatency` and `udpWriteBufferSize`, the service crash-looped, and the script still printed its success lines (seen on Ubuntu 22.04 and Rocky 9.9). The installer now compares the installed version with the release and keeps a newer binary; an older, equal or unreadable version is replaced as before. Real dnf and apt also never move a newer installed Caddy back, and the Rocky Caddy script now skips dnf when Caddy is installed.
- Seen once, not explained: one fresh install of this branch on Ubuntu 22.04 stopped at "Failed to detect latest version" (the `releases/latest` call), and the same call answered 200 a minute later from the same box. The 60 an hour API limit per address is the likeliest cause but was not proven. The installers do not retry that call.

---

## 2. Distribution and updates (GitHub)

- Main-channel boxes: `https://api.github.com/repos/takwerx/mediamtx-installer/releases/latest`, then pull
  `config-editor/mediamtx_config_editor.py` from the `main` raw URL. Dev-channel boxes pull from the `dev` raw URL.
  So **a push to `dev` deploys to dev-channel boxes, and a GitHub release deploys to main-channel boxes.**
- Unauthenticated GitHub API calls are limited per IP (60 an hour, https://docs.github.com/rest/using-the-rest-api/rate-limits-for-the-rest-api).
  ✅ verified 2026-10-31 from the worker Mac: two unauthenticated calls in a row returned `403 rate limit exceeded`. The editor sends a
  `User-Agent` and does not use a token, so many boxes behind one IP can fail the update check.
- When the API says 403, the newest tag is still readable without the API: `https://github.com/<repo>/releases/latest` answers
  `302` to `.../releases/tag/<tag>`, and `.../releases/download/<tag>/<file>` (including `checksums.sha256`) downloads with no API limit.
  ✅ verified 2026-11-24 on test12 while its address was at 60 of 60 API calls: the deployed v2.1.19 editor showed
  `HTTP Error 403: rate limit exceeded` on both Version Management checks, and the same checks with the fix answered from the redirect (ops #1214).
  The fix also reuses an answer for 10 minutes and keeps the last good one on disk (`/opt/mediamtx-webeditor/github_release_cache.json`).
  The release body and `published_at` are only in the API answer, so a redirect-only answer has none (it reuses the cached ones when the tag matches).
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
- Python for the editor's venv (ops #1030): the pinned urllib3 2.8.0 and requests 2.34.2 need Python 3.10 or newer. Ubuntu 22.04 has 3.10, 24.04 has 3.12. Rocky/RHEL 9's `python3` is 3.9, but its AppStream repo has `python3.12` and `python3.12-pip` (`dnf install python3.12 python3.12-pip`), and `python3.12 -m venv` works from that package alone. The editor's venv is built from `python3.12` there; the system `python3` stays 3.9 (dnf needs it). ✅ verified 2026-11-21 on throwaway AWS Rocky 9.9 and Rocky 9.8 (container) boxes: python3.12 3.12.16, venv from it holds Flask 3.1.3, urllib3 2.8.0, requests 2.34.2, psutil 7.2.2 (installed from the hashed pins); the service runs on `/usr/bin/python3.12`. Python 3.9 is not supported by the pins any more.
- A venv remembers its own folder in the first line of its scripts (`pip`) and in `pyvenv.cfg`. A venv built as `venv.new` and renamed to `venv` has `pip` scripts that point at `venv.new` until they are rewritten. The console's rebuild rewrites them. ✅ verified 2026-11-21 on Rocky 9.9: `venv/bin/pip --version` works after the swap.
- The console's Update replaces only the editor file and the KLV sidecar, never the venv (ops #1129). So the editor carries the pinned versions itself (`VENV_PINS`, kept equal to `requirements.txt` by a test) and, at start, builds a new venv beside the old one when any installed package differs, on any OS (Rocky 9 from `python3.12`, Ubuntu from the system `python3`). The new venv must hold exactly the pins before it replaces the old one; the old one stays as `venv.prev`. The rebuild reads `requirements.txt` from the update channel's branch (`main` or `dev`), so a release must be on that branch before boxes update. ✅ verified 2026-11-23 on throwaway AWS Ubuntu 22.04 (Python 3.10.12) and 24.04 (Python 3.12.3) boxes installed at v2.1.17: the dev editor without this change left urllib3 2.6.3, requests 2.32.5, certifi 2026.10.23; with it the rebuild took about 10 s and gave urllib3 2.8.0, requests 2.34.2, certifi 2026.11.20, one editor restart, MediaMTX not restarted.
- Caddy comes from Cloudsmith's apt repo (`https://dl.cloudsmith.io/public/caddy/stable/`), certificates from Let's Encrypt.
  📖 as written in `Ubuntu_22.04_Install_MediaMTX_Caddy.sh`; official install steps: https://caddyserver.com/docs/install#debian-ubuntu-raspbian
- Firewall: `ufw` where present, else `firewall-cmd` (runtime and permanent rule, no reload). SSH, 80, 443, 5000 and TAK ports are never closed by the editor.
- Browser player: hls.js is vendored and served from `/static/hls.min.js` so the console works air-gapped.

## 5. Open items (not contracts yet)
- Link GStreamer's `rtpklvpay` and `rtspclientsink` docs and prove KLV-over-RTSP on a box.
- Prove the cookieCheck behaviour (1.3) against a current MediaMTX on a box and record the version.
- Decide whether to move the editor to the new publisher-kind API names (1.2) before upstream drops the aliases.
