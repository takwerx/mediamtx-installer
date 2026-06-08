# MediaMTX Installer v2.0.9

## New: Main / Dev update channel

The **Versions** tab now has an **Update channel** switch — **Main** or **Dev** —
defaulting to **Main**.

- **Main** (default): updates come from published releases. Unchanged behavior for
  existing installs.
- **Dev**: pulls the latest build straight from the `dev` branch, for test boxes that
  want early features. A **🧪 On Dev channel** indicator shows on the dashboard so it's
  clear when a box is tracking dev. Switch back to **Main** and update to return to the
  released build at any time.

This is the groundwork that lets a box opt into pre-release features without a manual
reinstall.

### Notes
- Defaults to **Main** — no behavior change for existing installs.
- Dev-channel update detection compares against the build you last pulled, so it stays
  accurate even on boxes whose editor file is post-processed at startup (e.g. the
  infra-TAK LDAP overlay).
- The Versions tab now also loads correctly when opened directly / after an update reload.
