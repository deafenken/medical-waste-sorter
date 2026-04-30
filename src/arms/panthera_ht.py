"""Panthera-HT 6-DOF arm backend.

Wraps HighTorque-Robotics' open-source Panthera SDK
(https://github.com/HighTorque-Robotics/Panthera-HT_SDK) so the rest of the
pipeline can keep its mm/Cartesian interface even though the underlying SDK
speaks meters/radians/joint-space.

Conversion strategy:
  * Caller passes (x, y, z) in **millimeters**, base frame
  * We convert to **meters**
  * Build a **target rotation matrix** from a configurable end-effector pose
    (default: tool pointing straight down at the workbench)
  * Call ``robot.inverse_kinematics()`` to get joint angles
  * Call ``robot.moveJ()`` to drive the arm
  * Block until reached (iswait=True) so the caller's "done = move returned"
    semantics match the G-code path

Open questions (verify on real hardware):
  * Whether ``moveJ(duration=...)`` interpolates linearly in joint or
    Cartesian space — for short table-level moves the difference is small
  * Whether ``inverse_kinematics`` honors current joint state seed properly
    for IK convergence near singularities
  * Exact base-frame orientation (X forward vs X side); see fk[0] sanity test
    in the bring-up checklist below
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import numpy as np

from src.arms.base import ArmBackend

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Default end-effector orientations
# --------------------------------------------------------------------------- #
# Tool Z axis pointing into the table (downward suction / pick).
# Convention: rotation matrix maps tool frame -> base frame.
#   tool X = base X     (no in-plane rotation)
#   tool Y = -base Y    (right-handed flip so tool Z = -base Z)
#   tool Z = -base Z    (pointing down)
R_TOOL_DOWN = np.array(
    [[1.0, 0.0, 0.0],
     [0.0, -1.0, 0.0],
     [0.0, 0.0, -1.0]],
    dtype=np.float64,
)

# Tool pointing horizontally forward (J3 horizontal).
R_TOOL_FORWARD = np.array(
    [[1.0, 0.0, 0.0],
     [0.0, 0.0, -1.0],
     [0.0, 1.0, 0.0]],
    dtype=np.float64,
)

POSE_PRESETS = {
    "down": R_TOOL_DOWN,
    "forward": R_TOOL_FORWARD,
}


def _mm_to_m(v: float) -> float:
    return v / 1000.0


# --------------------------------------------------------------------------- #
# Backend
# --------------------------------------------------------------------------- #


class PantheraHTArm(ArmBackend):
    """6-DOF Panthera-HT via HighTorque-Robotics' Python SDK."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        home_joint_rad: Optional[List[float]] = None,
        approach_pose: str = "down",
        move_duration_s: float = 3.0,
        gripper_speed: float = 0.5,
        gripper_max_torque: float = 0.5,
        max_joint_torques: Optional[List[float]] = None,
        wait_tolerance_rad: float = 0.01,
        wait_timeout_s: float = 15.0,
    ) -> None:
        # Lazy import — the SDK has heavy native deps (pin, lcm, libserialport)
        # that we don't want to crash CI / sandbox installs that just do a
        # `import src.arms`.
        try:
            from Panthera_lib import Panthera   # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError(
                "Panthera SDK not installed. See docs/PANTHERA_HT.md §3 for "
                "install instructions:\n"
                "  pip install motor_whl/hightorque_robot-*.whl  (x86_64 only)\n"
                "  -OR build from source on ARM64-"
            ) from exc

        logger.info("Initializing Panthera SDK (config=%s)", config_path)
        self._robot = Panthera(config_path) if config_path else Panthera()

        self.move_duration_s = move_duration_s
        self.gripper_speed = gripper_speed
        self.gripper_max_torque = gripper_max_torque
        self.wait_tolerance_rad = wait_tolerance_rad
        self.wait_timeout_s = wait_timeout_s
        self.max_joint_torques = max_joint_torques  # forwarded to Joint_Pos_Vel

        if approach_pose not in POSE_PRESETS:
            raise ValueError(
                f"approach_pose must be one of {list(POSE_PRESETS)}, "
                f"got {approach_pose!r}"
            )
        self._R_target = POSE_PRESETS[approach_pose]
        self._approach_pose_name = approach_pose

        # Default home: all zeros, except elbow tucked in. Override via config.
        # Six-DOF zero pose in radians; user MUST override for their setup.
        self._home_q = np.array(
            home_joint_rad if home_joint_rad is not None
            else [0.0, math.pi / 2, math.pi / 2, 0.0, 0.0, 0.0],
            dtype=np.float64,
        )

        self._closed = False

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _ik(self, x_mm: float, y_mm: float, z_mm: float,
            init_q: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """Run IK for a Cartesian target (mm) with the configured tool pose."""
        target = [_mm_to_m(x_mm), _mm_to_m(y_mm), _mm_to_m(z_mm)]
        seed = init_q if init_q is not None else self._robot.get_current_pos()
        q = self._robot.inverse_kinematics(
            target_position=target,
            target_rotation=self._R_target,
            init_q=seed,
        )
        if q is None:
            logger.error(
                "IK failed for target (%.1f, %.1f, %.1f) mm with pose=%s",
                x_mm, y_mm, z_mm, self._approach_pose_name,
            )
            return None
        return np.asarray(q, dtype=np.float64)

    def _moveJ(self, q: np.ndarray, duration: Optional[float] = None) -> bool:
        try:
            self._robot.moveJ(
                pos=list(q),
                duration=duration if duration is not None else self.move_duration_s,
                iswait=True,
                tolerance=self.wait_tolerance_rad,
                timeout=self.wait_timeout_s,
            )
            return True
        except Exception:
            logger.exception("moveJ failed for q=%s", q)
            return False

    # --------------------------------------------------------------------- #
    # ArmBackend interface
    # --------------------------------------------------------------------- #
    def home(self) -> bool:
        logger.info("Home -> joint angles (rad): %s", self._home_q)
        return self._moveJ(self._home_q)

    def move(self, x: float, y: float, z: float,
             feed: Optional[float] = None) -> bool:
        q = self._ik(x, y, z)
        if q is None:
            return False
        # ``feed`` is a speed hint in mm/s; convert to a duration estimate so
        # the moveJ caller doesn't blast through the trajectory at full speed.
        duration = self.move_duration_s
        if feed is not None and feed > 0:
            # Estimate Cartesian distance from current pose
            try:
                fk = self._robot.forward_kinematics()
                cur = np.asarray(fk["position"], dtype=np.float64) * 1000.0
                tgt = np.array([x, y, z], dtype=np.float64)
                dist_mm = float(np.linalg.norm(tgt - cur))
                duration = max(0.5, dist_mm / max(1e-3, feed))
            except Exception:
                logger.debug("FK lookup failed, using default duration",
                             exc_info=True)
        return self._moveJ(q, duration=duration)

    def gripper_close(self, cmd: Optional[str] = None) -> bool:
        try:
            self._robot.gripper_close(
                pos=0.0, vel=self.gripper_speed,
                max_tqu=self.gripper_max_torque,
            )
            return True
        except Exception:
            logger.exception("gripper_close failed")
            return False

    def gripper_open(self, cmd: Optional[str] = None) -> bool:
        try:
            self._robot.gripper_open(
                vel=self.gripper_speed, max_tqu=self.gripper_max_torque,
            )
            return True
        except Exception:
            logger.exception("gripper_open failed")
            return False

    def stop(self) -> bool:
        try:
            self._robot.set_stop()
            return True
        except Exception:
            logger.exception("set_stop failed")
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._robot.set_stop()
        except Exception:
            logger.debug("set_stop during close raised", exc_info=True)
        # SDK has no explicit ``disconnect()`` documented; rely on GC.

    # --------------------------------------------------------------------- #
    # Optional Panthera-specific extras (not part of the abstract interface)
    # --------------------------------------------------------------------- #
    def move_joint(self, q_rad: List[float], duration_s: Optional[float] = None) -> bool:
        """Direct joint-space move (radians). Bypasses IK."""
        return self._moveJ(np.asarray(q_rad, dtype=np.float64), duration_s)

    def get_pose_mm(self) -> Tuple[List[float], np.ndarray]:
        """Current end-effector position (mm) and rotation matrix."""
        fk = self._robot.forward_kinematics()
        pos_m = fk["position"]
        return [pos_m[0] * 1000.0, pos_m[1] * 1000.0, pos_m[2] * 1000.0], \
            np.asarray(fk["rotation"], dtype=np.float64)

    @property
    def sdk(self):
        """Escape hatch for advanced users to call SDK methods directly."""
        return self._robot


def build(arm_cfg) -> PantheraHTArm:
    """Factory entry-point used by ``src.arms.build_arm``."""
    return PantheraHTArm(
        config_path=getattr(arm_cfg, "config_path", None),
        home_joint_rad=getattr(arm_cfg, "home_joint_rad", None),
        approach_pose=getattr(arm_cfg, "approach_pose", "down"),
        move_duration_s=float(getattr(arm_cfg, "move_duration_s", 3.0)),
        gripper_speed=float(getattr(arm_cfg, "gripper_speed", 0.5)),
        gripper_max_torque=float(getattr(arm_cfg, "gripper_max_torque", 0.5)),
        max_joint_torques=getattr(arm_cfg, "max_joint_torques", None),
        wait_tolerance_rad=float(getattr(arm_cfg, "wait_tolerance_rad", 0.01)),
        wait_timeout_s=float(getattr(arm_cfg, "wait_timeout_s", 15.0)),
    )
