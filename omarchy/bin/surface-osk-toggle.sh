#!/bin/sh
# Toggle the on-screen keyboard. Used by the Omarchy bar widget.
RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XDG_RUNTIME_DIR=$RT
for d in "$RT"/hypr/*; do
    [ -e "$d" ] && export HYPRLAND_INSTANCE_SIGNATURE=$(basename "$d")
done
for s in "$RT"/wayland-*; do
    [ -e "$s" ] || continue
    case "$s" in *.lock) continue ;; esac
    export WAYLAND_DISPLAY=$(basename "$s")
done
export WVKBD_SCALE=$(hyprctl monitors 2>/dev/null | awk '/scale:/{print $2; exit}')
cd /home/oz/Work/surface-kernel-fix
exec python -m surface_fix.cli osk toggle
