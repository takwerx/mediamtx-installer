# PLAN v2.1.0 — Extract KLV → CoT (per external source, target IP)

## 1. Headline

Add a per-external-source **"Extract KLV → CoT"** option to the MediaMTX config editor.
When enabled, MediaMTX taps the MISB ST0601 KLV metadata out of an incoming aircraft
video feed and ships decoded position / slant / frame-center samples as UDP datagrams to a
**target IP:port** (Mike's CoT proxy/aggregator). The aggregator — not this project — turns
those samples into CoT, merges them onto the aircraft's existing ADS-B UID, and emits
SPI/slant. This project's job ends at "decoded KLV on the wire."

## 2. Scope discipline — the contract boundary

This release ships the **producer half only**:

- MediaMTX side: ingest video (already exists via External Sources) → tap KLV → emit
  decoded samples to a target IP.
- It defines and documents the **wire format** (the interface Mike codes against).

It does **NOT** ship: CoT generation, UID merge/arbitration, SPI/slant CoT events, ADS-B
mute/failback, or any TAK Server interaction. Those live in Mike's aggregator. We hand him
a spec + a UDP feed; he builds the consumer.

Rationale: keeps MediaMTX a pure video/metadata service and the aggregator a pure
CoT-domain service. No second video client on the aggregator (it must never open SRT/RTSP).

## 3. The need

Aircraft ADS-B already produces a TAK icon (via Mike's proxy) carrying a video-playback URL
on the radial menu. Operators can't tell when the aircraft is actually streaming, and when
it does stream the richer truth (platform position, sensor slant, sensor point-of-interest)
lives in the video's KLV and is thrown away. We already pull and rebroadcast the feed in
MediaMTX (External Sources). MediaMTX preserves the KLV track for RTSP readers
(`config-editor/mediamtx_config_editor.py:2081`) — so the metadata is right there, untapped.

Goal: while the feed is live, stream its KLV out so the aggregator can drive the *same*
aircraft icon off the video and light up SPI/slant; when the feed drops, the aggregator
falls back to ADS-B. One icon, no flicker, no guessing whether it's streaming.

## 4. The design

### 4.1 Where the tap lives — MediaMTX `runOnReady`

The existing External Sources flow writes a path into `mediamtx.yml`:

```yaml
paths:
  <name>:
    source: srt://their-server:port/...
    sourceOnDemand: yes|no
```

(written by `api_add_external_source()` at `config-editor/mediamtx_config_editor.py:10944`,
path entry built at ~line 10991.)

When "Extract KLV → CoT" is enabled for that source, append two lifecycle hooks to the
same path block:

```yaml
    runOnReady: /opt/mediamtx-webeditor/klv-to-cot.py --path $MTX_PATH --hex <hex> --target <ip:port>
    runOnReadyRestart: yes
    runOnNotReady: /opt/mediamtx-webeditor/klv-to-cot.py --path $MTX_PATH --hex <hex> --target <ip:port> --downlink
```

- `runOnReady` fires when the path goes live → starts the decoder sidecar. MediaMTX kills
  the process when the path closes. **That process lifecycle IS the "video on/off" signal**
  the aggregator needs for ADS-B failback — for free.
- `runOnNotReady` fires once when the path closes → sends a single `{"event":"down"}`
  sentinel to the target so the aggregator can fail back immediately instead of waiting for
  sample staleness. (Belt-and-suspenders: aggregator should ALSO treat sample gaps > N s as
  down.)

### 4.2 The hex binding — derive from the path name

ST0601 KLV does not carry the ICAO hex. We bind it via the **MediaMTX path name**. Two modes:

- **Auto:** if the source's stream name is itself the hex/identifier (e.g. source named
  `a1b2c3`), pass `--hex $MTX_PATH` and let the sidecar use the path verbatim. Fleet-clean,
  zero extra config.
- **Explicit:** a small "Aircraft hex / ID" field on the form when KLV extraction is on,
  for cases where the stream name isn't the hex. Stored in the source metadata, interpolated
  into the `--hex` arg at config-write time.

The hex is opaque to us — we just stamp it on every sample so Mike can key the merge. He
maps hex ↔ tail ↔ ICAO ↔ TAK UID on his side (his proxy already does this for ADS-B).

### 4.3 The sidecar — `klv-to-cot.py`

Self-contained script dropped to `/opt/mediamtx-webeditor/klv-to-cot.py` by the installer.

Pipeline:
```
ffmpeg -loglevel error -rtsp_transport tcp -i rtsp://127.0.0.1:8554/$MTX_PATH \
       -map 0:d -c copy -f data pipe:1
  | klvdata stream parser (MISB ST0601)
  | extract fields → NDJSON datagram → UDP sendto(target_ip, target_port)
```

- Reads from the **local rebroadcast** (`127.0.0.1:8554/<path>`), not the upstream — let
  MediaMTX own reconnects; we tap the already-ingested copy.
- Decode with the `klvdata` Python package (MISB ST0601). Do **not** hand-roll the TLV /
  BER-OID / IMAPB / checksum parsing.
- One NDJSON line per decoded frame (rate-limit to ~the KLV cadence, typically 1–5 Hz; cap
  at e.g. 10 Hz so a chatty feed can't flood the aggregator — `log` the cap, don't silently
  drop).
- Emits a `{"event":"up"}` sentinel on first successful decode and (via the `--downlink`
  invocation) `{"event":"down"}` on path close.
- **Transport** (4.4a) selected by args:
  - Netbird/plain: `--target <netbird-ip:port> [--proto udp|tcp]` → open a plain UDP or TCP
    socket, write NDJSON lines. No TLS.
  - mTLS: `--target <host:port> --tls --cert <p> --key <p> --cacert <p>` → TCP+TLS client,
    present the TAK-format client cert, write NDJSON lines. Reconnect with backoff on drop.

Deps: `ffmpeg` (already used throughout the installer) + `python3` only. **No third-party
packages** — the ST0601 decoder is vendored in the script (only the ~16 tags in 4.4), and TLS
uses the stdlib `ssl` module. This keeps the box dependency-free (no pip step). Decoder
validated off-box against the repo's `config-editor/truck_60.ts` reference (288 local sets,
all fields plausible — Cheyenne WY truck clip).

