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
# `--auto` makes wvkbd show only when a text field is focused (real tablet
# tap-to-type behaviour) via the input-method protocol; the daemon still
# stops it entirely when the physical Type Cover is attached.
# Override with the SURFACE_OSK_ARGS environment variable (space separated).
OSK_DEFAULT_ARGS: List[str] = ["-L", "300", "--fn", "Noto Sans 18", "--auto"]


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

        # `_want` = the OSK process should be running (Type Cover detached).
        # wvkbd itself (with --auto) then shows only when a text field is
        # focused, giving real tablet tap-to-type behaviour. A `bind` uevent
        # (physical keyboard attached) stops it; `remove` (detached) starts it.
        self._want = False

        def sync() -> None:
            if self._want and not self._running():
                self._start()
            elif not self._want and self._running():
                self._stop()

        # Start enabled only if the Type Cover is not present at boot; a
        # `bind` uevent later disables it, a `remove` enables it. `--auto`
        # keeps it hidden until a text field is actually focused.
        self._want = not type_cover_attached(self.marker)
        sync()

        def monitor() -> None:
            # React immediately to Type Cover uevents. Match both the USB port
            # (covers the USB-device-level bind/remove that fires on
            # attach/detach) and the stable HID product id (covers input-device
            # uevents / re-enumeration on a different port).
            dev = _find_type_cover_usb()
            tokens = ["1-7"]
            if dev:
                tokens.append(os.path.basename(dev).lower())
                vid = _sysfs_read(dev, "idVendor")
                pid = _sysfs_read(dev, "idProduct")
                if vid and pid:
                    tokens.append(f"{vid}:{pid}".lower())

            def handle(action: str) -> None:
                if action in ("add", "bind"):
                    if self._want:
                        self._want = False
                        self._log("attached (bind): stopping OSK")
                        sync()
                elif action == "remove":
                    if not self._want:
                        self._want = True
                        self._log("detached (remove): starting OSK")
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
                    if action in ("add", "bind", "remove") and \
                            any(t in devpath.lower() for t in tokens):
                        handle(action)
            except Exception as e:  # pragma: no cover
                self._log(f"udev monitor error: {e}")

        threading.Thread(target=monitor, daemon=True).start()

        while True:
            # Fallback: if the device is truly absent, ensure the OSK is
            # enabled. We never disable from polling (only a bind uevent does)
            # so a lingering stale device cannot wrongly suppress the keyboard.
            if not type_cover_attached(self.marker) and not self._want:
                self._want = True
                self._log("detached (poll): starting OSK")
                sync()
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
