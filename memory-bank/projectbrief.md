# Project Brief — MediaMTX Installer

## Project Name
mediamtx-installer

## Owner / Maintainer
The TAK Syndicate (https://www.thetaksyndicate.org)
Repository: https://github.com/takwerx/mediamtx-installer

## What This Project Is
A production-ready deployment toolkit for [MediaMTX](https://github.com/bluenviron/mediamtx) — an open-source real-time media server. The project ships:

1. **Bash installation scripts** — fully automated, no-prompt deployment of MediaMTX + optional HTTPS (Caddy) on Ubuntu 22.04
2. **Python Flask web application** (`mediamtx_config_editor.py`) — a browser-based UI for managing every aspect of the running MediaMTX server without editing YAML manually

## Target Audience
- Emergency services (ATAK, TAK Server, drone ISR, UAS) operators
- Live video / event streaming engineers
- infra-TAK users deploying through the infra-TAK automation platform

## Core Goals
- Zero-prompt, fully automated MediaMTX deployment on Ubuntu 22.04
- Browser-based server management (no SSH for day-to-day ops)
- Native MPEG-TS demuxing for TAKICU / ATAK UAS / ISR camera feeds (no FFmpeg transcoding)
- HTTPS + RTSPS encryption via Let's Encrypt (Caddy)
- Integration with infra-TAK (LDAP overlay support)

## Non-Goals
- Cross-distro support (Ubuntu 22.04 only for the install scripts; the web editor is distro-agnostic once running)
- Replacing MediaMTX itself — this project wraps and deploys it
