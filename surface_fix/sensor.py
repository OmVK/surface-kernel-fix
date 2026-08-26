"""Orientation sensing from the accelerometer, and IPTS touch enablement.

The orientation logic is the same one validated on the Surface laptop: read the
live ``accel_3d`` IIO device, pick the dominant gravity axis, and map it to one
of the four named orientations Hyprland/GSettings/KScreen understand.
"""

from __future__ import annotations

import glob
import os
import subprocess
from typing import List, Optional

# Orientation -> Hyprland/Wayland transform index (0=normal,1=90cw,2=180,3=270cw)
ORIENTATION_TO_TRANSFORM = {
    "normal": 0,
    "right-up": 1,
    "bottom-up": 2,
    "left-up": 3,
}


def orient_to_transform(orientation: str) -> Optional[int]:
    return ORIENTATION_TO_TRANSFORM.get(orientation)


def find_accel_device() -> Optional[str]:
    """Return the sysfs path of the first IIO device exposing accel raw channels."""
    for dev in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
        if glob.glob(os.path.join(dev, "in_accel_*_raw")):
            return dev
    return None


def _read_int(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


class SysfsOrientation:
    """Polls the accelerometer and reports the current 4-way orientation."""

    def __init__(self, device: Optional[str] = None, threshold: float = 1.25) -> None:
        self.device = device or find_accel_device()
        self.threshold = threshold

    def _axes(self):
        d = self.device
        x = _read_int(os.path.join(d, "in_accel_x_raw"))
        y = _read_int(os.path.join(d, "in_accel_y_raw"))
        z = _read_int(os.path.join(d, "in_accel_z_raw"))
        return x, y, z

    def orientation(self) -> Optional[str]:
        if not self.device:
            return None
        x, y, z = self._axes()
        ax, ay, az = abs(x), abs(y), abs(z)

        if ax >= ay and ax >= az:
            largest, second = ax, max(ay, az)
            dom = "x"
        elif ay >= ax and ay >= az:
            largest, second = ay, max(ax, az)
            dom = "y"
        else:
            largest, second = az, max(ax, ay)
            dom = "z"

        # Require a clearly dominant axis; near-diagonal poses are ambiguous.
        if second == 0 or largest < self.threshold * second:
            return None

        if dom == "y":
            return "normal" if y < 0 else "bottom-up"
        if dom == "x":
            return "left-up" if x < 0 else "right-up"
        return "normal" if z < 0 else "bottom-up"


def ensure_input_stack() -> None:
    """Start the IPTS touch daemon (and sensor proxy) if present.

    These are distro-agnostic systemd units; the package install is handled by
    the distro backend, this only makes sure the runtime service is up.
    """
    for unit in ("iptsd.service", "iptsd-surface.service", "iio-sensor-proxy.service"):
        try:
            subprocess.run(["systemctl", "is-active", "--quiet", unit],
                           check=False)
            subprocess.run(["systemctl", "enable", "--now", unit],
                           check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass


def disable_raw_touch(device_name: str = "ipts-045e:001f-touchscreen") -> None:
    """Best-effort disable of the raw IPTS input device to avoid duplicate taps.

    On Hyprland this is done via hl.device(); other compositors ignore it.
    """
    # Handled in the Hyprland backend; kept here for symmetry / future use.
    pass
