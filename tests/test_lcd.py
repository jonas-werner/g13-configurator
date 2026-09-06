from __future__ import annotations

import unittest

from g13.hardware.lcd import (
    BACKLIGHT_SET_REPORT,
    BACKLIGHT_VALUE,
    MODE_LED_M1,
    MODE_LED_MR,
    MODE_LEDS_VALUE,
    set_mode_leds,
    set_backlight,
    text_frame,
)


class FakeDevice:
    def __init__(self) -> None:
        self.call = None

    def control_transfer(self, *args):
        self.call = args
        return len(args[-1])


class LcdTests(unittest.TestCase):
    def test_backlight_intensity_scales_rgb_channels(self) -> None:
        device = FakeDevice()
        set_backlight(device, 200, 100, 50, intensity=25)
        self.assertEqual(device.call[2], BACKLIGHT_VALUE)
        self.assertEqual(device.call[4], bytes([5, 50, 25, 12, 0]))

    def test_mode_led_report(self) -> None:
        device = FakeDevice()
        set_mode_leds(device, MODE_LED_M1 | MODE_LED_MR)
        self.assertEqual(device.call[1], BACKLIGHT_SET_REPORT)
        self.assertEqual(device.call[2], MODE_LEDS_VALUE)
        self.assertEqual(device.call[4], bytes([5, 0x09, 0, 0, 0]))

    def test_profile_name_is_centered(self) -> None:
        image = text_frame("Doom")
        bbox = image.getbbox()
        self.assertIsNotNone(bbox)
        left, top, right, bottom = bbox
        self.assertLess(abs((left + right) / 2 - 80), 3)
        self.assertLess(abs((top + bottom) / 2 - 21.5), 3)


if __name__ == "__main__":
    unittest.main()
