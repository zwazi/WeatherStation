#!/usr/bin/env python3
"""Build the sanitized JSON consumed by the WeatherStation Pages site."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
import re
import shutil
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from math import degrees, log, pi, radians, tan
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps


ARIZONA_TZ = ZoneInfo("America/Phoenix")
UTC = ZoneInfo("UTC")
STATION_ID = os.environ.get("TEMPEST_STATION_ID", "217249")
DEVICE_ID = os.environ.get("TEMPEST_DEVICE_ID", "1221453")
TEMPEST_TOKEN = os.environ.get("TEMPEST_TOKEN", "")

TUCSON_LAT = 32.3051
TUCSON_LON = -110.9156
RADAR_FRAME_WIDTH = 1400
RADAR_FRAME_HEIGHT = 600
RADAR_LAT_MIN = 28.8
RADAR_LAT_MAX = 36.0
RADAR_CENTER_LON = -111.1
WEB_MERCATOR_RADIUS = 6_378_137


def mercator_x(longitude: float) -> float:
    return WEB_MERCATOR_RADIUS * radians(longitude)


def mercator_y(latitude: float) -> float:
    return WEB_MERCATOR_RADIUS * log(tan(pi / 4 + radians(latitude) / 2))


def longitude_from_mercator(x_coordinate: float) -> float:
    return degrees(x_coordinate / WEB_MERCATOR_RADIUS)


RADAR_MERCATOR_Y_MIN = mercator_y(RADAR_LAT_MIN)
RADAR_MERCATOR_Y_MAX = mercator_y(RADAR_LAT_MAX)
RADAR_MERCATOR_X_CENTER = mercator_x(RADAR_CENTER_LON)
RADAR_MERCATOR_X_SPAN = (
    (RADAR_MERCATOR_Y_MAX - RADAR_MERCATOR_Y_MIN)
    * RADAR_FRAME_WIDTH
    / RADAR_FRAME_HEIGHT
)
RADAR_BBOX_WEB_MERCATOR = (
    RADAR_MERCATOR_X_CENTER - RADAR_MERCATOR_X_SPAN / 2,
    RADAR_MERCATOR_Y_MIN,
    RADAR_MERCATOR_X_CENTER + RADAR_MERCATOR_X_SPAN / 2,
    RADAR_MERCATOR_Y_MAX,
)
RADAR_BBOX = (
    round(longitude_from_mercator(RADAR_BBOX_WEB_MERCATOR[0]), 6),
    RADAR_LAT_MIN,
    round(longitude_from_mercator(RADAR_BBOX_WEB_MERCATOR[2]), 6),
    RADAR_LAT_MAX,
)
REFRESH_MINUTES = (1, 11, 21, 31, 41, 51)
RAIN_ICON_THRESHOLD = 50

NESDIS_CLOUD_IMAGE_SERVER = (
    "https://satellitemaps.nesdis.noaa.gov/arcgis/rest/services/"
    "ABI13_Last_24hr/ImageServer"
)
NESDIS_CLOUD_QUERY = f"{NESDIS_CLOUD_IMAGE_SERVER}/query"
NOAA_SATELLITE_SOURCE = NESDIS_CLOUD_IMAGE_SERVER
IEM_NEXRAD_WMS = (
    "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi"
)
IEM_RADAR_SOURCE = "https://mesonet.agron.iastate.edu/docs/nexrad_mosaic/"
NOWCOAST_RADAR_WMS = "https://nowcoast.noaa.gov/geoserver/weather_radar/wms"
NOWCOAST_CAPABILITIES = (
    f"{NOWCOAST_RADAR_WMS}?service=WMS&version=1.3.0&request=GetCapabilities"
)
NWS_POINT_URL = f"https://api.weather.gov/points/{TUCSON_LAT},{TUCSON_LON}"
NWS_ALERTS_URL = f"https://api.weather.gov/alerts/active?point={TUCSON_LAT},{TUCSON_LON}"
NWS_SOURCE = (
    "https://forecast.weather.gov/MapClick.php?lat=32.3051&lon=-110.9156"
    "&unit=0&lg=english&FcstType=graphical"
)
OPEN_METEO_AIR_QUALITY = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_AIR_QUALITY_SOURCE = "https://open-meteo.com/en/docs/air-quality-api"

DEFAULT_HEADERS = {
    "User-Agent": "WeatherStation Pages/1.0 (https://github.com/zwazi/WeatherStation)",
    "Accept": "*/*",
}
NWS_HEADERS = {**DEFAULT_HEADERS, "Accept": "application/geo+json"}


def fetch_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    """Fetch a URL with brief retries for transient upstream failures."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=headers or DEFAULT_HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as error:  # Upstream services use several error types.
            last_error = error
            if attempt < 2:
                time.sleep(attempt + 1)
    assert last_error is not None
    raise last_error


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict:
    return json.loads(fetch_bytes(url, headers).decode("utf-8"))


