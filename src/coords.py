"""Coordinate conversions: pixel + depth -> camera frame -> arm frame."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


def pixel_depth_to_camera(
    u: int,
    v: int,
    depth_value: float,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> Tuple[float, float, float]:
    """Pinhole back-projection.

    The original code negates Y so the camera frame is right-handed with Y
    pointing up (matches the convention used during hand-eye calibration).
    Keep that behavior for compatibility with saved transform matrices.
    """
    z = float(depth_value)
    x = (u - cx) * z / fx
    y = (v - cy) * z / fy
    return x, -y, z


def camera_to_arm(camera_xyz: Tuple[float, float, float],
                  image_to_arm: np.ndarray) -> np.ndarray:
    """Apply 4x4 affine transform learned from hand-eye calibration."""
    img_pos = np.ones(4, dtype=np.float64)
    img_pos[0:3] = camera_xyz
    return np.dot(image_to_arm, img_pos)[0:3]


def load_calibration(image_to_arm_path: str | Path) -> np.ndarray:
    p = Path(image_to_arm_path)
    if not p.exists():
        raise FileNotFoundError(
            f"Calibration matrix not found: {p}. "
            f"Run `python -m src.calibration` first."
        )
    matrix = np.load(p)
    if matrix.shape != (4, 4):
        logger.warning("image_to_arm matrix shape is %s, expected (4,4)", matrix.shape)
    return matrix
