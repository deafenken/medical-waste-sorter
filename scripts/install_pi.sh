#!/usr/bin/env bash
# One-shot Raspberry Pi (Bookworm 64-bit) bootstrap, uv-based.
#
# Default: installs system deps, sets up a uv-managed Python project,
#          installs the core Python dependencies, and (by default) the
#          Intel RealSense stack for the D405.
#
# Optional add-ons toggled via environment variables:
#   ORBBEC_SDK=1    — also build OpenNI2 ARM64 + Orbbec udev rules
#   HAILO_SDK=1     — install HailoRT + hailo-platform Python bindings
#   PANTHERA_SDK=1  — clone + build the Panthera-HT_SDK from source
#
# Re-running is idempotent.
#
#   chmod +x scripts/install_pi.sh
#   HAILO_SDK=1 PANTHERA_SDK=1 ./scripts/install_pi.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
echo "[install] repo root: $REPO_ROOT"

# ---------- 1. apt deps ----------
echo "[install] apt deps..."
sudo apt-get update
sudo apt-get install -y \
    python3 python3-dev python3-venv \
    git cmake build-essential pkg-config \
    libopencv-dev python3-opencv \
    libusb-1.0-0-dev \
    udev v4l-utils curl ca-certificates

# ---------- 2. dialout group (serial access for Panthera USB-FDCAN) ----------
if ! groups "$USER" | grep -q dialout; then
    echo "[install] adding $USER to dialout group (re-login required after install)"
    sudo usermod -aG dialout "$USER"
fi

# ---------- 3. uv (Python project manager) ----------
if ! command -v uv >/dev/null 2>&1; then
    echo "[install] installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Make uv available in this shell