def c_to_f(value):
    return value * 9 / 5 + 32 if value is not None else None


def ms_to_mph(value):
    return value * 2.236936 if value is not None else None


def mm_to_in(value):
    return value / 25.4 if value is not None else None


def mb_to_inhg(value):
    return value * 0.0295299830714 if value is not None else None


def km_to_mi(value):
    return value * 0.621371 if value is not None else None


def fmt(value, suffix: str = "", digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def cardinal(degrees) -> str:
    if degrees is None:
        return "—"
    directions = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return directions[round(degrees / 22.5) % 16]


def next_scheduled_refresh(now: datetime) -> datetime:
    for minute in REFRESH_MINUTES:
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate > now:
            return candidate
    return (now + timedelta(hours=1)).replace(minute=1, second=0, microsecond=0)


def forecast_hour_range(now: datetime) -> list[datetime]:
    """Return local hours from the current hour through tomorrow at 11 PM."""
    first_hour = now.astimezone(ARIZONA_TZ).replace(
        minute=0, second=0, microsecond=0
    )
    last_hour = (first_hour + timedelta(days=1)).replace(hour=23)
    count = int((last_hour - first_hour).total_seconds() // 3600) + 1
    return [first_hour + timedelta(hours=offset) for offset in range(count)]


def daily_heading(target: datetime, day_offset: int) -> str:
    prefix = "Today," if day_offset == 0 else "Tomorrow"
    return f"{prefix} {target.strftime('%A %-m/%-d')}"


def wind_direction_degrees(direction: str | None) -> float | None:
    if not direction:
        return None
    directions = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    try:
        return directions.index(direction.upper()) * 22.5
    except ValueError:
        return None


def air_quality_category(aqi: float) -> str:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for sensitive groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very unhealthy"
    return "Hazardous"


def get_air_quality() -> dict:
    params = {
        "latitude": TUCSON_LAT,
        "longitude": TUCSON_LON,
        "current": "us_aqi,pm2_5",
        "timezone": "America/Phoenix",
    }
    response = fetch_json(f"{OPEN_METEO_AIR_QUALITY}?{urlencode(params)}")
    current = response.get("current", {})
    aqi = current.get("us_aqi")
    if aqi is None:
        raise ValueError("Open-Meteo did not return a current U.S. AQI")
    observed_at = current.get("time")
    if observed_at:
        observed_at = datetime.fromisoformat(observed_at).replace(
            tzinfo=ARIZONA_TZ
        ).isoformat()
    return {
        "updated_at": observed_at,
        "us_aqi": round(aqi),
        "category": air_quality_category(aqi),
        "pm2_5": current.get("pm2_5"),
        "source": OPEN_METEO_AIR_QUALITY_SOURCE,
    }


def get_tempest_weather() -> dict:
    if not TEMPEST_TOKEN:
        raise RuntimeError("TEMPEST_TOKEN is not configured")

    station_url = (
        "https://swd.weatherflow.com/swd/rest/observations/stn/"
        f"{STATION_ID}?token={TEMPEST_TOKEN}"
    )
    device_url = (
        "https://swd.weatherflow.com/swd/rest/observations/device/"
        f"{DEVICE_ID}?token={TEMPEST_TOKEN}"
    )
    station = fetch_json(station_url)
    if station.get("status", {}).get("status_code") != 0:
        raise RuntimeError(
            station.get("status", {}).get("status_message", "Tempest API error")
        )

    values = dict(zip(station["ob_fields"], station["obs"][0]))
    summary = {}
    try:
        device = fetch_json(device_url)
        if device.get("status", {}).get("status_code") == 0:
            summary = device.get("summary", {})
    except Exception:
        # Current conditions remain useful if the optional device summary is down.
        pass

    timezone_name = station.get("timezone", "America/Phoenix")
    timezone = ZoneInfo(timezone_name)
    timestamp = values.get("timestamp")
    updated_at = (
        datetime.fromtimestamp(timestamp, timezone).isoformat()
        if timestamp
        else None
    )

    temperature = c_to_f(values.get("air_temp"))
    humidity = values.get("rh")
    wind_lull = ms_to_mph(values.get("wind_lull"))
    wind_average = ms_to_mph(values.get("wind_avg"))
    wind_gust = ms_to_mph(values.get("wind_gust"))
    wind_direction = values.get("wind_dir")
    station_pressure = mb_to_inhg(values.get("station_pressure"))
    sea_level_pressure = mb_to_inhg(values.get("sea_level_pressure"))
    rain_now = mm_to_in(values.get("precip_accumulation"))
    precipitation_type = values.get("precip_type")
    rain_today = mm_to_in(values.get("local_day_precip_accumulation"))
    rain_today_nc = mm_to_in(values.get("nc_local_day_precip_accumulation"))
    strikes = values.get("strike_count")
    strike_distance = km_to_mi(values.get("strike_distance"))
    illuminance = values.get("illuminance")
    uv = values.get("uv")
    solar = values.get("solar_radiation")

    feels_like = c_to_f(summary.get("feels_like"))
    heat_index = c_to_f(summary.get("heat_index"))
    wind_chill = c_to_f(summary.get("wind_chill"))
    pressure_trend = summary.get("pressure_trend")
    strikes_1h = summary.get("strike_count_1h")
    strikes_3h = summary.get("strike_count_3h")
    rain_1h = mm_to_in(summary.get("precip_total_1h"))
    last_strike_distance = km_to_mi(summary.get("strike_last_dist"))

    cards = [
        {
            "label": "Temperature",
            "signal": "TEMP",
            "value": fmt(temperature, "°F", 1),
            "detail": f"Feels like {fmt(feels_like, '°F', 1)}",
        },
        {
            "label": "Humidity",
            "signal": "RH",
            "value": fmt(humidity, "%"),
            "detail": "Relative humidity",
            "meter": humidity,
        },
        {
            "label": "Wind",
            "signal": "WIND",
            "value": fmt(wind_average, " mph", 1),
            "detail": (
                f"Gust {fmt(wind_gust, ' mph', 1)} · "
                f"{cardinal(wind_direction)} {fmt(wind_direction, '°')}"
            ),
        },
        {
            "label": "Rain Today",
            "signal": "RAIN",
            "value": fmt(rain_today, " in", 2),
            "detail": f"Last hour {fmt(rain_1h, ' in', 2)}",
        },
        {
            "label": "Lightning",
            "signal": "ELEC",
            "value": fmt(strikes),
            "detail": f"1h: {fmt(strikes_1h)} · 3h: {fmt(strikes_3h)}",
        },
        {
            "label": "UV / Light",
            "signal": "SOLAR",
            "value": fmt(uv, "", 1),
            "detail": f"{fmt(illuminance, ' lux')} · {fmt(solar, ' W/m²')}",
        },
    ]

    details = [
        {
            "title": "Current Conditions",
            "rows": [
                ["Temperature", fmt(temperature, "°F", 1)],
                ["Feels Like", fmt(feels_like, "°F", 1)],
                ["Heat Index", fmt(heat_index, "°F", 1)],
                ["Wind Chill", fmt(wind_chill, "°F", 1)],
                ["Humidity", fmt(humidity, "%")],
            ],
        },
        {
            "title": "Wind",
            "rows": [
                ["Lull", fmt(wind_lull, " mph", 1)],
                ["Average", fmt(wind_average, " mph", 1)],
                ["Gust", fmt(wind_gust, " mph", 1)],
                ["Direction", f"{cardinal(wind_direction)} / {fmt(wind_direction, '°')}"],
            ],
        },
        {
            "title": "Pressure",
            "rows": [
                ["Station Pressure", fmt(station_pressure, " inHg", 2)],
                ["Sea-Level Pressure", fmt(sea_level_pressure, " inHg", 2)],
                ["Trend", str(pressure_trend).title() if pressure_trend else "—"],
            ],
        },
        {
            "title": "Rain",
            "rows": [
                ["Current Accumulation", fmt(rain_now, " in", 2)],
                ["Today", fmt(rain_today, " in", 2)],
                ["Today NC", fmt(rain_today_nc, " in", 2)],
                ["Last Hour", fmt(rain_1h, " in", 2)],
            ],
        },
        {
            "title": "Lightning",
            "rows": [
                ["Current Strike Count", fmt(strikes)],
                ["Strike Distance", fmt(strike_distance, " mi", 1)],
                ["Last Strike Distance", fmt(last_strike_distance, " mi", 1)],
                ["1 Hour Strike Count", fmt(strikes_1h)],
                ["3 Hour Strike Count", fmt(strikes_3h)],
            ],
        },
        {
            "title": "Light",
            "rows": [
                ["Illuminance", fmt(illuminance, " lux")],
                ["UV Index", fmt(uv, "", 1)],
                ["Solar Radiation", fmt(solar, " W/m²")],
            ],
        },
    ]

    return {
        "is_raining": (
            (rain_now is not None and rain_now > 0)
            or precipitation_type in (1, 3)
        ),
        "station": {
            "id": STATION_ID,
            "timezone": timezone_name,
            "updated_at": updated_at,
        },
        "cards": cards,
        "details": details,
    }


def parse_valid_time(valid_time: str) -> tuple[datetime, datetime]:
    start_text, duration_text = valid_time.split("/", 1)
    start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    match = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        duration_text,
    )
    if not match:
        raise ValueError(f"Unsupported NWS time interval: {valid_time}")
    days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
    return start, start + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )


def nws_value_at(element: dict, target: datetime):
    for entry in element.get("values", []):
        try:
            start, end = parse_valid_time(entry["validTime"])
        except (KeyError, ValueError):
            continue
        if start <= target < end:
            return entry.get("value")
    return None


def round_number(value):
    return None if value is None else int(round(value))


def nws_temperature_at(properties: dict, key: str, target: datetime):
    value = nws_value_at(properties.get(key, {}), target)
    if value is None:
        return None
    unit = properties.get(key, {}).get("uom", "")
    return round_number(c_to_f(value) if unit.endswith("degC") else value)


def nws_wind_at(properties: dict, key: str, target: datetime):
    value = nws_value_at(properties.get(key, {}), target)
    if value is None:
        return None
    unit = properties.get(key, {}).get("uom", "")
    if unit.endswith("km_h-1"):
        value *= 0.621371
    elif unit.endswith("m_s-1"):
        value = ms_to_mph(value)
    return round_number(value)


def nws_percent_at(properties: dict, key: str, target: datetime):
    return round_number(nws_value_at(properties.get(key, {}), target))


def weather_types_at(properties: dict, target: datetime) -> set[str]:
    values = nws_value_at(properties.get("weather", {}), target) or []
    return {
        item.get("weather")
        for item in values
        if isinstance(item, dict) and item.get("weather")
    }


