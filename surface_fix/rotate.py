"""Auto-rotation daemon: polls the sensor and drives the compositor backend."""

from __future__ import annotations

import time
from typing import Optional

from .backends import BaseBackend
from .sensor import SysfsOrientation, orient_to_transform


class RotationDaemon:
    def __init__(self, backend: BaseBackend,
                 source: Optional[SysfsOrientation] = None,
                 poll: float = 0.4, debounce: int = 1) -> None:
        self.backend = backend
        self.source = source or SysfsOrientation()
        self.poll = poll
        self.debounce = debounce

    def run(self) -> None:
        if self.backend.mode == "native":
            # The desktop environment rotates itself; we only enable it.
            self.backend.enable_native_rotation()
            print(f"[{self.backend.name}] native auto-rotation active; "
                  f"daemon idle (DE handles rotation).")
            return

        print(f"[{self.backend.name}] manual rotation daemon started.")
        prev = None
        stable = 0
        while True:
            orientation = self.source.orientation()
            if orientation is None:
                prev = None
                stable = 0
                time.sleep(self.poll)
                continue
            if orientation == prev:
                stable += 1
            else:
                stable = 0
                prev = orientation
            if stable >= self.debounce:
                transform = orient_to_transform(orientation)
                if transform is not None:
                    self.backend.apply_rotation(orientation, transform)
                stable = 0
            time.sleep(self.poll)
