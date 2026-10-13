#!/usr/bin/env bash
# Root installer for surface-kernel-fix on Omarchy (Surface Pro 6).
# Run with: sudo ./install-system.sh  (from the repo root)
#
# The upstream `surface-fix setup` command is not used for the system half:
# its Limine backend mis-reads /boot (root-only) and its Arch key/repo steps
# are incomplete. This script does the same work the Omarchy-native way.
set -euo pipefail

REPO="https://pkg.surfacelinux.com/arch/"
SURFACE_KEY="56C464BAAC421453"
KEY_URL="https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc"
AUR_USER="${SUDO_USER:-oz}"

echo "== 1/6 Trust the linux-surface package signing key =="
curl -fsSL "$KEY_URL" | pacman-key --add -
pacman-key --lsign-key "$SURFACE_KEY"

echo "== 2/6 Add the linux-surface repository =="
if ! grep -q '^\[linux-surface\]' /etc/pacman.conf; then
  cat >> /etc/pacman.conf <<'EOF'

[linux-surface]
Server = https://pkg.surfacelinux.com/arch/
EOF
fi
pacman -Syu --noconfirm

echo "== 3/6 Install kernel + IPTS touch stack =="
pacman -S --noconfirm --needed \
  linux-surface linux-surface-headers \
  iptsd surface-ipts-firmware iio-sensor-proxy

echo "== 4/6 Enable the touch daemon =="
systemctl enable --now iptsd.service 2>/dev/null \
  || systemctl enable --now iptsd-surface.service 2>/dev/null \
  || echo "   (iptsd unit not active yet; it starts once the Surface kernel boots)"
systemctl enable --now iio-sensor-proxy.service 2>/dev/null || true

echo "== 5/6 Limine: surface kernel first + default entry =="
# Order the generated boot menu so the Surface kernel comes first.
LIMIT_TMP="$(mktemp)"
if [ -f /etc/default/limine ]; then
  grep -v '^BOOT_ORDER=' /etc/default/limine > "$LIMIT_TMP" || true
fi
printf 'BOOT_ORDER="linux-surface, *, *fallback, Snapshots"\n' >> "$LIMIT_TMP"
install -m 644 "$LIMIT_TMP" /etc/default/limine
rm -f "$LIMIT_TMP"

limine-mkinitcpio

# Point Limine's default_entry at the linux-surface entry (path form).
python3 - <<'PY'
import re

path = "/boot/limine.conf"
with open(path, encoding="utf-8") as fh:
    lines = fh.read().splitlines()

# Resolve the full entry path of the linux-surface entry (handles nesting).
stack = []          # (indent, name)
target = None
for ln in lines:
    if ln.strip().startswith("//"):
        continue
    m = re.match(r"^(\s*)/\+?(.*\S)\s*$", ln)
    if not m:
        continue
    indent = len(m.group(1))
    name = m.group(2)
    while stack and stack[-1][0] >= indent:
        stack.pop()
    full = "/".join([p[1] for p in stack] + [name])
    if "linux-surface" in name:
        target = full
        break
    stack.append((indent, name))

if not target:
    print("WARNING: no linux-surface entry in /boot/limine.conf yet;")
    print("         BOOT_ORDER already puts it first, leaving default_entry alone")
    raise SystemExit(0)

out, replaced = [], False
for ln in lines:
    if re.match(r"^\s*default_entry\s*:", ln):
        out.append(f"default_entry: {target}")
        replaced = True
    else:
        out.append(ln)
if not replaced:
    out.insert(0, f"default_entry: {target}")

with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
print(f"   default_entry -> {target}")
PY

echo "   current default_entry / first entries:"
grep -nE '^\s*default_entry\s*:' /boot/limine.conf || true
grep -nE '^\s*/' /boot/limine.conf | head -10 || true
limine-list 2>/dev/null || true

echo "== 6/6 On-screen keyboard (AUR: wvkbd-deskintl) =="
pacman -S --noconfirm --needed base-devel git wayland pango cairo fontconfig libxkbcommon scdoc
BUILD_DIR="$(mktemp -d /tmp/wvkbd-build.XXXXXX)"
chown "$AUR_USER:$AUR_USER" "$BUILD_DIR"
sudo -u "$AUR_USER" -H git clone https://aur.archlinux.org/wvkbd-deskintl.git "$BUILD_DIR/wvkbd-deskintl"
(
  cd "$BUILD_DIR/wvkbd-deskintl"
  sudo -u "$AUR_USER" -H makepkg -s --noconfirm --needed
)
pacman -U --noconfirm "$BUILD_DIR"/wvkbd-deskintl/*.pkg.tar.zst
rm -rf "$BUILD_DIR"
command -v wvkbd-deskintl

echo
echo "Done. Reboot to boot linux-surface (IPTS touch/pen active after reboot)."
echo "Verify afterwards: surface-fix status   (and: ls /dev/ipts)"
