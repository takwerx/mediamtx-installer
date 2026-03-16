# Web Editor v1.1.8 — Release notes

**Release date:** March 2026

## Highlights

- **Ku-band link simulator** — Simulate bad satellite-style links (delay, jitter, loss) on the receiver so you can test HLS playback without flying. One-click **Simulate link** per external source; auto-detects network interface when `eth0` isn’t present.
- **Share links** — Active Streams: **Share** generates a fixed 4-hour token link. External Sources: configurable duration (1h / 4h / 24h / Until revoked) via **Generate Share Link** modal.
- **HLS playback** — Tuned for impaired links (e.g. Ku-band): buffer and live-edge settings to reduce stalls; conservative stall recovery (reload after 15s stuck) when source restarts.
- **Add External Source** — Form submit fixed (event delegation + error handling) so **Add Source** works reliably after deleting a source.
- **SRT URL** — Prevents double `srt://` when host field contains a full SRT URL.

---

## Ku-band link simulator

- **Location:** `scripts/ku-band-simulator/`. Copy to `/opt/mediamtx-webeditor/ku-band-simulator/` (or set `MEDIAMTX_SIMULATOR_DIR`).
- **UI:** External Sources tab → **Simulate link** on a source row (sets SOURCE_IP from URL, writes config, turns simulator ON). **Turn simulator OFF** appears in the panel only after the simulator is on.
- **Defaults:** 600 ms delay, ±100 ms jitter, 1% packet loss (random). Override in `ku_band_simulator.conf` with `DELAY_MS`, `JITTER_MS`, `LOSS_PCT`.
- **Requirements:** Linux `tc` + `ifb`; sudo for the scripts (sudoers entry for the web editor user).

---

## Share links

- **Active Streams:** Click **Share** → generates a 4-hour token link and copies to clipboard.
- **External Sources:** Private streams show **Generate Share Link**; opens modal to choose duration, then generates token and copies.

---

## Other fixes and behavior

- Add Source form: submit handler uses event delegation so it works even when the form is in a tab; non-JSON and API errors are surfaced.
- Simulator OFF script: no longer prints “Missing config” when tearing down without a conf file.
- Watch page: fatal HLS errors still trigger 5s retry; optional conservative stall recovery (check every 5s, reload if stuck 15s) for source restarts.

---

## Version

- **Web Editor:** v1.1.8  
- **Compatible with:** MediaMTX (unchanged); Ubuntu 22.04 LTS.
