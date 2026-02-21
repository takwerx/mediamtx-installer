# TESTING.md — MediaMTX Web Editor Feature Testing Guide

This guide walks through every feature of the MediaMTX Web Editor so you can verify your installation is working correctly. Follow the sections in order or jump to whichever feature you want to test.

---

## Prerequisites

- MediaMTX installed and running
- Web Editor installed and accessible at `http://YOUR-IP:5000`
- Default login: `admin` / `admin` (change this immediately)
- **For streaming tests:** FFmpeg installed on a client machine (`sudo apt install ffmpeg` or `brew install ffmpeg`)

---

## 1. Login & Authentication

1. Open `http://YOUR-IP:5000` in a browser
2. Log in with `admin` / `admin`
3. You should land on the **Dashboard**

**Password Change:**
1. Click your username in the top right (person icon)
2. Enter current password and new password
3. Confirm — log out and back in with the new password

---

## 2. Dashboard

After login you should see:

- **Web Editor version** banner (e.g., "Web Editor v1.1.6 — up to date")
- **MediaMTX version** banner
- **Active Streams** count (0 if nothing is streaming)
- **Total Viewers** count
- **Recordings** disk usage
- **Uptime** for MediaMTX service
- **CPU, RAM, Disk** usage gauges
- **Network Activity** chart

All values should update automatically every few seconds.

---

## 3. Streaming a Test Stream with FFmpeg

This is the core test — publish a video stream and verify it shows up.

### RTSP Stream (default)

From any machine with FFmpeg and a video file:

```bash
ffmpeg -re -stream_loop -1 -i test_video.mp4 \
  -c copy -f rtsp rtsp://YOUR-IP:8554/teststream
```

Or generate a test pattern with no video file needed:

```bash
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=1000:sample_rate=44100 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -c:a aac -f rtsp rtsp://YOUR-IP:8554/teststream
```

**Verify:**
- Go to **Streaming → Active Streams** in the sidebar
- You should see `teststream` appear within 5 seconds
- Click the stream name to watch it via HLS in your browser

### RTMP Stream

Make sure RTMP is enabled in **Configuration → Protocols** first.

```bash
ffmpeg -re -stream_loop -1 -i test_video.mp4 \
  -c copy -f flv rtmp://YOUR-IP:1935/teststream
```

**Verify:** Stream appears in Active Streams just like RTSP.

### SRT Stream

Make sure SRT is enabled in Protocols.

```bash
ffmpeg -re -stream_loop -1 -i test_video.mp4 \
  -c copy -f mpegts srt://YOUR-IP:8890?streamid=publish:teststream&pkt_size=1316
```

**Verify:** Stream appears in Active Streams.

### HLS Playback

Any active stream is automatically available via HLS:

```
http://YOUR-IP:8888/teststream/
```

Open this URL in a browser — you should see the video playing. Typical latency is 4–6 seconds.

---

## 4. Active Streams

With a stream running:

1. Go to **Streaming → Active Streams**
2. Verify the stream name, source type (RTSP/RTMP/SRT), and viewer count display
3. Click the stream to open the built-in HLS player
4. Stop the FFmpeg process — the stream should disappear within a few seconds

---

## 5. Test Streams (Built-in)

1. Go to **Streaming → Test Streams**
2. Upload a short MP4 video file
3. Click **Play** to start the test stream
4. Verify it appears in Active Streams
5. Click **Stop** to end it
6. Optionally click **Optimize** to re-encode for better streaming compatibility

---

## 6. External Sources

1. Go to **Streaming → External Sources**
2. Click **Add External Source**
3. Choose a protocol (RTSP, SRT, RTMP, or UDP MPEG-TS)
4. Enter the remote stream URL and a local path name
5. Save — MediaMTX will begin pulling the remote stream
6. Verify it appears in Active Streams

**Example — Pull an RTSP camera:**
- Protocol: RTSP
- URL: `rtsp://camera-ip:554/stream1`
- Path: `camera1`

The stream will be available at `rtsp://YOUR-IP:8554/camera1`

---

## 7. Recordings

1. Go to **Streaming → Recordings**
2. Configure recording settings (format, retention, path)
3. Enable **Auto-Record** for specific stream paths
4. Start a test stream and verify a recording file is created
5. Check disk usage updates on the Dashboard

---

## 8. Protocol Settings

Go to **Configuration → Protocols**.

### Enable/Disable Protocols

Toggle RTSP, HLS, SRT, and RTMP on/off. The firewall (UFW) rules are automatically managed — enabling RTMP opens port 1935, disabling it closes port 1935.

### RTSP Settings

- Change port (default 8554)
- Set transport protocol (TCP only recommended for internet, UDP+TCP for LAN)
- Set encryption (No / Optional / Strict)

### RTSPS (Encrypted RTSP)

- Requires certificates from Caddy installer
- Port 8322 default
- Set RTSP Encryption to "Optional" or "Strict" to activate

### RTMP Settings

- Port 1935 default
- Encryption: No / Optional / Strict

### RTMPS (Encrypted RTMP)

- Port 1936 default
- Requires certificates from Caddy installer

### SRT Settings

- Port 8890/udp default
- Optional publish and read passphrases (10–79 characters)

### HLS Settings

- Port 8888 default

**Test:** Change a port, save, verify MediaMTX restarts and the new port works.

---

## 9. Users & Auth