export PATH="$HOME/.local/bin:$PATH"
# shellcheck disable=SC1091
[ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"
uv --version

# ---------- 3a. China mirror auto-config (opt-out via NO_CN_MIRROR=1) ----------
# uv downloads Python 3.11 standalone builds from github.com/astral-sh/python-
# build-standalone — that direct HTTP fetch is NOT covered by the user's
# `git config insteadOf` rewrite (which only affects `git clone`). On
# mainland China networks `uv venv` will silently hang for 10+ minutes
# trying to reach github.com. Same story for PyPI vs Tsinghua.
#
# These two env vars route uv through ghfast.top + Tsinghua so first-time
# bootstrap actually finishes. Set NO_CN_MIRROR=1 to disable.
if [ "${NO_CN_MIRROR:-0}" != "1" ]; then
    : "${UV_PYTHON_INSTALL_MIRROR:=https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download}"
    : "${UV_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"
    export UV_PYTHON_INSTALL_MIRROR UV_INDEX_URL
    echo "[install] CN mirrors enabled (UV_PYTHON_INSTALL_MIRROR=ghfast.top, UV_INDEX_URL=tsinghua)"
    echo "[install]   set NO_CN_MIRROR=1 to disable"
fi

# ---------- 4. Python project: create venv + install core deps ----------
echo "[install] uv sync (core deps only — extras come below)"
uv venv --python 3.11 --clear .venv
# Install core deps from pyproject.toml
uv sync

# Activate for subsequent uv pip install calls inside the script.
# shellcheck disable=SC1091
source .venv/bin/activate

# ---------- 4a. OpenNI2 ARM64 (only if ORBBEC_SDK=1) ----------
if [ "${ORBBEC_SDK:-0}" = "1" ]; then
    echo "[install] ORBBEC_SDK=1 — building OpenNI2 ARM64"
    OPENNI_DIR="$HOME/OpenNI2"
    if [ ! -d "$OPENNI_DIR" ]; then
        git clone https://github.com/orbbec/OpenNI2.git "$OPENNI_DIR"
    fi
    if [ ! -d "$OPENNI_DIR/Bin/Arm64-Release" ]; then
        echo "[install] building OpenNI2 (~5-10 min)"
        pushd "$OPENNI_DIR" >/dev/null
        make -j"$(nproc)" PLATFORM=Arm64
        popd >/dev/null
    fi
    RULES_SRC="$OPENNI_DIR/Packaging/Linux/primesense-usb.rules"
    RULES_DST="/etc/udev/rules.d/557-primesense-usb.rules"
    if [ -f "$RULES_SRC" ] && [ ! -f "$RULES_DST" ]; then
        echo "[install] installing Orbbec udev rules"
        sudo cp "$RULES_SRC" "$RULES_DST"
        sudo udevadm control --reload-rules
    fi
    uv pip install -e ".[orbbec]"
fi

# ---------- 4b. Intel RealSense (default for D405 users) ----------
# Three install paths depending on host:
#   x86_64 / Debian bookworm / Ubuntu jammy   → Intel apt repo (fast, has wheels)
#   Ubuntu noble + aarch64 (Pi 5 Ubuntu)      → must source-build librealsense
#                                               (apt repo has NO noble packages)
#   Other                                     → manual; we print instructions
#
# Set REALSENSE_FROM_SOURCE=1 to force the source-build path explicitly
# (~30-45 min on Pi 5). Set REALSENSE_SDK=0 to skip the whole block.
if [ "${REALSENSE_SDK:-1}" = "1" ]; then
    echo "[install] installing Intel RealSense stack"
    DISTRO="$(lsb_release -cs 2>/dev/null || echo unknown)"
    ARCH="$(uname -m)"

    # Decide whether Intel's apt repo will actually have packages for this host.
    APT_REPO_HAS_PACKAGES="no"
    case "$DISTRO" in
        bookworm|bullseye|jammy|focal) APT_REPO_HAS_PACKAGES="yes" ;;
    esac
    if [ "$ARCH" = "x86_64" ] && [ "$APT_REPO_HAS_PACKAGES" = "no" ]; then
        # On x86_64 the repo usually has SOMETHING even for newer distros
        APT_REPO_HAS_PACKAGES="yes"
    fi

    # Clean up stale apt source from earlier script versions that wrongly
    # added librealsense.list on noble/aarch64 (the InRelease GPG key was
    # never properly imported, so every later `apt-get update` fails with
    # NO_PUBKEY FB0B24895113F120 and blocks ALL subsequent apt installs).
    if [ "$APT_REPO_HAS_PACKAGES" = "no" ] \
       && [ -f /etc/apt/sources.list.d/librealsense.list ]; then
        echo "[install] removing stale librealsense apt source (no packages for $DISTRO/$ARCH)"
        sudo rm -f /etc/apt/sources.list.d/librealsense.list \
                   /etc/apt/keyrings/librealsense.pgp
        sudo apt-get update -qq || true
    fi

    if [ "$APT_REPO_HAS_PACKAGES" = "yes" ] && ! command -v rs-enumerate-devices >/dev/null 2>&1; then
        echo "[install] adding Intel RealSense apt repo for $DISTRO/$ARCH"
        sudo mkdir -p /etc/apt/keyrings
        curl -sSf https://librealsense.intel.com/Debian/librealsense.pgp \
            | sudo tee /etc/apt/keyrings/librealsense.pgp >/dev/null \
            || echo "[install] WARN: keyring add failed, continuing"
        echo "deb [signed-by=/etc/apt/keyrings/librealsense.pgp] \
https://librealsense.intel.com/Debian/apt-repo $DISTRO main" \
            | sudo tee /etc/apt/sources.list.d/librealsense.list >/dev/null
        sudo apt-get update
        sudo apt-get install -y librealsense2-utils librealsense2-dev \
            || { echo "[install] ERROR: apt install of librealsense failed."; \
                 echo "[install]   Rerun with REALSENSE_FROM_SOURCE=1 to source-build."; }
    elif [ "${REALSENSE_FROM_SOURCE:-0}" != "1" ]; then
        echo "[install] NOTE: $DISTRO/$ARCH is not covered by Intel's RealSense apt repo."
        echo "[install]       Skipping apt step. To install RealSense, rerun with:"
        echo "[install]           REALSENSE_FROM_SOURCE=1 ./scripts/install_pi.sh"
        echo "[install]       (this source-builds librealsense, ~30-45 min on Pi 5)"
    fi

    # ---- 4b-recover. Re-install pyrealsense2 into venv if it's missing ----
    # `uv venv --clear .venv` at the top of every run wipes the venv. cmake's
    # earlier install put pyrealsense2 *only* in the venv (because we passed
    # -DPYTHON_EXECUTABLE=$VENV_PY), so it's gone too. If we still have the
    # built librealsense tree in ~/librealsense/build, we can re-run just
    # `sudo make install` (~30s, no recompile) to put pyrealsense2 back —
    # without needing REALSENSE_FROM_SOURCE=1 every time.
    LIBRS_BUILD="$HOME/librealsense/build"
    SITE_PKGS_PRS="$REPO_ROOT/.venv/lib/python3.11/site-packages/pyrealsense2"
    if [ ! -f "$SITE_PKGS_PRS/__init__.py" ] \
       && [ -f "$LIBRS_BUILD/wrappers/python/CMakeFiles/pyrealsense2.dir/build.make" ] \
       && [ "${REALSENSE_FROM_SOURCE:-0}" != "1" ]; then
        echo "[install] pyrealsense2 missing from venv but librealsense build tree exists"
        echo "[install]   re-running sudo make install (~30s, no recompile)"
        pushd "$LIBRS_BUILD" >/dev/null
        sudo make install
        popd >/dev/null
        sudo chown -R "$USER:$USER" "$REPO_ROOT/.venv"
    fi

    # ---- 4b-source. Source-build librealsense + pyrealsense2 (opt-in) ----
    if [ "${REALSENSE_FROM_SOURCE:-0}" = "1" ]; then
        echo "[install] REALSENSE_FROM_SOURCE=1 — source-building librealsense"
        echo "[install]   estimated 30-45 min on Pi 5 (build + sudo make install)"

        sudo apt-get install -y \
            libssl-dev libusb-1.0-0-dev libudev-dev pkg-config \
            libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
            python3-dev cmake build-essential

        LIBRS_DIR="$HOME/librealsense"
        if [ ! -d "$LIBRS_DIR" ]; then
            git clone --depth 1 https://github.com/IntelRealSense/librealsense.git "$LIBRS_DIR"
        fi

        # Build using the venv's Python so the bindings target Python 3.11.
        VENV_PY="$REPO_ROOT/.venv/bin/python"
        if [ ! -x "$VENV_PY" ]; then
            echo "[install] ERROR: venv Python not found at $VENV_PY"
            exit 1
        fi

        pushd "$LIBRS_DIR" >/dev/null
        mkdir -p build && cd build
        cmake .. \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_EXAMPLES=false \
            -DBUILD_GRAPHICAL_EXAMPLES=false \
            -DBUILD_PYTHON_BINDINGS=true \
            -DPYTHON_EXECUTABLE="$VENV_PY" \
            -DCHECK_FOR_UPDATES=false
        make -j4
        sudo make install
        sudo cp ../config/99-realsense-libusb.rules /etc/udev/rules.d/
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        popd >/dev/null

        # `sudo make install` ran as root, so anything cmake dropped into
        # the venv (we passed -DPYTHON_EXECUTABLE=$VENV_PY which makes
        # cmake install pyrealsense2 directly into .venv/.../site-packages)
        # is now root-owned. Hand it back to $USER so uv / pip don't choke
        # on later steps.
        sudo chown -R "$USER:$USER" "$REPO_ROOT/.venv"

        # If cmake didn't put pyrealsense2 in the venv directly (older
        # librealsense versions, custom CMAKE_INSTALL_PREFIX, etc.), fall
        # back to symlinking the system-installed copy. We look for the
        # actual Python package — a directory named exactly `pyrealsense2`
        # under a `python*/` or `dist-packages` path — NOT the cmake
        # config dir at /usr/local/lib/cmake/pyrealsense2 which the old
        # heuristic falsely matched.
        SITE_PKGS="$REPO_ROOT/.venv/lib/python3.11/site-packages"
        if [ -f "$SITE_PKGS/pyrealsense2/__init__.py" ]; then
            echo "[install] pyrealsense2 already installed in venv by cmake — no symlink needed"
        else
            SYS_RS_DIR=$(find /usr/local/lib /usr/lib \
                -type d -name pyrealsense2 \
                \( -path '*python*' -o -path '*dist-packages*' \) \
                2>/dev/null | head -1)
            if [ -n "$SYS_RS_DIR" ] && [ -d "$SITE_PKGS" ]; then
                rm -rf "$SITE_PKGS/pyrealsense2"
                ln -s "$SYS_RS_DIR" "$SITE_PKGS/pyrealsense2"
                echo "[install] symlinked $SYS_RS_DIR -> $SITE_PKGS/pyrealsense2"
            else
                echo "[install] WARN: pyrealsense2 not found in venv or system Python dirs"
                echo "[install]   try: find /usr/local /usr/lib -name 'pyrealsense2*' 2>/dev/null"
            fi
        fi
    fi

    # Sanity check (loud — no stderr suppression this time).
    if python -c "import pyrealsense2 as rs; print('[install] pyrealsense2', rs.__version__, 'OK')"; then
        :
    else
        echo "[install] WARN: pyrealsense2 import failed."
        echo "[install]   - On aarch64 + Ubuntu noble, rerun with REALSENSE_FROM_SOURCE=1"
        echo "[install]   - On x86_64 / bookworm, check the apt step above for errors"
        echo "[install]   - See docs/TROUBLESHOOTING.md"
    fi
