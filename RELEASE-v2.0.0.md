# Web Editor v2.0.0 Release Notes

**Release Date:** March 18, 2026  
**Minimum MediaMTX Version:** v1.17.0

---

## Major Changes

### Native MPEG-TS Demuxing — No More FFmpeg Transcoding

MediaMTX v1.17.0 introduced automatic MPEG-TS unwrapping for RTSP publishers ([PR #5476](https://github.com/bluenviron/mediamtx/pull/5476)). This release takes full advantage of it:

- **RTSP sources wrapping H264/AAC inside MPEG-TS** (TAKICU, ATAK UAS Tool, ISR cameras) are now automatically demuxed into native tracks
- **HLS playback works natively** — browsers can play these streams without any FFmpeg transcoding step
- **KLV metadata tracks** are preserved for RTSP readers and automatically skipped by the HLS muxer
- **The `~^live/(.+)$` FFmpeg re-publish path has been removed** from the install script — it is no longer needed

**Before (v1.1.9):** RTSP MPEG-TS source → FFmpeg copies to new path → HLS serves from copy  
**After (v2.0.0):** RTSP MPEG-TS source → MediaMTX unwraps H264 → HLS serves directly

### HLS Tuning Page

New dedicated configuration page under **Configuration > HLS Tuning** with:

- **Segment Settings** — HLS variant (MPEG-TS/fMP4/Low-Latency), segment count, segment duration, part duration, max segment size
- **Muxer Settings** — Always remux toggle, muxer close timeout
- **One-click presets** — LAN/Low Latency, Internet/Cellular, Satellite (KU/KA) with recommended values
- **MPEG-TS Demux toggle** — Enable/disable `rtspDemuxMpegts` from the UI without editing YAML
- **Write Queue Size** — Tunable buffer for impaired links

All settings are saved to `mediamtx.yml` and MediaMTX is restarted automatically.

---

## Other Changes

### HLS.js Player Fixes

- **Fixed `document.write` crash** — Watch popups now call `popup.document.open()` before writing, preventing `Identifier 'video' has already been declared` error when clicking Watch multiple times
- **Reverted `liveDurationInfinity`** — This setting was causing the player to fall behind the live edge on impaired links with frequent muxer restarts. Removed in favor of HLS.js auto-managed buffer.
- **Set `liveBackBufferLength: -1`** — Lets HLS.js aggressively trim stale segments, improving recovery on streams with decode errors

### Install Script Updates

- **Added `rtspDemuxMpegts: true`** under `pathDefaults` in the default YAML — new installs get MPEG-TS demuxing out of the box
- **Removed `~^live/(.+)$` FFmpeg re-publish path** — no longer needed with native demuxing
- Updated install echo messages to reflect new capabilities

### Service Commands Reference

- Added `config-editor/SERVICE-COMMANDS.md` with all service management commands, file locations, and update instructions

---

## Upgrade Notes

### Existing Installations

The web editor update does **not** modify your existing `mediamtx.yml`. To enable MPEG-TS demuxing:

1. Update the web editor file via FileZilla/SCP
2. Restart the web editor: `sudo systemctl restart mediamtx-webeditor`
3. Go to **Configuration > HLS Tuning**
4. Check **"Enable MPEG-TS Demuxing for RTSP Publishers"** (checked by default)
5. Click **Save HLS Settings & Restart MediaMTX**

### Removing the FFmpeg live/ Path

If your existing YAML has the `~^live/(.+)$` path, you can safely remove it after enabling MPEG-TS demuxing. Streams published directly (without the `/live` prefix) will have their MPEG-TS unwrapped automatically.

### MediaMTX Version Requirement

MPEG-TS demuxing requires **MediaMTX v1.17.0 or later**. Update MediaMTX from the web editor's **System > Versions** page or manually.

---

## Known Issues

- **SRT decode errors** (`unexpected sequence number: X, expected 0`) — This is an upstream MediaMTX bug in the MPEG-TS demuxer for SRT sources on impaired links (Ku-band satellite). It causes periodic HLS muxer restarts. The HLS.js player tuning mitigates the impact but does not fix the root cause. Tracked upstream.
- **TAKICU RTSP stability** — Some TAKICU versions drop the RTSP connection after 20-40 seconds. This appears to be a TAKICU client-side issue, not a MediaMTX bug.
- **Chrome `document.write` warning** — Chrome warns about parser-blocking cross-site scripts loaded via `document.write`. This is a warning only and does not block functionality. A future release will migrate to standard `<script>` tag loading.
