# Experimental SteamOS setup

This installer is ready for volunteer testing. It has been exercised in a
VirtualBox VM booted from Valve's official SteamOS 3.8.14 recovery image.
It is not yet verified on a Steam Deck or a fully installed SteamOS system.

## Install

Switch to Desktop Mode and open Konsole. Download and extract the
[latest source archive](https://github.com/jonas-werner/g13-configurator/archive/refs/heads/main.tar.gz),
or update an existing checkout with `git pull --ff-only`. Open a terminal in
the extracted or checked-out project folder and run:

```sh
./install.sh
```

Run as your normal desktop user, not with `sudo`. The installer asks for sudo
when configuring device access. Your account needs a sudo password; if it has
none, set one with `passwd` first. Internet access and at least 2 GiB free on
your home filesystem are required, including when reinstalling.

Open **G13 Configurator (SteamOS experimental)** from the application menu.
The background service starts automatically at login and waits for the G13
when disconnected. You can also launch the GUI with:

```sh
~/.local/bin/g13-gui-steamos
```

The same `install.sh` detects `ID=steamos` in `/etc/os-release`. Other Linux
distributions retain the existing installation procedure. This is a native
installation, not a Flatpak, and does not require a GitHub release to build.

## What it changes

- Installs the app and its Python dependencies under
  `~/.local/share/g13-linux/steamos/`, reusing SteamOS's existing `evdev`.
- Creates a user service, application-menu entry, and launcher.
- Adds `/etc/udev/rules.d/70-g13-steamos.rules` for active-session access to the
  G13 and `/dev/uinput`, plus `/etc/modules-load.d/g13-steamos.conf` to load
  `uinput` at boot. It does not require a `plugdev` group.

It does not run pacman or disable the read-only filesystem. If SteamOS lacks
the expected system Python, evdev or libusb, it stops with an error. It also
refuses to overwrite an existing service or setup file it does not own.

Profiles and artwork remain under `~/.config/g13-linux/`. Reinstallation stages
the new environment before replacing the old one. Keep the extracted source
folder for diagnostics, reinstalling, and removal.

SteamOS updates can change system Python or device rules. If the app stops
working after an update, rerun `./install.sh`. Update persistence is not yet
verified; this installation is not independent of SteamOS's Python packages.

## Troubleshooting and removal

From the extracted project folder:

```sh
./install.sh --check
./install.sh --diagnose > steamos-diagnostics.txt
systemctl --user status g13d --no-pager
journalctl --user -u g13d -n 50 --no-pager
```

Diagnostics report OS/dependency versions, service state and device access,
without reading profile contents or credentials. Review output before sharing
it. If device access fails, reconnect the G13 and run the installer from the
active Desktop Mode session. Include your SteamOS version and whether the
problem occurs in Desktop Mode or Gaming Mode when reporting a problem.

To remove this experimental installation:

```sh
./install.sh --uninstall
```

Removal preserves profiles and artwork. Reconnect the G13 or reboot afterward
to refresh device permissions. It does not remove unrelated installations.

## Testing status

The VM uses Valve's recovery build `20260707.10`, Python 3.13.5 and system
evdev 1.9.0. Recovery media has a small home partition, so the VM has a separate
blank virtual disk mounted at the installer's runtime directory for space.
This storage accommodation is only for the recovery VM.

The lab can verify dependency installation, service management, GUI startup
and USB access. Physical button-by-button behavior and gameplay require a
person with the device. Gaming Mode, suspend/resume and SteamOS system updates
still need testing on a real installation. See the
[VM lab notes](../tools/steamos/README.md) for reproducibility and results.

For a first volunteer test, try installation in Desktop Mode, opening the GUI,
assigning a key, holding/releasing a shortcut, profile switching and the LCD.
Then try unplug/replug and reboot. Test Gaming Mode separately and report its
results as such; VM success does not establish Gaming Mode compatibility.
