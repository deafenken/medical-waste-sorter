"""Plain USB UVC color-only camera. Returns depth=None.

Use only when you don't have a depth sensor and want to do model dev /
visualization. The main pipeline degrades gracefully (skips 3D localization)
when depth is None.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from src.cameras.base import Camera

logger = logging.getLogger(__name__)


class UsbCamera(Camera):
    def __init__(
        self,
        color_device: int = 0,
        width: int = 640,
        height: int = 400,
        flip_color: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self.flip_color = flip_color
        self.cap = cv2.VideoCapture(color_device)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open USB camera {color_device}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        logger.warning(
            "Using USB color-only camera; depth will be None and 3D "
            "localization will not work. For development only."
        )

    def read(self) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        ok, color = self.cap.read()
        if not ok:
            raise RuntimeError("USB color frame grab failed")
        color = cv2.resize(color, (self.width, self.height))
        if self.flip_color:
            color = cv2.flip(color, 1)
        return color, None, None

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


def build(cam_cfg) -> UsbCamera:
    return UsbCamera(
        color_device=cam_cfg.color_device,
        width=cam_cfg.width,
        height=cam_cfg.height,
        flip_color=cam_cfg.flip_color,
    )
