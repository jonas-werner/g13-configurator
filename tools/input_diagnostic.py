"""Manual test: read raw G13 input reports live and print decoded state.

Run with the G13 plugged in, then press keys / move the stick and watch
the output change. Key names come from a reference driver and are not
all confirmed against this hardware yet -- see g13/hardware/report.py for
the ones flagged as shaky. If a name looks wrong for the key you pressed,
note the raw hex so the mapping in report.py can be corrected. Ctrl-C to
stop.
"""

from __future__ import annotations

from g13.hardware.device import G13Device
from g13.hardware.report import decode_report


def main() -> None:
    with G13Device() as g13:
        print("reading reports, press keys / move stick (Ctrl-C to stop)...")
        last: bytes | None = None
        while True:
            report = g13.read_report(timeout_ms=200)
            if report is None or report == last:
                continue
            last = report
            state = decode_report(report)
            keys = ", ".join(sorted(state.keys)) or "-"
            backlight = "on" if state.backlight_on else "off"
            print(
                f"{report.hex(' ')}   stick=({state.stick_x:3d},{state.stick_y:3d})"
                f"  backlight={backlight}  keys={keys}"
            )


if __name__ == "__main__":
    main()
