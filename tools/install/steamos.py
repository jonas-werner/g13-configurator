#!/usr/bin/env python3
"""Experimental SteamOS installer; invoked by install.sh, never as root."""
from __future__ import annotations

import argparse
import ctypes.util
import fcntl
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

MARKER = '# Managed by g13-linux experimental SteamOS installer'
REPO = Path(__file__).resolve().parents[2]
BASE = Path.home() / '.local/share/g13-linux/steamos'
CURRENT = BASE / 'current'
SERVICE = Path.home() / '.config/systemd/user/g13d.service'
LAUNCHER = Path.home() / '.local/bin/g13-gui-steamos'
DESKTOP = Path.home() / '.local/share/applications/g13-steamos.desktop'
RULE = Path('/etc/udev/rules.d/70-g13-steamos.rules')
MODULE = Path('/etc/modules-load.d/g13-steamos.conf')
RULE_TEXT = MARKER + '''
# Apply before systemd's seat/uaccess processing; no plugdev group required.
SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="c21c", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="misc", KERNEL=="uinput", MODE="0660", TAG+="uaccess"
'''


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def capture(args):
    result = subprocess.run([str(a) for a in args], text=True, capture_output=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def owned(path):
    return not path.is_symlink() and path.is_file() and MARKER in path.read_text()


def protect_existing():
    for path in (SERVICE, LAUNCHER, DESKTOP, RULE, MODULE):
        if (path.exists() or path.is_symlink()) and not owned(path):
            raise RuntimeError(f'Refusing to replace an existing unmanaged file: {path}')
    if CURRENT.exists() and not CURRENT.is_symlink():
        raise RuntimeError(f'Refusing to replace non-symlink {CURRENT}')


def atomic_text(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def point_current(runtime):
    temporary = BASE / 'current.new'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(runtime.name)
    os.replace(temporary, CURRENT)


def quoted(value, *, systemd=False):
    text = str(value).replace('\\', '\\\\').replace('"', '\\"')
    if systemd:
        text = text.replace('%', '%%').replace('$', '$$')
    return '"' + text + '"'


def preflight():
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    for executable in ('sudo', 'systemctl', 'udevadm', 'modprobe'):
        if not shutil.which(executable):
            raise RuntimeError(f'Missing host tool: {executable}')
    import venv  # noqa: F401
    import ensurepip  # noqa: F401
    try:
        import evdev  # noqa: F401
        version = importlib.metadata.version('evdev')
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise RuntimeError('SteamOS system Python lacks evdev. Run --diagnose and report the output; no system packages were changed.') from exc
    if tuple(int(n) for n in version.split('.')[:3]) < (1, 6, 1):
        raise RuntimeError(f'System evdev {version} is too old (need >=1.6.1).')
    if not ctypes.util.find_library('usb-1.0'):
        raise RuntimeError('System libusb-1.0 is missing.')
    run(['systemctl', '--user', 'show-environment'], stdout=subprocess.DEVNULL)
    protect_existing()
    if shutil.disk_usage(BASE).free < 2 * 1024**3:
        raise RuntimeError('At least 2 GiB free space is required on the installation filesystem.')
    print(f'Preflight passed: Python {sys.version.split()[0]}, system evdev {version}, libusb.', flush=True)
    return version


def refresh_rules():
    run(['sudo', 'udevadm', 'control', '--reload-rules'])
    run(['sudo', 'udevadm', 'trigger', '--subsystem-match=usb', '--attr-match=idVendor=046d', '--attr-match=idProduct=c21c'])
    run(['sudo', 'udevadm', 'trigger', '--subsystem-match=misc', '--sysname-match=uinput'])
    run(['sudo', 'udevadm', 'settle'])


def diagnose():
    print('G13 experimental SteamOS diagnostics (no profile contents or credentials)')
    print(Path('/etc/os-release').read_text())
    print('Python:', sys.version.split()[0])
    print('Session:', os.environ.get('XDG_SESSION_TYPE', 'unknown'))
    print('libusb:', ctypes.util.find_library('usb-1.0'))
    for package in ('evdev', 'PySide6', 'Pillow', 'pyusb', 'tomli-w'):
        try:
            print('System', package, importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError:
            print('System', package, 'not installed')
    print('uinput exists/writable:', Path('/dev/uinput').exists(), os.access('/dev/uinput', os.W_OK))
    print('Managed USB rule:', owned(RULE))
    print('Managed module rule:', owned(MODULE))
    print('Runtime:', CURRENT.resolve() if CURRENT.exists() else 'not installed')
    for command in (['systemctl', '--user', 'is-enabled', 'g13d'], ['systemctl', '--user', 'is-active', 'g13d']):
        print(' '.join(command), ':', capture(command)[1])
    python = CURRENT / 'bin/python'
    if python.exists():
        print('Installed dependency check:', capture([python, '-m', 'pip', 'check'])[1])
    for device in Path('/sys/bus/usb/devices').glob('*'):
        try:
            if (device/'idVendor').read_text().strip() == '046d' and (device/'idProduct').read_text().strip() == 'c21c':
                bus = int((device/'busnum').read_text())
                number = int((device/'devnum').read_text())
                node = Path(f'/dev/bus/usb/{bus:03d}/{number:03d}')
                print('G13:', node, 'read/write:', os.access(node, os.R_OK | os.W_OK))
        except (FileNotFoundError, NotADirectoryError):
            pass


def install():
    version = preflight()
    runtime = Path(tempfile.mkdtemp(prefix='runtime-', dir=BASE))
    previous = CURRENT.resolve() if CURRENT.exists() else None
    original = {p: (p.read_text(), p.stat().st_mode & 0o777) if p.exists() else None
                for p in (SERVICE, LAUNCHER, DESKTOP, RULE, MODULE)}
    activated = False
    root_changed = False
    try:
        run([sys.executable, '-m', 'venv', '--system-site-packages', runtime])
        constraint = runtime / 'constraints.txt'
        constraint.write_text(f'evdev=={version}\n')
        # Binary-only dependencies fail clearly rather than requiring headers/compiler.
        run([runtime/'bin/python', '-m', 'pip', 'install', '--no-cache-dir',
             '--only-binary=:all:', '--constraint', constraint, REPO])
        run([runtime/'bin/python', '-m', 'pip', 'check'])
        run([runtime/'bin/python', '-c',
             'import evdev, usb.backend.libusb1, PIL, tomli_w; from PySide6 import QtWidgets; '
             'assert usb.backend.libusb1.get_backend() is not None'])
        run(['sudo', '-v'])
        run(['sudo', 'modprobe', 'uinput'])
        root_changed = True
        for path, content in ((RULE, RULE_TEXT), (MODULE, MARKER+'\nuinput\n')):
            run(['sudo', 'install', '-d', '-m', '755', path.parent])
            run(['sudo', 'tee', path], input=content, text=True, stdout=subprocess.DEVNULL)
        refresh_rules()
        if not os.access('/dev/uinput', os.W_OK):
            raise RuntimeError('uinput is not writable. Run from the active SteamOS Desktop session and try again.')
        run([runtime/'bin/python', '-c',
             'from evdev import UInput; device=UInput(name="g13-install-check"); device.close()'])
        # Do not stop an existing working version until the new environment is ready.
        if owned(SERVICE):
            run(['systemctl', '--user', 'stop', 'g13d'])
        point_current(runtime)
        activated = True
        atomic_text(SERVICE, MARKER+'\n[Unit]\nDescription=G13 gameboard driver (experimental SteamOS)\n'
                    'After=graphical-session.target\n\n[Service]\nExecStart='+quoted(CURRENT/'bin/g13d', systemd=True)+
                    '\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n')
        # Shell quoting is deliberately separate from desktop/systemd quoting.
        import shlex
        atomic_text(LAUNCHER, '#!/bin/sh\n'+MARKER+'\nexec '+shlex.quote(str(CURRENT/'bin/g13-gui'))+' "$@"\n', 0o755)
        atomic_text(DESKTOP, MARKER+'\n[Desktop Entry]\nType=Application\nName=G13 Configurator (SteamOS experimental)\n'
                    'Exec='+quoted(LAUNCHER)+'\nTerminal=false\nCategories=Settings;HardwareSettings;\n')
        run(['systemctl', '--user', 'daemon-reload'])
        run(['systemctl', '--user', 'enable', '--now', 'g13d'])
        run(['systemctl', '--user', 'is-active', '--quiet', 'g13d'])
        print('Installed. Open G13 Configurator (SteamOS experimental) from the application menu.')
        print('The daemon waits for the G13 if it is disconnected. Profiles remain in ~/.config/g13-linux/profiles.')
        print('After a SteamOS update, rerun ./install.sh if Python or device access has changed.')
    except BaseException:
        if activated:
            subprocess.run(['systemctl', '--user', 'stop', 'g13d'])
            if original[SERVICE] is None:
                subprocess.run(['systemctl', '--user', 'disable', 'g13d'])
            if previous is not None:
                point_current(previous)
            else:
                CURRENT.unlink(missing_ok=True)
            for path in (SERVICE, LAUNCHER, DESKTOP):
                if original[path]:
                    atomic_text(path, *original[path])
                else:
                    path.unlink(missing_ok=True)
            subprocess.run(['systemctl', '--user', 'daemon-reload'])
            if previous is not None:
                subprocess.run(['systemctl', '--user', 'start', 'g13d'])
        if root_changed:
            for path in (RULE, MODULE):
                if original[path]:
                    subprocess.run(['sudo', 'tee', str(path)], input=original[path][0], text=True, stdout=subprocess.DEVNULL)
                else:
                    subprocess.run(['sudo', 'rm', '-f', str(path)])
            subprocess.run(['sudo', 'udevadm', 'control', '--reload-rules'])
        shutil.rmtree(runtime)
        raise
    if previous and previous.parent == BASE and previous.name.startswith('runtime-'):
        shutil.rmtree(previous)


def uninstall():
    protect_existing()
    if owned(SERVICE):
        run(['systemctl', '--user', 'disable', '--now', 'g13d'])
    for path in (SERVICE, LAUNCHER, DESKTOP):
        if owned(path):
            path.unlink()
    for path in (RULE, MODULE):
        if owned(path):
            run(['sudo', 'rm', str(path)])
    run(['systemctl', '--user', 'daemon-reload'])
    run(['sudo', 'udevadm', 'control', '--reload-rules'])
    CURRENT.unlink(missing_ok=True)
    for runtime in BASE.glob('runtime-*'):
        if runtime.is_dir() and not runtime.is_symlink():
            shutil.rmtree(runtime)
    print('Uninstalled. Profiles and artwork were preserved. Reconnect the G13 to refresh device permissions.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--diagnose', action='store_true')
    group.add_argument('--check', action='store_true', help='Check prerequisites without installing')
    group.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your normal desktop user; the installer uses sudo only for device setup.')
    if not any(line.strip() in ('ID=steamos', 'ID="steamos"') for line in Path('/etc/os-release').read_text().splitlines()):
        parser.error('This setup routine is only for ID=steamos.')
    if args.diagnose:
        diagnose()
        return
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE/'.installer.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.uninstall:
            uninstall()
        elif args.check:
            preflight()
        else:
            print('Experimental SteamOS installation; no pacman or read-only-root changes.', flush=True)
            install()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Installation stopped: {exc}\nRun ./install.sh --diagnose for details.', file=sys.stderr)
        sys.exit(1)
