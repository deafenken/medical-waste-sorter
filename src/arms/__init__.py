"""Arm backend factory.

Backends register themselves via the ``build(arm_cfg)`` callable in their
own module. The factory dispatches on ``arm_cfg.backend``.

To add a new backend:
  1. create ``src/arms/<your_backend>.py``
  2. expose a ``class FooArm(ArmBackend)`` and a ``build(arm_cfg) -> FooArm``
  3. add a config entry::

         arm:
           backend: foo
           # ... backend-specific fields
"""
from __future__ import annotations

from src.arms.base import ArmBackend, open_arm  # noqa: F401  (re-exports)


def build_arm(arm_cfg) -> ArmBackend:
    backend = getattr(arm_cfg, "backend", "gcode").lower()
    if backend == "gcode":
        from src.arms import gcode
        return gcode.build(arm_cfg)
    if backend in ("panthera_ht", "panthera"):
        from src.arms import panthera_ht
        return panthera_ht.build(arm_cfg)
    raise ValueError(
        f"Unknown arm backend: {backend!r}. "
        f"Known: gcode, panthera_ht."
    )
