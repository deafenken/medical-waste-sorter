"""YOLOv8 detector with multiple inference backends.

Backends supported:
  - pytorch : load .pt directly (slow on CPU; fine for desktop dev)
  - ncnn    : load *_ncnn_model directory (recommended for Pi CPU)
  - hailo   : Hailo-8 / Hailo-8L NPU via HailoRT (recommended for Pi 5 + Hailo-8)
  - rknn    : RK3588 NPU runtime (loaded only when available)
  - onnx    : ONNX runtime (cross-platform fallback)

The detector returns a list of ``Detection`` records so the main pipeline
doesn't depend on Ultralytics' result schema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from src.config import resolve_path

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    xmin: int
    ymin: int
    xmax: int
    ymax: int
    confidence: float
    cls_id: int
    cls_name: str

    @property
    def center(self) -> tuple[int, int]:
        return (
            int((self.xmax + self.xmin) / 2),
            int((self.ymax + self.ymin) / 2),
        )


class Detector:
    """Common interface."""

    names: dict

    def predict(self, frame_bgr: np.ndarray, conf: float = 0.5) -> List[Detection]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Ultralytics (covers pytorch + ncnn + onnx via single API)
# --------------------------------------------------------------------------- #


class UltralyticsDetector(Detector):
    def __init__(
        self,
        model_path: str,
        imgsz: int = 640,
        iou: float = 0.7,
        max_det: int = 100,
    ) -> None:
        from ultralytics import YOLO  # imported lazily

        logger.info("Loading model with Ultralytics: %s", model_path)
        self.model = YOLO(model_path)
        self.names = self.model.names
        self.imgsz = imgsz
        self.iou = iou
        self.max_det = max_det

    def warmup(self) -> None:
        """Run a single dummy inference to amortize first-call overhead.

        First-frame latency on Pi can be 1-2 seconds (graph allocation, lazy
        kernel compilation). Calling warmup() at startup keeps the live
        pipeline at steady-state FPS from frame #1.
        """
        try:
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            self.model.predict(source=dummy, save=False,
                               conf=0.99, verbose=False, imgsz=self.imgsz)
            logger.info("detector warmed up at imgsz=%d", self.imgsz)
        except Exception:
            logger.warning("detector warmup failed (non-fatal)", exc_info=True)

    def predict(self, frame_bgr: np.ndarray, conf: float = 0.5) -> List[Detection]:
        results = self.model.predict(
            source=frame_bgr,
            save=False,
            conf=conf,
            iou=self.iou,
            max_det=self.max_det,
            imgsz=self.imgsz,
            verbose=False,
        )
        if not results:
            return []
        boxes = results[0].boxes
        if boxes is None or boxes.data is None:
            return []
        out: List[Detection] = []
        for row in boxes.data.tolist():
            xmin, ymin, xmax, ymax, c, cls_idx = (
                int(row[0]), int(row[1]), int(row[2]), int(row[3]),
                float(row[4]), int(row[5]),
            )
            out.append(
                Detection(
                    xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax,
                    confidence=round(c, 3),
                    cls_id=cls_idx,
                    cls_name=self.names.get(cls_idx, str(cls_idx)),
                )
            )
        return out


# --------------------------------------------------------------------------- #
# RKNN backend (placeholder; populated when running on RK3588)
# --------------------------------------------------------------------------- #


class RknnDetector(Detector):  # pragma: no cover - hardware specific
    """Stub. See docs/RK3588.md for full conversion + runtime instructions."""

    def __init__(self, model_path: str, names: Optional[dict] = None) -> None:
        try:
            from rknnlite.api import RKNNLite
        except ImportError as exc:
            raise RuntimeError(
                "rknnlite not installed. On RK3588:  pip install rknn-toolkit-lite2"
            ) from exc

        self.rknn = RKNNLite()
        if self.rknn.load_rknn(model_path) != 0:
            raise RuntimeError(f"Failed to load RKNN model: {model_path}")
        if self.rknn.init_runtime() != 0:
            raise RuntimeError("Failed to init RKNN runtime")
        self.names = names or {
            0: "plastic bottle", 1: "glass bottle",
            2: "mask", 3: "gauze", 4: "injector",
        }

    def predict(self, frame_bgr: np.ndarray, conf: float = 0.5) -> List[Detection]:
        # NOTE: Pre/post-processing is YOLO-version specific.
        # See docs/RK3588.md for a working reference implementation.
        raise NotImplementedError(
            "Implement RKNN pre/post-processing per your model export. "
            "See docs/RK3588.md."
        )


# --------------------------------------------------------------------------- #
# Hailo backend (Pi 5 + Hailo-8 / Hailo-8L)
# --------------------------------------------------------------------------- #


class HailoDetector(Detector):  # pragma: no cover - hardware specific
    """Hailo-8 / Hailo-8L NPU backend.

    Pi 5 + Hailo-8 26 TOPS gives 30+ FPS on YOLOv8n at 640x640. Workflow:

      1. PC: convert best.pt -> best.onnx (Ultralytics export)
      2. PC: use Hailo Dataflow Compiler to convert ONNX -> .hef
             (requires calibration set captured with tools/capture_calib_set.py)
      3. Pi: install HailoRT runtime + hailo-platform Python bindings
      4. Pi: copy best.hef into models/, set detector.backend: hailo

    See docs/HAILO.md for full step-by-step.
    """

    def __init__(
        self,
        model_path: str,
        imgsz: int = 640,
        names: Optional[dict] = None,
    ) -> None:
        try:
            from hailo_platform import (
                VDevice, HEF, ConfigureParams, FormatType,   # noqa: F401
                HailoStreamInterface, InputVStreamParams,
                OutputVStreamParams, InferVStreams,
            )
        except ImportError as exc:
            raise RuntimeError(
                "hailo_platform not installed. On Pi 5 + Hailo-8:\n"
                "  Run:  scripts/install_pi.sh  with HAILO_SDK=1 set,\n"
                "  or follow docs/HAILO.md to install HailoRT + hailo-platform."
            ) from exc

        self._hef = HEF(model_path)
        self._device = VDevice()
        self._network_group = self._device.configure(
            self._hef,
            ConfigureParams.create_from_hef(
                hef=self._hef, interface=HailoStreamInterface.PCIe,
            ),
        )[0]
        self._network_group_params = self._network_group.create_params()
        self._input_vstreams_params = InputVStreamParams.make(
            self._network_group, format_type=FormatType.FLOAT32,
        )
        self._output_vstreams_params = OutputVStreamParams.make(
            self._network_group, format_type=FormatType.FLOAT32,
        )
        self.imgsz = imgsz
        self.names = names or {
            0: "plastic bottle", 1: "glass bottle",
            2: "mask", 3: "gauze", 4: "injector",
        }

    def predict(self, frame_bgr: np.ndarray, conf: float = 0.5) -> List[Detection]:
        # NOTE: Hailo's output layout depends on how you compiled the .hef.
        # Standard YOLOv8 hef from Hailo Model Zoo emits 3 detection heads
        # (small/medium/large grids) plus possibly a built-in NMS post-op.
        # See docs/HAILO.md and Hailo's reference repo for a working pre/post:
        #   https://github.com/hailo-ai/hailo_model_zoo
        raise NotImplementedError(
            "Implement Hailo pre/post-processing for your specific .hef. "
            "See docs/HAILO.md §4 for the reference pipeline."
        )


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def build_detector(det_cfg) -> Detector:
    backend = det_cfg.backend.lower()
    # Resolve relative to repo root so the pipeline runs from any cwd.
    model_path = str(resolve_path(det_cfg.model_path))
    imgsz = int(getattr(det_cfg, "imgsz", 640))
    iou = float(getattr(det_cfg, "iou_threshold", 0.7))
    max_det = int(getattr(det_cfg, "max_det", 100))
    if backend in ("pytorch", "ncnn", "onnx"):
        return UltralyticsDetector(model_path, imgsz=imgsz, iou=iou, max_det=max_det)
    if backend == "rknn":
        return RknnDetector(model_path)
    if backend == "hailo":
        return HailoDetector(model_path, imgsz=imgsz)
    raise ValueError(f"Unknown detector backend: {backend!r}")
