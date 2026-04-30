"""Intel RealSense backend (tested target: D405).

Why a separate file from Orbbec:
  * Different SDK (``pyrealsense2`` vs ``openni2``)
  * D405 returns depth in raw "z16" units that need scaling by
    ``depth_sensor.get_depth_scale()`` to get meters; we then convert to
    millimeters so the downstream pipeline keeps using mm everywhere
  * Color and depth are two streams from one device; we use ``rs.align`` to
    register depth to color so ``depth_mm[v, u]`` matches the same pixel as
    ``color[v, u]`` (this is **NOT** automatic on RealSense)
  * Intrinsics are queried from the device, not hardcoded

D405-specific notes:
  * Working distance: ~7-50 cm. Not great for top-down workspace monitoring
    from 30+cm above; better for eye-in-hand mounting on the arm end-effector
  * USB 3.0 required (USB 2.0 will fail to enumerate)
  * Default native resolutions: 1280x720, 848x480, 640x480
  * For best framerate at 1280x720, use 30 fps; pick lower res for higher fps
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from src.cameras.base import Camera, Intrinsics

logger = logging.getLogger(__name__)


class RealsenseCamera(Camera):
    """Intel RealSense (D405 / D435 / D435i / D455 ...).

    Tested with D405. Other models work as long as they expose color+depth
    via the same pipeline; D435i users will likely want to disable IR
    emitter for some scenes and may want to override resolution.
    """

    def __init__(
        self,
        width: int = 848,
        height: int = 480,
        fps: int = 30,
        flip_color: bool = False,
        align_to: str = "color",
        device_serial: Optional[str] = None,
        depth_min_mm: int = 50,
        depth_max_mm: int = 1500,
        log_intrinsics: bool = True,
    ) -> None:
        try:
            import pyrealsense2 as rs   # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError(
                "pyrealsense2 not installed. Install with:\n"
                "  pip install pyrealsense2\n"
                "On ARM64 (Pi 5) you may also need librealsense2 from\n"
                "  Intel's apt repo or built from source. See docs/PANTHERA_HT.md."
            ) from exc

        self._rs = rs
        self.width = width
        self.height = height
        self.flip_color = flip_color
        self.depth_min_mm = depth_min_mm
        self.depth_max_mm = depth_max_mm

        self._pipeline = rs.pipeline()
        cfg = rs.config()
        if device_serial:
            cfg.enable_device(device_serial)

        cfg.enable_stream(
            rs.stream.color, width, height, rs.format.bgr8, fps,
        )
        cfg.enable_stream(
            rs.stream.depth, width, height, rs.format.z16, fps,
        )

        try:
            profile = self._pipeline.start(cfg)
        except RuntimeError as exc:
            raise RuntimeError(
                f"RealSense pipeline.start() failed: {exc}. Common causes:\n"
                f"  - USB 2.0 cable / port (D405 needs USB 3.0)\n"
                f"  - resolution {width}x{height}@{fps} not supported by your model\n"
                f"  - librealsense2 udev rules not installed\n"
                f"    (sudo cp 99-realsense-libusb.rules /etc/udev/rules.d/)\n"
                f"  - device already in use by another process"
            ) from exc

        # Depth scale: raw_z16 * depth_scale = meters. Multiply by 1000 -> mm.
        depth_sensor = profile.get_device().first_depth_sensor()
        self._depth_scale = depth_sensor.get_depth_scale()
        logger.info("RealSense depth scale = %.6f m/unit", self._depth_scale)

        # Align depth -> color so depth_mm[v,u] corresponds to color[v,u].
        align_target = (rs.stream.color if align_to == "color"
                        else rs.stream.depth)
        self._align = rs.align(align_target)

        # Pull intrinsics for the *aligned* output (i.e., color stream
        # intrinsics are what main.py / calibration.py should use).
        color_profile = profile.get_stream(rs.stream.color)
        intr = color_profile.as_video_stream_profile().get_intrinsics()
        self._intrinsics = Intrinsics(
            fx=float(intr.fx), fy=float(intr.fy),
            cx=float(intr.ppx), cy=float(intr.ppy),
            width=int(intr.width), height=int(intr.height),
        )
        if log_intrinsics:
            logger.info(
                "RealSense color intrinsics (copy these into config.yaml):\n"
                "    fx=%.4f fy=%.4f cx=%.4f cy=%.4f  (%dx%d)",
                self._intrinsics.fx, self._intrinsics.fy,
                self._intrinsics.cx, self._intrinsics.cy,
                self._intrinsics.width, self._intrinsics.height,
            )

    # ------------------------------------------------------------------ #
    # Camera interface
    # ------------------------------------------------------------------ #
    def read(self) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        frames = self._pipeline.wait_for_frames(timeout_ms=5000)
        aligned = self._align.process(frames)
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if not color_frame or not depth_frame:
            raise RuntimeError("RealSense frame drop")

        color = np.asanyarray(color_frame.get_data())  # already BGR
        if self.flip_color:
            color = cv2.flip(color, 1)

        depth_raw = np.asanyarray(depth_frame.get_data())   # uint16
        # Convert raw z16 units -> millimeters
        # raw * depth_scale = meters; * 1000 = mm
        depth_mm_f = depth_raw.astype(np.float32) * (self._depth_scale * 1000.0)
        depth_mm = depth_mm_f.astype(np.uint16)

        # Build a colormap for visualization. Clip to a reasonable range first.
        clipped = np.clip(depth_mm, self.depth_min_mm, self.depth_max_mm)
        norm = ((clipped - self.depth_min_mm) /
                max(1, self.depth_max_mm - self.depth_min_mm) * 255).astype(np.uint8)
        depth_colormap = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        # Mask invalid (depth=0) pixels black so visualization isn't misleading
        depth_colormap[depth_mm == 0] = (0, 0, 0)

        return color, depth_mm, depth_colormap

    def close(self) -> None:
        try:
            self._pipeline.stop()
        except Exception:  # pragma: no cover
            logger.debug("RealSense pipeline.stop() raised", exc_info=True)

    def get_intrinsics(self) -> Optional[Intrinsics]:
        return self._intrinsics


def build(cam_cfg) -> RealsenseCamera:
    return RealsenseCamera(
        width=int(getattr(cam_cfg, "width", 848)),
        height=int(getattr(cam_cfg, "height", 480)),
        fps=int(getattr(cam_cfg, "fps", 30)),
        flip_color=bool(getattr(cam_cfg, "flip_color", False)),
        align_to=getattr(cam_cfg, "align_to", "color"),
        device_serial=getattr(cam_cfg, "device_serial", None),
        depth_min_mm=int(getattr(cam_cfg, "depth_min_mm", 50)),
        depth_max_mm=int(getattr(cam_cfg, "depth_max_mm", 1500)),
        log_intrinsics=bool(getattr(cam_cfg, "log_intrinsics", True)),
    )