fi

# ---------- 4c. Hailo-8 / Hailo-8L (only if HAILO_SDK=1) ----------
if [ "${HAILO_SDK:-0}" = "1" ]; then
    echo "[install] HAILO_SDK=1 — preparing Hailo-8 runtime install"
    cat <<'EOM'

  ⚠️  HailoRT is NOT redistributable; we cannot apt-get / pip install it
      automatically. You must:

        1. register at https://hailo.ai/developer-zone/
        2. download HailoRT (.deb) for ARM64 + matching kernel
        3. download hailo-platform Python wheel (cp311-aarch64)
        4. copy both to ~/hailo/  on this Pi
        5. rerun this script — the Hailo block will pick them up

      Looking now in ~/hailo/ ...

EOM
    HAILO_DEB=$(ls "$HOME/hailo/"hailort_*-arm64.deb 2>/dev/null | head -1 || true)
    HAILO_WHL=$(ls "$HOME/hailo/"hailo_platform-*-cp311-cp311-linux_aarch64.whl 2>/dev/null | head -1 || true)
    if [ -n "$HAILO_DEB" ] && [ -n "$HAILO_WHL" ]; then
        echo "[install] found $HAILO_DEB and $HAILO_WHL"
        sudo dpkg -i "$HAILO_DEB" || sudo apt-get install -f -y
        uv pip install "$HAILO_WHL"
        # Sanity check
        python -c "from hailo_platform import HEF; print('hailo_platform OK')" \
            || echo "[install] hailo_platform import failed; see docs/HAILO.md"
    else
        echo "[install] Hailo files not found — skipping Hailo install."
        echo "          See docs/HAILO.md for download + retry instructions."
    fi
