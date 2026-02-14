#!/bin/bash

# MediaMTX Installation Script for Ubuntu 22.04
# Installs MediaMTX streaming server with custom production configuration
# Includes FFmpeg for HLS transcoding
# v2.0 - Ships with proven custom YAML template

set -e

# Prevent interactive prompts
export DEBIAN_FRONTEND=noninteractive

echo "=========================================="
echo "MediaMTX Installer v2.0 (Ubuntu 22.04)"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# ==========================================
# Unattended-Upgrade Detection
# ==========================================
if pgrep -f "/usr/bin/unattended-upgrade$" > /dev/null; then
    echo ""
    echo "************************************************************"
    echo "  YOUR OPERATING SYSTEM IS CURRENTLY DOING UPGRADES"
    echo "  We need to wait until this is done."
    echo "  The process will auto-start once updates are complete."
    echo "************************************************************"
    echo ""
    
    SECONDS=0
    while pgrep -f "/usr/bin/unattended-upgrade$" > /dev/null; do
        printf "\rWaiting... %02d:%02d elapsed" $((SECONDS/60)) $((SECONDS%60))
        sleep 2
    done
    
    echo ""
    echo ""
    echo "✓ Updates complete after $((SECONDS/60)) minutes! Starting installation..."
    echo ""
    sleep 2
else
    echo "Checking for system upgrades in progress..."
    echo "✓ No system upgrades in progress, continuing..."
    echo ""
fi

# ==========================================
# Detect Architecture
# ==========================================
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        MEDIAMTX_ARCH="amd64"
        ;;
    aarch64)
        MEDIAMTX_ARCH="arm64v8"
        ;;
    armv7l)
        MEDIAMTX_ARCH="armv7"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "Detected architecture: $ARCH (MediaMTX: $MEDIAMTX_ARCH)"
echo ""

# ==========================================
# Step 1: Installing Dependencies
# ==========================================
echo "=========================================="
echo "Step 1: Installing Dependencies"
echo "=========================================="

apt-get update -qq
apt-get install -y wget tar ufw curl ffmpeg > /dev/null 2>&1 || apt-get install -y wget tar ufw curl ffmpeg
echo "✓ Dependencies installed (including FFmpeg)"

echo ""
echo "=========================================="
echo "Step 2: Detecting Latest MediaMTX Version"
echo "=========================================="

