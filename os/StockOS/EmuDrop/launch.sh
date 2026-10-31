#!/bin/sh
APP_DIR=$(dirname "$0")
cd $APP_DIR

chmod -R 777 .

# ---------------------------------------------------------------------------
# Self-update handling
# The updater writes .updating while it replaces files. A crash or power loss
# can leave that lock (and half-copied files) behind, so a stale lock is
# detected by its age and cleaned up, otherwise the app would look frozen.
# ---------------------------------------------------------------------------
LOCK="$APP_DIR/.updating"
if [ -f "$LOCK" ]; then
    lock_pid=$(cat "$LOCK" 2>/dev/null)
    if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
        echo "Removing stale update lock (updater not running)"
        rm -f "$LOCK"
    fi
fi

if [ -f "$LOCK" ]; then
    i=0
    while [ -f "$LOCK" ] && [ $i -lt 120 ]; do
        now=$(date +%s)
        mtime=$(stat -c %Y "$LOCK" 2>/dev/null || echo "$now")
        if [ $((now - mtime)) -gt 120 ]; then
            echo "Removing stale update lock"
            break
        fi
        sleep 1
        i=$((i + 1))
    done
    rm -f "$LOCK"
fi

# Recover from an update that was interrupted (power loss mid-copy)
if [ ! -f "$APP_DIR/EmuDrop" ] && [ -f "$APP_DIR/.update_backup/EmuDrop" ]; then
    echo "Restoring executable from update backup"
    cp -f "$APP_DIR/.update_backup/EmuDrop" "$APP_DIR/EmuDrop"
fi
rm -f "$APP_DIR/EmuDrop.new"
rm -rf "$APP_DIR/.update_staging" "$APP_DIR/.update_backup"

# Single instance guard: two copies would fight over the framebuffer and over
# the PyInstaller extraction directory in /tmp.
RUNTIME_LOCK="$APP_DIR/.running"
i=0
while [ $i -lt 30 ]; do
    if mkdir "$RUNTIME_LOCK" 2>/dev/null; then
        break
    fi
    if ! pidof EmuDrop > /dev/null 2>&1; then
        rm -rf "$RUNTIME_LOCK"
        continue
    fi
    sleep 1
    i=$((i + 1))
done
if [ ! -d "$RUNTIME_LOCK" ]; then
    echo "Another instance is already running"
    exit 0
fi


export PYSDL2_DLL_PATH="/usr/trimui/lib/"
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/mnt/SDCARD/System/lib/

# ---------------------------------------------------------------------------
# Proxy settings (single source of truth: assets/proxy.conf)
# The OTA scripts below use curl, which honours these environment variables.
# ---------------------------------------------------------------------------
if [ -f "$APP_DIR/assets/proxy.conf" ]; then
    . "$APP_DIR/assets/proxy.conf"
    if [ "$ENABLED" = "1" ] && [ -n "$HOST" ] && [ -n "$PORT" ]; then
        if [ -n "$USER" ]; then
            AUTH="$USER:$PASS@"
        else
            AUTH=""
        fi
        PROXY_URL="$SCHEME://$AUTH$HOST:$PORT"
        export http_proxy="$PROXY_URL" https_proxy="$PROXY_URL" all_proxy="$PROXY_URL"
        export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL" ALL_PROXY="$PROXY_URL"
        export no_proxy="$NO_PROXY" NO_PROXY="$NO_PROXY"
        unset AUTH PROXY_URL
        echo "Proxy enabled: $HOST:$PORT"
    fi
    unset ENABLED SCHEME HOST PORT USER PASS
fi

# Connectivity check over HTTP instead of ICMP: this cooperates with the proxy
# and with networks that drop ping.
if curl -s -k -m 8 -o /dev/null https://api.github.com/; then
    echo "Internet connection detected."
else
    echo "No internet connection. Press B to exit."
    exit
fi

# App self-update is intentionally disabled in this build: the binary is not
# published as a GitHub release yet, so app_ota.sh would overwrite it with the
# upstream release on every launch. Re-enable together with version.txt once a
# release channel for this fork exists.
# sh app_ota.sh
# Catalog (catalog.db) updates are handled by the in-app updater
# (user is asked before anything is downloaded).

echo performance >/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo 1608000 >/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq
echo 1 > /tmp/stay_awake #keep screen awake

export ROMS_DIR="/mnt/SDCARD/Roms/"
export IMGS_DIR="/mnt/SDCARD/Imgs/{SYSTEM}/{IMAGE_NAME}.png"
export EXECUTABLES_DIR="$APP_DIR/assets/executables/"

"$APP_DIR/EmuDrop"
rmdir "$RUNTIME_LOCK" 2>/dev/null
rm /tmp/stay_awake