def forecast_period_at(periods: list[dict], target: datetime) -> dict:
    for period in periods:
        try:
            start = datetime.fromisoformat(period["startTime"])
            end = datetime.fromisoformat(period["endTime"])
        except (KeyError, ValueError):
            continue
        if start <= target < end:
            return period
    return {}


def weather_icon_kind(
    summary: str = "",
    sky: int | None = None,
    rain: int | None = None,
    thunder: int | None = None,
    is_night: bool = False,
    is_raining: bool = False,
) -> str:
    """Choose a weather icon, reserving wet icons for likely or live rain."""
    text = summary.lower()
    show_rain = is_raining or (rain or 0) > RAIN_ICON_THRESHOLD
    if show_rain and ((thunder or 0) >= 20 or "thunder" in text):
        return "storm"
    if show_rain:
        return "rain"
    if "snow" in text:
        return "snow"
    if sky is None:
        if "partly" in text or "mostly sunny" in text:
            sky = 50
        elif "cloud" in text or "overcast" in text:
            sky = 70
        elif "clear" in text or "sunny" in text:
            sky = 10
    if sky is not None and sky <= 30:
        return "clear-night" if is_night else "clear"
    if sky is not None and sky <= 60:
        return "partly-cloudy-night" if is_night else "partly-cloudy"
    return "cloudy"