### 4.4 Wire format — THE INTERFACE MIKE CODES AGAINST

Payload: **newline-delimited JSON (NDJSON)**, one message per line. The payload is
**transport-agnostic** — Mike's aggregator parses the same NDJSON regardless of how it
arrives. Transport is selected per box (see 4.4a); the schema below is the frozen contract.

Sample message (one per KLV frame):
```json
{
  "event": "sample",
  "hex": "a1b2c3",                 // from --hex; the merge key
  "path": "chp_air1",              // MediaMTX path, for debugging
  "ts": 1733600000.123,           // ST0601 tag 2 (Unix µs → s), or wallclock if absent
  "platform": {                    // aircraft position — tags 13/14/15
    "lat": 34.123456, "lon": -118.123456, "alt_m": 1875.0,
    "heading_deg": 92.4,           // tag 5
    "pitch_deg": -1.2,             // tag 6
    "roll_deg": 0.4                // tag 7
  },
  "sensor": {                      // slant — tags 18/19/20/21
    "rel_az_deg": 145.0,           // tag 18 sensor relative azimuth
    "rel_el_deg": -23.5,           // tag 19 sensor relative elevation
    "rel_roll_deg": 0.0,           // tag 20
    "slant_range_m": 4200.0,       // tag 21
    "hfov_deg": 2.3, "vfov_deg": 1.3  // tags 16/17 (optional)
  },
  "spi": {                         // frame center / sensor point of interest — tags 23/24/25
    "lat": 34.150000, "lon": -118.150000, "elev_m": 410.0
  }
}
```

Lifecycle messages:
```json
{"event":"up",   "hex":"a1b2c3", "path":"chp_air1", "ts":1733600000.0}
{"event":"down", "hex":"a1b2c3", "path":"chp_air1", "ts":1733600090.0}
```

Field rules:
- Any sub-object/field MAY be absent if the KLV frame omits that tag — consumer must treat
  missing as "unknown," not zero.
