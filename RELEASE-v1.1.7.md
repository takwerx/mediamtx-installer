# v1.1.7 — SRT Transport Tuning for External Sources

## What's New

### SRT Transport Profile Tuning

External Sources now include SRT transport tuning — critical for pulling streams over satellite, cellular, or other high-latency links.

Previously, SRT external sources were added with bare default settings (120ms latency buffer), which is unusable for anything beyond a LAN or low-latency internet connection. Streams pulled over satellite or cellular would buffer, stutter, or drop entirely.

**New Transport Profile presets:**

- **Internet / LAN** — Default SRT settings (120ms latency). For reliable networks with low round-trip times.
- **Cellular / 4G-5G** — 500ms latency buffer with loss tolerance. Handles jitter and intermittent loss on wireless/mobile connections.
- **Satellite (KU/KA Band)** — 2000ms latency buffer with full satellite optimization. Covers geostationary satellite round-trip (~1200ms) plus retransmission margin.
- **Custom** — Expose all individual SRT parameters for manual fine-tuning.

**SRT parameters now configurable per-source:**

| Parameter | What it does |
|---|---|
| Latency | Receive buffer size in ms — must cover full round-trip time + margin |
| Peer Latency | Latency announced during negotiation — prevents peer from negotiating down |
| Receive Latency | Explicit receiver buffer — set equal to latency |
| Payload Size | Packet size (1316 = 7×188 for MPEG-TS alignment) |
| Loss Max TTL | Out-of-order packet tolerance before declaring loss — satellite links reorder packets |
| Too-Late Packet Drop | Drop unrecoverable packets instead of freezing the stream |
| NAK Reports | Periodic negative acknowledgments for faster retransmission |

### External Sources List Improvements

- New **Transport** column shows a colored badge (LAN / Cellular / Satellite) auto-detected from the source's latency setting
- Source URLs in the table are cleaned up — tuning parameters are hidden for readability while the full URL is preserved in the config

### Edit Support

- Editing an existing SRT source parses all tuning parameters from the URL and auto-detects the matching profile
- Non-standard parameter combinations fall back to Custom with all fields exposed

## Who This Helps

- Anyone pulling SRT streams from aircraft over satellite (KU/KA band)
- Anyone pulling SRT streams over cellular/LTE/5G connections
- Agency-to-agency SRT stream sharing over unreliable or high-latency links

## Upgrade Notes

- No configuration changes required — existing external sources continue to work as-is (detected as Internet/LAN profile)
- To tune an existing source: edit it in External Sources, select the appropriate Transport Profile, and save
- No backend changes — tuning parameters are appended to the SRT URL that MediaMTX already uses