1. Go to **Configuration → Users & Auth**
2. **Add a user** with a username, password, and permissions
3. **Edit a user** — change password or permissions
4. **Delete a user**
5. Verify that streams respect user permissions (a user with read-only on a specific path can view but not publish)

**Note:** Passwords that are purely numeric (e.g., `12344321`) are handled correctly and won't crash MediaMTX.

---

## 10. Basic Settings

1. Go to **Configuration → Basic Settings**
2. Adjust settings like read/write buffer sizes, logging level, etc.
3. Save and verify MediaMTX restarts cleanly

---

## 11. Advanced YAML

1. Go to **Configuration → Advanced YAML**
2. View the raw MediaMTX YAML configuration
3. Make a minor edit (e.g., change a comment)
4. Save — a backup is automatically created before overwriting
5. Verify the change persists

**Warning:** Direct YAML editing can break MediaMTX if the syntax is invalid. Use the structured editors (Protocols, Users, etc.) when possible.

---

## 12. Service Control

1. Go to **System → Service Control**
2. **Restart MediaMTX** — verify it comes back up (Dashboard shows "Running")
3. **Stop MediaMTX** — verify it stops (Dashboard shows not running)
4. **Start MediaMTX** — verify it comes back

---

## 13. Firewall (UFW)

1. Go to **System → Firewall**
2. View current UFW rules
3. **Add a rule** — e.g., allow port 9000/tcp
4. **Remove a rule** — remove the rule you just added
5. Verify protected ports (SSH, HTTP/HTTPS, Web Editor 5000) cannot be removed

---

## 14. Versions

1. Go to **System → Versions**
2. View current Web Editor and MediaMTX versions
3. If an update is available, click **Update** and verify the new version loads after restart
4. Test **Rollback** to a previous version

---

## 15. Web Users

1. Go to **Admin → Web Users**
2. View existing web editor users (admin, viewer roles)
3. **Add a viewer account** — log out, log in as viewer, verify they can only see Active Streams
4. **Enable self-registration** if desired
5. **Approve/deny** pending registrations
6. Configure **email notifications** for registration alerts

---

## 16. Styling & Theme

1. Go to **Admin → Styling**
2. Try each **Quick Preset** (Default Blue, Fire Red, Tactical Green, etc.)
3. Verify the header gradient and accent color change throughout the app
4. Upload an **agency/business logo** — verify it appears in the header
5. Change the **header title** and **subtitle**
6. Try the **Blackout** preset for all-black mode
7. Click **Save Theme** to persist changes

---

## 17. Live Logs

1. Go to **Status → Live Logs**
2. Verify real-time MediaMTX log output is streaming
3. Start a test stream — you should see connection logs appear
4. Toggle auto-scroll on/off

---

## 18. SSL/TLS with Caddy (Optional)

If you have a domain name pointed at your server:

```bash
cd ~/mediamtx-installer
sudo ./ubuntu-22.04/Ubuntu_22.04_Install_MediaMTX_Caddy.sh
```

Enter your domain when prompted. After completion:

1. Access the Web Editor at `https://YOUR-DOMAIN`
2. Go to **Configuration → Protocols**
3. Set RTSP Encryption to "Optional" — verify certificate status shows green
4. Set RTMP Encryption to "Optional" — verify RTMPS on port 1936
5. Test an encrypted stream:
   ```bash
   ffmpeg -re -stream_loop -1 -i test_video.mp4 \
     -c copy -f rtsp rtsps://YOUR-DOMAIN:8322/teststream
   ```

---

## 19. DJI Drone Streaming (RTMP)

DJI drones (Avata, Mini series, etc.) stream via RTMP:

1. Enable RTMP in **Configuration → Protocols**
2. In the DJI Fly app, go to **Transmission Settings → RTMP Address**
3. Enter: `rtmp://YOUR-IP:1935/drone1`
4. Start the livestream on the drone
5. Verify `drone1` appears in **Active Streams**
6. Watch via HLS: `http://YOUR-IP:8888/drone1/`

For encrypted RTMPS (requires Caddy SSL):
- Enter: `rtmps://YOUR-DOMAIN:1936/drone1`

---

## 20. Mobile / Responsive Testing

1. Open the Web Editor on a phone or tablet
2. Tap the floating ☰ button to open the sidebar
3. Navigate between sections
4. Watch a stream in the built-in HLS player
5. Verify forms and controls are usable on small screens

---

## Troubleshooting

**Stream not appearing in Active Streams:**
- Verify MediaMTX is running (Dashboard or `sudo systemctl status mediamtx`)
- Check the port is open: `sudo ufw status`
- Check Live Logs for connection errors
- Verify the protocol is enabled in Protocols tab

**Web Editor not loading:**
- Check the service: `sudo systemctl status mediamtx-webeditor`
- Check port 5000 is open: `sudo ufw allow 5000/tcp`
- View logs: `sudo journalctl -u mediamtx-webeditor -f`

**SSL certificates not working:**
- Re-run the Caddy installer: `sudo ./ubuntu-22.04/Ubuntu_22.04_Install_MediaMTX_Caddy.sh`
- Check certificate paths in Protocols tab
- Verify Caddy is running: `sudo systemctl status caddy`

**MediaMTX crash loop after config change:**
- Check logs: `sudo journalctl -u mediamtx -f`
- Restore from backup: `sudo cp /usr/local/etc/mediamtx_backups/LATEST_BACKUP.yml /usr/local/etc/mediamtx.yml`
- Restart: `sudo systemctl restart mediamtx`
