"""Hyprland backend: applies display rotation + touch alignment via hyprctl eval."""

from __future__ import annotations

import re
from typing import List, Optional

from . import BaseBackend, _hyprctl


class HyprlandBackend(BaseBackend):
    mode = "manual"
    name = "hyprland"
    RAW_TOUCH = "ipts-045e:001f-touchscreen"

    def __init__(self, output: Optional[str] = None) -> None:
        self._output = output

    # --- detection ----------------------------------------------------------
    def _output_name(self) -> str:
        if self._output:
            return self._output
        out = _hyprctl(["monitors"])
        m = re.search(r"Monitor\s+(\S+)", out)
        return m.group(1) if m else "eDP-1"

    def touch_devices(self) -> List[str]:
        out = _hyprctl(["devices"])
        names: List[str] = []
        in_touch = False
        for line in out.splitlines():
            if line.startswith("Touch:"):
                in_touch = True
                continue
            if line.startswith("Switches:"):
                in_touch = False
                continue
            if in_touch:
                if "Touch Device at" in line:
                    continue
                name = line.strip()
                if name:
                    names.append(name)
        return names

    # --- application --------------------------------------------------------
    def apply_rotation(self, orientation: str, transform: int) -> None:
        output = self._output_name()
        _hyprctl([
            "eval",
            f'hl.monitor({{output="{output}", mode="preferred", '
            f'position="auto", scale="auto", transform={transform}}})',
        ])
        self.apply_touch_transform(transform)

    def apply_touch_transform(self, transform: int) -> None:
        # Disable the raw IPTS device so only the calibrated iptsd virtual
        # touchscreen is used (avoids duplicate/conflicting input).
        _hyprctl(["eval", f'hl.device({{name="{self.RAW_TOUCH}", enabled=false}})'])
        for dev in self.touch_devices():
            if dev == self.RAW_TOUCH:
                continue
            _hyprctl(["eval", f'hl.device({{name="{dev}", transform={transform}}})'])

    def current_transform(self) -> Optional[int]:
        out = _hyprctl(["monitors"])
        m = re.search(r"transform:\s*(\d)", out)
        return int(m.group(1)) if m else None

    def enable_native_rotation(self) -> None:
        # Hyprland has no native auto-rotate; the daemon drives it.
        pass
