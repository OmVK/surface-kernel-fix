# surface-kernel-fix

A **cross-distro** tool that sets up a Microsoft Surface (and similar IPTS
tablets/laptops) on Linux the way we validated on a Surface laptop:

1. **Surface kernel as default** — installs the patched `linux-surface` kernel
   and makes it the first boot entry (per-bootloader).
2. **Touch / pen** — installs and starts the `iptsd` IPTS daemon + firmware and
   `iio-sensor-proxy`.
3. **Auto-rotation** — a daemon that reads the accelerometer and rotates the
   display to match its physical tilt.
4. **Touch alignment** — rotates the touch input together with the display so
   taps land where you touch.

## Supported targets

| Layer         | Supported                                          |
|---------------|----------------------------------------------------|
| Distros       | Arch (incl. Omarchy/Manjaro), Fedora, Debian/Ubuntu |
| Compositors   | Hyprland (manual), GNOME & KDE (native auto-rotate) |
| Bootloaders   | Limine, GRUB, systemd-boot                          |

The compositor/display/bootloader are all **auto-detected**; the right backend
is selected at runtime.

## Install

```bash
pip install -e .            # or: python -m build && pip install dist/*
sudo surface-fix setup     # installs kernel + enables rotation service
```

`setup` detects your environment, adds the `linux-surface` repository for your
distro, installs the kernel and input stack, makes the Surface kernel the
default boot entry, and installs a `surface-fix.service` user unit that runs
the rotation daemon on login.

## Usage

```bash
surface-fix status    # show detected environment + current orientation
surface-fix rotate    # run the rotation daemon in the foreground (Ctrl-C to stop)
surface-fix setup     # full install (see above)
```

After `setup`, **reboot** — the Surface kernel boots by default and the
rotation daemon starts automatically.

## How it works

```
detect  -> distro, bootloader, compositor, display server
kernel   -> distro package backend (pacman/dnf/apt) + bootloader backend
sensor   -> reads accel_3d IIO device, maps dominant gravity axis to orientation
rotate  -> daemon polls orientation and calls the compositor backend
backends-> Hyprland: hyprctl eval hl.monitor + hl.device (display + touch)
           GNOME/KDE: enable the DE's native auto-rotation (iio-sensor-proxy)
```

The orientation logic (dominant-axis with a hysteresis threshold) is the same
one proven on the Surface laptop and does not depend on `monitor-sensor`
change-events, so it reacts reliably even when the device is only tilted
(partly upright) rather than perfectly flat.

## Extending

* New distro: add repo wiring in `surface_fix/distro.py` + a package-manager
  branch.
* New compositor: add a backend under `surface_fix/backends/` implementing
  `apply_rotation` / `apply_touch_transform` (or set `mode = "native"`).
* New bootloader: add a backend in `surface_fix/bootloader.py`.
