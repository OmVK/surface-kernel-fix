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
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="surface-fix",
        description="Cross-distro Surface kernel, touch and auto-rotation helper.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Install Surface kernel + touch + enable rotation")
    sub.add_parser("rotate", help="Run the auto-rotation daemon in the foreground")
    sub.add_parser("status", help="Show detected environment and current state")
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
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
