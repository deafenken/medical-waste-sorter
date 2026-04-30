"""Camera backend factory.

Backends register themselves via ``build(cam_cfg)`` in their own module.

To add a new backend:
  1. create ``src/cameras/<your_backend>.py``
  2. expose ``class FooCamera(Camera)`` and a ``build(cam_cfg) -> FooCamera``
  3. add a config entry::

         camera:
           backend: foo
           # ... backend-specific fields
"""
from __future__ import annotations

from src.cameras.base import Camera, Intrinsics, open_camera  # noqa: F401


def build_camera(cam_cfg) -> Camera:
    backend = getattr(cam_cfg, "backend", "orbbec").lower()
    if backend == "orbbec":
        from src.cameras import orbbec
        return orbbec.build(cam_cfg)
    if backend == "realsense":
        from src.cameras import realsense
        return realsense.build(cam_cfg)
    if backend == "usb":
        from src.cameras import usb
        return usb.build(cam_cfg)
    raise ValueError(
        f"Unknown camera backend: {backend!r}. "
        f"Known: orbbec, realsense, usb."
    )
