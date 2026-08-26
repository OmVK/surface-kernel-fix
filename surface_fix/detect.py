"""Environment detection: distro, bootloader, compositor, display server."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum


class Distro(str, Enum):
    ARCH = "arch"
    FEDORA = "fedora"
    DEBIAN = "debian"  # also covers Ubuntu/Linux Mint
    UNKNOWN = "unknown"


class Bootloader(str, Enum):
    LIMINE = "limine"
    GRUB = "grub"
    SYSTEMD_BOOT = "systemd-boot"
    UNKNOWN = "unknown"


class Compositor(str, Enum):
    HYPRLAND = "hyprland"
    GNOME = "gnome"
    KDE = "kde"
    SWAY = "sway"
    OTHER = "other"


def detect_distro() -> Distro:
    """Identify the distribution family from /etc/os-release."""
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            data = fh.read()
    except FileNotFoundError:
        return Distro.UNKNOWN

    def field(name: str) -> str:
        m = re.search(rf'^{name}="?([^"\n]+)"?', data, re.MULTILINE)
        return m.group(1).lower() if m else ""

    id_val = field("ID")
    id_like = field("ID_LIKE")

    if id_val in ("arch", "archarm", "manjaro", "omarchy") or "arch" in id_like:
        return Distro.ARCH
    if id_val in ("fedora", "rhel", "centos", "nobara") or "fedora" in id_like:
        return Distro.FEDORA
    if id_val in ("debian", "ubuntu", "linuxmint", "pop") or "debian" in id_like:
        return Distro.DEBIAN
    return Distro.UNKNOWN


def detect_bootloader() -> Bootloader:
    """Best-effort detection of the active bootloader."""
    # Limine stores its config on the ESP; GRUB has grub-install/grub-set-default.
    if os.path.exists("/boot/limine.conf") or os.path.exists("/boot/EFI/BOOT/limine.cfg"):
        return Bootloader.LIMINE
    if os.path.exists("/boot/grub/grub.cfg") or os.path.exists("/etc/grub.d") or \
            _which("grub-set-default"):
        return Bootloader.GRUB
    if os.path.exists("/boot/loader/loader.conf") or os.path.exists("/efi/loader/loader.conf") \
            or os.path.exists("/boot/efi/loader/loader.conf"):
        return Bootloader.SYSTEMD_BOOT
    # Fallback: ask bootctl (readable without root) which bootloader is active.
    try:
        out = subprocess.run(["bootctl", "status"], capture_output=True,
                             text=True, check=False).stdout
        if "Limine" in out:
            return Bootloader.LIMINE
        if "systemd-boot" in out or "systemd_boot" in out:
            return Bootloader.SYSTEMD_BOOT
    except FileNotFoundError:
        pass
    return Bootloader.UNKNOWN


def detect_compositor() -> Compositor:
    """Detect the running Wayland compositor / desktop from the environment."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    session = (os.environ.get("DESKTOP_SESSION") or "").lower()
    if "hyprland" in desktop or "hyprland" in session:
        return Compositor.HYPRLAND
    if "gnome" in desktop or "gnome" in session:
        return Compositor.GNOME
    if "kde" in desktop or "plasma" in desktop:
        return Compositor.KDE
    if "sway" in desktop or "sway" in session:
        return Compositor.SWAY
    # Fall back to process scan.
    if _process_running("Hyprland"):
        return Compositor.HYPRLAND
    if _process_running("gnome-shell"):
        return Compositor.GNOME
    if _process_running("sway"):
        return Compositor.SWAY
    if _process_running("plasmashell") or _process_running("kwin"):
        return Compositor.KDE
    return Compositor.OTHER


def detect_display_server() -> str:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def _process_running(name: str) -> bool:
    import subprocess
    try:
        out = subprocess.run(
            ["pgrep", "-x", name], capture_output=True, text=True, check=False
        )
        return out.returncode == 0
    except FileNotFoundError:
        return False


@dataclass
class Environment:
    distro: Distro
    bootloader: Bootloader
    compositor: Compositor
    display_server: str

    def describe(self) -> str:
        return (
            f"distro={self.distro.value} bootloader={self.bootloader.value} "
            f"compositor={self.compositor.value} display={self.display_server}"
        )


def detect_environment() -> Environment:
    return Environment(
        distro=detect_distro(),
        bootloader=detect_bootloader(),
        compositor=detect_compositor(),
        display_server=detect_display_server(),
    )
