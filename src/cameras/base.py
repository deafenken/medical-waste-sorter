"""Abstract camera backend.

Concrete backends (Orbbec OpenNI2, Intel RealSense, plain USB, ...) implement
the same ``read()`` returning ``(color_bgr, depth_mm, depth_colormap)``.
``depth_mm`` and ``depth_colormap`` may be ``None`` for color-only backends.

Coordinate / unit conventions (chosen to match the original Astra Pro path
so calibration matrices keep working):
  * color image: BGR uint8 [H, W, 3]
  * depth image: uint16 [H, W], values in **millimeters**
  * 0 means "no valid depth reading at this pixel"
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class Intrinsics:
    """Pinhole intrinsics + image size."""
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def as_dict(self) -> dict:
        return {"fx": self.fx, "fy": self.fy, "cx": self.cx,
                "cy": self.cy, "width": self.width, "height": self.height}


class Camera(ABC):
    """Common interface."""

    width: int
    height: int

    @abstractmethod
    def read(self) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        """Return (color_bgr, depth_mm or None, depth_colormap or None)."""

    @abstractmethod
    def close(self) -> None:
        """Release hardware resources. Idempotent."""

    def get_intrinsics(self) -> Optional[Intrinsics]:
        """Return device-reported intrinsics if available; else None.

        Backends that read intrinsics from hardware (RealSense) should override
        this. Backends that rely on hardcoded values (Astra) can return None
        and let the caller fall back to ``cfg.camera.intrinsics``.
        """
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@contextmanager
def open_camera(cam_cfg):
    """Context manager that builds + tears down a camera via the factory."""
    from src.cameras import build_camera   # lazy import to avoid cycles
    cam = build_camera(cam_cfg)
    try:
        yield cam
    finally:
        cam.close()
