#!/usr/bin/env python3
"""
klv-to-cot.py — MediaMTX KLV extraction sidecar (mediamtx-installer v2.1.0)

Taps the MISB ST0601 KLV metadata out of a live video path and ships decoded
platform / sensor / frame-center samples as newline-delimited JSON to a remote
aggregator (Mike's CoT proxy). This script produces decoded KLV ONLY — it does
NOT generate CoT, merge UIDs, or talk to TAK Server. See PLAN-v2.1.0.

Launched by MediaMTX runOnReady on an External Source path:
    runOnReady: /opt/mediamtx-webeditor/klv-to-cot.py --path $MTX_PATH --hex <hex> --target <ip:port>
    runOnNotReady: /opt/mediamtx-webeditor/klv-to-cot.py --path $MTX_PATH --hex <hex> --target <ip:port> --downlink

Self-contained: needs only python3 + ffmpeg. No third-party packages (the
ST0601 decoder is vendored below — only the ~16 tags the aggregator consumes).

Transport (same NDJSON payload either way — see PLAN §4.4 / §4.4a):
  Netbird/plain:  --target <netbird-ip:port> [--proto udp|tcp]
  mTLS:           --target <host:port> --tls --cert <p> --key <p> --cacert <p>

Testing off-box (no MediaMTX needed):
  ffmpeg -i config-editor/truck_60.ts -map 0:d -c copy -f data - \
    | ./klv-to-cot.py --path truck --hex test01 --input - --dry-run
"""

import argparse
import json
import os
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------------------
# ST0601 UAS Datalink Local Set — minimal vendored decoder
# ---------------------------------------------------------------------------

# 16-byte Universal Key that prefixes every ST0601 local set.
UAS_LS_KEY = bytes.fromhex("060E2B34020B01010E01030101000000")

# Per-tag decoders. Each entry: (output_path, fn(raw_bytes) -> float|int).
# Linear maps per MISB ST0601; ranges/precision per the standard.
_INT_MAX_4 = 2**31 - 1
_UINT_MAX_4 = 2**32 - 1
_INT_MAX_2 = 2**15 - 1
_UINT_MAX_2 = 2**16 - 1


def _u(b):
    return int.from_bytes(b, "big", signed=False)


def _s(b):
    return int.from_bytes(b, "big", signed=True)


# The symmetric signed tags (lat/lon, elevation angles) map
# -full..+full -> -range..+range, i.e. value = s * range / full.
def _sym_s(b, rng, full):
    return _s(b) * rng / full


def _uns(b, lo, hi, full):
    return lo + _u(b) * (hi - lo) / full


# tag -> (json_path tuple, decoder)
TAGS = {
    2:  (("ts_us",),                 lambda b: _u(b)),                       # Precision Time Stamp (µs)
    5:  (("platform", "heading_deg"), lambda b: _uns(b, 0, 360, _UINT_MAX_2)),
    6:  (("platform", "pitch_deg"),   lambda b: _sym_s(b, 20, _INT_MAX_2)),
    7:  (("platform", "roll_deg"),    lambda b: _sym_s(b, 50, _INT_MAX_2)),
    13: (("platform", "lat"),         lambda b: _sym_s(b, 90, _INT_MAX_4)),
    14: (("platform", "lon"),         lambda b: _sym_s(b, 180, _INT_MAX_4)),
    15: (("platform", "alt_m"),       lambda b: _uns(b, -900, 19000, _UINT_MAX_2)),
    16: (("sensor", "hfov_deg"),      lambda b: _uns(b, 0, 180, _UINT_MAX_2)),
    17: (("sensor", "vfov_deg"),      lambda b: _uns(b, 0, 180, _UINT_MAX_2)),
    18: (("sensor", "rel_az_deg"),    lambda b: _uns(b, 0, 360, _UINT_MAX_4)),
    19: (("sensor", "rel_el_deg"),    lambda b: _sym_s(b, 180, _INT_MAX_4)),
    20: (("sensor", "rel_roll_deg"),  lambda b: _uns(b, 0, 360, _UINT_MAX_4)),
    21: (("sensor", "slant_range_m"), lambda b: _uns(b, 0, 5_000_000, _UINT_MAX_4)),
    23: (("spi", "lat"),              lambda b: _sym_s(b, 90, _INT_MAX_4)),
    24: (("spi", "lon"),              lambda b: _sym_s(b, 180, _INT_MAX_4)),
    25: (("spi", "elev_m"),           lambda b: _uns(b, -900, 19000, _UINT_MAX_2)),
}


