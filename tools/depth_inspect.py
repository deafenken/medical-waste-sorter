"""Click on the color image to print depth + 3D coordinates at that pixel.

Useful for sanity-checking the camera intrinsics and depth range.

    python tools/depth_inspect.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import cameras as camera_mod  # noqa: E402
from src import config as config_mod  # noqa: E402
from src.coords import pixel_depth_to_camera  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main() -> None:
    cfg = config_mod.load_config()
    intr = cfg.camera.intrinsics

    state = {"depth": None}

    def on_click(event, x, y, _flags, _param):
        if event != cv2.EVENT_LBUTTONDBLCLK:
            return
        depth = state["depth"]
        if depth is None:
            return
        if not (0 <= y < depth.shape[0] and 0 <= x < depth.shape[1]):
            return
        z = float(depth[y, x])
        if z <= 0:
            print(f"({x},{y}) depth=0 invalid")
            return
        xc, yc, zc = pixel_depth_to_camera(x, y, z, intr.fx, intr.fy, intr.cx, intr.cy)
        print(f"({x},{y}) depth={z:.0f}mm  cam=({xc:.1f}, {yc:.1f}, {zc:.1f})")

    cv2.namedWindow("color")
    cv2.setMouseCallback("color", on_click)

    with camera_mod.open_camera(cfg.camera) as cam:
        while True:
            color, depth_mm, depth_color = cam.read()
            state["depth"] = depth_mm
            cv2.imshow("color", color)
            if depth_color is not None:
                cv2.imshow("depth", depth_color)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
