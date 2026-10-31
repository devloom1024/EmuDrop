"""In-app update support for EmuDrop.

Two independent update channels:

* **application** - releases of this fork (``devloom1024/EmuDrop``), tags of the
  form ``v3.x.y-hk.N``. Upstream's ``v2.x`` tags live in another repository and
  are therefore never considered.
* **catalog** - the game database published by upstream as ``vX.Y.Z-db``
  releases (``catalog-vX.Y.Z.db``).

Nothing is ever installed automatically. :func:`check_app_update` and
:func:`check_db_update` only *report* availability; the caller shows a dialog
and the user decides (A = update now, B = cancel, which simply means the same
prompt appears again on the next launch).
"""

import json
import os
import re
import shutil
import subprocess
import tarfile
import time

import requests

from utils import net
from utils.config import Config
from utils.logger import logger

APP_REPO = "devloom1024/EmuDrop"
DB_REPO = "ahmadteeb/EmuDrop"
APP_ASSET_NAME = "EmuDropStockOS.tar.gz"

API_ROOT = "https://api.github.com/repos"

VERSION_FILE = "version.txt"
DEFAULT_VERSION = "v0.0.0"

_APP_DIR = Config.BASE_DIR


# ---------------------------------------------------------------------------
# local version handling
# ---------------------------------------------------------------------------

def app_dir():
    return _APP_DIR


def version_path():
    return os.path.join(_APP_DIR, VERSION_FILE)


def read_versions():
    """Return ``(app_version, db_version)`` from version.txt (missing -> v0.0.0)."""
    app_version, db_version = DEFAULT_VERSION, DEFAULT_VERSION
    try:
        with open(version_path(), "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle.read().splitlines()]
    except OSError:
        return app_version, db_version

    if lines and lines[0]:
        app_version = lines[0]
    if len(lines) > 1 and lines[1]:
        db_version = lines[1]
    return app_version, db_version


def write_versions(app_version, db_version):
    try:
        with open(version_path(), "w", encoding="utf-8") as handle:
            handle.write(f"{app_version}\n{db_version}\n")
    except OSError as exc:
        logger.error(f"Could not write {VERSION_FILE}: {exc}")


def parse_version(text):
    """Turn ``v3.1.2-hk.7`` into a comparable tuple ``(3, 1, 2, 7)``."""
    if not text:
        return (0,)
    core = text.strip().lower()
    if core.startswith("v"):
        core = core[1:]
    numbers = [int(part) for part in re.findall(r"\d+", core)]
    return tuple(numbers) if numbers else (0,)


# ---------------------------------------------------------------------------
# update discovery
# ---------------------------------------------------------------------------

def _get_json(url, params=None):
    session = net.get_session()
    response = session.get(url, params=params, timeout=(5, 20))
    response.raise_for_status()
    return response.json()


def check_app_update():
    """Return update info dict when a newer app release exists, else None."""
    local_version, _ = read_versions()
    try:
        data = _get_json(f"{API_ROOT}/{APP_REPO}/releases/latest")
    except requests.HTTPError as exc:
        # 404 simply means no release has been published yet
        logger.info(f"App update check: HTTP {exc.response.status_code if exc.response else '?'}")
        return None
    except Exception as exc:  # network/offline - never block the app
        logger.info(f"App update check failed: {type(exc).__name__}: {exc}")
        return None

    tag = data.get("tag_name") or ""
    if not tag or parse_version(tag) <= parse_version(local_version):
        logger.info(f"App update check: up to date ({local_version})")
        return None

    assets = data.get("assets", [])
    asset = next((a for a in assets if a.get("name") == APP_ASSET_NAME), None)
    if not asset:
        # Asset names may embed the version, accept any tar.gz package.
        asset = next((a for a in assets if str(a.get("name", "")).endswith(".tar.gz")), None)
    if not asset:
        logger.warning(f"Release {tag} has no .tar.gz package asset")
        return None

    logger.info(f"App update available: {tag} (current {local_version})")
    return {
        "version": tag,
        "current": local_version,
        "url": asset["browser_download_url"],
        "size": int(asset.get("size") or 0),
        "notes": (data.get("body") or "").strip(),
    }


def check_db_update():
    """Return update info dict when a newer catalog database exists, else None."""
    _, local_db = read_versions()
    try:
        tags = _get_json(f"{API_ROOT}/{DB_REPO}/tags", params={"per_page": 40})
    except Exception as exc:
        logger.info(f"Catalog update check failed: {type(exc).__name__}: {exc}")
        return None

    db_tags = [t.get("name", "") for t in tags if t.get("name", "").endswith("-db")]
    if not db_tags:
        return None

    latest_tag = db_tags[0]
    version = latest_tag[:-3]  # strip the "-db" suffix
    if parse_version(version) <= parse_version(local_db):
        logger.info(f"Catalog up to date ({local_db})")
        return None

    logger.info(f"Catalog update available: {version} (current {local_db})")
    return {
        "version": version,
        "current": local_db,
        "tag": latest_tag,
        "url": f"https://github.com/{DB_REPO}/releases/download/{latest_tag}/catalog-{version}.db",
    }


# ---------------------------------------------------------------------------
# downloading
# ---------------------------------------------------------------------------

def download(url, destination, progress_cb=None, chunk_size=65536):
    """Stream ``url`` to ``destination``; retries once without TLS verification."""
    session = net.get_session()
    try:
        response = session.get(url, stream=True, timeout=(10, 60))
    except requests.exceptions.SSLError as exc:
        logger.warning(f"TLS verification failed for {url}, retrying unverified: {exc}")
        session.verify = False
        response = session.get(url, stream=True, timeout=(10, 60))

    with response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size):
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    return destination


