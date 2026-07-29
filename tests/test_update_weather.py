import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.update_weather import (
    RADAR_BBOX_WEB_MERCATOR,
    RADAR_FRAME_HEIGHT,
    RADAR_FRAME_WIDTH,
    cardinal,
    cloud_alpha,
    daily_heading,
    forecast_hour_range,
    next_scheduled_refresh,
    parse_wms_times,
    parse_valid_time,
    round_to_five_minutes,
    sanitized_error,
    select_four_hour_timeline,
    weather_icon_kind,
    wind_direction_degrees,
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

    def test_forecast_covers_current_hour_through_end_of_tomorrow(self):
        now = datetime(2026, 7, 28, 19, 34, tzinfo=ARIZONA)
        hours = forecast_hour_range(now)
        self.assertEqual(hours[0], datetime(2026, 7, 28, 19, 0, tzinfo=ARIZONA))
        self.assertEqual(hours[-1], datetime(2026, 7, 29, 23, 0, tzinfo=ARIZONA))
        self.assertEqual(len(hours), 29)

    def test_daily_headings_use_explicit_arizona_calendar_days(self):
        today = datetime(2026, 7, 28, 19, 34, tzinfo=ARIZONA)
        tomorrow = today + timedelta(days=1)
        self.assertEqual(daily_heading(today, 0), "Today, Tuesday 7/28")
        self.assertEqual(daily_heading(tomorrow, 1), "Tomorrow Wednesday 7/29")

    def test_wind_direction_converts_to_compass_rotation(self):
        self.assertEqual(wind_direction_degrees("N"), 0)
        self.assertEqual(wind_direction_degrees("WNW"), 292.5)
        self.assertIsNone(wind_direction_degrees("VRB"))

    def test_radar_bbox_matches_leaflet_mercator_aspect(self):
        west, south, east, north = RADAR_BBOX_WEB_MERCATOR
        self.assertAlmostEqual(
            (east - west) / (north - south),
            RADAR_FRAME_WIDTH / RADAR_FRAME_HEIGHT,
            places=6,
        )

    def test_cloud_mask_removes_land_and_preserves_bright_clouds(self):
        self.assertEqual(cloud_alpha(42), 0)
        self.assertGreater(cloud_alpha(180), 0)
        self.assertLessEqual(cloud_alpha(255), 225)

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
        values = parse_wms_times(xml, "conus_base_reflectivity_mosaic")
        self.assertEqual(len(values), 2)
        self.assertEqual(values[1].minute, 4)

    def test_four_hour_timeline_is_evenly_reduced_to_24_frames(self):
        start = datetime(2026, 7, 28, 18, 0, tzinfo=ZoneInfo("UTC"))
        values = [start + timedelta(minutes=5 * index) for index in range(49)]
        selected = select_four_hour_timeline(values)
        self.assertEqual(len(selected), 24)
        self.assertEqual(selected[0], values[0])
        self.assertEqual(selected[-1], values[-1])

    def test_iem_timestamp_rounds_to_nearest_five_minutes(self):
        value = datetime(2026, 7, 28, 23, 58, 0, tzinfo=ZoneInfo("UTC"))
        expected = datetime(2026, 7, 29, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(round_to_five_minutes(value), expected)

    def test_weather_icon_prioritizes_thunder_over_sky_cover(self):
        self.assertEqual(weather_icon_kind(sky=5, thunder=40), "storm")

    def test_weather_icon_distinguishes_clear_night(self):
        self.assertEqual(weather_icon_kind(sky=10, is_night=True), "clear-night")

    def test_weather_icon_treats_partly_cloudy_as_partial_cover(self):
        self.assertEqual(weather_icon_kind(summary="Partly Cloudy"), "partly-cloudy")

    def test_error_messages_never_preserve_token_values(self):
        error = RuntimeError("request failed at https://example.test/?token=secret-value&x=1")
        message = sanitized_error(error)
        self.assertNotIn("secret-value", message)
        self.assertIn("token=[redacted]", message)


if __name__ == "__main__":
    unittest.main()
