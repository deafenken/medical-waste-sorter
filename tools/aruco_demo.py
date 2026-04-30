"""Real-time ArUco detection on the live color stream. Useful for
verifying the standalone color camera and confirming your printed
calibration target is recognised by the chosen dictionary.

    python tools/aruco_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import cameras as camera_mod  # noqa: E402
from src import config as config_mod  # noqa: E402
from src.calibration import get_aruco_detector  # noqa: E402


def main() -> None:
    cfg = config_mod.load_config()
    detector = get_aruco_detector(cfg.calibration.aruco_dict)

    with camera_mod.open_camera(cfg.camera) as cam:
        while True:
            color, _depth, _depth_cm = cam.read()
            corners, ids, _ = detector.detectMarkers(color)
            if ids is not None:
                cv2.aruco.drawDetectedMarkers(color, corners, ids)
            cv2.imshow("aruco", color)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
