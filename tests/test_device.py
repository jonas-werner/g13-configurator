from __future__ import annotations

import errno
import unittest
from unittest.mock import Mock, patch

import usb.core

from g13.hardware.device import G13Device


class DeviceTests(unittest.TestCase):
    def test_unplug_while_opening_disposes_handle_and_preserves_error(self) -> None:
        device = G13Device()
        handle = Mock()
        failure = usb.core.USBError('gone during claim', errno=errno.ENODEV)
        with patch('usb.core.find', return_value=handle), \
             patch('usb.util.claim_interface', side_effect=failure), \
             patch('usb.util.release_interface', side_effect=usb.core.USBError('gone', errno=errno.ENODEV)), \
             patch('usb.util.dispose_resources') as dispose:
            with self.assertRaises(usb.core.USBError) as raised:
                device.open()
            self.assertIs(raised.exception, failure)
            dispose.assert_called_once_with(handle)
        self.assertIsNone(device._dev)
        self.assertFalse(device._detached_kernel_driver)

    def test_only_read_timeouts_are_ignored(self) -> None:
        device = G13Device()
        device._dev = Mock()
        device._dev.read.side_effect = usb.core.USBTimeoutError('timeout')
        self.assertIsNone(device.read_report())
        for code in (errno.ENODEV, errno.EPIPE, errno.EIO, errno.EACCES):
            with self.subTest(errno=code):
                failure = usb.core.USBError('USB failure', errno=code)
                device._dev.read.side_effect = failure
                with self.assertRaises(usb.core.USBError) as raised:
                    device.read_report()
                self.assertIs(raised.exception, failure)

    def test_unplug_during_close_still_disposes_handle(self) -> None:
        device = G13Device()
        handle = device._dev = Mock()
        device._detached_kernel_driver = True
        handle.attach_kernel_driver.side_effect = usb.core.USBError('gone', errno=errno.ENODEV)
        with patch('usb.util.release_interface', side_effect=usb.core.USBError('gone', errno=errno.ENODEV)), \
             patch('usb.util.dispose_resources') as dispose:
            device.close()
            dispose.assert_called_once_with(handle)
            device.close()
            dispose.assert_called_once()
        self.assertIsNone(device._dev)
        self.assertFalse(device._detached_kernel_driver)

    def test_other_close_errors_surface_after_disposal(self) -> None:
        device = G13Device()
        handle = device._dev = Mock()
        with patch('usb.util.release_interface', side_effect=usb.core.USBError('I/O', errno=errno.EIO)), \
             patch('usb.util.dispose_resources') as dispose:
            with self.assertRaises(usb.core.USBError):
                device.close()
            dispose.assert_called_once_with(handle)
