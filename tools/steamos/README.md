# SteamOS VM experiment

This lab builds a private VirtualBox VM from Valve's official recovery image.
It does not use a community Vagrant box. It is an experiment, not a claim of
SteamOS support or a replacement for testing on a real SteamOS device.

## Source and trust

- [Valve recovery instructions](https://help.steampowered.com/en/faqs/view/1b71-edf2-eb6d-2bb3)
- [Valve download page and license](https://store.steampowered.com/steamos/download/?ver=steamdeck)
- [Valve image directory](https://steamdeck-images.steamos.cloud/recovery/)
- Pinned image: `steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2`

The script downloads over HTTPS directly from Valve's image server. It records
an SHA-256 hash for reproducibility; a locally calculated hash alone is **not**
a publisher authenticity check. No independent publisher checksum/signature
has been established for this image. The image directory is linked through
Valve's own download flow. Review Valve's license before using the image.

All downloads, virtual disks and VM state live in the already ignored
`GITIGNORE-US/steamos-vm/` directory. Do not publish the OS image or a derived
box; distribute these setup scripts instead.

## Recovery boot test

Prerequisites: VirtualBox with its host driver working, curl, bzip2, and
roughly 25 GB free space for downloads, conversion and the recovery VM.

```sh
tools/steamos/prepare-vm.sh
VBoxManage startvm g13-steamos-lab --type gui
```

The VM has 8 GB RAM, 4 CPUs, EFI firmware, a VBoxSVGA display and NAT networking.
Its own recovery disk and a blank 16 GiB virtual scratch disk are attached. There are no host directory
shares, raw host disks, or automatic USB capture filters. The script refuses
to replace a VM with the same name.

This boots recovery media, not a fully installed SteamOS system. A successful
recovery boot can establish basic VM feasibility, but cannot establish update
persistence or Gaming Mode compatibility. Full installation should target a
separate blank **virtual** disk.

## G13 passthrough (after the guest boots)

The Linux host user needs VirtualBox USB access (`vboxusers`). Start with the
built-in USB 1.1 controller; no Oracle Extension Pack is installed by this lab.

Stop the host's G13 daemon before attaching the physical device to the guest,
otherwise it will compete with VirtualBox's USB ownership:

```sh
systemctl --user stop g13d
VBoxManage list usbhost
# Use the UUID for vendor 046d / product c21c only:
VBoxManage controlvm g13-steamos-lab usbattach G13_USB_UUID
```

After testing, detach the G13 and restore the host daemon:

```sh
VBoxManage controlvm g13-steamos-lab usbdetach G13_USB_UUID
systemctl --user start g13d
```

Check both raw USB and `/dev/uinput` permissions inside the guest. Test keys,
held/delayed shortcuts, profile switches, joystick, LCD and LEDs, then unplug
and reconnect. A desktop text editor suffices for basic input validation.
`check-guest.sh` collects read-only dependency, session and permission details;
run it inside the guest, not on the host.

## Vagrant follow-up

Vagrant consumes a prepared base box rather than installing this recovery
image directly. Once a full local guest is installed and SSH access is
configured, it can be packaged locally with `vagrant package --base VM_NAME`.
See [HashiCorp's packaging documentation](https://developer.hashicorp.com/vagrant/docs/cli/package).
Do not use a third-party `config.vm.box` URL as a shortcut. We have not yet
built or validated a Vagrant base box.

## Observed results (2026-10-03)

Tested Valve recovery build 20260707.10, SteamOS 3.8.14, kernel
6.16.12-valve24.4, Python 3.13.5, VirtualBox 7.0.26.

- The official recovery image boots in VirtualBox with EFI.
- **Use VBoxSVGA**, not VMSVGA: this image includes `vboxvideo` but lacks
  `vmwgfx`. With VBoxSVGA the Plasma Wayland desktop and configurator both run.
- A normal isolated venv install fails building `evdev` because Linux input
  headers are missing. Valve's image already includes `evdev` 1.9.0.
- `python3 -m venv --system-site-packages VENV` followed by `VENV/bin/pip
  install PROJECT` succeeds without pacman or installing development headers.
  This is an experimental workaround tied to the system Python/evdev versions,
  not a self-contained distribution that is guaranteed to survive upgrades.
- The recovery image's 2 GiB home partition fills during installation. Use the
  separate scratch disk for the venv and pip cache. On this VM it is formatted
  ext4, labelled `G13LAB`, and mounted at `/mnt/g13-lab`.
- All 71 project tests passed inside the SteamOS guest.
- The real Logitech G13 passed through using the built-in USB 1.1 controller.
  No Extension Pack was needed.
- The `deck` desktop user already had an ACL granting write access to
  `/dev/uinput`. `plugdev` did not exist.
- A guest-only `/etc/udev/rules.d/70-g13-lab.rules` with the following rule
  enabled unprivileged USB access after reloading/triggering udev:

  ```udev
  SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="c21c", MODE="0660", TAG+="uaccess"
  ```

- `g13d` ran as `deck`, opened the real device and served its profile API. The
  graphical configurator showed **Daemon connected** with loaded profiles.
  This exercised device initialization and LCD/backlight writes, but physical
  key-by-key input, visual LCD inspection and gameplay were not manually tested.
- USB ownership and the host daemon's previous active profile were restored
  after the experiment. The test VM was then shut down.

The initial lab did not change the host installation. The subsequent experimental
installer described below adds SteamOS dispatch to `install.sh`.
Gaming Mode, suspend/resume, a full SteamOS installation, update persistence,
Flatpak packaging, and Vagrant import remain untested.

### Resuming this local VM

The created VM has a localhost-only SSH forward at port 22226. A dedicated
private test key and host-key record are in `GITIGNORE-US/steamos-vm/`; they
are not included in source control. After starting the VM:

```sh
ssh -i GITIGNORE-US/steamos-vm/lab.key -p 22226 \
  -o UserKnownHostsFile=GITIGNORE-US/steamos-vm/known_hosts deck@127.0.0.1
```

The installed environment is `/mnt/g13-lab/venv`, and the copied source and tests
are `/home/deck/g13-test`. To open the GUI in the guest's desktop session:

```sh
systemd-run --user --unit=g13-lab-gui --collect /mnt/g13-lab/venv/bin/g13-gui
```

After attaching the G13 as above, start its guest daemon with:

```sh
systemd-run --user --unit=g13-lab-daemon --collect /mnt/g13-lab/venv/bin/g13d
```

Stop the guest daemon before returning USB ownership to the host.

## Installer trial (2026-10-03)

The experimental installer is documented in [docs/steamos.md](../../docs/steamos.md).
A second VM, `g13-steamos-installer-test`, was created from the untouched official
image rather than reusing the manually prepared environment. The preparation
script accepts `G13_LAB_DIR` and `G13_VM_NAME` for separate lab instances.

Recovery-only preparation: enabled SSH on loopback port 22227, copied the project
source, and formatted the VM's blank 16 GiB scratch disk as ext4, label
`G13INSTALL`. It is mounted through guest fstab at
`/home/deck/.local/share/g13-linux/steamos` and owned by `deck`. No dependency or
G13 permission fixes were performed before running `./install.sh`.

Verified in the fresh VM:

- Preflight and installation with system evdev 1.9.0, binary Qt/Pillow dependencies,
  no compiler, no pacman and no read-only-root toggle.
- Reinstall replaces the runtime while preserving profile file hashes.
- Uninstall removes service enablement, launcher, runtime and managed device
  files while preserving profile file hashes; installation then succeeds again.
- The service and runtime mount survive a guest reboot.
- Forced dependency failure (`PIP_NO_INDEX=1`) during reinstall leaves the previous
  runtime and running service intact, without abandoned staging environments.
- All 78 project tests pass, including installer rollback/conflict tests.
- Physical G13 passthrough works with the installed service and its device rules.
  The GUI shows **Daemon connected**, the profile API responds, and initialization
  exercises LCD/backlight writes. The host daemon and previous active profile
  were restored afterward.

Screenshots and detailed logs are kept locally in ignored
`GITIGNORE-US/steamos-installer-test/`. These checks do not establish physical
key-by-key/gameplay behavior, Gaming Mode, suspend/resume or OS-update persistence.

Build a shareable application-source trial archive with:

```sh
bash tools/steamos/package-trial.sh
```

This creates `dist/g13-linux-steamos-experimental.tar.gz` and its SHA-256 file.
It includes setup instructions and source, but no VM images, SSH keys or lab logs.
It requires internet access when installing dependencies; it is not an offline
bundle or a Flatpak. Publishing a GitHub release is a separate step.
