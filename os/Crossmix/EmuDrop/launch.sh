#!/bin/sh
APP_DIR=$(dirname "$0")
cd $APP_DIR

chmod -R 777 .

# Wait for an in-progress self-update to finish before starting (the updater
# writes this lock while it replaces files, and restarts us when done).
i=0
while [ -f "$APP_DIR/.updating" ] && [ $i -lt 90 ]; do
    sleep 1
    i=$((i + 1))
done


export PYSDL2_DLL_PATH="/usr/trimui/lib/"
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/mnt/SDCARD/System/lib/
export INFOSCREEN="/mnt/SDCARD/System/usr/trimui/scripts/infoscreen.sh"

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
    fi
    unset ENABLED SCHEME HOST PORT USER PASS
fi

$INFOSCREEN -m "Checking internet connection..." -t 0.2

# Connectivity check over HTTP instead of ICMP: this cooperates with the proxy
# and with networks that drop ping.
if curl -s -k -m 8 -o /dev/null https://api.github.com/; then
    $INFOSCREEN -m "Internet connection detected." -t 0.1
else
    $INFOSCREEN -m "No internet connection. Press B to exit." -k B
    exit
fi

# App self-update is intentionally disabled in this build: the binary is not
# published as a GitHub release yet, so app_ota.sh would overwrite it with the
# upstream release on every launch. Re-enable together with version.txt once a
# release channel for this fork exists.
# ./app_ota.sh
# Catalog (catalog.db) updates are handled by the in-app updater
# (user is asked before anything is downloaded).

echo performance >/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo 1608000 >/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq
echo 1 > /tmp/stay_awake #keep screen awake

export ROMS_DIR="/mnt/SDCARD/Roms/"
export IMGS_DIR="/mnt/SDCARD/Imgs/{SYSTEM}/{IMAGE_NAME}.png"
export EXECUTABLES_DIR="$APP_DIR/assets/executables/"

./EmuDrop
rm /tmp/stay_awake
