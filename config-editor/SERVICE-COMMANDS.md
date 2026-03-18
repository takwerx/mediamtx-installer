# MediaMTX Web Editor - Service Commands

## Service Name
`mediamtx-webeditor`

## Common Commands

```bash
# Restart the web editor (after uploading new code)
sudo systemctl restart mediamtx-webeditor

# Check status
sudo systemctl status mediamtx-webeditor

# View live logs
sudo journalctl -u mediamtx-webeditor -f

# View last 50 log lines
sudo journalctl -u mediamtx-webeditor -n 50

# Stop the web editor
sudo systemctl stop mediamtx-webeditor

# Start the web editor
sudo systemctl start mediamtx-webeditor
```

## File Locations

| Item | Path |
|------|------|
| Python app | `/opt/mediamtx-webeditor/mediamtx_config_editor.py` |
| Service file | `/etc/systemd/system/mediamtx-webeditor.service` |
| MediaMTX config | `/usr/local/etc/mediamtx.yml` |
| Backups | `/opt/mediamtx-webeditor/backups/` |

## Updating the Web Editor

1. Upload the new `mediamtx_config_editor.py` to `/opt/mediamtx-webeditor/` via FileZilla or SCP
2. Restart the service:
   ```bash
   sudo systemctl restart mediamtx-webeditor
   ```
3. Hard-refresh the browser (`Ctrl+Shift+R` or `Cmd+Shift+R`)

## Related Services

```bash
# MediaMTX streaming server
sudo systemctl restart mediamtx
sudo systemctl status mediamtx
sudo journalctl -u mediamtx -f

# Caddy reverse proxy (if installed)
sudo systemctl restart caddy
sudo systemctl status caddy
```
