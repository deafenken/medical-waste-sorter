"""G-code over USB-Serial backend (GRBL / Marlin compatible).

Used by hobby-grade SCARA / 3D-printer-style arms. Kept as the default
fallback path so the original tutorial flow still works for new contributors
without specialized hardware.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import serial

from src.arms.base import ArmBackend

logger = logging.getLogger(__name__)


class GCodeArm(ArmBackend):
    """GRBL / Marlin G-code over USB-CDC serial."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 5.0,
        wait_for_ok: bool = True,
        ack_timeout_s: float = 10.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.wait_for_ok = wait_for_ok
        self.ack_timeout_s = ack_timeout_s
        logger.info("Opening serial %s @ %d", port, baudrate)
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout_s)
        time.sleep(2.0)  # GRBL/Marlin reset on connect
        self._drain_banner()

    # --------------------------------------------------------------------- #
    # low level
    # --------------------------------------------------------------------- #
    def _drain_banner(self) -> List[str]:
        banner: List[str] = []
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self._readline_nonblocking()
            if not line:
                break
            banner.append(line)
            logger.debug("banner: %s", line)
        return banner

    def _readline_nonblocking(self) -> Optional[str]:
        try:
            raw = self.ser.readline()
        except serial.SerialException as exc:
            logger.error("Serial read failed: %s", exc)
            return None
        if not raw:
            return None
        return raw.decode(errors="replace").strip()

    # --------------------------------------------------------------------- #
    # ArmBackend interface
    # --------------------------------------------------------------------- #
    def send(self, cmd: str) -> bool:
        if not self.ser.is_open:
            logger.error("Serial not open, cannot send: %s", cmd)
            return False
        line = cmd.strip() + "\r\n"
        logger.info(">>> %s", cmd.strip())
        self.ser.write(line.encode("utf-8"))
        self.ser.flush()
        if not self.wait_for_ok:
            return True
        return self._await_ack(cmd)

    def _await_ack(self, cmd: str) -> bool:
        deadline = time.time() + self.ack_timeout_s
        while time.time() < deadline:
            line = self._readline_nonblocking()
            if line is None:
                continue
            logger.debug("<<< %s", line)
            low = line.lower()
            if low.startswith("ok") or "ok" == low:
                return True
            if low.startswith("error") or low.startswith("alarm") or low.startswith("!!"):
                logger.error("Controller error after %r: %s", cmd, line)
                return False
        logger.warning("ACK timeout waiting for response to %r", cmd)
        return False

    def home(self) -> bool:
        return self.send("G28")

    def move(self, x: float, y: float, z: float,
             feed: Optional[float] = None) -> bool:
        cmd = f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f}"
        if feed is not None:
            cmd += f" F{feed}"
        return self.send(cmd)

    def gripper_close(self, cmd: Optional[str] = None) -> bool:
        return self.send(cmd or "M5")

    def gripper_open(self, cmd: Optional[str] = None) -> bool:
        return self.send(cmd or "M3")

    def stop(self) -> bool:
        # GRBL: 0x18 (Ctrl-X) is soft-reset; "!" pauses. We use M112 as a
        # widely-recognized emergency-stop G-code.
        return self.send("M112")

    def close(self) -> None:
        try:
            if self.ser.is_open:
                self.ser.close()
        except Exception:  # pragma: no cover
            logger.debug("Error closing serial", exc_info=True)


def build(arm_cfg) -> GCodeArm:
    """Factory entry-point used by ``src.arms.build_arm``."""
    return GCodeArm(
        port=arm_cfg.port,
        baudrate=arm_cfg.baudrate,
        timeout_s=getattr(arm_cfg, "timeout_s", 5.0),
        wait_for_ok=getattr(arm_cfg, "wait_for_ok", True),
        ack_timeout_s=getattr(arm_cfg, "ack_timeout_s", 10.0),
    )
