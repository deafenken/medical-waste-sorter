#!/usr/bin/env bash
# One-shot Raspberry Pi (Bookworm 64-bit) bootstrap.
# Installs system deps, builds Orbbec OpenNI2 (ARM64), creates a venv,
# and exports the YOLO model to NCNN.
#
# Usage:
#   chmod +x scripts/install_pi.sh
#   ./scripts/install_pi.sh
#
# Re-running is idempotent.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
echo "[install] repo root: $REPO_ROOT"

# ---------- 1. apt deps ----------
echo "[install] apt deps..."
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    git cmake build-essential \
    libopencv-dev python3-opencv \
    libusb-1.0-0-dev \
    udev v4l-utils \
    pkg-config

# ---------- 2. dialout group (serial access) ----------
if ! groups "$USER" | grep -q dialout; then
    echo "[install] adding $USER to dialout group (re-login required after install)"
    sudo usermod -aG dialout "$USER"
fi

# ---------- 3. virtualenv ----------
if [ ! -d "$REPO_ROOT/venv" ]; then
    echo "[install] creating venv ./venv"
    python3 -m venv "$REPO_ROOT/venv"
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/venv/bin/activate"
pip install --upgrade pip wheel
pip install -r "$REPO_ROOT/requirements.txt"

# ---------- 4a. OpenNI2 ARM64 (only needed for Orbbec backend) ----------
if [ "${ORBBEC_SDK:-0}" = "1" ]; then
    OPENNI_DIR="$HOME/OpenNI2"
    if [ ! -d "$OPENNI_DIR" ]; then
        echo "[install] cloning OpenNI2"
        git clone https://github.com/orbbec/OpenNI2.git "$OPENNI_DIR"
    fi
    if [ ! -d "$OPENNI_DIR/Bin/Arm64-Release" ]; then
        echo "[install] building OpenNI2 (this takes ~5-10 min)"
        pushd "$OPENNI_DIR" >/dev/null
        make -j"$(nproc)" PLATFORM=Arm64
        popd >/dev/null
    fi
    # udev rules
    RULES_SRC="$OPENNI_DIR/Packaging/Linux/primesense-usb.rules"
    RULES_DST="/etc/udev/rules.d/557-primesense-usb.rules"
    if [ -f "$RULES_SRC" ] && [ ! -f "$RULES_DST" ]; then
        echo "[install] installing Orbbec udev rules"
        sudo cp "$RULES_SRC" "$RULES_DST"
        sudo udevadm control --reload-rules
    fi
fi

# ---------- 4b. Intel RealSense (default for D405 users) ----------
# Skip with REALSENSE_SDK=0 if you only use Orbbec / USB.
if [ "${REALSENSE_SDK:-1}" = "1" ]; then
    echo "[install] installing Intel RealSense stack"
    # Try Intel's apt repo first (covers librealsense2 native lib + udev rules).
    # If it fails (e.g., Intel doesn't have packages for your distro), we fall
    # back to letting pip pull pyrealsense2 wheel which bundles the runtime.
    if ! dpkg -l | grep -q librealsense2-utils; then
        if ! command -v rs-enumerate-devices >/dev/null 2>&1; then
            echo "[install] adding Intel RealSense apt repo"
            sudo mkdir -p /etc/apt/keyrings
            curl -sSf https://librealsense.intel.com/Debian/librealsense.pgp \
                | sudo tee /etc/apt/keyrings/librealsense.pgp >/dev/null \
                || echo "[install] WARNING: keyring add failed, continuing anyway"
            DISTRO="$(lsb_release -cs 2>/dev/null || echo bookworm)"
            echo "deb [signed-by=/etc/apt/keyrings/librealsense.pgp] \
https://librealsense.intel.com/Debian/apt-repo $DISTRO main" \
                | sudo tee /etc/apt/sources.list.d/librealsense.list >/dev/null
            sudo apt-get update || true
            sudo apt-get install -y librealsense2-utils librealsense2-dev \
                || echo "[install] apt install failed; will rely on pip wheel"
        fi
    fi
    # Python bindings — pip wheel works for x86_64 and ARM64 (cp310/cp311 etc.)
    pip install pyrealsense2 \
        || echo "[install] WARNING: pyrealsense2 wheel install failed."
    # Sanity check
    python -c "import pyrealsense2 as rs; print('pyrealsense2', rs.__version__)" \
        2>/dev/null \
        || echo "[install] pyrealsense2 import failed — see TROUBLESHOOTING.md"