def current_weather_icon_kind(
    grid: dict,
    period: dict,
    now: datetime,
    is_raining: bool = False,
) -> str:
    """Choose the current icon from current NWS grid values when available."""
    target = now.astimezone(UTC)
    precipitation = nws_percent_at(grid, "probabilityOfPrecipitation", target)
    weather_types = weather_types_at(grid, target)
    rain = precipitation
    if weather_types and not weather_types.intersection(
        {"rain", "rain_showers", "drizzle", "thunderstorms"}
    ):
        rain = 0
    if rain is None:
        rain = period.get("probabilityOfPrecipitation", {}).get("value")
    return weather_icon_kind(
        summary=period.get("shortForecast", ""),
        sky=nws_percent_at(grid, "skyCover", target),
        rain=rain,
        thunder=nws_percent_at(grid, "probabilityOfThunder", target),
        is_night=not period.get("isDaytime", True),
        is_raining=is_raining,
    )


def get_nws_forecast(now: datetime, is_raining: bool = False) -> dict:
    point = fetch_json(NWS_POINT_URL, NWS_HEADERS)["properties"]
    grid = fetch_json(point["forecastGridData"], NWS_HEADERS)["properties"]
    periods = fetch_json(point["forecast"], NWS_HEADERS)["properties"]["periods"]
    hourly_periods = fetch_json(point["forecastHourly"], NWS_HEADERS)["properties"]["periods"]

    hours = forecast_hour_range(now)
    rows = {
        "Temperature": [],
        "Dew point": [],
        "Surface wind": [],
        "Gusts": [],
        "Relative Humidity": [],
        "Precipitation Potential": [],
        "Sky Cover": [],
        "Rain": [],
        "Thunder": [],
    }
    hourly = []
    daily_values: dict = {}
    rain_types = {"rain", "rain_showers", "drizzle", "thunderstorms"}

    for local_hour in hours:
        target = local_hour.astimezone(UTC)
        temperature = nws_temperature_at(grid, "temperature", target)
        dewpoint = nws_temperature_at(grid, "dewpoint", target)
        wind = nws_wind_at(grid, "windSpeed", target)
        gust = nws_wind_at(grid, "windGust", target)
        humidity = nws_percent_at(grid, "relativeHumidity", target)
        precipitation = nws_percent_at(grid, "probabilityOfPrecipitation", target)
        sky = nws_percent_at(grid, "skyCover", target)
        thunder = nws_percent_at(grid, "probabilityOfThunder", target)
        weather_types = weather_types_at(grid, target)
        official_hour = forecast_period_at(hourly_periods, local_hour)
        wind_direction = official_hour.get("windDirection")
        hour_summary = official_hour.get("shortForecast", "")
        rain = precipitation
        if weather_types and not weather_types.intersection(rain_types):
            rain = 0

        rows["Temperature"].append(fmt(temperature, "°F"))
        rows["Dew point"].append(fmt(dewpoint, "°F"))
        rows["Surface wind"].append(fmt(wind, " mph"))
        rows["Gusts"].append(fmt(gust, " mph"))
        rows["Relative Humidity"].append(fmt(humidity, "%"))
        rows["Precipitation Potential"].append(fmt(precipitation, "%"))
        rows["Sky Cover"].append(fmt(sky, "%"))
        rows["Rain"].append(fmt(rain, "%"))
        rows["Thunder"].append(fmt(thunder, "%"))
        is_night = local_hour.hour < 6 or local_hour.hour >= 20
        values_for_day = daily_values.setdefault(
            local_hour.date(), {"temperatures": [], "rain": [], "summaries": []}
        )
        if temperature is not None:
            values_for_day["temperatures"].append(temperature)
        if precipitation is not None:
            values_for_day["rain"].append(precipitation)
        if hour_summary:
            values_for_day["summaries"].append(hour_summary)
        hourly.append(
            {
                "timestamp": local_hour.isoformat(),
                "date": local_hour.date().isoformat(),
                "time": local_hour.strftime("%-I %p"),
                "day": local_hour.strftime("%a"),
                "temperature": fmt(temperature, "°"),
                "precipitation": fmt(precipitation, "%"),
                "wind": fmt(wind, " mph"),
                "wind_direction": wind_direction,
                "wind_degrees": wind_direction_degrees(wind_direction),
                "gust": fmt(gust, " mph"),
                "humidity": fmt(humidity, "%"),
                "icon": weather_icon_kind(
                    summary=hour_summary,
                    sky=sky,
                    rain=rain,
                    thunder=thunder,
                    is_night=is_night,
                    is_raining=is_raining and local_hour == hours[0],
                ),
            }
        )

    local_now = now.astimezone(ARIZONA_TZ)
    daily = []
    for day_offset in range(2):
        target_date = local_now.date() + timedelta(days=day_offset)
        matching_periods = []
        for period in periods:
            try:
                start = datetime.fromisoformat(period["startTime"]).astimezone(ARIZONA_TZ)
            except (KeyError, ValueError):
                continue
            if start.date() == target_date:
                matching_periods.append(period)
        daytime = next(
            (period for period in matching_periods if period.get("isDaytime")), None
        )
        nighttime = next(
            (period for period in matching_periods if not period.get("isDaytime")), None
        )
        values_for_day = daily_values.get(
            target_date, {"temperatures": [], "rain": [], "summaries": []}
        )
        full_day_temperatures = []
        full_day_rain = []
        midnight = local_now.replace(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        for hour_offset in range(24):
            target = (midnight + timedelta(hours=hour_offset)).astimezone(UTC)
            temperature = nws_temperature_at(grid, "temperature", target)
            precipitation = nws_percent_at(grid, "probabilityOfPrecipitation", target)
            if temperature is not None:
                full_day_temperatures.append(temperature)
            if precipitation is not None:
                full_day_rain.append(precipitation)
        summary_period = daytime or (matching_periods[0] if matching_periods else None)
        summary = (
            (summary_period.get("shortForecast") if summary_period else None)
            or next(iter(values_for_day["summaries"]), "Forecast available")
        )
        high = daytime.get("temperature") if daytime else None
        low = nighttime.get("temperature") if nighttime else None
        if high is None and full_day_temperatures:
            high = max(full_day_temperatures)
        if low is None and full_day_temperatures:
            low = min(full_day_temperatures)
        rain_values = full_day_rain or list(values_for_day["rain"])
        for period in matching_periods:
            value = period.get("probabilityOfPrecipitation", {}).get("value")
            if value is not None:
                rain_values.append(value)
        daily.append(
            {
                "date": target_date.isoformat(),
                "day": daily_heading(local_now + timedelta(days=day_offset), day_offset),
                "summary": summary,
                "icon": weather_icon_kind(
                    summary=summary,
                    rain=max(rain_values) if rain_values else None,
                    is_raining=is_raining and day_offset == 0,
                ),
                "high": fmt(high, "°F"),
                "low": fmt(low, "°F"),
                "rain": fmt(max(rain_values) if rain_values else None, "%"),
            }
        )

    update_time = grid.get("updateTime")
    updated = (
        datetime.fromisoformat(update_time.replace("Z", "+00:00"))
        if update_time
        else now
    )
    return {
        "updated_at": updated.astimezone(ARIZONA_TZ).isoformat(),
        "current_summary": periods[0].get("shortForecast", "Current conditions"),
        "current_icon": current_weather_icon_kind(
            grid, periods[0], now, is_raining
        ),
        "hourly": hourly,
        "hours": [
            {
                "timestamp": hour.isoformat(),
                "time": hour.strftime("%-I %p"),
                "day": hour.strftime("%a"),
            }
            for hour in hours
        ],
        "rows": [
            {"label": label, "values": values}
            for label, values in rows.items()
        ],
        "daily": daily,
    }


def get_nws_alerts() -> list[dict]:
    response = fetch_json(NWS_ALERTS_URL, NWS_HEADERS)
    alerts = []
    for feature in response.get("features", []):
        properties = feature.get("properties", {})
        event = properties.get("event")
        if not event:
            continue
        alerts.append(
            {
                "event": event,
                "headline": properties.get("headline") or event,
                "severity": properties.get("severity") or "Unknown",
                "url": properties.get("@id") or feature.get("id") or NWS_ALERTS_URL,
            }
        )
    return alerts[:3]


def parse_wms_times(xml_data: bytes, layer_name: str) -> list[datetime]:
    root = ET.fromstring(xml_data)
    for layer in root.iter():
        if layer.tag.rsplit("}", 1)[-1] != "Layer":
            continue
        name = next(
            (
                child.text
                for child in layer
                if child.tag.rsplit("}", 1)[-1] == "Name"
            ),
            None,
        )
        if name != layer_name:
            continue
        dimension = next(
            (
                child
                for child in layer
                if child.tag.rsplit("}", 1)[-1] == "Dimension"
                and child.attrib.get("name") == "time"
            ),
            None,
        )
        if dimension is not None and dimension.text:
            return [
                datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                for value in dimension.text.split(",")
                if value.strip()
            ]
    raise ValueError(f"NOAA nowCOAST did not list timestamps for {layer_name}")


def select_four_hour_timeline(
    available_times: list[datetime], frame_count: int = 24
) -> list[datetime]:
    """Select evenly spaced WMS timestamps across the latest four hours."""
    if not available_times:
        return []
    latest = max(available_times)
    window_start = latest - timedelta(hours=4)
    window = sorted(value for value in available_times if value >= window_start)
    if len(window) <= frame_count:
        return window
    last_index = len(window) - 1
    indices = [round(index * last_index / (frame_count - 1)) for index in range(frame_count)]
    return [window[index] for index in indices]


def round_to_five_minutes(timestamp: datetime) -> datetime:
    """Return the nearest five-minute IEM mosaic timestamp."""
    timestamp = timestamp.astimezone(UTC)
    elapsed = timestamp.minute * 60 + timestamp.second
    rounded = int((elapsed + 150) // 300) * 5
    return timestamp.replace(minute=0, second=0, microsecond=0) + timedelta(
        minutes=rounded
    )


def nesdis_cloud_url(raster_id: int) -> str:
    params = {
        "bbox": ",".join(str(value) for value in RADAR_BBOX_WEB_MERCATOR),
        "bboxSR": 3857,
        "imageSR": 3857,
        "size": f"{RADAR_FRAME_WIDTH},{RADAR_FRAME_HEIGHT}",
        "format": "png32",
        "transparent": "false",
        "interpolation": "RSP_BilinearInterpolation",
        "mosaicRule": json.dumps(
            {
                "mosaicMethod": "esriMosaicLockRaster",
                "lockRasterIds": [raster_id],
            },
            separators=(",", ":"),
        ),
        "f": "image",
    }
    return f"{NESDIS_CLOUD_IMAGE_SERVER}/exportImage?{urlencode(params)}"


def get_cloud_records() -> list[dict]:
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": "objectid,name,start_time,end_time",
        "orderByFields": "start_time DESC",
        "resultRecordCount": 200,
        "returnGeometry": "false",
    }
    records = []
    for attempt in range(3):
        response = fetch_json(f"{NESDIS_CLOUD_QUERY}?{urlencode(params)}")
        records = []
        for feature in response.get("features", []):
            attributes = feature.get("attributes", {})
            if (
                attributes.get("objectid") is None
                or attributes.get("start_time") is None
            ):
                continue
            records.append(
                {
                    "raster_id": int(attributes["objectid"]),
                    "timestamp": datetime.fromtimestamp(
                        attributes["start_time"] / 1000, UTC
                    ),
                }
            )
        if records:
            break
        if attempt < 2:
            time.sleep(attempt + 1)
    if not records:
        raise ValueError("NOAA/NESDIS did not list ABI Band 13 archive records")
    latest = max(record["timestamp"] for record in records)
    window = sorted(
        (
            record
            for record in records
            if record["timestamp"] >= latest - timedelta(hours=4)
        ),
        key=lambda record: record["timestamp"],
    )
    if len(window) <= 24:
        return window
    indices = [round(index * (len(window) - 1) / 23) for index in range(24)]
    return [window[index] for index in indices]


def nowcoast_radar_url(timestamp: datetime) -> str:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "conus_base_reflectivity_mosaic",
        "STYLES": "weather_radar_base_reflectivity",
        "SRS": "EPSG:3857",
        "BBOX": ",".join(str(value) for value in RADAR_BBOX_WEB_MERCATOR),
        "WIDTH": RADAR_FRAME_WIDTH,
        "HEIGHT": RADAR_FRAME_HEIGHT,
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
        "TIME": timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return f"{NOWCOAST_RADAR_WMS}?{urlencode(params)}"


def iem_radar_url(timestamp: datetime) -> str:
    """Build a full-detail IEM N0Q/N0B mosaic request for the Tucson region."""
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "nexrad-n0q-wmst",
        "STYLES": "",
        "SRS": "EPSG:3857",
        "BBOX": ",".join(str(value) for value in RADAR_BBOX_WEB_MERCATOR),
        "WIDTH": RADAR_FRAME_WIDTH,
        "HEIGHT": RADAR_FRAME_HEIGHT,
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
        "TIME": timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return f"{IEM_NEXRAD_WMS}?{urlencode(params)}"


def cloud_alpha(value: int) -> int:
    """Turn the dark ABI13 surface into transparent, pale cloud cover."""
    if value <= 42:
        return 0
    return min(225, round((value - 42) * 1.65))


def write_cloud_overlay(source_url: str, output_path: Path) -> None:
    """Download one NOAA ABI13 frame and retain only its cloud signal."""
    raw_image = fetch_bytes(source_url)
    with Image.open(BytesIO(raw_image)) as source:
        gray = ImageOps.grayscale(source.convert("RGB"))
        alpha = gray.point(cloud_alpha)
        cloud = Image.new("RGBA", source.size, (242, 245, 249, 0))
        cloud.putalpha(alpha)
        cloud.save(output_path, "WEBP", lossless=True, method=6)


def get_imagery(output_dir: Path) -> dict:
    cloud_records = get_cloud_records()
    try:
        fallback_radar_times = parse_wms_times(
            fetch_bytes(NOWCOAST_CAPABILITIES),
            "conus_base_reflectivity_mosaic",
        )
    except Exception:
        fallback_radar_times = []

    generated_at = int(time.time())
    staging_dir = output_dir.with_name(f".{output_dir.name}-staging")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    cloud_jobs = []
    frames = []
    for index, record in enumerate(cloud_records):
        satellite_time = record["timestamp"]
        radar_time = round_to_five_minutes(satellite_time)
        offset = round(abs((radar_time - satellite_time).total_seconds()) / 60)
        filename = f"cloud-{index:02d}.webp"
        cloud_jobs.append(
            (nesdis_cloud_url(record["raster_id"]), staging_dir / filename)
        )
        frame = {
            "satellite_url": f"data/imagery/{filename}?v={generated_at}",
            "satellite_timestamp": satellite_time.isoformat(),
            "radar_url": iem_radar_url(radar_time),
            "radar_timestamp": radar_time.isoformat(),
            "offset_minutes": offset,
        }
        if fallback_radar_times:
            fallback_time = min(
                fallback_radar_times,
                key=lambda candidate: abs(candidate - satellite_time),
            )
            if abs(fallback_time - satellite_time) <= timedelta(minutes=3):
                frame["radar_fallback_url"] = nowcoast_radar_url(fallback_time)
        frames.append(frame)

    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(write_cloud_overlay, source_url, path)
                for source_url, path in cloud_jobs
            ]
            for future in futures:
                future.result()
        if output_dir.exists():
            shutil.rmtree(output_dir)
        staging_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return {
        "frames": frames,
        "product": "NOAA GOES ABI Band 13 clouds + IEM NEXRAD reflectivity",
        "bounds": [
            [RADAR_BBOX[1], RADAR_BBOX[0]],
            [RADAR_BBOX[3], RADAR_BBOX[2]],
        ],
        "location": {"lat": TUCSON_LAT, "lon": TUCSON_LON},
        "sources": {
            "satellite": NOAA_SATELLITE_SOURCE,
            "radar": IEM_RADAR_SOURCE,
            "nws": NWS_SOURCE,
        },
    }


