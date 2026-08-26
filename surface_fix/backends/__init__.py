"""Compositor backend interface and factory."""

from __future__ import annotations

import subprocess
from typing import List, Optional

from ..detect import Compositor


class BaseBackend:
    #: ``manual`` backends apply rotation themselves; ``native`` ones let the
    #: desktop environment handle it (we only enable it).
    mode = "manual"
    name = "base"

    def apply_rotation(self, orientation: str, transform: int) -> None:
        raise NotImplementedError

    def apply_touch_transform(self, transform: int) -> None:
        """Align touch input. Default no-op (most DEs do this automatically)."""

    def current_transform(self) -> Optional[int]:
        return None

    def enable_native_rotation(self) -> None:
        """Ensure the DE's built-in auto-rotation is turned on."""


def get_backend(compositor: Compositor) -> BaseBackend:
    if compositor == Compositor.HYPRLAND:
        return hyprland.HyprlandBackend()
    if compositor == Compositor.GNOME:
        return gnome.GnomeBackend()
    if compositor == Compositor.KDE:
        return kde.KdeBackend()
    raise NotImplementedError(f"No backend for compositor {compositor}")


def _hyprctl(args: List[str], recover_sig: bool = True) -> str:
    """Run a hyprctl command, recovering HYPRLAND_INSTANCE_SIGNATURE if needed."""
    if recover_sig:
        import os
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            import glob
            runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            matches = sorted(glob.glob(f"{runtime}/hypr/*"), key=os.path.getmtime,
                             reverse=True)
            if matches:
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = matches[0].split("/")[-1]
    try:
        out = subprocess.run(["hyprctl", *args], capture_output=True, text=True,
                             check=False)
        return out.stdout
    except FileNotFoundError:
        return ""


# Submodules import BaseBackend/_hyprctl above, so import them last.
from . import gnome, hyprland, kde  # noqa: E402