fi

# ---------- 5. config.yaml ----------
if [ ! -f "$REPO_ROOT/config.yaml" ]; then
    echo "[install] creating config.yaml from example"
    cp "$REPO_ROOT/config.example.yaml" "$REPO_ROOT/config.yaml"
    if [ "${ORBBEC_SDK:-0}" = "1" ] && [ -d "${OPENNI_DIR:-/nonexistent}/Bin/Arm64-Release" ]; then
        DRIVER_PATH="$OPENNI_DIR/Bin/Arm64-Release/OpenNI2"
        sed -i "s|openni_redist_path:.*|openni_redist_path: $DRIVER_PATH|" \
            "$REPO_ROOT/config.yaml"
        echo "[install] set openni_redist_path -> $DRIVER_PATH"
    fi
fi

# ---------- 5b. Optional: Panthera-HT SDK (for 6-DOF arm users) ----------
# Only attempted if PANTHERA_SDK=1 is exported, since it's heavy and not
# everyone uses this arm. ARM64 users currently need to source-build because
# upstream only ships x86_64 wheels.
if [ "${PANTHERA_SDK:-0}" = "1" ]; then
    echo "[install] PANTHERA_SDK=1 set; preparing Panthera-HT SDK deps"
    sudo apt-get install -y liblcm-dev libyaml-cpp-dev libserialport-dev
    pip install pin scipy pybind11

    PANTHERA_DIR="$HOME/Panthera-HT_SDK"
    if [ ! -d "$PANTHERA_DIR" ]; then
        git clone https://github.com/HighTorque-Robotics/Panthera-HT_SDK.git \
            "$PANTHERA_DIR"
    fi

    ARCH="$(uname -m)"
    if [ "$ARCH" = "x86_64" ]; then
        echo "[install] x86_64 detected; trying precompiled wheel"
        WHL=$(ls "$PANTHERA_DIR/panthera_python/motor_whl/"hightorque_robot-*-cp310-cp310-linux_x86_64.whl 2>/dev/null | head -1 || true)
        if [ -n "$WHL" ]; then
            pip install "$WHL"
        else
            echo "[install] no matching wheel found; falling back to source build"
            ARCH="needs-source-build"
        fi
    fi

    if [ "$ARCH" != "x86_64" ]; then
        echo "[install] $ARCH detected; building Panthera SDK from source"
        cd "$PANTHERA_DIR/panthera_cpp/motor_cpp" \
            && mkdir -p build && cd build && cmake .. && make -j"$(nproc)"
        cd "$PANTHERA_DIR/panthera_python" \
            && mkdir -p build && cd build && cmake .. && make -j"$(nproc)"
        cd "$PANTHERA_DIR/panthera_python" \
            && pip install -r requirements.txt
        echo "[install] NOTE: source build done; verify with"
        echo "         python -c 'import hightorque_robot; print(\"ok\")'"
    fi
    cd "$REPO_ROOT"
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
  - RealSense (D405/D435/...) Python bindings installed: yes
  - Orbbec OpenNI2 SDK built:  no   (re-run with ORBBEC_SDK=1 if needed)
  - Panthera-HT SDK installed: no   (re-run with PANTHERA_SDK=1 if needed)

Next steps:
  1. log out and back in (so the dialout group takes effect)
  2. activate the venv:           source venv/bin/activate
  3. edit config.yaml             (set arm.backend, camera.backend etc.)
  4. for D405 + Panthera-HT: re-run as
     PANTHERA_SDK=1 ./scripts/install_pi.sh
     (RealSense is already installed by default)
  5. test arm:    python tools/test_arm.py
  6. test camera: python tools/depth_inspect.py
                  -> on first run with RealSense, copy the printed fx/fy/cx/cy
                     into config.yaml -> camera.intrinsics
  4. test serial connectivity:    python tools/port_probe.py --port /dev/ttyUSB0
  5. test camera:                 python tools/depth_inspect.py
  6. run hand-eye calibration:    python -m src.calibration --force
  7. run the pipeline:            python -m src.main

EOF
