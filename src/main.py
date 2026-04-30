"""Main pipeline: detect medical waste with YOLOv8, localize in 3D,
and command a G-code arm to sort items into three category bins.

Run from the repo root:

    python -m src.main          # uses ./config.yaml
    python -m src.main --config /path/to/other.yaml

Press 'q' in any preview window to exit.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import signal
import sys
import time
from multiprocessing import Process, Queue, Value

import cv2
import numpy as np

from src import cameras as camera_mod
from src import config as config_mod
from src import arms as arms_mod
from src.coords import camera_to_arm, load_calibration, pixel_depth_to_camera
from src.detector import build_detector
from src.tracker import SimpleTracker

logger = logging.getLogger(__name__)

# Robot status values
STATUS_SEARCHING = 0
STATUS_BUSY = 1


def robust_depth_at(depth_mm: np.ndarray, u: int, v: int, half: int = 2) -> float:
    """Median of non-zero depth in a (2*half+1) x (2*half+1) window.

    Single-pixel depth lookups are noisy (Astra returns 0 on edges/specular
    surfaces). Taking the median of valid samples in a small ROI is much
    more stable. Returns 0.0 if there are no valid samples.
    """
    h, w = depth_mm.shape
    u0 = max(0, u - half)
    u1 = min(w, u + half + 1)
    v0 = max(0, v - half)
    v1 = min(h, v + half + 1)
    patch = depth_mm[v0:v1, u0:u1]
    valid = patch[patch > 0]
    if valid.size == 0:
        return 0.0
    return float(np.median(valid))


# --------------------------------------------------------------------------- #
# Vision worker
# --------------------------------------------------------------------------- #


def vision_worker(cfg_path: str, target_queue: Queue, robot_status):
    """Run camera + detector in a separate process so the arm pipeline
    is never blocked by frame grabbing.

    Pipeline per frame:
      1. read color + depth from camera
      2. detector.predict(conf=conf_draw)         ; low threshold, draw all
      3. tracker.update(detections)                ; assign persistent IDs
      4. select best stable track:
            consecutive_hits >= vote_window AND last_conf >= conf_trigger
      5. if best track has valid depth & class mapping, queue target
    """
    cfg = config_mod.load_config(cfg_path)
    logging.basicConfig(
        level=getattr(logging, cfg.runtime.log_level, "INFO"),
        format="[vision] %(asctime)s %(levelname)s: %(message)s",
    )

    detector = build_detector(cfg.detector)
    detector.warmup() if hasattr(detector, "warmup") else None
    intr = cfg.camera.intrinsics

    # Build class -> bin mapping (cls_name from YOLO -> bin index 0/1/2)
    bin_index = {"pathological": 0, "infectious": 1, "sharps": 2}
    cls_to_bin_idx = {}
    for cls_name, bin_name in vars(cfg.detector.category_to_bin).items():
        if bin_name not in bin_index:
            logger.warning("unknown bin %r mapped from %r", bin_name, cls_name)
            continue
        cls_to_bin_idx[cls_name] = bin_index[bin_name]

    # Optimization knobs (with sane defaults if user has an old config.yaml)
    conf_draw = float(getattr(cfg.detector, "conf_draw",
                              getattr(cfg.detector, "conf_threshold", 0.4)))
    conf_trigger = float(getattr(cfg.detector, "conf_trigger",
                                 getattr(cfg.detector, "conf_threshold", 0.7)))
    vote_window = int(getattr(cfg.detector, "vote_window", 3))
    use_tracker = bool(getattr(cfg.detector, "use_tracker", True))

    tracker = SimpleTracker(
        iou_threshold=float(getattr(cfg.detector, "tracker_iou", 0.3)),
        max_lost=int(getattr(cfg.detector, "tracker_max_lost", 5)),
    )

    show = cfg.runtime.show_window
    if show:
        cv2.namedWindow("color")
        cv2.namedWindow("depth")

    fps_smoothed = 0.0
    triggered_tracks: set[int] = set()  # avoid double-queueing same track

    with camera_mod.open_camera(cfg.camera) as cam:
        try:
            while True:
                t0 = time.time()
                color, depth_mm, depth_colormap = cam.read()

                # --- detection (draw threshold = low) ------------------- #
                detections = detector.predict(color, conf=conf_draw)

                # --- tracking ------------------------------------------- #
                if use_tracker:
                    live_tracks = tracker.update(detections)
                else:
                    live_tracks = None  # fall back to single-frame logic

                # --- visualize all detections (low conf) ---------------- #
                for det in detections:
                    color_box = (0, 200, 0) if det.confidence >= conf_trigger \
                                else (0, 200, 200)
                    cv2.rectangle(color, (det.xmin, det.ymin),
                                  (det.xmax, det.ymax), color_box, 2)
                    if show:
                        cv2.putText(color,
                                    f"{det.cls_name} {det.confidence:.2f}",
                                    (det.xmin, det.ymin - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_box, 1)

                # --- pick the candidate to grasp ------------------------ #
                best_box = None  # (cls_name, center_x_pix, center_y_pix, conf)
                if use_tracker and live_tracks:
                    stable = tracker.best_stable_track(
                        min_hits=vote_window, min_conf=conf_trigger
                    )
                    if stable is not None and stable.track_id not in triggered_tracks:
                        cx, cy = stable.center
                        best_box = (stable.cls_name, cx, cy, stable.last_conf,
                                    stable.track_id)
                        # show track id + hits
                        if show:
                            cv2.putText(color,
                                        f"id{stable.track_id} hits={stable.consecutive_hits}",
                                        (stable.box[0], stable.box[3] + 15),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                        (0, 0, 255), 1)
                else:
                    # tracker disabled: pick highest-confidence detection above
                    # the trigger threshold (legacy behavior).
                    candidates = [d for d in detections if d.confidence >= conf_trigger]
                    if candidates:
                        best = max(candidates, key=lambda d: d.confidence)
                        cx, cy = best.center
                        best_box = (best.cls_name, cx, cy, best.confidence, None)

                # --- localize & queue ----------------------------------- #
                if best_box is not None and depth_mm is not None \
                        and robot_status.value == STATUS_SEARCHING:
                    cls_name, cx_pix, cy_pix, conf_val, tid = best_box
                    if (0 <= cy_pix < depth_mm.shape[0]
                            and 0 <= cx_pix < depth_mm.shape[1]
                            and cls_name in cls_to_bin_idx):
                        z_raw = robust_depth_at(depth_mm, cx_pix, cy_pix, half=2)
                        if cfg.camera.depth_min_mm <= z_raw <= cfg.camera.depth_max_mm:
                            x_cam, y_cam, z_cam = pixel_depth_to_camera(
                                cx_pix, cy_pix, z_raw,
                                intr.fx, intr.fy, intr.cx, intr.cy,
                            )
                            bin_idx = cls_to_bin_idx[cls_name]
                            target_queue.put([x_cam, y_cam, z_cam, bin_idx])
                            robot_status.value = STATUS_BUSY
                            if tid is not None:
                                triggered_tracks.add(tid)
                            logger.info(
                                "queued cls=%s conf=%.2f xyz=(%.0f,%.0f,%.0f) "
                                "bin=%d track=%s",
                                cls_name, conf_val, x_cam, y_cam, z_cam,
                                bin_idx, tid,
                            )

                # Periodically prune triggered_tracks of long-dead IDs to
                # avoid unbounded memory.
                if use_tracker and len(triggered_tracks) > 100:
                    live_ids = {t.track_id for t in tracker.tracks}
                    triggered_tracks &= live_ids

                # --- overlays ------------------------------------------- #
                dt = max(1e-6, time.time() - t0)
                fps_smoothed = 0.9 * fps_smoothed + 0.1 * (1.0 / dt) \
                    if fps_smoothed else 1.0 / dt
                if show:
                    status_text = ("Searching" if robot_status.value == STATUS_SEARCHING
                                   else "Running")
                    color_status = ((0, 255, 0) if robot_status.value == STATUS_SEARCHING
                                    else (0, 0, 255))
                    cv2.putText(color, f"FPS: {fps_smoothed:.1f}",
                                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 255, 255), 2)
                    cv2.putText(color, f"Status: {status_text}",
                                (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                color_status, 2)
                    if use_tracker:
                        cv2.putText(color, f"tracks: {len(tracker.tracks)}",
                                    (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    (255, 255, 0), 2)
                    cv2.imshow("color", color)
                    if depth_colormap is not None:
                        cv2.imshow("depth", depth_colormap)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                if cfg.runtime.inference_interval_ms:
                    time.sleep(cfg.runtime.inference_interval_ms / 1000.0)

        finally:
            if show:
                cv2.destroyAllWindows()


# --------------------------------------------------------------------------- #
# Arm pipeline
# --------------------------------------------------------------------------- #


def arm_pipeline(cfg, target_queue: Queue, robot_status,
                 vision_proc=None) -> None:
    image_to_arm = load_calibration(
        config_mod.resolve_path(cfg.calibration.image_to_arm_npy)
    )

    bins_by_idx = [
        cfg.arm.bins.pathological,  # 0
        cfg.arm.bins.infectious,    # 1
        cfg.arm.bins.sharps,        # 2
    ]
    home = cfg.arm.home_pos

    with arms_mod.open_arm(cfg.arm) as arm:
        if cfg.arm.home_on_start:
            arm.home()
            time.sleep(1.0)
            arm.move(home[0], home[1], home[2])

        while True:
            # If the vision worker died (model load failed, camera disconnected,
            # etc.), bail out instead of polling forever.
            if vision_proc is not None and not vision_proc.is_alive():
                logger.error("vision worker exited (code=%s); shutting down",
                             vision_proc.exitcode)
                return

            if robot_status.value != STATUS_BUSY:
                time.sleep(0.2)
                continue

            try:
                target = target_queue.get(timeout=2.0)
            except Exception:
                logger.debug("queue empty, returning to search")
                robot_status.value = STATUS_SEARCHING
                continue

            x_cam, y_cam, z_cam, bin_idx = target
            arm_xyz = camera_to_arm((x_cam, y_cam, z_cam), image_to_arm)
            ax, ay, az = float(arm_xyz[0]), float(arm_xyz[1]), float(arm_xyz[2])
            logger.info("target arm xyz = (%.1f, %.1f, %.1f) bin=%d",
                        ax, ay, az, int(bin_idx))

            # 1. lift up
            arm.move(home[0], home[1], home[2])
            # 2. approach above target
            arm.move(ax, ay, az + cfg.arm.approach_offset_z)
            # 3. descend
            arm.move(ax, ay, az + cfg.arm.pick_offset_z)
            # 4. close gripper
            arm.gripper_close(cfg.arm.gripper_close_cmd)
            time.sleep(cfg.arm.gripper_dwell_s)
            # 5. lift up again
            arm.move(ax, ay, az + cfg.arm.approach_offset_z)
            # 6. go to bin
            bin_pos = bins_by_idx[int(bin_idx)]
            arm.move(bin_pos[0], bin_pos[1], bin_pos[2])
            # 7. open gripper
            arm.gripper_open(cfg.arm.gripper_open_cmd)
            time.sleep(cfg.arm.gripper_dwell_s)
            # 8. return home
            arm.move(home[0], home[1], home[2])

            robot_status.value = STATUS_SEARCHING
            logger.info("cycle complete, back to searching")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description="Medical waste sorting pipeline")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()

    cfg = config_mod.load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, cfg.runtime.log_level, "INFO"),
        format="[main] %(asctime)s %(levelname)s: %(message)s",
    )

    target_queue: Queue = Queue()
    robot_status = Value(ctypes.c_int8, STATUS_SEARCHING)

    cfg_path = cfg._path

    vision = Process(target=vision_worker,
                     args=(cfg_path, target_queue, robot_status),
                     name="vision")
    vision.daemon = True
    vision.start()

    def _sigterm(_sig, _frm):
        logger.info("shutdown requested")
        if vision.is_alive():
            vision.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        arm_pipeline(cfg, target_queue, robot_status, vision_proc=vision)
    finally:
        if vision.is_alive():
            vision.terminate()
            vision.join(timeout=3)


if __name__ == "__main__":
    main()
