"""On-screen keyboard auto-show for tablet mode (Type Cover detached).

Detection: this Surface does not expose a ``SW_TABLET_MODE`` switch and the
Type Cover USB device / input nodes can linger as stale entries after a
detach, so we treat the cover as attached only when BOTH the Type Cover USB
device (``/sys/bus/usb/devices/1-7``, matched by product) AND a Type Cover
input device (matched by name under ``/sys/class/input``) are present. On a
real detach the kernel removes one or both (``ACTION=remove`` uevents), which
flips detection to detached and shows the OSK. The OSK itself is ``wvkbd``
(preferred on Wayland; ``squeekboard`` needs a GNOME/Phosh session).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from typing import List, Optional

BY_ID = "/dev/input/by-id"
USB_BASE = "/sys/bus/usb/devices"
INPUT_BASE = "/sys/class/input"
LOG_PATH = "/tmp/surface-osk.log"

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


def detect_scale() -> float:
    """Best-effort detection of the primary output scale (HiDPI).

    Compositors sometimes report scale 1.0 to layer-shell clients even on
    HiDPI outputs, which makes the OSK render blurry/undersized. We read the
    real scale from ``hyprctl monitors`` so wvkbd can be told the correct
    value via WVKBD_SCALE.
    """
    try:
        out = subprocess.run(["hyprctl", "monitors"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return 1.0
    best = 1.0
    for line in out.splitlines():
        line = line.strip().lower()
        if line.startswith("scale:"):
            try:
                best = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return best


def _sysfs_read(*parts: str) -> str:
    try:
        with open(os.path.join(*parts), "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def detect_fullscreen() -> bool:
    """True when the focused window is fullscreen (so the OSK is unneeded)."""
    try:
        out = subprocess.run(["hyprctl", "activewindow", "-j"],
                             capture_output=True, text=True, timeout=5).stdout
        data = json.loads(out)
        return bool(data.get("fullscreen")) or bool(data.get("fullscreenClient"))
    except Exception:
        return False


def _find_type_cover_usb(marker: str = "Surface Type Cover") -> Optional[str]:
    """Return the sysfs path of the Type Cover USB device, or None if absent."""
    if not os.path.isdir(USB_BASE):
        return None
    for dev in os.listdir(USB_BASE):
        if marker.lower() in _sysfs_read(USB_BASE, dev, "product").lower():
            return os.path.join(USB_BASE, dev)
    return None


def type_cover_attached(marker: str = "Type Cover") -> bool:
    """True when a Surface Type Cover is physically connected.

    On this Surface the kernel does not expose a ``SW_TABLET_MODE`` switch and
    the Type Cover USB device / input nodes can *linger* as stale entries after
    a detach. The reliable signal is the reverse: on a real detach the kernel
    removes either the Type Cover USB device (e.g. ``/sys/bus/usb/devices/1-7``)
    or its input devices (``ACTION=remove`` uevents on the keyboard/mouse/
    touchpad input nodes). So the cover is treated as attached only when BOTH
    the USB device and at least one Type Cover input device are present.

    Fail-safe: if we cannot determine the state we assume attached, so we never
    pop up the keyboard on a false positive.
    """
    if _find_type_cover_usb() is None:
        return False
    if not os.path.isdir(INPUT_BASE):
        return True
    try:
        for inp in os.listdir(INPUT_BASE):
            name = _sysfs_read(INPUT_BASE, inp, "device", "name")
            if marker.lower() in name.lower():
                return True
    except OSError:
        return True
    return False


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
                 marker: str = "Type Cover", poll: float = 2.0,
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
        target = self.log_path or LOG_PATH
        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
        except OSError:
            pass
        print(line, flush=True)

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
        env = dict(os.environ)
        scale = env.get("WVKBD_SCALE") or env.get("SURFACE_OSK_SCALE") \
            or str(detect_scale())
        env["WVKBD_SCALE"] = scale
        self._log(f"tablet mode: starting {self.osk_cmd} (WAYLAND_DISPLAY="
                  f"{env.get('WAYLAND_DISPLAY')} scale={scale})")
        self._proc = subprocess.Popen(
            [self.osk_cmd, *self.args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

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
        _recover_wayland_env()
        self._log(f"started; OSK_CMD={self.osk_cmd} poll={self.poll}s "
                  f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')}")

        # `_want` = we want the OSK shown because the Type Cover is detached.
        # It is set True by a detach (remove uevent / truly-absent poll) and
        # initialised True when a keyboard is already shown; it is set False
        # ONLY by an attach (bind) uevent. Polling never clears it, so a
        # "stuck" lingering device (present while physically detached) does
        # not wrongly hide the keyboard.
        self._want = False
        self._fullscreen = detect_fullscreen()

        def sync() -> None:
            desired = self._want and not self._fullscreen
            if desired and not self._running():
                self._start()
            elif not desired and self._running():
                self._stop()

        if self._running():
            self._want = True  # already shown (detached) -> keep it
        elif not type_cover_attached(self.marker):
            self._want = True
            self._start()  # detached at boot -> show
        self._log(f"initial state: want={self._want} fullscreen={self._fullscreen}")
        sync()

        def monitor() -> None:
            # Match uevents on the Type Cover input devices. `bind`/`add` =>
            # attached (hide); `remove` => detached (show). udev events are
            # authoritative and fire even when the device lingers as a stale
            # entry. We match on the stable HID product id (045e:09c2) which
            # appears in the input-device uevent devpaths regardless of which
            # USB port the cover enumerates on.
            dev = _find_type_cover_usb()
            token = "045e:09c2"
            if dev:
                vid = _sysfs_read(dev, "idVendor")
                pid = _sysfs_read(dev, "idProduct")
                if vid and pid:
                    token = f"{vid}:{pid}".lower()

            def handle(action: str) -> None:
                if action in ("add", "bind"):
                    if self._want:
                        self._want = False
                        self._log("attached (bind): hiding")
                        sync()
                elif action == "remove":
                    if not self._want:
                        self._want = True
                        self._log("detached (remove): showing")
                        sync()

            try:
                proc = subprocess.Popen(
                    ["udevadm", "monitor", "--udev"],
                    stdout=subprocess.PIPE, text=True,
                    env=dict(os.environ),
                )
                pat = re.compile(r"^(KERNEL|UDEV)\s*\[\S+\]\s+(\w+)\s+(\S+)")
                for line in proc.stdout:
                    m = pat.match(line)
                    if not m:
                        continue
                    action, devpath = m.group(2), m.group(3)
                    if token in devpath.lower():
                        handle(action)
            except Exception as e:  # pragma: no cover
                self._log(f"udev monitor error: {e}")

        threading.Thread(target=monitor, daemon=True).start()

        while True:
            # Polling fallback: only *shows* on a truly-absent device (covers a
            # missed remove uevent); it never hides. Fullscreen is re-checked
            # every poll so the keyboard hides for videos and returns after.
            if not type_cover_attached(self.marker) and not self._want:
                self._want = True
                self._log("detached (poll): showing")
                sync()
            fs = detect_fullscreen()
            if fs != self._fullscreen:
                self._fullscreen = fs
                self._log(f"fullscreen change: {fs}")
            sync()
            time.sleep(self.poll)


def launch_keyboard(osk_cmd: Optional[str] = None,
                    args: Optional[List[str]] = None,
                    log_path: Optional[str] = None) -> None:
    """Force-launch the OSK (manual fallback when auto-detect is stuck)."""
    cmd = osk_cmd or find_osk()
    if not cmd:
        return
    _recover_wayland_env()
    env = dict(os.environ)
    scale = env.get("WVKBD_SCALE") or env.get("SURFACE_OSK_SCALE") \
        or str(detect_scale())
    env["WVKBD_SCALE"] = scale
    a = args if args is not None else list(OSK_DEFAULT_ARGS)
    subprocess.Popen([cmd, *a], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     env=env, start_new_session=True)


def hide_keyboard(osk_cmd: Optional[str] = None) -> None:
    """Force-hide the OSK (manual fallback)."""
    cmd = osk_cmd or find_osk()
    if not cmd:
        return
    subprocess.run(["pkill", "-f", cmd], check=False)


def osk_toggle(osk_cmd: Optional[str] = None,
               args: Optional[List[str]] = None) -> str:
    """Toggle the OSK; returns 'shown' or 'hidden'."""
    cmd = osk_cmd or find_osk()
    if not cmd:
        return "no-osk"
    if shutil.which("pgrep") and subprocess.run(
            ["pgrep", "-f", cmd], capture_output=True).returncode == 0:
        hide_keyboard(cmd)
        return "hidden"
    launch_keyboard(cmd, args)
    return "shown"
