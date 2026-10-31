# EmuDrop fork notes (TrimUI Brick Pro)

This is a personal fork of [ahmadteeb/EmuDrop](https://github.com/ahmadteeb/EmuDrop)
tuned for a **TrimUI Brick Pro** (Tina Linux, 1024×768, glibc 2.33). Upstream is
not modified in the fork's history; every change is a separate commit.

## What this fork changes

| Area | Change |
|---|---|
| Proxy | `assets/proxy.conf` is the single source of truth for HTTP proxy settings, shared by the app (`requests`) and the shell scripts (`curl`). In-app screen: **Y** on the platforms view. `NO_PROXY` is honoured by both. |
| Network robustness | ROM mirrors with expired/broken TLS certificates no longer abort downloads: one retry without verification, logged as a warning. |
| Device profile | `device/Trimui Brick Pro/settings.json` declares the panel reference resolution (1024×768) and the measured button indices, so the UI is laid out for this device instead of being scaled down from 1280×720. |
| Input | Fixed the button map: D-pad entries are SDL hat constants and previously overwrote the face buttons (A acted as UP). |
| Updates | The app checks GitHub in the background. If a newer release exists it shows a dialog with **A = update**, **B = cancel** (cancel keeps no state, so it asks again next launch). The changelog comes from the release notes. Nothing is installed automatically and the app never restarts itself. |
| Packaging | PyInstaller **onedir** instead of onefile: no 40 MB extraction to `/tmp` on every start (fast startup, no extraction races). |
| Build | Debian bullseye toolchain (glibc 2.31) because TrimUI firmware ships glibc 2.33 and bookworm binaries fail with `GLIBC_2.35 not found`. |
| Scripts | `launch.sh` / OTA scripts are POSIX `sh` (the device has no bash) and never block the firmware launcher. |

## Versioning

`v3.<minor>.<patch>-dl.<build>` — the `3.x` range and the `-dl` suffix keep fork
releases distinguishable from upstream's `v2.x` tags. The version lives in the
`VERSION` file and is stamped into `version.txt` at build time:

```
line 1: app version   (v3.0.15-dl.1)
line 2: catalog db version (upstream vX.Y.Z-db)
```

## Building

```bash
make -C tools/toolchain release DEVICE="Trimui Brick Pro" TARGET_OS=StockOS
# optional: VERSION=v3.0.15-dl.1
```

Requires Docker on an arm64 host. Output: `dist/EmuDrop/` (copy it to
`/mnt/SDCARD/Apps/EmuDrop` on the device).

## Releases

Pushing a `v3.*` tag runs `.github/workflows/release.yml` on `ubuntu-24.04-arm`,
builds inside the bullseye toolchain container (glibc 2.31) and publishes
`EmuDrop-<tag>.tar.gz`.

## How an update is applied

1. Download the release asset to `.update_staging.tar.gz`, extract to `.update_staging/`.
2. Write `.updating` (lock, with the updater pid) and `.update_target` (version).
3. Wait for the app to exit, then swap files:
   * `_internal/` and `assets/` are only copied when their build id
     (`.runtime-id` / `.assets-id`) differs — a code-only release copies ~3 MB
     instead of ~50 MB, which matters a lot on the FAT SD card,
   * the executable is copied to `EmuDrop.new`, size-checked and renamed into
     place,
   * `version.txt` is written last, so it never claims a half-applied update,
   * `assets/proxy.conf` is preserved across the swap.
4. Restart is left to the user; the next launch reports
   `Update complete — now running vX` (or a warning when it did not land).

Failure handling: the script rolls back on error, `launch.sh` clears stale locks
and half-copied files, and `/tmp/emudrop_update.log` records every step.

## Known limitations

* HTTP proxies only (no SOCKS) — matches what the bundled `requests` supports.
* The upstream repository has no LICENSE file, so treat this fork as
  "personal use"; do not redistribute builds.
* `app_ota.sh` is disabled in favour of the in-app updater.
