# How to Upload mediamtx-installer to GitHub

## ✅ Folder Structure

```
mediamtx-installer/
├── README.md
├── DEPLOYMENT_GUIDE.md
├── LICENSE
├── ubuntu-22.04/
│   ├── Ubuntu_22_04_MediaMTX_install.sh
│   └── Install_MediaMTX_Caddy.sh
└── config-editor/
    ├── Install_MediaMTX_Config_Editor.sh
    └── mediamtx_config_editor.py
```

**6 files organized in folders**

---

## 🚀 Upload Instructions

### Step 1: Update Existing Repo

If you already have the repo at `github.com/takwerx/mediamtx-installer`:

```bash
# Clone your repo
git clone https://github.com/takwerx/mediamtx-installer.git
cd mediamtx-installer

# Remove old files
rm -f ubuntu-22.04/Ubuntu_22.04_Caddy_setup.sh
rm -f ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh
rm -f rocky-9/*

# Copy new files
cp ~/Downloads/Ubuntu_22_04_MediaMTX_install.sh ubuntu-22.04/
cp ~/Downloads/Install_MediaMTX_Caddy.sh ubuntu-22.04/
cp ~/Downloads/Install_MediaMTX_Config_Editor.sh config-editor/
cp ~/Downloads/mediamtx_config_editor.py config-editor/
cp ~/Downloads/README.md .
cp ~/Downloads/DEPLOYMENT_GUIDE.md .

# Commit and push
git add .
git commit -m "v2.0 - Custom YAML template, renamed Caddy installer, web editor updates"
git push origin main
```

### Step 2: Create GitHub Release (for auto-update)

1. Go to https://github.com/takwerx/mediamtx-installer/releases/new
2. Tag: `v1.0.0`
3. Title: `v1.0.0`
4. Release notes:
   ```
   Initial stable release
   - Dashboard with system stats and active streams
   - User management with agency/group labels
   - Recording with retention management
   - Theme/styling customization
   - Auto-update system
   - RTSPS/HLS encryption support
   ```
5. Publish release (no file upload needed)

---

## 📋 File Summary

| File | Location | Purpose |
|------|----------|---------|
| `Ubuntu_22_04_MediaMTX_install.sh` | ubuntu-22.04/ | MediaMTX + FFmpeg + custom YAML |
| `Install_MediaMTX_Caddy.sh` | ubuntu-22.04/ | Caddy + HTTPS + cert paths |
| `Install_MediaMTX_Config_Editor.sh` | config-editor/ | Web editor installer |
| `mediamtx_config_editor.py` | config-editor/ | Web editor application |
| `README.md` | root | Project overview |
| `DEPLOYMENT_GUIDE.md` | root | Full deployment documentation |

---

## ⚠️ Important Changes from v1

- **Caddy script renamed** from `Ubuntu_22_04_Caddy_setup.sh` to `Install_MediaMTX_Caddy.sh`
- **No username/password prompts** in MediaMTX installer (managed via web editor)
- **Custom YAML template** shipped with installer (not default MediaMTX config)
- **Rocky Linux 9 scripts** not yet updated for v2 (coming soon)
- **Web editor requires** psutil and requests packages (added to installer)