# Get latest version from GitHub
LATEST_VERSION=$(curl -s https://api.github.com/repos/bluenviron/mediamtx/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to detect latest version. Please check your internet connection."
    exit 1
fi

echo "Latest MediaMTX version: $LATEST_VERSION"

# Construct download URL
DOWNLOAD_URL="https://github.com/bluenviron/mediamtx/releases/download/v${LATEST_VERSION}/mediamtx_v${LATEST_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"

echo ""
echo "=========================================="
echo "Step 3: Downloading MediaMTX"
echo "=========================================="

# Create temporary directory
TMP_DIR=$(mktemp -d)
cd "$TMP_DIR"

wget -q -O mediamtx.tar.gz "$DOWNLOAD_URL"
if [ $? -ne 0 ]; then
    echo "Failed to download MediaMTX"
    exit 1
fi
echo "✓ Downloaded MediaMTX v${LATEST_VERSION}"

echo ""
echo "=========================================="
echo "Step 4: Installing MediaMTX"
echo "=========================================="

tar -xzf mediamtx.tar.gz

# Move executable to /usr/local/bin
mv mediamtx /usr/local/bin/
chmod +x /usr/local/bin/mediamtx

# Create config directory
mkdir -p /usr/local/etc

echo "✓ MediaMTX binary installed to /usr/local/bin/"

echo ""
echo "=========================================="
echo "Step 5: Installing Custom Configuration"
echo "=========================================="

# Generate random 16-character HLS viewer password
HLS_PASS=$(openssl rand -base64 16 | tr -d '/+=\n' | head -c 16)

# Write the custom configuration
cat > /usr/local/etc/mediamtx.yml << 'CONFIGEOF'
###############################################
# Global settings

# Settings in this section are applied anywhere.

###############################################
# Global settings -> General

# Verbosity of the program; available values are "error", "warn", "info", "debug".
logLevel: info
# Destinations of log messages; available values are "stdout", "file" and "syslog".
logDestinations: [stdout]
# When destination is "stdout" or "file", emit logs in structured format (JSON).
logStructured: no
# When "file" is in logDestinations, this is the file which will receive logs.
logFile: mediamtx.log
# When "syslog" is in logDestinations, use prefix for logs.
sysLogPrefix: mediamtx

# Timeout of read operations.
readTimeout: 10s
# Timeout of write operations.
writeTimeout: 10s
# Size of the queue of outgoing packets.
# A higher value allows to increase throughput, a lower value allows to save RAM.
writeQueueSize: 512
# Maximum size of outgoing UDP packets.
# This can be decreased to avoid fragmentation on networks with a low UDP MTU.
udpMaxPayloadSize: 1472
# Size of the read buffer of every UDP socket.
# This can be increased to decrease packet losses.
# It defaults to the default value of the operating system.
udpReadBufferSize: 0

# Command to run when a client connects to the server.
# This is terminated with SIGINT when a client disconnects from the server.
# The following environment variables are available:
# * MTX_CONN_TYPE: connection type
# * MTX_CONN_ID: connection ID
# * RTSP_PORT: RTSP server port
runOnConnect:
# Restart the command if it exits.
runOnConnectRestart: no
# Command to run when a client disconnects from the server.
# Environment variables are the same of runOnConnect.
runOnDisconnect:

###############################################
# Global settings -> Authentication

# Authentication method. Available values are:
# * internal: credentials are stored in the configuration file
# * http: an external HTTP URL is contacted to perform authentication
# * jwt: an external identity server provides authentication through JWTs
authMethod: internal

# Internal authentication.
# list of users.
authInternalUsers:
# Internal FFmpeg - localhost only
- user: any
  ips: ['127.0.0.1', '::1']
  permissions:
  - action: read
  - action: publish
  - action: api
# HLS PLAYER
- user: hlsviewer
  pass: changeme
  ips: []
  permissions:
  - action: read
# Public test stream - no auth, teststream only
- user: any
  pass: ''
  ips: []
  permissions:
  - action: read
    path: teststream
authHTTPAddress:
# Actions to exclude from HTTP-based authentication.
# Format is the same as the one of user permissions.
authHTTPExclude:
- action: api
- action: metrics
- action: pprof

# JWT-based authentication.
# Users have to login through an external identity server and obtain a JWT.
# This JWT must contain the claim "mediamtx_permissions" with permissions,
# for instance:
# {
#  "mediamtx_permissions": [
#     {
#       "action": "publish",
#       "path": "somepath"
#     }
#   ]
# }
# Users are expected to pass the JWT in the Authorization header or as password.
# This is the JWKS URL that will be used to pull (once) the public key that allows
# to validate JWTs.
authJWTJWKS:
# If the JWKS URL has a self-signed or invalid certificate,
# you can provide the fingerprint of the certificate in order to
# validate it anyway. It can be obtained by running:
# openssl s_client -connect jwt_jwks_domain:443 </dev/null 2>/dev/null | sed -n '/BEGIN/,/END/p' > server.crt
# openssl x509 -in server.crt -noout -fingerprint -sha256 | cut -d "=" -f2 | tr -d ':'
authJWTJWKSFingerprint:
# name of the claim that contains permissions.
authJWTClaimKey: mediamtx_permissions
# Actions to exclude from JWT-based authentication.
# Format is the same as the one of user permissions.
authJWTExclude: []
# allow passing the JWT through query parameters of HTTP requests (i.e. ?jwt=JWT).
# This is a security risk and will be disabled by default in the future.
authJWTInHTTPQuery: true

###############################################
# Global settings -> Control API

# Enable controlling the server through the Control API.
api: yes
# Address of the Control API listener.
apiAddress: :9997
# Enable TLS/HTTPS on the Control API server.
apiEncryption: no
# Path to the server key. This is needed only when encryption is yes.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
apiServerKey:
# Path to the server certificate.
apiServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
apiAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the HTTP server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
apiTrustedProxies: []

###############################################
# Global settings -> Metrics

# Enable Prometheus-compatible metrics.
metrics: no
# Address of the metrics HTTP listener.
metricsAddress: :9998
# Enable TLS/HTTPS on the Metrics server.
metricsEncryption: no
# Path to the server key. This is needed only when encryption is yes.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
metricsServerKey:
# Path to the server certificate.
metricsServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
metricsAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the HTTP server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
metricsTrustedProxies: []

###############################################
# Global settings -> PPROF

# Enable pprof-compatible endpoint to monitor performances.
pprof: no
# Address of the pprof listener.
pprofAddress: :9999
# Enable TLS/HTTPS on the pprof server.
pprofEncryption: no
# Path to the server key. This is needed only when encryption is yes.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
pprofServerKey:
# Path to the server certificate.
pprofServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
pprofAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the HTTP server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
pprofTrustedProxies: []

###############################################
# Global settings -> Playback server

# Enable downloading recordings from the playback server.
playback: no
# Address of the playback server listener.
playbackAddress: :9996
# Enable TLS/HTTPS on the playback server.
playbackEncryption: no
# Path to the server key. This is needed only when encryption is yes.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
playbackServerKey:
# Path to the server certificate.
playbackServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
playbackAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the HTTP server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
playbackTrustedProxies: []

###############################################
# Global settings -> RTSP server

# Enable publishing and reading streams with the RTSP protocol.
rtsp: yes
# List of enabled RTSP transport protocols.
# UDP is the most performant, but doesn't work when there's a NAT/firewall between
# server and clients.
# UDP-multicast allows to save bandwidth when clients are all in the same LAN.
# TCP is the most versatile.
# The handshake is always performed with TCP.
rtspTransports: [tcp]
# Use secure protocol variants (RTSPS, TLS, SRTP).
# Available values are "no", "strict", "optional".
rtspEncryption: "no"
# Address of the TCP/RTSP listener. This is needed only when encryption is "no" or "optional".
rtspAddress: :8554
# Address of the TCP/TLS/RTSPS listener. This is needed only when encryption is "strict" or "optional".
rtspsAddress: :8322
# Address of the UDP/RTP listener. This is needed only when "udp" is in rtspTransports.
rtpAddress: :8000
# Address of the UDP/RTCP listener. This is needed only when "udp" is in rtspTransports.
rtcpAddress: :8001
# IP range of all UDP-multicast listeners. This is needed only when "multicast" is in rtspTransports.
multicastIPRange: 224.1.0.0/16
# Port of all UDP-multicast/RTP listeners. This is needed only when "multicast" is in rtspTransports.
multicastRTPPort: 8002
# Port of all UDP-multicast/RTCP listeners. This is needed only when "multicast" is in rtspTransports.
multicastRTCPPort: 8003
# Address of the UDP/SRTP listener. This is needed only when "udp" is in rtspTransports and encryption is enabled.
srtpAddress: :8004
# Address of the UDP/SRTCP listener. This is needed only when "udp" is in rtspTransports and encryption is enabled.
srtcpAddress: :8005
# Port of all UDP-multicast/SRTP listeners. This is needed only when "multicast" is in rtspTransports and encryption is enabled.
multicastSRTPPort: 8006
# Port of all UDP-multicast/SRTCP listeners. This is needed only when "multicast" is in rtspTransports and encryption is enabled.
multicastSRTCPPort: 8007
# Path to the server key. This is needed only when encryption is "strict" or "optional".
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
rtspServerKey:
# Path to the server certificate. This is needed only when encryption is "strict" or "optional".
rtspServerCert:
# Authentication methods. Available are "basic" and "digest".
# "digest" doesn't provide any additional security and is available for compatibility only.
rtspAuthMethods: [basic]

###############################################
# Global settings -> RTMP server

# Enable publishing and reading streams with the RTMP protocol.
rtmp: no
# Address of the RTMP listener. This is needed only when encryption is "no" or "optional".
rtmpAddress: :1935
# Encrypt connections with TLS (RTMPS).
# Available values are "no", "strict", "optional".
rtmpEncryption: "no"
# Address of the RTMPS listener. This is needed only when encryption is "strict" or "optional".
rtmpsAddress: :1936
# Path to the server key. This is needed only when encryption is "strict" or "optional".
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
rtmpServerKey:
# Path to the server certificate. This is needed only when encryption is "strict" or "optional".
rtmpServerCert:

###############################################
# Global settings -> HLS server

# Enable reading streams with the HLS protocol.
hls: yes
# Address of the HLS listener.
hlsAddress: :8888
# Enable TLS/HTTPS on the HLS server.
# This is required for Low-Latency HLS.
hlsEncryption: no
# Path to the server key. This is needed only when encryption is yes.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
hlsServerKey:
# Path to the server certificate.
hlsServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
hlsAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the HLS server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
hlsTrustedProxies: ['127.0.0.1']
# By default, HLS is generated only when requested by a user.
# This option allows to generate it always, avoiding the delay between request and generation.
hlsAlwaysRemux: no
# Variant of the HLS protocol to use. Available options are:
# * mpegts - uses MPEG-TS segments, for maximum compatibility.
# * fmp4 - uses fragmented MP4 segments, more efficient.
# * lowLatency - uses Low-Latency HLS.
hlsVariant: mpegts
# Number of HLS segments to keep on the server.
# Segments allow to seek through the stream.
# Their number doesn't influence latency.
hlsSegmentCount: 3
# Minimum duration of each segment.
# A player usually puts 3 segments in a buffer before reproducing the stream.
# The final segment duration is also influenced by the interval between IDR frames,
# since the server changes the duration in order to include at least one IDR frame
# in each segment.
hlsSegmentDuration: 500ms
# Minimum duration of each part.
# A player usually puts 3 parts in a buffer before reproducing the stream.
# Parts are used in Low-Latency HLS in place of segments.
# Part duration is influenced by the distance between video/audio samples
# and is adjusted in order to produce segments with a similar duration.
hlsPartDuration: 200ms
# Maximum size of each segment.
# This prevents RAM exhaustion.
hlsSegmentMaxSize: 50M
# Directory in which to save segments, instead of keeping them in the RAM.
# This decreases performance, since reading from disk is less performant than
# reading from RAM, but allows to save RAM.
hlsDirectory: ''
# The muxer will be closed when there are no
# reader requests and this amount of time has passed.
hlsMuxerCloseAfter: 60s

###############################################
# Global settings -> WebRTC server

# Enable publishing and reading streams with the WebRTC protocol.
webrtc: no
# Address of the WebRTC HTTP listener.
webrtcAddress: :8889
# Enable TLS/HTTPS on the WebRTC server.
webrtcEncryption: no
# Path to the server key.
# This can be generated with:
# openssl genrsa -out server.key 2048
# openssl req -new -x509 -sha256 -key server.key -out server.crt -days 3650
webrtcServerKey:
# Path to the server certificate.
webrtcServerCert:
# List of allowed CORS origins.
# Supports wildcards: ['http://*.example.com']
webrtcAllowOrigins: ['*']
# List of IPs or CIDRs of proxies placed before the WebRTC server.
# If the server receives a request from one of these entries, IP in logs
# will be taken from the X-Forwarded-For header.
webrtcTrustedProxies: []
# Address of a local UDP listener that will receive connections.
# Use a blank string to disable.
webrtcLocalUDPAddress: :8189
# Address of a local TCP listener that will receive connections.
# This is disabled by default since TCP is less efficient than UDP and
# introduces a progressive delay when network is congested.
webrtcLocalTCPAddress: ''
# WebRTC clients need to know the IP of the server.
# Gather IPs from interfaces and send them to clients.
webrtcIPsFromInterfaces: yes
# List of interfaces whose IPs will be sent to clients.
# An empty value means to use all available interfaces.
webrtcIPsFromInterfacesList: []
# List of additional hosts or IPs to send to clients.
webrtcAdditionalHosts: []
# ICE servers. Needed only when local listeners can't be reached by clients.
# STUN servers allows to obtain and share the public IP of the server.
# TURN/TURNS servers forces all traffic through them.
webrtcICEServers2: []
  # - url: stun:stun.l.google.com:19302
  # if user is "AUTH_SECRET", then authentication is secret based.
  # the secret must be inserted into the password field.
  # username: ''
  # password: ''
  # clientOnly: false
# Time to wait for the WebRTC handshake to complete.
webrtcHandshakeTimeout: 10s
# Maximum time to gather video tracks.
webrtcTrackGatherTimeout: 2s
# The maximum time to gather STUN candidates.
webrtcSTUNGatherTimeout: 5s

###############################################
# Global settings -> SRT server

# Enable publishing and reading streams with the SRT protocol.
srt: yes
# Address of the SRT listener.
srtAddress: :8890

###############################################
# Default path settings

# Settings in "pathDefaults" are applied anywhere,
# unless they are overridden in "paths".
pathDefaults:

  ###############################################
  # Default path settings -> General

  # Source of the stream. This can be:
  # * publisher -> the stream is provided by a RTSP, RTMP, WebRTC or SRT client
  # * rtsp://existing-url -> the stream is pulled from another RTSP server / camera
  # * rtsps://existing-url -> the stream is pulled from another RTSP server / camera with RTSPS
  # * rtsp+http://existing-url -> the stream is pulled from another RTSP server / camera, with HTTP tunneling
  # * rtsps+http://existing-url -> the stream is pulled from another RTSP server / camera, with HTTPS tunneling
  # * rtsp+ws://existing-url -> the stream is pulled from another RTSP server / camera, with WebSocket tunneling
  # * rtsps+ws://existing-url -> the stream is pulled from another RTSP server / camera, with secure WebSocket tunneling
  # * rtmp://existing-url -> the stream is pulled from another RTMP server / camera
  # * rtmps://existing-url -> the stream is pulled from another RTMP server / camera with RTMPS
  # * http://existing-url/stream.m3u8 -> the stream is pulled from another HLS server / camera
  # * https://existing-url/stream.m3u8 -> the stream is pulled from another HLS server / camera with HTTPS
  # * udp+mpegts://ip:port -> the stream is pulled from MPEG-TS over UDP, by listening on the specified address
  # * unix+mpegts://socket -> the stream is pulled from MPEG-TS over Unix socket, by using the socket
  # * udp+rtp://ip:port -> the stream is pulled from RTP over UDP, by listening on the specified address
  # * unix+rtp://socket -> the stream is pulled from RTP over Unix socket, by using the socket
  # * srt://existing-url -> the stream is pulled from another SRT server / camera
  # * whep://existing-url -> the stream is pulled from another WebRTC server / camera
  # * wheps://existing-url -> the stream is pulled from another WebRTC server / camera with HTTPS
  # * redirect -> the stream is provided by another path or server
  # * rpiCamera -> the stream is provided by a Raspberry Pi Camera
  # The following variables can be used in the source string:
  # * $MTX_QUERY: query parameters (passed by first reader)
  # * $G1, $G2, ...: regular expression groups, if path name is
  #   a regular expression.
  source: publisher
  # If the source is a URL, and the source TLS certificate is self-signed
  # or invalid, you can provide the fingerprint of the certificate in order to
  # validate it anyway. It can be obtained by running:
  # openssl s_client -connect source_ip:source_port </dev/null 2>/dev/null | sed -n '/BEGIN/,/END/p' > server.crt
  # openssl x509 -in server.crt -noout -fingerprint -sha256 | cut -d "=" -f2 | tr -d ':'
  sourceFingerprint:
  # If the source is a URL, it will be pulled only when at least
  # one reader is connected, saving bandwidth.
  sourceOnDemand: no
  # If sourceOnDemand is "yes", readers will be put on hold until the source is
  # ready or until this amount of time has passed.
  sourceOnDemandStartTimeout: 10s
  # If sourceOnDemand is "yes", the source will be closed when there are no
  # readers connected and this amount of time has passed.
  sourceOnDemandCloseAfter: 10s
  # Maximum number of readers. Zero means no limit.
  maxReaders: 0
  # SRT encryption passphrase required to read from this path.
  # If the stream is not available, redirect readers to this path.
  # It can be can be a relative path (i.e. /otherstream) or an absolute RTSP URL.
  fallback:
  # Use absolute timestamp of frames, instead of replacing them with the current time.
  useAbsoluteTimestamp: false

  ###############################################
  # Default path settings -> Record

  # Record streams to disk.
  record: no
  # Path of recording segments.
  # Extension is added automatically.
  # Available variables are %path (path name), %Y %m %d (year, month, day),
  # %H %M %S (hours, minutes, seconds), %f (microseconds), %z (time zone), %s (unix epoch).
  recordPath: /opt/mediamtx-webeditor/recordings/%path_%Y-%m-%d_%H-%M-%S-%f
  # Format of recorded segments.
  # Available formats are "fmp4" (fragmented MP4) and "mpegts" (MPEG-TS).
  recordFormat: mpegts
  # fMP4 segments are concatenation of small MP4 files (parts), each with this duration.
  # MPEG-TS segments are concatenation of 188-bytes packets, flushed to disk with this period.
  # When a system failure occurs, the last part gets lost.
  # Therefore, the part duration is equal to the RPO (recovery point objective).
  recordPartDuration: 1s
  # This prevents RAM exhaustion.
  recordMaxPartSize: 50M
  # Minimum duration of each segment.
  recordSegmentDuration: 1h
  # Delete segments after this timespan.
  # Set to 0s to disable automatic deletion.
  recordDeleteAfter: 720h

  ###############################################
  # Default path settings -> Publisher source (when source is "publisher")

  # Allow another client to disconnect the current publisher and publish in its place.
  overridePublisher: yes
  # SRT encryption passphrase required to publish to this path.

  ###############################################
  # Default path settings -> RTSP source (when source is a RTSP or a RTSPS URL)

  # Transport protocol used to pull the stream. available values are "automatic", "udp", "multicast", "tcp".
  rtspTransport: automatic
  # Support sources that don't provide server ports or use random server ports. This is a security issue
  # and must be used only when interacting with sources that require it.
  rtspAnyPort: no
  # Range header to send to the source, in order to start streaming from the specified offset.
  # available values:
  # * clock: Absolute time
  # * npt: Normal Play Time
  # * smpte: SMPTE timestamps relative to the start of the recording
  rtspRangeType:
  # Available values:
  # * clock: UTC ISO 8601 combined date and time string, e.g. 20230812T120000Z
  # * npt: duration such as "300ms", "1.5m" or "2h45m", valid time units are "ns", "us" (or "µs"), "ms", "s", "m", "h"
  # * smpte: duration such as "300ms", "1.5m" or "2h45m", valid time units are "ns", "us" (or "µs"), "ms", "s", "m", "h"
  rtspRangeStart:

  ###############################################
  # Default path settings -> RTP source (when source is RTP)

  # session description protocol (SDP) of the RTP stream.
  rtpSDP:

  ###############################################
  # Default path settings -> Redirect source (when source is "redirect")

  # path which clients will be redirected to.
  # It can be can be a relative path (i.e. /otherstream) or an absolute RTSP URL.
  sourceRedirect:

  ###############################################
  # Default path settings -> Raspberry Pi Camera source (when source is "rpiCamera")

  # ID of the camera.
  rpiCameraCamID: 0
  # Whether this is a secondary stream.
  rpiCameraSecondary: false
  # Width of frames.
  rpiCameraWidth: 1920
  # Height of frames.
  rpiCameraHeight: 1080
  # Flip horizontally.
  rpiCameraHFlip: false
  # Flip vertically.
  rpiCameraVFlip: false
  # Brightness [-1, 1].
  rpiCameraBrightness: 0
  # Contrast [0, 16].
  rpiCameraContrast: 1
  # Saturation [0, 16].
  rpiCameraSaturation: 1
  # Sharpness [0, 16].
  rpiCameraSharpness: 1
  # Exposure mode.
  # values: normal, short, long, custom.
  rpiCameraExposure: normal
  # Auto-white-balance mode.
  # (auto, incandescent, tungsten, fluorescent, indoor, daylight, cloudy or custom).
  rpiCameraAWB: auto
  # Auto-white-balance fixed gains. This can be used in place of rpiCameraAWB.
  # format: [red,blue].
  rpiCameraAWBGains: [0, 0]
  # Denoise operating mode (off, cdn_off, cdn_fast, cdn_hq).
  rpiCameraDenoise: "off"
  # Fixed shutter speed, in microseconds.
  rpiCameraShutter: 0
  # Metering mode of the AEC/AGC algorithm (centre, spot, matrix or custom).
  rpiCameraMetering: centre
  # Fixed gain.
  rpiCameraGain: 0
  # EV compensation of the image in range [-10, 10].
  rpiCameraEV: 0
  # Region of interest, in format x,y,width,height (all normalized between 0 and 1).
  rpiCameraROI:
  # Whether to enable HDR on Raspberry Camera 3.
  rpiCameraHDR: false
  # Tuning file.
  rpiCameraTuningFile:
  # Sensor mode, in format [width]:[height]:[bit-depth]:[packing]
  # bit-depth and packing are optional.
  rpiCameraMode:
  # frames per second.
  rpiCameraFPS: 30
  # Autofocus mode (auto, manual or continuous).
  rpiCameraAfMode: continuous
  # Autofocus range (normal, macro or full).
  rpiCameraAfRange: normal
  # Autofocus speed (normal or fast).
  rpiCameraAfSpeed: normal
  # Lens position (for manual autofocus only), will be set to focus to a specific distance
  # calculated by the following formula: d = 1 / value
  # Examples: 0 moves the lens to infinity.
  #           0.5 moves the lens to focus on objects 2m away.
  #           2 moves the lens to focus on objects 50cm away.
  rpiCameraLensPosition: 0.0
  # Autofocus window, in the form x,y,width,height where the coordinates
  # are given as a proportion of the entire image.
  rpiCameraAfWindow:
  # Manual flicker correction period, in microseconds.
  rpiCameraFlickerPeriod: 0
  # Enables printing text on each frame.
  rpiCameraTextOverlayEnable: false
  # Text that is printed on each frame.
  # format is the one of the strftime() function.
  rpiCameraTextOverlay: '%Y-%m-%d %H:%M:%S - MediaMTX'
  # Codec (auto, hardwareH264, softwareH264 or mjpeg).
  # When is "auto" and stream is primary, it defaults to hardwareH264 (if available) or softwareH264.
  # When is "auto" and stream is secondary, it defaults to mjpeg.
  rpiCameraCodec: auto
  # Period between IDR frames (when codec is hardwareH264 or softwareH264).
  rpiCameraIDRPeriod: 60
  # Bitrate (when codec is hardwareH264 or softwareH264).
  rpiCameraBitrate: 5000000
  # Hardware H264 profile (baseline, main or high) (when codec is hardwareH264).
  rpiCameraHardwareH264Profile: main
  # Hardware H264 level (4.0, 4.1 or 4.2) (when codec is hardwareH264).
  rpiCameraHardwareH264Level: '4.1'
  # Software H264 profile (baseline, main or high) (when codec is softwareH264).
  rpiCameraSoftwareH264Profile: baseline
  # Software H264 level (4.0, 4.1 or 4.2) (when codec is softwareH264).
  rpiCameraSoftwareH264Level: '4.1'
  # M-JPEG JPEG quality (when codec is mjpeg).
  rpiCameraMJPEGQuality: 60

  ###############################################
  # Default path settings -> Hooks

  # Command to run when this path is initialized.
  # This can be used to publish a stream when the server is launched.
  # This is terminated with SIGINT when the program closes.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnInit:
  # Restart the command if it exits.
  runOnInitRestart: no

  # Command to run when this path is requested by a reader
  # and no one is publishing to this path yet.
  # This can be used to publish a stream on demand.
  # This is terminated with SIGINT when there are no readers anymore.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * MTX_QUERY: query parameters (passed by first reader)
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnDemand:
  # Restart the command if it exits.
  runOnDemandRestart: no
  # Readers will be put on hold until the runOnDemand command starts publishing
  # or until this amount of time has passed.
  runOnDemandStartTimeout: 10s
  # The command will be closed when there are no
  # readers connected and this amount of time has passed.
  runOnDemandCloseAfter: 10s
  # Command to run when there are no readers anymore.
  # Environment variables are the same of runOnDemand.
  runOnUnDemand:

  # Command to run when the stream is ready to be read, whenever it is
  # published by a client or pulled from a server / camera.
  # This is terminated with SIGINT when the stream is not ready anymore.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * MTX_QUERY: query parameters (passed by publisher)
  # * MTX_SOURCE_TYPE: source type
  # * MTX_SOURCE_ID: source ID
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnReady:
  # Restart the command if it exits.
  runOnReadyRestart: no
  # Command to run when the stream is not available anymore.
  # Environment variables are the same of runOnReady.
  runOnNotReady:

  # Command to run when a client starts reading.
  # This is terminated with SIGINT when a client stops reading.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * MTX_QUERY: query parameters (passed by reader)
  # * MTX_READER_TYPE: reader type
  # * MTX_READER_ID: reader ID
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnRead:
  # Restart the command if it exits.
  runOnReadRestart: no
  # Command to run when a client stops reading.
  # Environment variables are the same of runOnRead.
  runOnUnread:

  # Command to run when a recording segment is created.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * MTX_SEGMENT_PATH: segment file path
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnRecordSegmentCreate:

  # Command to run when a recording segment is complete.
  # The following environment variables are available:
  # * MTX_PATH: path name
  # * MTX_SEGMENT_PATH: segment file path
  # * MTX_SEGMENT_DURATION: segment duration
  # * RTSP_PORT: RTSP server port
  # * G1, G2, ...: regular expression groups, if path name is
  #   a regular expression.
  runOnRecordSegmentComplete:
  srtPublishPassphrase:
  srtReadPassphrase:
paths:
  teststream:
    record: no
  # example:
  # my_camera:
  #   source: rtsp://my_camera

  # Settings under path "all_others" are applied to all paths that
  # do not match another entry.
  all_others:
  ~^live/(.+)$:
    runOnReady: ffmpeg -i rtsp://localhost:8554/live/$G1 -c copy -f rtsp
      rtsp://localhost:8554/$G1
    runOnReadyRestart: true
CONFIGEOF

# Replace HLS viewer password with random generated one
sed -i "s/pass: changeme/pass: $HLS_PASS/" /usr/local/etc/mediamtx.yml

echo "✓ Custom configuration installed"
echo "  - FFmpeg localhost user (internal, no auth)"
echo "  - HLS viewer user (read-only)"
echo "  - Public teststream (no auth required)"
echo "  - FFmpeg live/ path transcoding"
echo "  - Recording OFF by default (enable via Web Editor)"
echo "  - Encryption OFF by default (enable after Caddy install)"

echo ""
echo "=========================================="
echo "Step 6: Creating systemd Service"
echo "=========================================="

cat > /etc/systemd/system/mediamtx.service <<EOF
[Unit]
Description=MediaMTX RTSP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mediamtx
systemctl start mediamtx

echo "✓ MediaMTX service created and started"

echo ""
echo "=========================================="
echo "Step 7: Configuring Firewall (UFW)"
echo "=========================================="

ufw --force enable > /dev/null 2>&1

# MediaMTX ports
ufw allow 8554/tcp   # RTSP
ufw allow 8322/tcp   # RTSPS
ufw allow 8888/tcp   # HLS
ufw allow 8890/udp   # SRT
ufw allow 8000/udp   # RTP
ufw allow 8001/udp   # RTCP

# Keep SSH open (detect current port - may have been changed by hardening)
SSH_PORT=$(grep "^Port " /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}')
SSH_PORT=${SSH_PORT:-22}
ufw allow ${SSH_PORT}/tcp   # SSH

echo "✓ Firewall configured"

# Cleanup
cd /
rm -rf "$TMP_DIR"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "MediaMTX v${LATEST_VERSION} is running!"
echo ""
echo "  Config: /usr/local/etc/mediamtx.yml"
echo ""
echo "  HLS Viewer Credentials:"
echo "    Username: hlsviewer"
echo "    Password: $HLS_PASS"
echo "    (Change in Web Editor → Users & Auth tab)"
echo ""
echo "  Ports:"
echo "    RTSP:  8554/tcp"
echo "    RTSPS: 8322/tcp (enable encryption after Caddy)"
echo "    HLS:   8888/tcp"
echo "    SRT:   8890/udp"
echo ""
echo "  Service Commands:"
echo "    Status:  systemctl status mediamtx"
echo "    Logs:    journalctl -u mediamtx -f"
echo "    Restart: systemctl restart mediamtx"
echo ""
echo "  Next Steps:"
echo "    1. Install Web Config Editor"
echo "    2. Install Caddy for HTTPS/RTSPS"
echo ""
