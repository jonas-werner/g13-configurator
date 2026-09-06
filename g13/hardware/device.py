"""Low-level USB access to the Logitech G13 gameboard.

Opens the device, detaches it from hid-generic, and claims the HID
interface so raw reports can be read/written directly via pyusb.
"""

from __future__ import annotations

import usb.core
import usb.util

VENDOR_ID = 0x046D
PRODUCT_ID = 0xC21C
INTERFACE = 0
ENDPOINT_IN = 0x81
ENDPOINT_OUT = 0x02
REPORT_SIZE = 8


class G13NotFoundError(RuntimeError):
    """Raised when no G13 device is found on the USB bus."""


class G13Device:
    """Owns the USB handle to a G13: claims the HID interface for raw report I/O."""

    def __init__(self) -> None:
        self._dev: usb.core.Device | None = None
        self._detached_kernel_driver = False

    def open(self) -> None:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise G13NotFoundError(
                f"no G13 found (vendor={VENDOR_ID:#06x}, product={PRODUCT_ID:#06x})"
            )

        if dev.is_kernel_driver_active(INTERFACE):
            dev.detach_kernel_driver(INTERFACE)
            self._detached_kernel_driver = True

        usb.util.claim_interface(dev, INTERFACE)
        self._dev = dev

    def close(self) -> None:
        if self._dev is None:
            return
        usb.util.release_interface(self._dev, INTERFACE)
        if self._detached_kernel_driver:
            try:
                self._dev.attach_kernel_driver(INTERFACE)
            except usb.core.USBError:
                pass
        usb.util.dispose_resources(self._dev)
        self._dev = None
        self._detached_kernel_driver = False

    def __enter__(self) -> "G13Device":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def read_report(self, timeout_ms: int = 1000) -> bytes | None:
        """Read one raw input report. Returns None on timeout."""
        if self._dev is None:
            raise RuntimeError("device not open")
        try:
            data = self._dev.read(ENDPOINT_IN, REPORT_SIZE, timeout=timeout_ms)
        except usb.core.USBTimeoutError:
            return None
        return bytes(data)

    def write(self, endpoint: int, data: bytes) -> int:
        """Write raw bytes to an interrupt OUT endpoint (e.g. the LCD)."""
        if self._dev is None:
            raise RuntimeError("device not open")
        return self._dev.write(endpoint, data)

    def control_transfer(
        self, request_type: int, request: int, value: int, index: int, data: bytes
    ) -> int:
        """Send a USB control transfer (e.g. the HID SET_REPORT backlight command)."""
        if self._dev is None:
            raise RuntimeError("device not open")
        return self._dev.ctrl_transfer(request_type, request, value, index, data)


if __name__ == "__main__":
    print("opening G13...")
    with G13Device() as g13:
        print(f"claimed interface {INTERFACE}, kernel driver detached: {g13._detached_kernel_driver}")
    print("closed cleanly, kernel driver reattached")
