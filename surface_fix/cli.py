"""Command-line interface for surface-fix."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List

from .detect import detect_environment
from .kernel import setup_kernel
from .rotate import RotationDaemon
from .sensor import SysfsOrientation, ensure_input_stack
from .backends import get_backend
from .osk import OskDaemon, find_osk, type_cover_attached


SYSTEMD_UNIT = """\
[Unit]
Description=Surface auto-rotation daemon (surface-fix)
After=graphical-session.target

[Service]
Type=simple
ExecStart={bin} rotate
Restart=always
RestartSec=2

[Install]
WantedBy=graphical-session.target
"""

SYSTEMD_OSK_UNIT = """\
[Unit]
Description=Surface on-screen keyboard (auto-show when Type Cover detached)
After=graphical-session.target

[Service]
Type=simple
ExecStart={bin} osk run
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical-session.target
"""


def _write_user_service(bin_path: str) -> None:
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(unit_dir, exist_ok=True)
    unit_path = os.path.join(unit_dir, "surface-fix.service")
    with open(unit_path, "w", encoding="utf-8") as fh:
        fh.write(SYSTEMD_UNIT.format(bin=bin_path))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "surface-fix.service"], check=False)
    print(f"[setup] installed + enabled user service {unit_path}")


def _write_osk_service(bin_path: str) -> None:
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(unit_dir, exist_ok=True)
    unit_path = os.path.join(unit_dir, "surface-osk.service")
    with open(unit_path, "w", encoding="utf-8") as fh:
        fh.write(SYSTEMD_OSK_UNIT.format(bin=bin_path))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "surface-osk.service"], check=False)
    print(f"[osk] installed + enabled user service {unit_path}")


def cmd_setup(args: argparse.Namespace) -> int:
    env = detect_environment()
    print(f"[setup] detected: {env.describe()}")
    if env.distro.value == "unknown":
        print("[setup] ERROR: unsupported/unknown distro.", file=sys.stderr)
        return 2
    if env.bootloader.value == "unknown":
        print("[setup] WARNING: unknown bootloader; kernel may not be defaulted.",
              file=sys.stderr)

    setup_kernel(env)
    print("[setup] installing touch/rotation userspace (iptsd, iio-sensor-proxy)...")
    from .distro import PackageManager
    PackageManager(env.distro).install_input_stack()
    ensure_input_stack()
    print("[setup] touch daemon enabled.")

    bin_path = os.path.abspath(sys.argv[0])
    _write_user_service(bin_path)
    print("[setup] done. Reboot to boot the Surface kernel with auto-rotation.")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    env = detect_environment()
    backend = get_backend(env.compositor)
    daemon = RotationDaemon(backend, source=SysfsOrientation())
    try:
        daemon.run()
    except KeyboardInterrupt:
        print("\n[rotate] stopped.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    env = detect_environment()
    print(f"distro:     {env.distro.value}")
    print(f"bootloader: {env.bootloader.value}")
    print(f"compositor: {env.compositor.value} ({env.display_server})")
    backend = get_backend(env.compositor)
    print(f"backend:    {backend.name} (mode={backend.mode})")
    src = SysfsOrientation()
    print(f"accel dev:  {src.device}")
    print(f"orientation:{src.orientation()}")
    if backend.mode == "manual":
        print(f"transform:  {backend.current_transform()}")
        if hasattr(backend, "touch_devices"):
            print(f"touch devs: {backend.touch_devices()}")
    print(f"osk:        {find_osk() or 'none (install wvkbd)'}")
    print(f"type cover: {'attached' if type_cover_attached() else 'detached -> OSK active'}")
    return 0


def cmd_osk(args: argparse.Namespace) -> int:
    from .distro import PackageManager
    if args.osk_command == "run":
        daemon = OskDaemon()
        try:
            daemon.run()
        except KeyboardInterrupt:
            print("\n[osk] stopped.")
        return 0
    if args.osk_command == "status":
        print(f"osk binary: {find_osk() or 'NONE (install wvkbd)'}")
        print(f"type cover: {'attached' if type_cover_attached() else 'detached -> OSK active'}")
        return 0
    if args.osk_command == "enable":
        env = detect_environment()
        print(f"[osk] installing on-screen keyboard for {env.distro.value}...")
        PackageManager(env.distro).install_osk()
        bin_path = os.path.abspath(sys.argv[0])
        _write_osk_service(bin_path)
        print("[osk] enabled. Detach the Type Cover to see the keyboard.")
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="surface-fix",
        description="Cross-distro Surface kernel, touch and auto-rotation helper.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Install Surface kernel + touch + enable rotation")
    sub.add_parser("rotate", help="Run the auto-rotation daemon in the foreground")
    sub.add_parser("status", help="Show detected environment and current state")

    osk_p = sub.add_parser("osk", help="On-screen keyboard for tablet mode")
    osk_sub = osk_p.add_subparsers(dest="osk_command", required=True)
    osk_sub.add_parser("run", help="Run the OSK daemon in the foreground (Ctrl-C to stop)")
    osk_sub.add_parser("status", help="Show OSK availability + Type Cover state")
    osk_sub.add_parser("enable", help="Install OSK + enable auto-show service")
    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "setup":
        return cmd_setup(args)
    if args.command == "rotate":
        return cmd_rotate(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "osk":
        return cmd_osk(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
