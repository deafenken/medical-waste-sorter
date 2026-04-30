"""Compatibility shim.

This module used to host the G-code arm implementation directly. It now
re-exports from the backend-pluggable ``src.arms`` package so external code
that did ``from src.serial_arm import GCodeArm, open_arm`` keeps working.

New code should import from the new locations:

    from src.arms import build_arm, open_arm
    from src.arms.gcode import GCodeArm
    from src.arms.panthera_ht import PantheraHTArm
"""
from src.arms import open_arm  # noqa: F401
from src.arms.gcode import GCodeArm  # noqa: F401

__all__ = ["GCodeArm", "open_arm"]
