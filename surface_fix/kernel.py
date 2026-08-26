"""Install the linux-surface kernel and make it the default boot entry."""

from __future__ import annotations

from .bootloader import get_backend
from .detect import Environment
from .distro import PackageManager


def install_surface_kernel(env: Environment) -> None:
    pm = PackageManager(env.distro)
    pm.install_surface_kernel()
    print("[kernel] linux-surface installed")


def make_surface_default(env: Environment) -> None:
    backend = get_backend(env.bootloader)
    backend.set_surface_default()
    print("[kernel] surface kernel set as default boot entry")


def setup_kernel(env: Environment) -> None:
    install_surface_kernel(env)
    make_surface_default(env)