- `hex` is always present; it is the only field the aggregator MUST key on.
- Lat/lon in decimal degrees WGS84; altitudes/ranges in meters; angles in degrees.
- This schema is the frozen contract for v2.1.0. Additive fields only in later versions.

### 4.4a Transport — Mike is remote (Netbird default, mTLS fallback)

The aggregator is off-box and remote, so plain UDP on the open internet is out. Mike already
runs **Netbird** (WireGuard mesh) and terminates **TLS** for the TAK data he ingests. Two
transport modes, selected per source; **same NDJSON payload either way**:

- **Netbird (default, recommended).** Target is Mike's **Netbird overlay IP:port**. WireGuard
  already provides encryption, mutual auth, and NAT traversal, so the sidecar stays a plain
  socket to a private address — **no app-layer TLS, no certs on the MediaMTX box**. UDP NDJSON
  is fine here (datagram telemetry inside an encrypted tunnel); TCP NDJSON also works if Mike
  prefers reliable delivery. This is the least-moving-parts option and the default.

- **mTLS (fallback, no Netbird on a given box).** **TCP NDJSON over mutual TLS** to Mike's
  public TLS endpoint, presenting a client cert in the **same format as his TAK Server feeds**
  (he already accepts that — reuse it). The sidecar needs a cert/key/CA path trio. Note: TLS is
  TCP-only, so this mode is TCP-framed NDJSON (not UDP). Schema is unchanged.

Decision rule: if the box is on Netbird → Netbird mode (simplest, no certs). Otherwise → mTLS.
Both reduce to "open a socket, write NDJSON lines"; only connection setup differs.

What Mike does with it (his side, documented here only for shared understanding):
- `up` → mute ADS-B for that hex's UID; start writing platform CoT from `platform`,
  re-inject the existing video-URL/callsign details so the radial play button survives.
- per `sample` → update platform UID (merged), emit SPI CoT (`b-m-p-s-p-i`, own UID) from
  `spi`, draw slant line from `platform`+`sensor`.
- `down` (or samples stale > N s) → expire SPI/slant UIDs, resume ADS-B on the platform UID.

### 4.5 UI changes (External Sources tab)

- On the Add/Edit External Source form (`config-editor/mediamtx_config_editor.py:2112`+):
  add a section, shown for all protocols, after the protocol-specific fields:
  - checkbox **"Extract KLV → CoT (send sensor metadata to an aggregator)"**
  - when checked, reveal:
    - **Transport**: `Netbird (plain socket over WireGuard)` (default) | `mTLS (public)`.
    - **Aggregator target (host/IP:port)** (required, validated). For Netbird this is Mike's
      overlay IP; for mTLS his public TLS host.
    - **Aircraft hex / ID** (optional; default = stream name).
    - When `mTLS` is selected: **Client cert / key / CA** paths (TAK-format cert reused).
    - When `Netbird` is selected: optional **proto** UDP (default) | TCP.
  - help text: explains this taps MISB KLV and forwards to a remote CoT proxy over Netbird or
    mTLS; does not affect video playback.
- Source row in "Configured External Sources" list: show a small badge when KLV→CoT is on
  (mirror the existing per-source badge/action pattern used by demux / Simulate link).

### 4.6 Backend changes

- `api_add_external_source()` (`:10944`) and the edit handler: accept `klvToCot` (bool),
  `klvTransport` (`netbird`|`mtls`), `klvTarget` (str `host:port`), `klvHex` (str, optional),
  `klvProto` (`udp`|`tcp`, netbird only), and `klvCert`/`klvKey`/`klvCaCert` paths (mtls only).
  Validate target as `host/IP:port` (1–65535); for mtls require the three cert paths exist and
  are readable. When `klvToCot` true, write the `runOnReady`/`runOnReadyRestart`/`runOnNotReady`
  lines into the path block (4.1) with the transport args from 4.3, and store all fields in
  `external_sources` metadata (`load/save_external_sources_metadata`, `:10877`/`:10887`).
  Do not store cert *contents* — only paths.