def _ber_len(buf, i):
    """Decode a BER length at buf[i]. Returns (length, next_index) or (None, i) if short."""
    if i >= len(buf):
        return None, i
    first = buf[i]
    if first < 0x80:
        return first, i + 1
    n = first & 0x7F
    if i + 1 + n > len(buf):
        return None, i
    return int.from_bytes(buf[i + 1:i + 1 + n], "big"), i + 1 + n


def _parse_local_set(payload):
    """Parse the TLV body of one ST0601 local set into {tag: raw_bytes}."""
    out = {}
    i = 0
    n = len(payload)
    while i < n:
        tag = payload[i]  # ST0601 tags 1..94 are single-byte
        i += 1
        length, i = _ber_len(payload, i)
        if length is None or i + length > n:
            break
        out[tag] = payload[i:i + length]
        i += length
    return out


def _to_sample(tags):
    """Convert raw {tag: bytes} into the nested NDJSON sample dict (omitting absent fields)."""
    nested = {}
    ts_us = None
    for tag, raw in tags.items():
        spec = TAGS.get(tag)
        if not spec:
            continue
        path, fn = spec
        try:
            val = fn(raw)
        except Exception:
            continue
        if path == ("ts_us",):
            ts_us = val
            continue
        d = nested
        for k in path[:-1]:
            d = d.setdefault(k, {})
        d[path[-1]] = round(val, 6) if isinstance(val, float) else val
    if ts_us:
        nested["ts"] = round(ts_us / 1_000_000.0, 3)
    return nested


