"""Compatibility shim.

Camera backends moved to ``src.cameras`` (plural) when we added RealSense
support. This module re-exports the old names so existing imports keep
working.

New code should use:

    from src.cameras import build_camera, open_camera
    from src.cameras.orbbec import OrbbecCamera
    from src.cameras.realsense import RealsenseCamera
    from src.cameras.usb import UsbCamera
"""
from src.cameras import build_camera, open_camera  # noqa: F401
from src.cameras.base import Camera  # noqa: F401
from src.cameras.orbbec import OrbbecCamera  # noqa: F401
from src.cameras.usb import UsbCamera  # noqa: F401

__all__ = [
    "Camera", "OrbbecCamera", "UsbCamera",
    "build_camera", "open_camera",
]
