#!/usr/bin/env bash
# Build a local VirtualBox recovery VM from Valve's image, not a third-party box.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAB="${G13_LAB_DIR:-$ROOT/GITIGNORE-US/steamos-vm}"
IMAGE=steamdeck-oobe-repair-20260707.10-3.8.14.img
URL="https://steamdeck-images.steamos.cloud/recovery/$IMAGE.bz2"
VM="${G13_VM_NAME:-g13-steamos-lab}"
mkdir -p "$LAB"
command -v VBoxManage >/dev/null
command -v curl >/dev/null
command -v bzip2 >/dev/null
if VBoxManage showvminfo "$VM" >/dev/null 2>&1; then
    echo "$VM already exists; refusing to replace it."
    exit 1
fi
if [[ ! -f "$LAB/$IMAGE.bz2" ]]; then
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
        --output "$LAB/$IMAGE.bz2.part" "$URL"
    mv "$LAB/$IMAGE.bz2.part" "$LAB/$IMAGE.bz2"
fi
# A local hash records what was tested. It is not a publisher signature.
sha256sum "$LAB/$IMAGE.bz2" > "$LAB/image.sha256"
printf '%s\n' "$URL" > "$LAB/image-source.txt"
if [[ ! -f "$LAB/recovery.vdi" ]]; then
    if [[ ! -f "$LAB/$IMAGE" ]]; then
        bzip2 --decompress --stdout "$LAB/$IMAGE.bz2" > "$LAB/$IMAGE.part"
        mv "$LAB/$IMAGE.part" "$LAB/$IMAGE"
    fi
    VBoxManage convertfromraw "$LAB/$IMAGE" "$LAB/recovery.vdi" --format VDI
fi
VBoxManage createvm --name "$VM" --ostype ArchLinux_64 --basefolder "$LAB" --register
VBoxManage modifyvm "$VM" --memory 8192 --cpus 4 --firmware efi \
    --graphicscontroller vboxsvga --vram 128 --accelerate3d off \
    --nic1 nat --usb on --usbehci off --usbxhci off \
    --clipboard-mode disabled --draganddrop disabled
VBoxManage storagectl "$VM" --name SATA --add sata --controller IntelAhci
VBoxManage storageattach "$VM" --storagectl SATA --port 0 --device 0 \
    --type hdd --medium "$LAB/recovery.vdi"
VBoxManage createmedium disk --filename "$LAB/scratch.vdi" --size 16384 --format VDI
VBoxManage storageattach "$VM" --storagectl SATA --port 1 --device 0 \
    --type hdd --medium "$LAB/scratch.vdi"
echo "Created $VM. Start with: VBoxManage startvm $VM --type gui"
echo "No host folders, raw host disks, or USB devices are attached."
