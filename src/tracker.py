"""Lightweight IoU-based multi-object tracker (ByteTrack-Lite).

Compared to full ByteTrack:
  * No Kalman filter — tracks are purely IoU-matched on each frame
  * No appearance embedding
  * No motion prediction

For our use case (mostly stationary medical waste on a workbench) this is
plenty: it gives each detected object a stable ``track_id`` across frames so
the voting layer can count consecutive observations of the same physical
item rather than re-detecting from scratch every tick.

Public API:

    tracker = SimpleTracker(iou_threshold=0.3, max_lost=5)
    for frame in frames:
        detections = detector.predict(frame)
        tracked = tracker.update(detections)   # List[Track]
        for trk in tracked:
            if trk.consecutive_hits >= 3 and trk.last_conf > 0.7:
                trigger_grasp(trk)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.detector import Detection


def iou_xyxy(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    """Standard IoU on axis-aligned bounding boxes (xmin, ymin, xmax, ymax)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


@dataclass
class Track:
    track_id: int
    cls_name: str
    cls_id: int
    box: Tuple[int, int, int, int]   # xmin, ymin, xmax, ymax
    last_conf: float
    consecutive_hits: int = 1        # frames seen in a row (resets on miss)
    total_hits: int = 1
    age_since_seen: int = 0          # frames since last match
    history: List[Tuple[int, int]] = field(default_factory=list)  # centers

    @property
    def center(self) -> Tuple[int, int]:
        return ((self.box[0] + self.box[2]) // 2,
                (self.box[1] + self.box[3]) // 2)


class SimpleTracker:
    """Greedy IoU tracker with class-aware matching."""

    def __init__(self, iou_threshold: float = 0.3, max_lost: int = 5,
                 class_aware: bool = True) -> None:
        self.iou_threshold = iou_threshold
        self.max_lost = max_lost
        self.class_aware = class_aware
        self._tracks: Dict[int, Track] = {}
        self._next_id = 0

    @property
    def tracks(self) -> List[Track]:
        return list(self._tracks.values())

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 0

    def update(self, detections: List[Detection]) -> List[Track]:
        """Match new detections to existing tracks; return all live tracks."""

        # 1) Build IoU matrix between detections and tracks, then do greedy
        #    match — pick highest IoU pair, mark both used, repeat.
        det_used = [False] * len(detections)
        track_used = {tid: False for tid in self._tracks}

        # Sort all (track_id, det_idx, iou) tuples by IoU descending
        pairs: List[Tuple[float, int, int]] = []
        for tid, trk in self._tracks.items():
            for di, det in enumerate(detections):
                if self.class_aware and det.cls_id != trk.cls_id:
                    continue
                iou = iou_xyxy(trk.box, (det.xmin, det.ymin, det.xmax, det.ymax))
                if iou >= self.iou_threshold:
                    pairs.append((iou, tid, di))
        pairs.sort(reverse=True, key=lambda p: p[0])

        for iou, tid, di in pairs:
            if track_used[tid] or det_used[di]:
                continue
            track_used[tid] = True
            det_used[di] = True
            self._update_track(self._tracks[tid], detections[di])

        # 2) Tracks not matched this frame -> increment age, possibly drop
        dead: List[int] = []
        for tid, used in track_used.items():
            if used:
                continue
            trk = self._tracks[tid]
            trk.age_since_seen += 1
            trk.consecutive_hits = 0  # reset streak on miss
            if trk.age_since_seen > self.max_lost:
                dead.append(tid)
        for tid in dead:
            del self._tracks[tid]

        # 3) Detections not matched -> spawn new tracks
        for di, used in enumerate(det_used):
            if used:
                continue
            self._spawn(detections[di])

        return self.tracks

    # ------------------------------------------------------------------ #
    def _update_track(self, trk: Track, det: Detection) -> None:
        trk.box = (det.xmin, det.ymin, det.xmax, det.ymax)
        trk.last_conf = det.confidence
        trk.consecutive_hits += 1
        trk.total_hits += 1
        trk.age_since_seen = 0
        trk.history.append(trk.center)
        if len(trk.history) > 30:
            trk.history.pop(0)

    def _spawn(self, det: Detection) -> None:
        tid = self._next_id
        self._next_id += 1
        self._tracks[tid] = Track(
            track_id=tid,
            cls_name=det.cls_name,
            cls_id=det.cls_id,
            box=(det.xmin, det.ymin, det.xmax, det.ymax),
            last_conf=det.confidence,
            consecutive_hits=1,
            total_hits=1,
            age_since_seen=0,
            history=[((det.xmin + det.xmax) // 2,
                      (det.ymin + det.ymax) // 2)],
        )

    # ------------------------------------------------------------------ #
    def best_stable_track(self, min_hits: int, min_conf: float) -> Optional[Track]:
        """Return the track most likely to be a real, stable object.

        Picks the track with the most consecutive hits whose latest
        confidence is at least ``min_conf`` and whose ``consecutive_hits``
        is at least ``min_hits``. Ties broken by confidence.
        """
        candidates = [
            t for t in self._tracks.values()
            if t.consecutive_hits >= min_hits and t.last_conf >= min_conf
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: (t.consecutive_hits, t.last_conf),
                        reverse=True)
        return candidates[0]
