from __future__ import annotations

import unittest
from datetime import datetime

from g13.system_stats import StatsSnapshot, SystemStats, clock_frame, stats_frame


class SystemStatsTests(unittest.TestCase):
    def test_clock_and_date_frame(self) -> None:
        frame = clock_frame(datetime(2026, 9, 6, 20, 35))
        self.assertEqual(frame.size, (160, 43))
        self.assertIsNotNone(frame.getbbox())

    def test_stats_dashboard_frame(self) -> None:
        frame = stats_frame(
            StatsSnapshot(
                cpu_percent=12,
                memory_percent=34,
                disk_percent=56,
                net_up_bps=1024,
                net_down_bps=2 * 1024 * 1024,
                cpu_temp=61,
                gpu_percent=78,
                gpu_memory_percent=45,
                gpu_temp=70,
            )
        )
        self.assertEqual(frame.size, (160, 43))
        self.assertIsNotNone(frame.getbbox())

    def test_live_sample_ranges(self) -> None:
        monitor = SystemStats()
        snapshot = monitor.sample()
        self.assertGreaterEqual(snapshot.cpu_percent, 0)
        self.assertLessEqual(snapshot.cpu_percent, 100)
        self.assertGreater(snapshot.memory_percent, 0)
        self.assertGreaterEqual(snapshot.disk_percent, 0)
        self.assertGreaterEqual(snapshot.net_up_bps, 0)
        self.assertGreaterEqual(snapshot.net_down_bps, 0)


if __name__ == "__main__":
    unittest.main()