fi

# ---------- 4d. Panthera-HT SDK (only if PANTHERA_SDK=1) ----------
if [ "${PANTHERA_SDK:-0}" = "1" ]; then
    echo "[install] PANTHERA_SDK=1 — installing Panthera-HT SDK"
    sudo apt-get install -y liblcm-dev libyaml-cpp-dev libserialport-dev
    uv pip install -e ".[panthera]"

    PANTHERA_DIR="$HOME/Panthera-HT_SDK"
    if [ ! -d "$PANTHERA_DIR" ]; then
        git clone https://github.com/HighTorque-Robotics/Panthera-HT_SDK.git \
            "$PANTHERA_DIR"
    fi
    ARCH="$(uname -m)"
    if [ "$ARCH" = "x86_64" ]; then
        WHL=$(ls "$PANTHERA_DIR/panthera_python/motor_whl/"hightorque_robot-*-cp310-cp310-linux_x86_64.whl 2>/dev/null | head -1 || true)
        if [ -n "$WHL" ]; then
            uv pip install "$WHL"
        else
            echo "[install] no x86_64 wheel found; falling back to source build"
            ARCH="needs-source-build"
        fi
    fi
    if [ "$ARCH" != "x86_64" ]; then
        echo "[install] $ARCH detected; building Panthera SDK from source"
        cd "$PANTHERA_DIR/panthera_cpp/motor_cpp" \
            && mkdir -p build && cd build && cmake .. && make -j"$(nproc)"
        cd "$PANTHERA_DIR/panthera_python" \
            && mkdir -p build && cd build && cmake .. && make -j"$(nproc)"
        cd "$PANTHERA_DIR/panthera_python" && uv pip install -r requirements.txt
        cd "$REPO_ROOT"
        echo "[install] source build done; verify with"
        echo "          python -c 'import hightorque_robot; print(\"ok\")'"
    fi
