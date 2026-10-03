#!/usr/bin/env bash
# Read-only diagnostics. Run INSIDE the SteamOS guest before installing g13d.
set -u
printf 'OS\n'
cat /etc/os-release
printf '\nSession: %s\n' "${XDG_SESSION_TYPE:-unknown}"
printf '\nPython\n'
if command -v python3 >/dev/null; then
    python3 --version
    python3 - <<'PY'
import importlib.util
import sys
print('Meets Python >= 3.11:', sys.version_info >= (3, 11))
for module in ('venv', 'pip', 'usb', 'evdev', 'PySide6', 'PIL', 'tomli_w'):
    print(f'{module}:', bool(importlib.util.find_spec(module)))
PY
fi
printf '\nUSB\n'
if command -v lsusb >/dev/null; then lsusb -d 046d:c21c; fi
printf '\nVirtual input device\n'
ls -l /dev/uinput 2>/dev/null || true
[[ -w /dev/uinput ]] && echo 'uinput writable' || echo 'uinput NOT writable'
printf '\nIdentity and groups\n'
id
getent group plugdev || true
printf '\nUser service manager\n'
systemctl --user is-system-running || true
printf '\nSystem mount modes\n'
for target in / /home /etc; do
    findmnt -T "$target" -no TARGET,OPTIONS 2>/dev/null || true
done
printf '\nlibusb\n'
ldconfig -p 2>/dev/null | grep 'libusb-1.0' || true
