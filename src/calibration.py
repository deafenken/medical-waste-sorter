"""Hand-eye calibration.

Runs the arm through ``DEFAULT_CALI_POINTS``, captures the ArUco marker
center in camera coordinates at each pose, and solves for a 4x4 affine
mapping between camera frame and arm frame using least-squares.

Run as a module from repo root:

    python -m src.calibration

It will use ``config.yaml`` for camera and arm configuration.
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from cv2 import aruco

from src import cameras as camera_mod
from src import config as config_mod
from src import arms as arms_mod
from src.coords import pixel_depth_to_camera

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ArUco helpers
# --------------------------------------------------------------------------- #

ARUCO_DICTS = {
    name: getattr(aruco, name)
    for name in dir(aruco)
    if name.startswith(("DICT_4X4_", "DICT_5X5_", "DICT_6X6_", "DICT_7X7_",
                        "DICT_ARUCO_ORIGINAL", "DICT_APRILTAG_"))
}


def get_aruco_detector(dict_name: str):
    if dict_name not in ARUCO_DICTS:
        raise ValueError(
            f"Unknown ArUco dictionary {dict_name}; "
            f"valid: {sorted(ARUCO_DICTS)}"
        )
    arucoDict = aruco.getPredefinedDictionary(ARUCO_DICTS[dict_name])
    arucoParams = aruco.DetectorParameters()
    return aruco.ArucoDetector(arucoDict, arucoParams)


def detect_marker_center(
    detector,
    color_image: np.ndarray,
    depth_mm: np.ndarray,
    intr,
    show: bool = True,
) -> Optional[Tuple[float, float, float]]:
    corners, ids, _ = detector.detectMarkers(color_image)

    if ids is None or len(corners) == 0:
        if show:
            cv2.putText(color_image, "no marker", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow("calibration", color_image)
            cv2.waitKey(1)
        return None

    aruco.drawDetectedMarkers(color_image, corners, ids)

    # use the first detected marker
    corner = corners[0][0]
    # Original code averaged corner 0 and 3 (left edge midpoint) when calib=True
    x_pix = (corner[0][0] + corner[3][0]) / 2.0
    y_pix = (corner[0][1] + corner[3][1]) / 2.0

    u, v = int(x_pix), int(y_pix)
    if not (0 <= v < depth_mm.shape[0] and 0 <= u < depth_mm.shape[1]):
        logger.warning("marker pixel (%d, %d) outside depth frame", u, v)
        return None

    depth_value = float(depth_mm[v, u])
    if depth_value <= 0:
        logger.warning("invalid depth at (%d, %d)", u, v)
        return None

    x_cam, y_cam, z_cam = pixel_depth_to_camera(
        u, v, depth_value, intr.fx, intr.fy, intr.cx, intr.cy
    )

    if show:
        cv2.circle(color_image, (u, v), 4, (0, 0, 255), -1)
        cv2.putText(color_image,
                    f"x={x_cam:.1f} y={y_cam:.1f} z={z_cam:.1f}",
                    (u + 10, v),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imshow("calibration", color_image)
        cv2.waitKey(1)

    return x_cam, y_cam, z_cam


# --------------------------------------------------------------------------- #
# Calibration runner
# --------------------------------------------------------------------------- #


def load_points(module_path: str):
    mod = importlib.import_module(module_path)
    return mod.DEFAULT_CALI_POINTS


def run_calibration(cfg, force: bool = False) -> None:
    img_to_arm_path = config_mod.resolve_path(cfg.calibration.image_to_arm_npy)
    arm_to_img_path = config_mod.resolve_path(cfg.calibration.arm_to_image_npy)

    if not force and img_to_arm_path.exists() and arm_to_img_path.exists():
        logger.info("Calibration files already exist; pass --force to redo")
        return

    img_to_arm_path.parent.mkdir(parents=True, exist_ok=True)

    points = load_points(cfg.calibration.points_module)
    np_pts = np.array(points, dtype=np.float64)

    # 4xN homogeneous arm coordinates
    arm_cord = np.column_stack(
        (np_pts[:, 0:3], np.ones(np_pts.shape[0]))
    ).T

    # apply end-effector -> aruco offset (default [0, 35, 0])
    offset = np.array(
        cfg.calibration.end_effector_to_aruco_offset_mm, dtype=np.float64
    )
    for i in range(arm_cord.shape[1]):
        arm_cord[0, i] += offset[0]
        arm_cord[1, i] += offset[1]
        arm_cord[2, i] += offset[2]

    centers = np.ones(arm_cord.shape, dtype=np.float64)

    detector = get_aruco_detector(cfg.calibration.aruco_dict)

    logger.warning(
        "Place the ArUco marker on the end effector now. "
        "Calibration starts in 30 seconds..."
    )
    time.sleep(30)

    show = cfg.runtime.show_window

    with camera_mod.open_camera(cfg.camera) as cam, \
            arms_mod.open_arm(cfg.arm) as arm:

        if cfg.arm.home_on_start:
            arm.home()

        good = 0
        for idx, pt in enumerate(points):
            logger.info("[%d/%d] move arm to %s", idx + 1, len(points), pt)
            arm.move(pt[0], pt[1], pt[2])
            time.sleep(0.8)  # let mechanical settle

            color, depth_mm, _ = cam.read()
            if depth_mm is None:
                raise RuntimeError(
                    "Calibration requires depth; configure backend=orbbec"
                )
            cv2.putText(color, "Status: Calibrating", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            center = detect_marker_center(
                detector, color, depth_mm, cfg.camera.intrinsics, show=show
            )
            if center is None:
                logger.warning("no marker detected at point %d", idx)
                continue

            centers[0:3, idx] = center
            good += 1

        if show:
            cv2.destroyAllWindows()

    if good < 6:
        raise RuntimeError(
            f"Only {good} valid samples; need >= 6 for a stable solve. "
            "Check ArUco placement, lighting, and reachability."
        )

    image_to_arm = np.dot(arm_cord, np.linalg.pinv(centers))
    arm_to_image = np.linalg.pinv(image_to_arm)

    np.save(img_to_arm_path, image_to_arm)
    np.save(arm_to_img_path, arm_to_image)
    logger.info("Saved %s", img_to_arm_path)
    logger.info("Saved %s", arm_to_img_path)

    # sanity print
    print("\n=== Sanity check (image_to_arm) ===")
    errs = []
    for i in range(centers.shape[1]):
        if np.allclose(centers[0:3, i], 1.0):
            continue  # skipped
        expected = arm_cord[0:3, i]
        result = np.dot(image_to_arm, centers[:, i])[0:3]
        err = np.linalg.norm(expected - result)
        errs.append(err)
        print(f"pt{i:02d}  expected={expected.round(1)}  result={result.round(1)}  err={err:.2f}mm")

    if errs:
        print(f"\nMean error: {np.mean(errs):.2f} mm   Max error: {np.max(errs):.2f} mm")


def main():
    parser = argparse.ArgumentParser(description="Hand-eye calibration")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing calibration matrices")
    args = parser.parse_args()

    cfg = config_mod.load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, cfg.runtime.log_level, "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run_calibration(cfg, force=args.force)


if __name__ == "__main__":
    main()
