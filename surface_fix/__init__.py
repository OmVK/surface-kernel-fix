"""surface-fix: cross-distro Surface kernel + touch + auto-rotation helper."""

from __future__ import annotations

__version__ = "0.1.0"

from .detect import detect_environment, Environment
from .kernel import setup_kernel
from .rotate import RotationDaemon
from .sensor import SysfsOrientation, ensure_input_stack
from .backends import get_backend

__all__ = [
    "detect_environment",
    "Environment",
    "setup_kernel",
    "RotationDaemon",
    "SysfsOrientation",
    "ensure_input_stack",
    "get_backend",
]
