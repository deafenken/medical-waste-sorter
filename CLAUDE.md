# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project at a glance

Medical-waste sorting robotic arm. Vision pipeline (YOLOv8) detects 5 classes
(plastic bottle, glass bottle, mask, gauze, injector), 3D-localizes via depth
camera, and a 6-DOF arm picks-and-places into one of three category bins
(pathological / infectious / sharps). Target deployment: Raspberry Pi 5 16GB +
Hailo-8 26 TOPS NPU + Intel RealSense D405 + Panthera-HT 6-DOF arm. The
codebase is also designed to fall back to commodity hardware (G-code arm,
Orbbec Astra Pro, USB camera) so contributors without the hi-end stack can
still run it end-to-end.

---

## Common commands

The project uses **uv** (Astral's Python project manager) — not pip + venv.
Most commands assume `uv` is on PATH; otherwise run `./scripts/install_pi.sh`
first to bootstrap.

### Setup (Pi 5)

```bash
# One-shot install. Optional flags compose freely:
./scripts/install_pi.sh                                    # core + RealSense
ORBBEC_SDK=1 ./scripts/install_pi.sh                       # + OpenNI2 ARM64 build
HAILO_SDK=1 ./scripts/install_pi.sh                        # + HailoRT (needs ~/hailo/*.deb,*.whl)
PANTHERA_SDK=1 ./scripts/install_pi.sh                     # + Panthera-HT SDK source build
```

The script is idempotent. Re-running picks up only what's missing.

### Daily development

```bash
# Activate the project's venv, OR use uv run instead
source .venv/bin/activate

# Most things work either way:
uv run python -m src.main                                  # main pipeline
uv run python -m src.calibration --force                   # hand-eye calibration

# Diagnostic tools (run individually before the full pipeline)
uv run python tools/port_probe.py --port /dev/ttyUSB0     # detect arm protocol
uv run python tools/test_arm.py                           # manual jog REPL
uv run python tools/depth_inspect.py                      # click pixel -> 3D coords
uv run python tools/aruco_demo.py                         # live ArUco recognition

# Model conversion utilities
uv run python tools/export_ncnn.py models/best.pt          # PT -> NCNN dir
uv run python tools/quantize_ncnn.py models/best.pt --int8 \
    --calib calib_set                                      # INT8 NCNN
uv run python tools/capture_calib_set.py --count 100       # capture INT8 calibration images
```

### Tests / CI

There's no pytest suite. CI (`.github/workflows/ci.yml`) does:

```bash
python -m compileall -q src tools                          # syntax check
# + ad-hoc smoke tests for: config loader, coords math, robust_depth_at edge
#   cases, SimpleTracker behavior, arm/camera/detector factory error paths,
#   model class names ↔ config category_to_bin consistency, pyproject.toml
#   schema sanity
```

Reproduce CI locally:

```bash
python -m compileall -q src tools
# Then copy the inline `python -c "..."` blocks from .github/workflows/ci.yml
```

There is no enforced linter. `ruff` is declared as an optional dev dep in
`pyproject.toml`; it is not wired into CI.

### Adding a dependency

```bash
uv add <package>                                           # writes to pyproject.toml
uv add --optional hailo <package>                          # adds to extras group
uv sync                                                    # reinstall after manual edit
```

---

## Architecture

The pipeline is intentionally split into **pluggable backends** so the same
business logic runs across very different hardware. Three abstraction layers:

```
src/main.py
  ├── vision_worker (subprocess)
  │     ├── src/cameras/         <-- Camera ABC; orbbec | realsense | usb
  │     ├── src/detector.py      <-- Detector ABC; pytorch|ncnn|onnx (Ultralytics) | hailo | rknn
  │     ├── src/tracker.py       <-- IoU tracker for multi-frame voting
  │     └── src/coords.py        <-- pixel + depth -> camera frame -> arm frame
  └── arm_pipeline (main process)
        ├── src/arms/            <-- ArmBackend ABC; gcode | panthera_ht
        └── src/calibration.py   <-- 50-point ArUco -> 4×4 image_to_arm matrix
```

Communication between the two processes goes through one
`multiprocessing.Queue` (target candidates) and one `multiprocessing.Value`
(robot status flag, `STATUS_SEARCHING` ↔ `STATUS_BUSY`). The arm pipeline
also receives the vision `Process` handle so it can detect and bail out if
vision crashes (a previously fixed silent-hang bug).

### Pluggable-backend pattern

Every backend module exposes the same two things:

1. A class that subclasses the abstract base (`ArmBackend` / `Camera` /
   `Detector`).
2. A module-level `build(cfg) -> instance` factory function.

The package `__init__.py` dispatches on `cfg.backend` to the right module.
Native SDK imports are **lazy** — they happen inside `__init__` of the
concrete class, NOT at module top level. This keeps CI green without
HailoRT, OpenNI2, RKNN-Lite, etc., installed.

Adding a new backend: drop a file into `src/arms/` or `src/cameras/`, define
the class + `build()`, add a branch in `__init__.py`. No other code changes.

### Configuration is the public API

All runtime knobs live in `config.yaml` (gitignored) — created from
`config.example.yaml`. `src/config.py` reads YAML into a recursive
`SimpleNamespace` tree so callers do `cfg.camera.intrinsics.fx` instead of
dict lookups. Two places need slight care:

- Sections that act like **maps with arbitrary keys** (e.g.
  `detector.category_to_bin` whose keys are class names like
  `"plastic bottle"`) are still accessed via `vars(ns)` to get the
  underlying dict, since spaces aren't valid Python attribute names.
- Path fields (model paths, calibration npy paths) are resolved against the
  repo root via `src.config.resolve_path()` so the pipeline runs from any
  cwd. Backends should **always** route paths through this helper before
  passing to SDKs.

### Coordinate conventions

The Cartesian interface presented to the rest of the pipeline is **mm in the
arm's base frame**, even when an underlying SDK uses different units (e.g.
the Panthera-HT wrapper converts mm↔m and rad↔deg internally). This keeps
hand-eye calibration math, bin positions, and operator-facing values
consistent.

