# Build image for the ARM64 (aarch64) handheld targets.
#
# IMPORTANT: keep the glibc of this image at or below the oldest target device.
# The TrimUI family (Stock / CrossMix firmware) ships glibc 2.33, so a Debian
# bookworm based image (glibc 2.36) produces binaries that fail with
# "GLIBC_2.35 not found". Debian bullseye (glibc 2.31) is the safe choice.
#
# QEMU is not required: the build host is arm64 as well, so the arm64 image runs
# natively.
FROM python:3.11-slim-bullseye

# binutils provides objdump, required by PyInstaller on Linux.
RUN apt-get update && \
    apt-get install -y --no-install-recommends binutils && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

VOLUME /root/workspace
WORKDIR /root/workspace

# Starting the container with Bash
CMD ["/bin/bash"]