fi

# ---------- 5. config.yaml ----------
if [ ! -f "$REPO_ROOT/config.yaml" ]; then
    echo "[install] creating config.yaml from example"
    cp "$REPO_ROOT/config.example.yaml" "$REPO_ROOT/config.yaml"
    if [ "${ORBBEC_SDK:-0}" = "1" ] && [ -d "${OPENNI_DIR:-/nonexistent}/Bin/Arm64-Release" ]; then
        DRIVER_PATH="$OPENNI_DIR/Bin/Arm64-Release/OpenNI2"
        sed -i "s|openni_redist_path:.*|openni_redist_path: $DRIVER_PATH|" \
            "$REPO_ROOT/config.yaml"
    fi
fi

# ---------- 6. NCNN export ----------
NCNN_DIR="$REPO_ROOT/models/best_ncnn_model"
if [ ! -d "$NCNN_DIR" ] && [ -f "$REPO_ROOT/models/best.pt" ]; then
    echo "[install] exporting YOLO model to NCNN format..."
    python "$REPO_ROOT/tools/export_ncnn.py" "$REPO_ROOT/models/best.pt" \
        || echo "[install] WARNING: NCNN export failed; you can rerun later"
fi

cat <<EOF

[install] DONE.

Default behavior:
  - uv venv at ./.venv with core deps installed
  - Intel RealSense (D405) Python bindings: yes
  - Orbbec OpenNI2:  $( [ "${ORBBEC_SDK:-0}" = "1" ] && echo "yes" || echo "no  (rerun with ORBBEC_SDK=1)")
  - Hailo-8 SDK:     $( [ "${HAILO_SDK:-0}" = "1" ] && echo "attempted" || echo "no  (rerun with HAILO_SDK=1 + ~/hailo/ files)")
  - Panthera-HT SDK: $( [ "${PANTHERA_SDK:-0}" = "1" ] && echo "yes" || echo "no  (rerun with PANTHERA_SDK=1)")

Next steps:
  1. log out and back in (so the dialout group takes effect)
  2. activate the venv:           source .venv/bin/activate
                                  (or use:  uv run <command> )
  3. edit config.yaml             (set arm.backend, camera.backend, etc.)
  4. test camera:                 uv run python tools/depth_inspect.py
                                  -> first run with RealSense: copy printed
                                     fx/fy/cx/cy into config.yaml -> camera.intrinsics
  5. test arm:                    uv run python tools/test_arm.py
  6. hand-eye calibration:        uv run python -m src.calibration --force
  7. run pipeline:                uv run python -m src.main

EOF