The hand-eye math negates Y when back-projecting depth (`coords.py`) — this
is intentional and matches the convention used during calibration; the
saved `image_to_arm.npy` assumes it. Don't "fix" the negation without
re-calibrating.

### Vision pipeline knobs that matter

In `vision_worker` (in `src/main.py`):

- **Dual confidence threshold**: `conf_draw` (low) draws boxes for human
  inspection; `conf_trigger` (high) gates which detections feed the tracker.
- **IoU tracker + voting**: a detection only enters the queue after
  `vote_window` consecutive frames of the same class at the same location
  (matched by `tracker_iou`). This kills the most common false-trigger mode.
- **Robust depth lookup**: `robust_depth_at()` takes the median of non-zero
  pixels in a 5×5 ROI, not a single pixel — depth sensors return 0 on
  edges/specular surfaces and a single bad pixel would crash the arm into
  the table.
- **Already-triggered set**: a detected track is not queued twice; the
  `triggered_tracks` set is pruned periodically to bound memory.

### CI conventions worth knowing

- The class-name consistency check **hardcodes** the 5 known classes from
  the committed `models/best.pt` and ensures `config.example.yaml`'s
  `category_to_bin` matches exactly. If you retrain with different classes,
  update both the CI list and the YAML in the same commit.
- Each backend skeleton has a CI test that imports the module and verifies
  the factory routes correctly even when the underlying SDK is missing
  (raises `RuntimeError` with a helpful install message, not `ValueError`
  for unknown backend). Preserve this when adding a new backend.

### Backward-compatibility shims

`src/camera.py` and `src/serial_arm.py` are kept as thin re-export modules
pointing at `src/cameras/` and `src/arms/` packages. External code that
imported the old paths still works. Don't put new logic in the shims.

---

## Hardware-specific notes

| Aspect | Reality |
|---|---|
| Target deploy box | Raspberry Pi 5 16GB. **USB-3 (blue) ports** are required for D405; black USB-2 ports work for the Panthera USB-FDCAN debug board, keyboard, etc. |
| Depth camera | D405 needs USB 3.0; depth_scale auto-read from device, converted to mm; depth aligned to color via `rs.align(rs.stream.color)` so `depth_mm[v,u]` matches `color[v,u]`. |
| Arm SDK | Panthera-HT SDK is **MIT** but only ships precompiled wheels for x86_64. ARM64 path = source build (`PANTHERA_SDK=1` does this; ARM64 is the slower, more failure-prone path). The SDK uses meters/radians; the wrapper in `src/arms/panthera_ht.py` converts. |
| NPU | Hailo-8 path needs an offline DFC compile step on x86_64 (see `docs/HAILO.md`). The on-device runtime (HailoRT + `hailo_platform`) is closed-source and **must be downloaded manually** from Hailo Developer Zone — `install_pi.sh` looks under `~/hailo/` for the `.deb` and `.whl` files. |
| Network | The repo's authors have hit campus-network / proxy issues frequently. `scripts/install_pi.sh` does NOT configure git/pip mirrors — the user is expected to set `git config --global url."https://ghfast.top/...".insteadOf` and a Tsinghua pip mirror in `~/.config/pip/pip.conf` before running install. |

---

## Documentation map

The `docs/` tree is the source of truth for hardware-specific procedures.
Keep the linked set in `README.md` "目录结构" in sync when adding a doc.

- `docs/DEPLOY.md` — phase-by-phase first-time bringup
- `docs/HAILO.md` — Hailo-8 .hef compilation + HailoRT install
- `docs/PANTHERA_HT.md` — 6-DOF arm SDK adaptation
- `docs/CALIBRATION.md` — hand-eye procedure deep-dive
- `docs/OPTIMIZATION.md` — confidence/voting/INT8 tuning
- `docs/RK3588.md` — alternative target (RKNN NPU path)
- `docs/TROUBLESHOOTING.md` — common failures, by subsystem
- `docs/BOM.md` / `docs/PUBLISH.md` — hardware list / GitHub publishing notes
