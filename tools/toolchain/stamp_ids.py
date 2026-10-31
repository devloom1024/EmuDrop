"""Stamp the packaged app tree with content ids.

The updater uses these ids to skip copying large trees that did not change
between releases (38 MB of PyInstaller runtime, ~11 MB of assets), which is very
slow on the handheld's FAT formatted SD card.

Usage: python3 tools/toolchain/stamp_ids.py <packaged-app-dir>
"""
import hashlib
import os
import sys


def tree_id(root, skip_names):
    digest = hashlib.sha256()
    entries = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name in skip_names:
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            entries.append(f"{rel}\0{size}")
    for entry in sorted(entries):
        digest.update(entry.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:32]


def main(app_dir):
    internal = os.path.join(app_dir, "_internal")
    assets = os.path.join(app_dir, "assets")

    if os.path.isdir(internal):
        value = tree_id(internal, {".runtime-id"})
        with open(os.path.join(internal, ".runtime-id"), "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        print(f"_internal id: {value}")

    if os.path.isdir(assets):
        value = tree_id(assets, {".assets-id"})
        with open(os.path.join(assets, ".assets-id"), "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        print(f"assets id:    {value}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1])
