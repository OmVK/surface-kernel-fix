"""GNOME backend: relies on GNOME's native auto-rotation (iio-sensor-proxy)."""

from __future__ import annotations

import subprocess

from . import BaseBackend, _hyprctl


class GnomeBackend(BaseBackend):
    mode = "native"
    name = "gnome"

    def apply_rotation(self, orientation: str, transform: int) -> None:
        # GNOME rotates the display itself via iio-sensor-proxy; nothing to do.
        pass

    def apply_touch_transform(self, transform: int) -> None:
        # GNOME keeps touch input aligned with the display automatically.
        pass

    def enable_native_rotation(self) -> None:
        # Unlock orientation (orientation-lock=false lets it rotate freely).
        for schema in ("org.gnome.settings-daemon.peripherals.touchscreen",
                       "org.gnome.settings-daemon.plugins.orientation"):
            subprocess.run(
                ["gsettings", "set", schema, "orientation-lock", "false"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        print("[gnome] native auto-rotation enabled (iio-sensor-proxy drives it)")
