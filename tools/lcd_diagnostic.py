"""Manual test: render text to the LCD and cycle the backlight color."""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from g13.hardware.device import G13Device
from g13.hardware.lcd import LCD_HEIGHT, LCD_WIDTH, push_image, set_backlight

BACKLIGHT_COLORS = [
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("white", (255, 255, 255)),
]


def main() -> None:
    image = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), color=0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, LCD_WIDTH - 1, LCD_HEIGHT - 1), outline=1)
    draw.text((4, 4), "Hello, G13!", fill=1)
    draw.text((4, 16), "LCD + backlight test", fill=1)

    with G13Device() as g13:
        print("pushing test image to LCD...")
        push_image(g13, image)

        print("cycling backlight color...")
        for name, (r, g, b) in BACKLIGHT_COLORS:
            print(f"  -> {name}")
            set_backlight(g13, r, g, b)
            time.sleep(1.5)

        input("check the device, then press Enter to release it...")


if __name__ == "__main__":
    main()
