"""KDE backend: relies on KScreen's native auto-rotation (iio-sensor-proxy)."""

from __future__ import annotations

import subprocess

from . import BaseBackend, _hyprctl


class KdeBackend(BaseBackend):
    mode = "native"
    name = "kde"

    def apply_rotation(self, orientation: str, transform: int) -> None:
        # KScreen auto-rotates when the sensor proxy is present; nothing to do.
        pass

    def apply_touch_transform(self, transform: int) -> None:
        # KScreen aligns touch input with the display automatically.
        pass

    def enable_native_rotation(self) -> None:
        # Ensure the KScreen auto-rotate module is enabled.
        subprocess.run(
            ["kwriteconfig5", "kded5", "kded_modules", "kscreen"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        subprocess.run(
            ["qdbus", "org.kde.kded5", "/kded", "loadModule", "kscreen"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        print("[kde] native auto-rotation enabled via KScreen")
