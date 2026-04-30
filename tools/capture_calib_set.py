"""Capture calibration images for INT8 quantization.

INT8 quantization of YOLOv8 NCNN / ONNX / RKNN models needs a small
representative dataset (~50-200 images) so the quantizer can determine
per-tensor activation ranges. The closer this set matches your real
deployment scene (lighting, angle, object diversity), the better the
quantized model holds accuracy.

Usage:

    python tools/capture_calib_set.py                 # default 100 frames -> calib_set/
    python tools/capture_calib_set.py --count 200 --out custom_dir/
    python tools/capture_calib_set.py --interval 1.0  # 1 frame per second

Press 'q' (or Ctrl+C) to stop early.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import cameras as camera_mod  # noqa: E402
from src import config as config_mod  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100,
                        help="how many frames to capture")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="seconds between frames")
    parser.add_argument("--out", type=Path,
                        default=Path("calib_set"),
                        help="output directory")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    cfg = config_mod.load_config()

    print(f"Capturing {args.count} frames into {args.out}")
    print("Tips:")
    print("  * place real medical waste samples in the workspace")
    print("  * vary lighting (turn lights on/off, partial shadow)")
    print("  * vary object position/orientation between captures")
    print("  * include a few empty-table frames")
    print("  * press 'q' to stop early")
    print()

    saved = 0
    last_t = 0.0
    with camera_mod.open_camera(cfg.camera) as cam:
        while saved < args.count:
            color, _depth, _depth_cm = cam.read()
            now = time.time()
            cv2.putText(color, f"{saved}/{args.count}",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 255, 0), 2)
            cv2.imshow("calib_set capture (q to stop)", color)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            if now - last_t >= args.interval:
                fname = args.out / f"calib_{saved:04d}.jpg"
                cv2.imwrite(str(fname), color)
                logger.info("saved %s", fname)
                saved += 1
                last_t = now

    cv2.destroyAllWindows()

    # Write the dataset.txt manifest used by RKNN / NCNN quantizers
    manifest = args.out / "dataset.txt"
    with manifest.open("w") as fh:
        for p in sorted(args.out.glob("calib_*.jpg")):
            fh.write(f"{p.resolve()}\n")
    logger.info("wrote %s with %d entries", manifest, saved)
    print(f"\nDone. Captured {saved} frames.")
    print(f"Now run:")
    print(f"  python tools/quantize_ncnn.py --calib {args.out}")
    print(f"  # or for RK3588:")
    print(f"  # python tools/convert_to_rknn.py --calib {args.out}")


if __name__ == "__main__":
    main()
