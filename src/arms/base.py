"""Abstract arm backend.

Every concrete backend (G-code, Panthera-HT, MyCobot, Dobot, ...) implements
the same minimal interface so the rest of the pipeline (main.py, calibration.py)
is hardware-agnostic.

Coordinate convention used by THIS interface:
  * Cartesian XYZ in **millimeters**, in the arm's base frame
  * The wrapper is responsible for converting to whatever units the underlying
    SDK uses (e.g. Panthera SDK is in meters & radians)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Optional


class ArmBackend(ABC):
    """Minimal arm interface used by the rest of the pipeline."""

    @abstractmethod
    def home(self) -> bool:
        """Move to a safe home pose. Returns True on success."""

    @abstractmethod
    def move(
        self,
        x: float,
        y: float,
        z: float,
        feed: Optional[float] = None,
    ) -> bool:
        """Move end-effector to (x, y, z) in **millimeters**, base frame.

        ``feed`` is an optional speed hint (mm/min for G-code, m/s for SDKs
        that take linear velocity, otherwise ignored).
        """

    @abstractmethod
    def gripper_close(self, cmd: Optional[str] = None) -> bool:
        """Close the gripper / pump on suction. ``cmd`` is backend-specific."""

    @abstractmethod
    def gripper_open(self, cmd: Optional[str] = None) -> bool:
        """Release the gripper / vent the suction."""

    @abstractmethod
    def stop(self) -> bool:
        """Soft-stop: halt motion immediately, leave servos powered.

        Hard E-stops should be wired in hardware (24V relay button), not relied
        on this software call.
        """

    @abstractmethod
    def close(self) -> None:
        """Release all hardware resources."""

    # Optional helpers — default no-ops so concrete backends can override
    def send(self, raw: str) -> bool:
        """Send a backend-native command (G-code line, SDK passthrough)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support raw passthrough"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@contextmanager
def open_arm(arm_cfg):
    """Context manager that builds + tears down an arm via the factory."""
    from src.arms import build_arm   # imported lazily to avoid circular import
    arm = build_arm(arm_cfg)
    try:
        yield arm
    finally:
        arm.close()
