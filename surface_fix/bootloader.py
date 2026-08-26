"""Set the default boot entry to the installed linux-surface kernel.

Each backend knows how to point its bootloader at the Surface kernel so it
boots first without manual menu interaction.
"""

from __future__ import annotations

import re
import subprocess
from typing import List

from .detect import Bootloader, Distro


def _sudo(args: List[str]) -> int:
    import os
    if os.geteuid() != 0:
        args = ["sudo", *args]
    return subprocess.run(args, check=False).returncode


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def _write(path: str, content: str) -> None:
    _sudo(["bash", "-c", f"cat > '{path}' <<'EOF'\n{content}\nEOF"])


class BootloaderBackend:
    name = "base"

    def set_surface_default(self) -> None:
        raise NotImplementedError


class LimineBackend(BootloaderBackend):
    name = "limine"

    def __init__(self, config_path: str = "/boot/limine.conf") -> None:
        self.config_path = config_path

    def _surface_entry_path(self) -> str:
        """Find the menu path of the linux-surface entry (e.g. 'Omarchy/linux-surface')."""
        text = _read(self.config_path)
        # Match a leaf entry whose comment/kernel-id marks it as the surface kernel.
        current_bundle = ""
        for line in text.splitlines():
            m = re.match(r"\s*/\+?(.*)", line)
            if m and not line.strip().startswith("//"):
                current_bundle = m.group(1).strip()
                continue
            if "kernel-id=surface" in line or "linux-surface" in line:
                # The preceding bundle (if any) forms the path prefix.
                leaf = "linux-surface"
                return f"{current_bundle}/{leaf}" if current_bundle else leaf
        return "linux-surface"

    def set_surface_default(self) -> None:
        path = self._surface_entry_path()
        text = _read(self.config_path)
        new_lines = []
        replaced = False
        for line in text.splitlines():
            if re.match(r"\s*default_entry\s*:", line):
                new_lines.append(f"default_entry: {path}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.insert(0, f"default_entry: {path}")
        _write(self.config_path, "\n".join(new_lines))
        print(f"[limine] default_entry set to '{path}'")


class GrubBackend(BootloaderBackend):
    name = "grub"

    def set_surface_default(self) -> None:
        # GRUB menuentry title for the Surface kernel (varies by distro).
        title = self._find_surface_menuentry()
        if title:
            _sudo(["grub-set-default", title])
            print(f"[grub] default set to menuentry '{title}'")
        # Regenerate config so the default persists.
        _sudo(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        print("[grub] regenerated grub.cfg")

    def _find_surface_menuentry(self) -> str:
        out = subprocess.run(
            ["grep", "-i", "surface", "/boot/grub/grub.cfg"],
            capture_output=True, text=True, check=False,
        ).stdout
        m = re.search(r"menuentry '([^']*surface[^']*)'", out)
        return m.group(1) if m else ""


class SystemdBootBackend(BootloaderBackend):
    name = "systemd-boot"

    def __init__(self, loader_conf: str = "/boot/loader/loader.conf") -> None:
        self.loader_conf = loader_conf

    def set_surface_default(self) -> None:
        # The Surface entry is the .efi whose title mentions surface.
        entries_dir = "/boot/loader/entries"
        import glob
        surface_entry = None
        for ef in glob.glob(f"{entries_dir}/*.conf"):
            if "surface" in _read(ef).lower():
                surface_entry = ef.split("/")[-1]
                break
        if not surface_entry:
            print("[systemd-boot] no surface entry found")
            return
        text = _read(self.loader_conf)
        new_lines = []
        replaced = False
        for line in text.splitlines():
            if re.match(r"\s*default\s", line, re.IGNORECASE):
                new_lines.append(f"default {surface_entry}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"default {surface_entry}")
        _write(self.loader_conf, "\n".join(new_lines))
        print(f"[systemd-boot] default set to '{surface_entry}'")


def get_backend(bootloader: Bootloader) -> BootloaderBackend:
    if bootloader == Bootloader.LIMINE:
        return LimineBackend()
    if bootloader == Bootloader.GRUB:
        return GrubBackend()
    if bootloader == Bootloader.SYSTEMD_BOOT:
        return SystemdBootBackend()
    raise NotImplementedError(f"No bootloader backend for {bootloader}")