# ---------------------------------------------------------------------------
# applying updates
# ---------------------------------------------------------------------------

def _safe_extract(archive_path, target_dir):
    """Extract a tar.gz without allowing paths outside ``target_dir``."""
    root = os.path.normpath(target_dir)
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            if name in (".", "./"):
                continue
            member_path = os.path.normpath(os.path.join(root, name))
            if member_path != root and not member_path.startswith(root + os.sep):
                raise RuntimeError(f"Unsafe path in archive: {member.name}")
        tar.extractall(target_dir)


UPDATE_SCRIPT = """#!/bin/sh
# Generated by EmuDrop's in-app updater. Runs after the app exits.
APP_DIR="$1"
STAGE="$2"
BACKUP="$APP_DIR/.update_backup"
LOCK="$APP_DIR/.updating"
LOG="/tmp/emudrop_update.log"

exec >> "$LOG" 2>&1
echo "=== update $(date) ==="

# Always drop the lock, even if we are killed half way.
cleanup_lock() {
    rm -f "$LOCK"
}
trap cleanup_lock EXIT INT TERM HUP

echo $$ > "$LOCK"

i=0
while [ $i -lt 60 ]; do
    if ! pidof EmuDrop > /dev/null 2>&1; then
        break
    fi
    sleep 1
    i=$((i + 1))
done

cd "$APP_DIR" || exit 1
rm -rf "$BACKUP"
mkdir -p "$BACKUP"

# Save the user's proxy configuration (the only file in assets that the package
# would overwrite and that the user may have customised).
cp -f assets/proxy.conf "$BACKUP/proxy.conf" 2>/dev/null

for item in launch.sh app_ota.sh db_ota.sh config.json icon.png; do
    [ -f "$APP_DIR/$item" ] && cp -f "$APP_DIR/$item" "$BACKUP/$item"
done

ok=1
for item in "$STAGE"/*; do
    [ -e "$item" ] || continue
    name=$(basename "$item")
    # The executable and version.txt are handled last, so an interrupted update
    # leaves a consistent install (old binary + old version string).
    case "$name" in
        EmuDrop|version.txt) continue ;;
    esac
    if [ "$name" = "assets" ] || [ "$name" = "_internal" ]; then
        # Skip the big, rarely changing trees when their build id is identical:
        # copying 38 MB of runtime or 11 MB of assets over FAT is slow.
        stamp="$name/.assets-id"
        [ "$name" = "_internal" ] && stamp="_internal/.runtime-id"
        new_id=$(cat "$STAGE/$stamp" 2>/dev/null)
        old_id=$(cat "$APP_DIR/$stamp" 2>/dev/null)
        if [ -n "$new_id" ] && [ "$new_id" = "$old_id" ]; then
            echo "$name unchanged (id $new_id), skipping"
        elif [ "$name" = "_internal" ]; then
            rm -rf "$APP_DIR/_internal"
            cp -rf "$STAGE/_internal" "$APP_DIR/_internal" || ok=0
        else
            cp -rf "$STAGE/assets/." "$APP_DIR/assets/" || ok=0
        fi
    else
        cp -rf "$item" "$APP_DIR/" || ok=0
    fi
done

# Executable: copy next to the old one and rename it into place.
if [ -f "$STAGE/EmuDrop" ]; then
    if cp -f "$STAGE/EmuDrop" "$APP_DIR/EmuDrop.new"; then
        if [ "$(wc -c < "$STAGE/EmuDrop")" = "$(wc -c < "$APP_DIR/EmuDrop.new")" ]; then
            mv -f "$APP_DIR/EmuDrop.new" "$APP_DIR/EmuDrop" || ok=0
        else
            echo "binary copy incomplete"
            rm -f "$APP_DIR/EmuDrop.new"
            ok=0
        fi
    else
        ok=0
    fi
fi

[ -f "$BACKUP/proxy.conf" ] && { cp -f "$BACKUP/proxy.conf" "$APP_DIR/assets/proxy.conf" || ok=0; }

if [ "$ok" = "1" ]; then
    # Version stamp is written last: it marks a fully successful swap.
    if [ -f "$STAGE/version.txt" ]; then
        cp -f "$STAGE/version.txt" "$APP_DIR/version.txt" || ok=0
    fi
fi

if [ "$ok" = "1" ]; then
    echo "update ok: $(head -n 1 "$APP_DIR/version.txt")"
    rm -rf "$STAGE" "$BACKUP"
else
    echo "update FAILED, restoring backup"
    for item in EmuDrop launch.sh app_ota.sh db_ota.sh config.json icon.png; do
        [ -f "$BACKUP/$item" ] && cp -f "$BACKUP/$item" "$APP_DIR/$item"
    done
    rm -f "$APP_DIR/EmuDrop.new"
    rm -rf "$STAGE"
fi

rm -f "$LOCK"
trap - EXIT INT TERM HUP

# Do not restart the app from here: the firmware launcher and this script would
# both start it, and two concurrent PyInstaller instances can delete each
# other's extraction directory in /tmp. The user starts EmuDrop again when
# ready; it reports the update result on that next launch.
echo "update finished"
exit 0
"""


