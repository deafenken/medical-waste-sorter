"""Orbbec depth camera (Astra Pro / Astra+) via OpenNI2.

Color stream comes from the matching USB UVC sibling (treated as a regular
``cv2.VideoCapture``). Depth stream comes from OpenNI2.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from src.cameras.base import Camera

logger = logging.getLogger(__name__)


class OrbbecCamera(Camera):
    def __init__(
        self,
        openni_redist_path: str,
        color_device: int = 0,
        width: int = 640,
        height: int = 400,
        fps: int = 30,
        flip_color: bool = True,
    ) -> None:
        from openni import openni2
        from openni import _openni2 as c_api

        self._openni2 = openni2
        self.width = width
        self.height = height
        self.flip_color = flip_color

        openni2.initialize(openni_redist_path)
        self.dev = openni2.Device.open_any()
        logger.info("Orbbec device opened: %s", self.dev.get_device_info())

        self.depth_stream = self.dev.create_depth_stream()
        self.depth_stream.set_video_mode(
            c_api.OniVideoMode(
                pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM,
                resolutionX=width,
                resolutionY=height,
                fps=fps,
            )
        )
        self.depth_stream.start()

        self.cap = cv2.VideoCapture(color_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open color device {color_device}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        # Depth in mm (OpenNI2 ONI_PIXEL_FORMAT_DEPTH_1_MM)
        frame = self.depth_stream.read_frame()
        buf = frame.get_buffer_as_uint16()
        depth_mm = np.ndarray(
            (frame.height, frame.width), dtype=np.uint16, buffer=buf
        ).copy()

        gray = cv2.convertScaleAbs(depth_mm, alpha=0.17)
        gray = cv2.medianBlur(gray, 5)
        depth_colormap = cv2.applyColorMap(gray, cv2.COLORMAP_JET)

        # Color
        ok, color = self.cap.read()
        if not ok:
            raise RuntimeError("USB color frame grab failed")
        color = cv2.resize(color, (self.width, self.height))
        if self.flip_color:
            color = cv2.flip(color, 1)

        return color, depth_mm, depth_colormap

    def close(self) -> None:
        try:
            if self.cap is not None:
                self.cap.release()
        finally:
            try:
                self.depth_stream.stop()
                self.dev.close()
                self._openni2.unload()
            except Exception:  # pragma: no cover
                logger.debug("Error during Orbbec close", exc_info=True)


def build(cam_cfg) -> OrbbecCamera:
    return OrbbecCamera(
        openni_redist_path=cam_cfg.openni_redist_path,
        color_device=cam_cfg.color_device,
        width=cam_cfg.width,
        height=cam_cfg.height,
        fps=cam_cfg.fps,
        flip_color=cam_cfg.flip_color,
    )
