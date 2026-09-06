"""LCD and backlight control for the Logitech G13.

Protocol confirmed against two independent reference drivers named in this
project's brief -- Lordbooker/linux-g13-driver and ecraven/g13 -- which
agree exactly on these details:

- The LCD is a 160x43 1-bit panel addressed as 6 vertical "pages" of 8 rows
  each (48 controller rows; only the top 43 are visible). Each byte covers
  one column within one page, bit N = row N within that page. A frame is
  pushed as a 32-byte header (only byte 0 set, to 0x03) followed by the
  960-byte page-addressed buffer (992 bytes total), written to the
  interrupt OUT endpoint. An "init" control transfer must be sent before
  every frame write, or the device ignores it.
- The backlight RGB color is set via a HID SET_REPORT (Feature) control
  transfer with wValue 0x0307 and a payload of [5, R, G, B, 0]. (wValue
  0x0305 looks similar but is actually the M1-M4 mode-indicator LEDs, not
  the RGB backlight -- easy to mix up.)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from g13.hardware.device import G13Device

LCD_WIDTH = 160
LCD_HEIGHT = 43
LCD_PAGES = 6  # 6 * 8 = 48 controller rows; only the top 43 are visible
LCD_BUFFER_SIZE = LCD_WIDTH * LCD_PAGES  # 960 bytes
LCD_HEADER_SIZE = 32
LCD_ENDPOINT = 0x02

LCD_INIT_REQUEST_TYPE = 0x00  # standard | host-to-device | device
LCD_INIT_REQUEST = 0x09
LCD_INIT_VALUE = 0x0001

BACKLIGHT_REQUEST_TYPE = 0x21  # host-to-device | class | interface
BACKLIGHT_SET_REPORT = 0x09  # HID SET_REPORT
BACKLIGHT_VALUE = 0x0307  # NOT 0x0305 -- that's the mode-indicator LEDs
MODE_LEDS_VALUE = 0x0305
MODE_LED_M1 = 0x01
MODE_LED_M2 = 0x02
MODE_LED_M3 = 0x04
MODE_LED_MR = 0x08


def image_to_lcd_buffer(image: Image.Image) -> bytes:
    """Convert a PIL image to the G13's page-addressed 1bpp buffer."""
    img = image.convert("1")
    if img.size != (LCD_WIDTH, LCD_HEIGHT):
        img = img.resize((LCD_WIDTH, LCD_HEIGHT))

    pixels = img.load()
    buf = bytearray(LCD_BUFFER_SIZE)
    for page in range(LCD_PAGES):
        for col in range(LCD_WIDTH):
            byte = 0
            for bit in range(8):
                row = page * 8 + bit
                if row < LCD_HEIGHT and pixels[col, row]:
                    byte |= 1 << bit
            buf[page * LCD_WIDTH + col] = byte
    return bytes(buf)


def init_lcd(g13: G13Device) -> None:
    """Required before each LCD frame write, or the device ignores it."""
    g13.control_transfer(LCD_INIT_REQUEST_TYPE, LCD_INIT_REQUEST, LCD_INIT_VALUE, 0, b"")


def push_image(g13: G13Device, image: Image.Image) -> None:
    """Render a PIL image to the LCD."""
    init_lcd(g13)
    header = bytearray(LCD_HEADER_SIZE)
    header[0] = 0x03
    payload = bytes(header) + image_to_lcd_buffer(image)
    g13.write(LCD_ENDPOINT, payload)


def scaled_backlight(
    red: int, green: int, blue: int, intensity: int = 100
) -> tuple[int, int, int]:
    """Scale an RGB color to a percentage intensity."""
    factor = max(0, min(100, intensity)) / 100
    return tuple(round(channel * factor) for channel in (red, green, blue))


def set_backlight(
    g13: G13Device, red: int, green: int, blue: int, intensity: int = 100
) -> None:
    """Set RGB hue and 0-100% intensity."""
    red, green, blue = scaled_backlight(red, green, blue, intensity)
    data = bytes([5, red, green, blue, 0])
    g13.control_transfer(
        BACKLIGHT_REQUEST_TYPE,
        BACKLIGHT_SET_REPORT,
        BACKLIGHT_VALUE,
        0,  # wIndex: interface 0
        data,
    )


def set_mode_leds(g13: G13Device, mask: int) -> None:
    """Set the M1/M2/M3/MR indicator LEDs from the low four bits."""
    data = bytes([5, mask & 0x0F, 0, 0, 0])
    g13.control_transfer(
        BACKLIGHT_REQUEST_TYPE,
        BACKLIGHT_SET_REPORT,
        MODE_LEDS_VALUE,
        0,
        data,
    )


def text_frame(text: str) -> Image.Image:
    """A single-frame image showing text, used when a profile has no image."""
    image = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), color=0)
    draw = ImageDraw.Draw(image)
    words = text.split() or [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate) > LCD_WIDTH - 8:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    lines = lines[:3]
    rendered = "\n".join(lines)
    left, top, right, bottom = draw.multiline_textbbox((0, 0), rendered, align="center")
    x = (LCD_WIDTH - (right - left)) / 2
    y = (LCD_HEIGHT - (bottom - top)) / 2 - top
    draw.multiline_text((x, y), rendered, fill=1, align="center")
    return image


def load_frames(path: Path) -> list[tuple[Image.Image, int]]:
    """Load an image file as (frame, duration_ms) pairs for the LCD.

    A static image yields a single frame; an animated GIF yields one per
    frame using its embedded per-frame durations.
    """
    frames = []
    with Image.open(path) as img:
        for index in range(getattr(img, "n_frames", 1)):
            img.seek(index)
            frames.append((img.copy().convert("1"), img.info.get("duration", 0)))
    return frames
