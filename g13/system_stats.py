"""Small, dependency-free system monitor and 160x43 LCD renderers."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LCD_SIZE = (160, 43)


@lru_cache
def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


@lru_cache
def _clock_font(size: int) -> ImageFont.ImageFont:
    try:
        match = subprocess.run(
            ["fc-match", "-f", "%{family}\n%{file}", "Orbitron:style=Bold"],
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
        ).stdout.splitlines()
        if match and "Orbitron" in match[0] and len(match) > 1:
            return ImageFont.truetype(match[1], size)
    except (OSError, subprocess.SubprocessError):
        pass
    return _font(size, bold=True)


def clock_frame(now: datetime | None = None) -> Image.Image:
    """Render a large digital clock with weekday and date on the right."""
    now = now or datetime.now()
    image = Image.new("1", LCD_SIZE, 0)
    draw = ImageDraw.Draw(image)
    time_font = _clock_font(24)
    date_font = _font(9, bold=True)
    time_text = now.strftime("%H:%M")
    time_box = draw.textbbox((0, 0), time_text, font=time_font)
    draw.text((3, (43 - (time_box[3] - time_box[1])) // 2 - time_box[1]), time_text, 1, font=time_font)

    date_lines = (now.strftime("%a").upper(), now.strftime("%d %b").upper())
    right_left = 103
    draw.line((98, 4, 98, 38), fill=1)
    for index, line in enumerate(date_lines):
        box = draw.textbbox((0, 0), line, font=date_font)
        x = right_left + (57 - (box[2] - box[0])) // 2
        draw.text((x, 6 + index * 17), line, 1, font=date_font)
    return image


@dataclass(frozen=True)
class StatsSnapshot:
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    net_up_bps: float
    net_down_bps: float
    cpu_temp: float | None = None
    gpu_percent: float | None = None
    gpu_memory_percent: float | None = None
    gpu_temp: float | None = None


def _percent(value: float | None) -> str:
    return "--" if value is None else f"{round(value):d}"


def _temperature(value: float | None) -> str:
    return "--" if value is None else f"{round(value):d}C"


def _rate(value: float) -> str:
    for divisor, suffix in ((1024**3, "G"), (1024**2, "M"), (1024, "K")):
        if value >= divisor:
            amount = value / divisor
            return f"{amount:.1f}{suffix}" if amount < 10 else f"{amount:.0f}{suffix}"
    return f"{value:.0f}B"


def stats_frame(snapshot: StatsSnapshot) -> Image.Image:
    """Render the compact three-line system dashboard."""
    image = Image.new("1", LCD_SIZE, 0)
    draw = ImageDraw.Draw(image)
    font = _font(10, bold=True)
    lines = (
        f"CPU {_percent(snapshot.cpu_percent):>3}% {_temperature(snapshot.cpu_temp):>3}  "
        f"MEM {_percent(snapshot.memory_percent):>3}%",
        f"GPU {_percent(snapshot.gpu_percent):>3}% {_temperature(snapshot.gpu_temp):>3}  "
        f"VRM {_percent(snapshot.gpu_memory_percent):>3}%",
        f"UP {_rate(snapshot.net_up_bps):>5}   DOWN {_rate(snapshot.net_down_bps):>5}",
    )
    for row, line in enumerate(lines):
        draw.text((1, row * 14), line, fill=1, font=font)
    return image


class SystemStats:
    def __init__(self) -> None:
        self._last_cpu = self._read_cpu_times()
        self._last_network = self._read_network_bytes()
        self._last_sample_time = time.monotonic()

    @staticmethod
    def _read_cpu_times() -> tuple[int, int]:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    @staticmethod
    def _read_memory_percent() -> float:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, raw = line.split(":", 1)
            values[name] = int(raw.split()[0])
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0))
        return (total - available) / total * 100

    @staticmethod
    def _read_network_bytes() -> tuple[int, int]:
        received = sent = 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            interface, raw = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = raw.split()
            received += int(fields[0])
            sent += int(fields[8])
        return received, sent

    @staticmethod
    def _read_cpu_temperature() -> float | None:
        temperatures = []
        for path in Path("/sys/class/hwmon").glob("hwmon*/temp*_input"):
            try:
                value = int(path.read_text().strip()) / 1000
            except (OSError, ValueError):
                continue
            if 0 < value < 150:
                temperatures.append(value)
        return max(temperatures, default=None)

    @staticmethod
    def _read_gpu() -> tuple[float | None, float | None, float | None]:
        if shutil.which("nvidia-smi"):
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=True,
                )
                utilization, used, total, temperature = (
                    float(value.strip()) for value in result.stdout.splitlines()[0].split(",")
                )
                memory_percent = used / total * 100 if total else 0
                return utilization, memory_percent, temperature
            except (OSError, ValueError, subprocess.SubprocessError, IndexError):
                pass

        for device in Path("/sys/class/drm").glob("card*/device"):
            busy_path = device / "gpu_busy_percent"
            if not busy_path.exists():
                continue
            try:
                utilization = float(busy_path.read_text().strip())
                used = int((device / "mem_info_vram_used").read_text().strip())
                total = int((device / "mem_info_vram_total").read_text().strip())
                memory_percent = used / total * 100 if total else None
            except (OSError, ValueError):
                memory_percent = None
                try:
                    utilization = float(busy_path.read_text().strip())
                except (OSError, ValueError):
                    continue
            return utilization, memory_percent, None
        return None, None, None

    def sample(self) -> StatsSnapshot:
        now = time.monotonic()
        total, idle = self._read_cpu_times()
        previous_total, previous_idle = self._last_cpu
        total_delta = total - previous_total
        idle_delta = idle - previous_idle
        cpu_percent = (1 - idle_delta / total_delta) * 100 if total_delta else 0
        self._last_cpu = (total, idle)

        received, sent = self._read_network_bytes()
        previous_received, previous_sent = self._last_network
        elapsed = max(0.001, now - self._last_sample_time)
        self._last_network = (received, sent)
        self._last_sample_time = now

        disk = shutil.disk_usage("/")
        gpu_percent, gpu_memory_percent, gpu_temp = self._read_gpu()
        return StatsSnapshot(
            cpu_percent=max(0, min(100, cpu_percent)),
            memory_percent=self._read_memory_percent(),
            disk_percent=disk.used / disk.total * 100,
            net_up_bps=max(0, sent - previous_sent) / elapsed,
            net_down_bps=max(0, received - previous_received) / elapsed,
            cpu_temp=self._read_cpu_temperature(),
            gpu_percent=gpu_percent,
            gpu_memory_percent=gpu_memory_percent,
            gpu_temp=gpu_temp,
        )