def sanitized_error(error: Exception) -> str:
    message = re.sub(r"token=[^&\s]+", "token=[redacted]", str(error), flags=re.I)
    return f"{type(error).__name__}: {message}"


def load_existing(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": 1}


def build_payload(output_path: Path) -> dict:
    now = datetime.now(ARIZONA_TZ)
    payload = load_existing(output_path)
    payload["schema_version"] = 1
    payload["generated_at"] = now.isoformat()
    payload["next_refresh_at"] = next_scheduled_refresh(now).isoformat()
    payload["errors"] = {}
    payload["is_raining"] = False

    for section, loader in (
        ("tempest", get_tempest_weather),
        ("air_quality", get_air_quality),
        (
            "forecast",
            lambda: get_nws_forecast(now, bool(payload.get("is_raining"))),
        ),
        ("alerts", get_nws_alerts),
        ("imagery", lambda: get_imagery(output_path.parent / "imagery")),
    ):
        try:
            result = loader()
            if section == "tempest":
                payload.update(result)
            else:
                payload[section] = result
        except Exception as error:
            payload["errors"][section] = sanitized_error(error)
            print(f"warning: {section}: {payload['errors'][section]}")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "weather.json",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    payload = build_payload(args.output)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    print(
        f"wrote {args.output} with "
        f"{len(payload.get('imagery', {}).get('frames', []))} synchronized frames"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
