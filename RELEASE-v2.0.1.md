# Web Editor v2.0.1 Release Notes

**Release Date:** March 18, 2026  
**Minimum MediaMTX Version:** v1.17.0

---

## Fix: infra-TAK LDAP overlay compatibility

v2.0.0 introduced route conflicts on infra-TAK deployments. When the web editor auto-updated, the LDAP overlay's `/watch/` route clashed with the editor's, crashing Flask at startup with "View function mapping is overwriting an existing endpoint."

### What's fixed

- **Startup-safe route registration** — The editor now detects the LDAP overlay at `/opt/mediamtx-webeditor/mediamtx_ldap_overlay.py` and skips registering its own `/watch/<stream_name>` route. The overlay provides a visibility-aware version of that route instead.
- **Automatic overlay re-sync on update** — When the editor auto-updates, it re-copies the overlay from the infra-TAK repo (`/root/infra-TAK/` or `/opt/infra-TAK/`) before restarting, preventing stale overlay conflicts going forward.

### Who is affected

- **infra-TAK deployments only.** Standalone installs (no LDAP overlay) are unaffected.
- If you updated to v2.0.0 and had to run "Patch web editor" from the infra-TAK console, this fix eliminates that step for future updates.

### Upgrade path

| Current Version | Action |
|---|---|
| **v1.1.9 or earlier** | Auto-update pulls v2.0.1. The OLD editor's `apply_update()` runs (no overlay re-sync), but the NEW code starts up overlay-safe. No manual patching needed. |
| **v2.0.0** | Auto-update pulls v2.0.1. v2.0.0's `apply_update()` has the overlay re-sync. Startup is also overlay-safe. Clean upgrade. |
| **Standalone (no infra-TAK)** | No action needed. Update as usual. |

---

## All changes since v2.0.0

- Startup overlay detection: skip `/watch/` route registration when LDAP overlay is present
- `LDAP_OVERLAY_ACTIVE` flag evaluated once at import time for zero-cost runtime
- `apply_update()` re-syncs overlay from infra-TAK repo before restarting
- Startup log line confirms overlay detection

---

## Testing updates locally

To validate an update without deploying to production, you can override the GitHub URL the editor checks:

```bash
# On a test VPS, temporarily point the updater at a branch or fork:
sudo sed -i 's|GITHUB_REPO = "takwerx/mediamtx-installer"|GITHUB_REPO = "yourfork/mediamtx-installer"|' \
  /opt/mediamtx-webeditor/mediamtx_config_editor.py
sudo systemctl restart mediamtx-webeditor

# Create a GitHub release on your fork with the test version, then
# use the web editor's "Check for Update" → "Apply Update" flow.

# When done, restore the original repo:
sudo sed -i 's|GITHUB_REPO = "yourfork/mediamtx-installer"|GITHUB_REPO = "takwerx/mediamtx-installer"|' \
  /opt/mediamtx-webeditor/mediamtx_config_editor.py
sudo systemctl restart mediamtx-webeditor
```

Alternatively, test the file replacement directly without the auto-updater:

```bash
# 1. Backup current version
sudo cp /opt/mediamtx-webeditor/mediamtx_config_editor.py \
       /opt/mediamtx-webeditor/mediamtx_config_editor.py.pre-test

# 2. Copy new version from your local machine (via scp/sftp)
scp mediamtx_config_editor.py root@YOUR-VPS:/opt/mediamtx-webeditor/

# 3. Restart and check logs
sudo systemctl restart mediamtx-webeditor
sudo journalctl -u mediamtx-webeditor -n 50 --no-pager

# 4. Verify the web editor loads, then roll back if needed:
sudo cp /opt/mediamtx-webeditor/mediamtx_config_editor.py.pre-test \
       /opt/mediamtx-webeditor/mediamtx_config_editor.py
sudo systemctl restart mediamtx-webeditor
```