class StreamScanner:
    """Incrementally scan a byte stream for ST0601 local sets, yielding raw tag dicts."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, chunk):
        self.buf.extend(chunk)
        while True:
            idx = self.buf.find(UAS_LS_KEY)
            if idx < 0:
                # Keep a tail in case the key spans the next chunk boundary.
                if len(self.buf) > len(UAS_LS_KEY):
                    del self.buf[:-len(UAS_LS_KEY)]
                return
            start = idx + len(UAS_LS_KEY)
            length, after_len = _ber_len(self.buf, start)
            if length is None:
                return  # need more bytes for the length field
            end = after_len + length
            if end > len(self.buf):
                return  # need more bytes for the full payload
            payload = bytes(self.buf[after_len:end])
            del self.buf[:end]
            yield _parse_local_set(payload)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class Sender:
    """Writes NDJSON lines over UDP, TCP, or TCP+mTLS. Reconnects with backoff (TCP/TLS)."""

    def __init__(self, host, port, proto="udp", tls=False,
                 cert=None, key=None, cacert=None, dry_run=False):
        self.host, self.port = host, port
        self.proto = "tcp" if tls else proto
        self.tls = tls
        self.cert, self.key, self.cacert = cert, key, cacert
        self.dry_run = dry_run
        self.sock = None
        self._backoff = 1.0
        if not dry_run and self.proto == "udp":
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _connect_tcp(self):
        s = socket.create_connection((self.host, self.port), timeout=10)
        if self.tls:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.cacert)
            if self.cert and self.key:
                ctx.load_cert_chain(self.cert, self.key)
            s = ctx.wrap_socket(s, server_hostname=self.host)
        self.sock = s
        self._backoff = 1.0

    def send(self, obj):
        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        if self.dry_run:
            sys.stdout.write(line.decode())
            sys.stdout.flush()
            return
        try:
            if self.proto == "udp":
                self.sock.sendto(line, (self.host, self.port))
            else:
                if self.sock is None:
                    self._connect_tcp()
                self.sock.sendall(line)
        except (OSError, ssl.SSLError) as e:
            # UDP rarely raises; TCP/TLS drops -> reconnect on next send with backoff.
            sys.stderr.write(f"[klv-to-cot] send failed: {e}\n")
            if self.proto != "udp" and self.sock is not None:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None
                time.sleep(min(self._backoff, 30))
                self._backoff = min(self._backoff * 2, 30)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_target(t):
    host, _, port = t.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError("target must be host:port")
    return host, int(port)


def build_args():
    p = argparse.ArgumentParser(description="MediaMTX KLV -> NDJSON sidecar")
    p.add_argument("--path", required=True, help="MediaMTX path name (used in rtsp url + tagging)")
    p.add_argument("--hex", required=True, help="aircraft hex/id; stamped on every message (merge key)")
    p.add_argument("--target", required=True, type=parse_target, help="aggregator host:port")
    p.add_argument("--token", default="", help="ingest token; stamped on every message (aggregator drops messages without a valid token)")
    p.add_argument("--proto", choices=["udp", "tcp"], default="tcp", help="netbird transport (ignored with --tls)")
    p.add_argument("--tls", action="store_true", help="use TCP+mTLS")
    p.add_argument("--cert", help="client cert (mTLS)")
    p.add_argument("--key", help="client key (mTLS)")
    p.add_argument("--cacert", help="CA cert (mTLS)")
    p.add_argument("--rtsp-base", default="rtsp://127.0.0.1:8554", help="local MediaMTX rtsp base")
    p.add_argument("--input", help="read raw KLV from FILE or '-' (stdin) instead of spawning ffmpeg (testing)")
    p.add_argument("--max-hz", type=float, default=10.0, help="max samples/sec sent (rate cap)")
    p.add_argument("--downlink", action="store_true", help="send a single 'down' sentinel and exit")
    p.add_argument("--dry-run", action="store_true", help="print NDJSON to stdout instead of sending")
    return p.parse_args()


def main():
    a = build_args()
    host, port = a.target
    sender = Sender(host, port, proto=a.proto, tls=a.tls,
                    cert=a.cert, key=a.key, cacert=a.cacert, dry_run=a.dry_run)

    def envelope(event, extra=None):
        msg = {"event": event, "hex": a.hex, "path": a.path, "ts": round(time.time(), 3)}
        if a.token:
            msg["token"] = a.token  # aggregator authenticates/routes by this; required in prod
        if extra:
            msg.update(extra)
        return msg

    # runOnNotReady invocation: one-shot down sentinel.
    if a.downlink:
        sender.send(envelope("down"))
        sender.close()
        return 0

    # Source: ffmpeg tapping the local rebroadcast, or a file/stdin for testing.
    proc = None
    if a.input:
        reader = sys.stdin.buffer if a.input == "-" else open(a.input, "rb")
    else:
        url = f"{a.rtsp_base}/{a.path}"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "+igndts",
               "-rtsp_transport", "tcp", "-i", url,
               "-map", "0:d", "-c", "copy", "-f", "data", "pipe:1"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        reader = proc.stdout

        # The KLV data substream's timestamps aren't monotonic over RTSP, so ffmpeg's data
        # muxer logs "non monotonic dts" ~30x/sec — pure noise that would flood MediaMTX's
        # logs. Drop those lines; forward any genuine ffmpeg errors (e.g. connect failures).
        def _filter_ffmpeg_stderr(pipe):
            for line in iter(pipe.readline, b''):
                if b'monoton' in line:
                    continue
                try:
                    sys.stderr.buffer.write(line)
                    sys.stderr.flush()
                except Exception:
                    break
        threading.Thread(target=_filter_ffmpeg_stderr, args=(proc.stderr,), daemon=True).start()

    def shutdown(*_):
        if proc and proc.poll() is None:
            proc.terminate()
        sender.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    scanner = StreamScanner()
    sent_up = False
    min_interval = 1.0 / a.max_hz if a.max_hz > 0 else 0.0
    last_sent = 0.0

    try:
        while True:
            # read1() returns as soon as data is available rather than blocking for a full
            # 64KB. Plain read(n) would batch ~6s of KLV then process it in one burst, so
            # the rate-limiter (same instant for the whole batch) would emit only one sample
            # per batch — starving the aggregator regardless of --max-hz.
            chunk = reader.read1(65536) if hasattr(reader, "read1") else reader.read(65536)
            if not chunk:
                break
            for tags in scanner.feed(chunk):
                sample = _to_sample(tags)
                if not sample.get("platform") and not sample.get("spi"):
                    continue  # nothing useful decoded from this set
                if not sent_up:
                    sender.send(envelope("up"))
                    sent_up = True
                now = time.monotonic()
                if now - last_sent < min_interval:
                    continue  # rate cap
                last_sent = now
                sender.send(envelope("sample", sample))
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
        sender.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