- Delete handler: nothing extra (path removal already drops the hooks).
- `api_list_external_sources()` (`:10896`): include `klv_to_cot`, `klv_transport`,
  `klv_target`, `klv_hex` (and proto/cert paths) in the returned source objects so the UI can
  render the badge/edit state.
- Installer: drop `klv-to-cot.py` to `/opt/mediamtx-webeditor/`, `chmod +x`, ensure
  `klvdata` installed. Make the script path a constant alongside the others (`:54` style).
- Egress: outbound to the target is normal egress; no inbound UFW rule needed (unlike the
  udp+mpegts ingest case at `:11040`). Netbird traffic rides the existing `wt0`/WireGuard
  interface; mTLS is a normal outbound TCP connection. No new listener is opened on this box.

## 5. Acceptance test

Prereqs: a feed with KLV (the repo ships an H264+KLV reference at `teststream` /
`config-editor/mediamtx_config_editor.py:5392`; use it or a real aircraft SRT).

```bash
# 1. Stand-in aggregator listener (pick the transport you're testing):
#    Netbird/UDP:  nc -u -l 0.0.0.0 9000      (or socat -u UDP-RECV:9000 -)
#    Netbird/TCP:  nc -l 0.0.0.0 9000
#    mTLS:         openssl s_server -accept 9000 -cert mike.crt -key mike.key \
#                    -CAfile ca.crt -Verify 1 -quiet
nc -u -l 0.0.0.0 9000

# 2. In the web editor: Add/Edit External Source for the test feed,
#    enable "Extract KLV → CoT", Transport = Netbird, target = <this-box-ip>:9000,
#    hex = a1b2c3. Save. (For end-to-end, target = Mike's Netbird IP:port instead.)
#    (MediaMTX restarts; path now has runOnReady.)

# 3. Confirm the hooks landed in config:
grep -A6 'klvtest:' /usr/local/etc/mediamtx.yml   # path name as configured
#   expect: source:, runOnReady:, runOnReadyRestart: yes, runOnNotReady:

# 4. Start the feed (or it's pull-on-demand). Watch the nc window:
#   expect {"event":"up",...} then a stream of {"event":"sample",..."platform":{...}}
#   with plausible lat/lon for the test KLV.

# 5. Stop the feed. Expect a single {"event":"down",...} then silence.

# 6. Verify no impact on video: HLS/RTSP playback of the same path still works.
```

PASS = lifecycle up/down bracket a steady NDJSON sample stream carrying platform + (when
present) spi/sensor, every message stamped with the configured hex, and video playback
unaffected.

## 6. What this does NOT ship

- No CoT generation, no TAK Server connection — aggregator's job (Mike).
- No UID merge / ADS-B mute / failback / SPI / slant CoT — aggregator's job.
- No new ingest protocols — uses the existing External Sources pull paths as-is.
- Transport security is handled by Netbird (WireGuard) or mTLS — not re-implemented here. No
  bespoke crypto. (Plain UDP on the open internet is explicitly NOT a mode.)
- No cert issuance/rotation for the mTLS mode — operator supplies the TAK-format client cert
  paths; lifecycle of those certs is out of scope.
- No multi-aggregator fan-out — one target per source for v2.1.0.
- No reconciliation of KLV vs ADS-B position jump at handoff — aggregator's call.

## 7. Open items to confirm with Mike before build

1. Transport: **Netbird** (his overlay IP, plain socket — simplest) or **mTLS** (reuse his
   TAK client-cert ingest)? Default Netbird unless he wants everything funneled through his
   existing TLS ingest. If mTLS, he provides the CA + a client cert in TAK format.
   And framing: NDJSON ok, or different framing on his end?
2. Port convention (one shared listener port for all aircraft, keyed by `hex` in-band — the
   design above — vs a port per aircraft)? In-band hex is strongly preferred.
3. Does he want the `up`/`down` sentinels, or will he infer purely from sample staleness?
   (We ship sentinels regardless; question is whether he uses them.)
4. Confirm the field set in 4.4 covers what his CoT emitter needs (esp. whether he wants
   raw sensor angles vs a pre-computed SPI — we give both).
