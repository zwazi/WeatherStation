import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.update_weather import (
    cardinal,
    next_scheduled_refresh,
    parse_nowcoast_radar_times,
    parse_valid_time,
    sanitized_error,
)


ARIZONA = ZoneInfo("America/Phoenix")


class UpdateWeatherTests(unittest.TestCase):
    def test_next_refresh_uses_requested_minute_sequence(self):
        now = datetime(2026, 7, 28, 14, 11, 0, tzinfo=ARIZONA)
        self.assertEqual(next_scheduled_refresh(now).minute, 21)

    def test_next_refresh_rolls_into_next_hour(self):
        now = datetime(2026, 7, 28, 14, 58, 0, tzinfo=ARIZONA)
        expected = datetime(2026, 7, 28, 15, 1, 0, tzinfo=ARIZONA)
        self.assertEqual(next_scheduled_refresh(now), expected)

    def test_cardinal_wraps_at_north(self):
        self.assertEqual(cardinal(359), "N")
        self.assertEqual(cardinal(225), "SW")

    def test_parse_nws_interval(self):
        start, end = parse_valid_time("2026-07-28T21:00:00+00:00/PT3H")
        self.assertEqual((end - start).total_seconds(), 10_800)

    def test_parse_nowcoast_timestamp_list(self):
        xml = b"""
        <WMS_Capabilities xmlns="http://www.opengis.net/wms">
          <Capability><Layer><Layer>
            <Name>conus_base_reflectivity_mosaic</Name>
            <Dimension name="time">2026-07-28T20:00:00Z,2026-07-28T20:04:00Z</Dimension>
          </Layer></Layer></Capability>
        </WMS_Capabilities>
        """
        values = parse_nowcoast_radar_times(xml)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[1].minute, 4)

    def test_error_messages_never_preserve_token_values(self):
        error = RuntimeError("request failed at https://example.test/?token=secret-value&x=1")
        message = sanitized_error(error)
        self.assertNotIn("secret-value", message)
        self.assertIn("token=[redacted]", message)


if __name__ == "__main__":
    unittest.main()
