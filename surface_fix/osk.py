"""On-screen keyboard auto-show for tablet mode (Type Cover detached).

Detection uses the kernel ``/dev/input/by-id`` node, which disappears on a
real disconnect even when the compositor keeps a cached device entry (this is
exactly what broke the naive ``hyprctl devices`` check on Hyprland). The OSK
itself is launched as a regular Wayland client (``wvkbd`` is preferred because
``squeekboard`` requires a GNOME/Phosh session and silently exits elsewhere).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import List, Optional

BY_ID = "/dev/input/by-id"

# Preferred OSK binaries (Surface/tablet-friendly on Wayland first).
OSK_CANDIDATES: List[str] = [
    "wvkbd-deskintl", "wvkbd-mobintl", "corekeyboard", "squeekboard",
]

# Default launch flags for the wvkbd variants (landscape, readable size).
# Use a font that is actually installed (DejaVu Sans is usually absent,
# causing cairo to fall back to a tiny bitmap font that looks blurry).
# Override with the SURFACE_OSK_ARGS environment variable (space separated).
OSK_DEFAULT_ARGS: List[str] = ["-L", "300", "--fn", "Noto Sans 18"]


def find_osk() -> Optional[str]:
    """Return the first available OSK binary, or None."""
    for candidate in OSK_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    return None


def type_cover_attached(marker: str = "Surface_Type_Cover") -> bool:
    """True when a Surface Type Cover is physically connected.

    Fail-safe: if the by-id directory is unavailable we assume attached so we
    never pop up the keyboard on a false positive.
    """
    if not os.path.isdir(BY_ID):
        return True
    try:
        entries = os.listdir(BY_ID)
    except OSError:
        return True
    return any(marker.lower() in entry.lower() for entry in entries)


def _recover_wayland_env() -> None:
    """Best-effort recovery of the session env when launched headless."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        hypr_dir = os.path.join(runtime, "hypr")
        if os.path.isdir(hypr_dir):
            inst = next((d for d in os.listdir(hypr_dir) if d), None)
            if inst:
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = inst
    if not os.environ.get("WAYLAND_DISPLAY"):
        socks = [s for s in os.listdir(runtime) if s.startswith("wayland-")]
        if socks:
            os.environ["WAYLAND_DISPLAY"] = socks[0]


class OskDaemon:
    def __init__(self, osk_cmd: Optional[str] = None,
                 marker: str = "Surface_Type_Cover", poll: float = 2.0,
                 log_path: Optional[str] = None,
                 args: Optional[List[str]] = None) -> None:
        self.osk_cmd = osk_cmd or find_osk()
        self.marker = marker
        self.poll = poll
        self.log_path = log_path
        self.args = args if args is not None else list(OSK_DEFAULT_ARGS)
        self._proc: Optional[subprocess.Popen] = None

    def _log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        else:
            print(line)

    def _running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if self.osk_cmd and shutil.which("pgrep"):
            return subprocess.run(["pgrep", "-f", self.osk_cmd],
                                 capture_output=True).returncode == 0
        return False

    def _start(self) -> None:
        if not self.osk_cmd:
            self._log("no OSK binary found (install wvkbd-deskintl)")
            return
        if self._running():
            return
        _recover_wayland_env()
        self._log(f"tablet mode: starting {self.osk_cmd}")
        self._proc = subprocess.Popen([self.osk_cmd, *self.args],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)

    def _stop(self) -> None:
        if not self._running():
            return
        self._log(f"laptop mode: stopping {self.osk_cmd}")
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None
        else:
            subprocess.run(["pkill", "-f", self.osk_cmd], check=False)

    def run(self) -> None:
        self._log(f"started; OSK_CMD={self.osk_cmd} poll={self.poll}s")
        while True:
            if type_cover_attached(self.marker):
                self._stop()
            else:
                self._start()
            time.sleep(self.poll)