def _normalize_stage(staging):
    """Flatten an archive that wraps everything in a single top-level folder."""
    entries = os.listdir(staging)
    if len(entries) != 1:
        return
    inner = os.path.join(staging, entries[0])
    if not os.path.isdir(inner):
        return
    markers = ("EmuDrop", "launch.sh", "assets")
    if not any(os.path.exists(os.path.join(inner, marker)) for marker in markers):
        return
    for name in os.listdir(inner):
        shutil.move(os.path.join(inner, name), os.path.join(staging, name))
    os.rmdir(inner)


def prepare_app_update(info, progress_cb=None):
    """Download and stage an app update.

    Returns the path of the detached shell script that performs the swap.
    """
    staging = os.path.join(_APP_DIR, ".update_staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    archive = os.path.join(_APP_DIR, ".update_staging.tar.gz")
    try:
        download(info["url"], archive, progress_cb=progress_cb)
        _safe_extract(archive, staging)
        _normalize_stage(staging)
    finally:
        if os.path.exists(archive):
            os.remove(archive)

    script = os.path.join("/tmp", "emudrop_apply_update.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(UPDATE_SCRIPT)
    os.chmod(script, 0o755)
    return script


def launch_update_script(script):
    """Start the swap script detached from this process, then the caller exits."""
    logger.info(f"Starting update script {script}")
    subprocess.Popen(
        ["sh", script, _APP_DIR, os.path.join(_APP_DIR, ".update_staging")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def apply_db_update(info, progress_cb=None):
    """Download the catalog database to a staging path.

    Returns the staged file path; :func:`swap_staged_database` installs it.
    """
    staged = os.path.join(Config.ASSETS_DIR, "catalog.pending.db")
    download(info["url"], staged, progress_cb=progress_cb)
    return staged


def swap_staged_database():
    """Replace assets/catalog.db with a previously downloaded pending copy."""
    staged = os.path.join(Config.ASSETS_DIR, "catalog.pending.db")
    target = os.path.join(Config.ASSETS_DIR, "catalog.db")
    if not os.path.isfile(staged):
        return False
    try:
        os.replace(staged, target)
        logger.info("Staged catalog database installed")
        return True
    except OSError as exc:
        logger.error(f"Could not install staged catalog database: {exc}")
        return False


RESULT_FILE = ".update_target"


def write_update_target(version):
    """Remember which version an update was started for (shown after restart)."""
    try:
        with open(os.path.join(_APP_DIR, RESULT_FILE), "w", encoding="utf-8") as handle:
            handle.write(version or "")
    except OSError as exc:
        logger.warning(f"Could not write update marker: {exc}")


def pop_update_result():
    """Return ``(target_version, installed_version)`` and clear the marker."""
    path = os.path.join(_APP_DIR, RESULT_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            target = handle.read().strip()
    except OSError:
        target = ""
    try:
        os.remove(path)
    except OSError:
        pass
    installed, _ = read_versions()
    return target, installed


def cleanup_stale_update_files():
    """Remove leftovers of an interrupted update attempt."""
    for name in (".update_staging", ".update_staging.tar.gz"):
        path = os.path.join(_APP_DIR, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
