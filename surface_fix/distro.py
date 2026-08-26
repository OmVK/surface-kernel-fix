"""Distribution abstractions: package managers, linux-surface repo setup."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List

from .detect import Distro


def _sudo(args: List[str]) -> int:
    """Run a command, prepending sudo when not already root."""
    if os.geteuid() != 0:
        args = ["sudo", *args]
    return subprocess.run(args, check=False).returncode


class PackageManager:
    """Installs packages and the linux-surface repository per distro."""

    def __init__(self, distro: Distro) -> None:
        self.distro = distro

    # --- public API ---------------------------------------------------------
    def setup_surface_repo(self) -> None:
        """Add the linux-surface package repository for this distro."""
        if self.distro == Distro.ARCH:
            self._setup_arch()
        elif self.distro == Distro.FEDORA:
            self._setup_fedora()
        elif self.distro == Distro.DEBIAN:
            self._setup_debian()
        else:
            raise NotImplementedError(f"No surface repo known for {self.distro}")

    def install(self, packages: List[str]) -> None:
        if self.distro == Distro.ARCH:
            _sudo(["pacman", "-S", "--noconfirm", *packages])
        elif self.distro == Distro.FEDORA:
            _sudo(["dnf", "-y", "install", *packages])
        elif self.distro == Distro.DEBIAN:
            _sudo(["apt-get", "update"])
            _sudo(["apt-get", "install", "-y", *packages])
        else:
            raise NotImplementedError(f"No installer for {self.distro}")

    def install_surface_kernel(self) -> None:
        """Install the patched Surface kernel (+ headers)."""
        self.setup_surface_repo()
        if self.distro == Distro.ARCH:
            self.install(["linux-surface", "linux-surface-headers"])
        elif self.distro == Distro.FEDORA:
            self.install(["linux-surface"])
        elif self.distro == Distro.DEBIAN:
            self.install(["linux-surface", "linux-surface-headers"])

    def install_input_stack(self) -> None:
        """Install touch/rotation userspace (IPTS daemon + sensor proxy)."""
        if self.distro == Distro.ARCH:
            self.install(["iptsd", "surface-ipts-firmware", "iio-sensor-proxy"])
        elif self.distro == Distro.FEDORA:
            self.install(["iptsd", "iio-sensor-proxy"])
        elif self.distro == Distro.DEBIAN:
            self.install(["iptsd", "iio-sensor-proxy"])

    def install_osk(self) -> None:
        """Install an on-screen keyboard suitable for tablet mode.

        ``wvkbd`` is the preferred Wayland OSK (``wvkbd-deskintl`` gives a full
        keyboard with Ctrl/Alt/Super on the main rows). On Arch it lives in the
        AUR, so we fall back to an AUR helper when the repo package is missing.
        """
        candidates = {
            Distro.ARCH: ["wvkbd"],
            Distro.FEDORA: ["wvkbd"],
            Distro.DEBIAN: ["wvkbd"],
        }.get(self.distro, ["wvkbd"])
        try:
            self.install(candidates)
        except NotImplementedError:
            pass
        if not (shutil.which("wvkbd") or shutil.which("wvkbd-deskintl")):
            if self.distro == Distro.ARCH:
                for helper in ("yay", "paru"):
                    if shutil.which(helper):
                        subprocess.run([helper, "-S", "--noconfirm", "wvkbd"],
                                       check=False)
                        break
                else:
                    print("-> wvkbd not found. On Arch it is in the AUR; install "
                          "it with: yay -S wvkbd  (then rebuild for deskintl).")
            else:
                print(f"-> Could not install an OSK for {self.distro}. "
                      "Please install 'wvkbd' manually.")

    # --- repo wiring --------------------------------------------------------
    def _setup_arch(self) -> None:
        conf = "/etc/pacman.conf"
        if "[linux-surface]" in _read(conf):
            return
        keyring = (
            "curl -s https://raw.githubusercontent.com/linux-surface/linux-surface/"
            "master/pkg/keys/surface.asc | sudo pacman-key --add - && "
            "sudo pacman-key --lsign-key 56C464BAAC421453"
        )
        print("-> Adding linux-surface keyring (run manually if prompted):")
        print("   ", keyring)
        repo = (
            "\n[linux-surface]\n"
            "Server = https://pkg.surfacelinux.com/arch/\n"
        )
        _sudo(["bash", "-c", f"echo '{repo}' >> {conf}"])
        _sudo(["pacman", "-Sy"])

    def _setup_fedora(self) -> None:
        # Official linux-surface COPR.
        _sudo(["dnf", "-y", "copr", "enable", "okuno/linux-surface"])
        _sudo(["dnf", "-y", "update"])

    def _setup_debian(self) -> None:
        # Debian/Ubuntu apt repository from linux-surface.
        _sudo(["apt-get", "install", "-y", "wget", "gnupg"])
        _sudo(["wget", "-qO", "/tmp/surface.asc",
               "https://raw.githubusercontent.com/linux-surface/linux-surface/"
               "master/pkg/keys/surface.asc"])
        _sudo(["bash", "-c",
               "install -d /etc/apt/keyrings && "
               "gpg --dearmor < /tmp/surface.asc > /etc/apt/keyrings/surface.gpg"])
        list_line = (
            "deb [arch=amd64 signed-by=/etc/apt/keyrings/surface.gpg] "
            "https://pkg.surfacelinux.com/debian/ debian main\n"
        )
        _sudo(["bash", "-c",
               f"echo '{list_line}' > /etc/apt/sources.list.d/linux-surface.list"])
        _sudo(["apt-get", "update"])


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def _sudo_run(args: List[str]) -> int:
    return _sudo(args)
