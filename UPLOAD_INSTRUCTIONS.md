# How to Upload mediamtx-installer to GitHub

## ✅ **Folder Structure** (Matching TAK Server Repo)

```
mediamtx-installer/
├── README.md
├── DEPLOYMENT_GUIDE.md
├── LICENSE
├── rocky-9/
│   ├── Rocky_9_MediaMTX_install.sh
│   └── Rocky_9_Caddy_setup.sh
├── ubuntu-22.04/
│   ├── Ubuntu_22.04_MediaMTX_install.sh
│   └── Ubuntu_22.04_Caddy_setup.sh
└── config-editor/
    ├── Install_MediaMTX_Config_Editor.sh
    └── mediamtx_config_editor.py
```

**Total: 9 files organized in folders (same structure as tak-server-installer)**

---

## 🚀 **Step-by-Step Upload Instructions**

### **Step 1: Create Repository on GitHub**

1. Go to https://github.com/new
2. **Repository name:** `mediamtx-installer`
3. **Description:** `Automated MediaMTX streaming server installation scripts with Caddy reverse proxy and web-based configuration editor`
4. **Public** (selected)
5. ✅ **Add a README file** (check this)
6. **Choose a license:** MIT License
7. Click **"Create repository"**

---

### **Step 2: Prepare Files on Your Computer**

1. Download the **mediamtx-installer-repo** folder from Claude
2. Open the folder - you should see:
   - README.md
   - DEPLOYMENT_GUIDE.md
   - LICENSE
   - rocky-9/ (folder)
   - ubuntu-22.04/ (folder)
   - config-editor/ (folder)

**IMPORTANT:** You'll upload the **contents** of this folder, NOT the folder itself!

---

### **Step 3: Upload to GitHub**

#### **Option A: Web Upload (Easiest)**

1. **Delete the default files GitHub created:**
   - In your repo, click on README.md → three dots "..." → Delete file
   - Do the same for LICENSE

2. **Upload your files:**
   - Click **"Add file"** → **"Upload files"**
   - **Open the mediamtx-installer-repo folder on your computer**
   - **Select ALL contents:**
     - README.md
     - DEPLOYMENT_GUIDE.md
     - LICENSE
     - rocky-9/ (folder)
     - ubuntu-22.04/ (folder)
     - config-editor/ (folder)
   - **Drag these 6 items** into the GitHub upload area
   - **Commit message:** `Initial commit - MediaMTX installer scripts`
   - Click **"Commit changes"**

**IMPORTANT:** Upload the **contents of the folder**, NOT the "mediamtx-installer-repo" folder itself. Otherwise you'll get a nested folder structure.

#### **Option B: Git Command Line**

```bash
# Clone your new repo
git clone https://github.com/YOUR-USERNAME/mediamtx-installer.git
cd mediamtx-installer

# Delete default files
rm README.md LICENSE

# Copy your files (from wherever you downloaded the folder)
cp -r ~/Downloads/mediamtx-installer-repo/* .

# Add and commit
git add .
git commit -m "Initial commit - MediaMTX installer scripts"

# Push to GitHub
git push origin main
```

---

### **Step 4: Verify Upload**

After uploading, your repo should look like this:

```
github.com/YOUR-USERNAME/mediamtx-installer
├── README.md
├── DEPLOYMENT_GUIDE.md
├── LICENSE
├── rocky-9/
│   ├── install.sh
│   └── caddy-setup.sh
├── ubuntu-22.04/
│   ├── install.sh
│   └── caddy-setup.sh
└── config-editor/
    ├── install.sh
    └── mediamtx_config_editor.py
```

**Check that you don't see:**
- A nested `mediamtx-installer-repo` folder
- Files in the wrong place

**If you see nested folders**, delete everything and re-upload just the **contents**.

---

### **Step 5: Update README with Your Username**

1. Click on **README.md** in your repo
2. Click the pencil icon (Edit this file)
3. **Find and Replace** `YOUR-USERNAME` with your actual GitHub username
   - Example: Change `github.com/YOUR-USERNAME/mediamtx-installer` 
   - To: `github.com/takwerx/mediamtx-installer` (or whatever your username is)
4. Scroll through and replace all instances (there are 6)
5. **Commit message:** `Update URLs with GitHub username`
6. Click **"Commit changes"**

---

### **Step 6: Update LICENSE with Your Name**

1. Click on **LICENSE**
2. Click the pencil icon (Edit this file)
3. Change `Copyright (c) 2025 [Your Name/Organization]`
4. To your actual name or organization name
5. **Commit message:** `Add copyright holder`
6. Click **"Commit changes"**

---

### **Step 7: Add Topics (Optional but Recommended)**

1. On your repo main page, click the gear ⚙️ icon next to "About"
2. Add topics:
   - mediamtx
   - streaming-server
   - rtsp
   - rtmp
   - hls
   - webrtc
   - srt
   - caddy
   - automation
   - rocky-linux
   - ubuntu
3. Click **"Save changes"**

This helps people find your repo!

---

## ✅ **Final Checklist**

After uploading:
- [ ] Repo has correct folder structure (rocky-9/, ubuntu-22.04/, config-editor/)
- [ ] No nested folders
- [ ] README.md has your GitHub username (not YOUR-USERNAME)
- [ ] LICENSE has your name
- [ ] All scripts are in correct folders
- [ ] Topics added to repo
- [ ] Repo is Public (not Private)

---

## 🌐 **Share Your Repo**

Once uploaded, your installation URLs will be:

**Rocky Linux 9:**
```bash
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/rocky-9/Rocky_9_MediaMTX_install.sh
chmod +x Rocky_9_MediaMTX_install.sh
sudo ./Rocky_9_MediaMTX_install.sh
```

**Ubuntu 22.04:**
```bash
wget https://raw.githubusercontent.com/YOUR-USERNAME/mediamtx-installer/main/ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh
chmod +x Ubuntu_22.04_MediaMTX_install.sh
sudo ./Ubuntu_22.04_MediaMTX_install.sh
```

Update your website/documentation with these new URLs!

---

## 🆘 **Troubleshooting**

**Problem: Nested folder structure**
- Solution: Delete everything, re-upload only the **contents** of the folder

**Problem: Scripts not executable**
- Solution: Scripts are automatically executable when downloaded via wget

**Problem: 404 error when trying to wget**
- Solution: Make sure repo is Public, not Private

**Problem: URLs not working**
- Solution: Make sure you replaced YOUR-USERNAME with your actual username

---

**Questions?** Check that your structure matches the tak-server-installer repo exactly!
