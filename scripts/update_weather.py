#!/usr/bin/env python3
"""Build the sanitized JSON consumed by the WeatherStation Pages site."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


ARIZONA_TZ = ZoneInfo("America/Phoenix")
UTC = ZoneInfo("UTC")
STATION_ID = os.environ.get("TEMPEST_STATION_ID", "000000")
DEVICE_ID = os.environ.get("TEMPEST_DEVICE_ID", "000000")
TEMPEST_TOKEN = os.environ.get("TEMPEST_TOKEN", "")

REGIONAL_LAT = 32.2
REGIONAL_LON = -110.9
RADAR_BBOX = (-116.0, 29.0, -108.0, 36.0)
RADAR_FRAME_SIZE = 600
FORECAST_HOURS = 12
REFRESH_MINUTES = (1, 11, 21, 31, 41, 51)

NOWCOAST_SATELLITE_WMS = "https://nowcoast.noaa.gov/geoserver/satellite/wms"
NOWCOAST_SATELLITE_CAPABILITIES = (
    f"{NOWCOAST_SATELLITE_WMS}?service=WMS&version=1.3.0&request=GetCapabilities"
)
NOWCOAST_SATELLITE_LAYER = "goes_longwave_imagery"
NOAA_SATELLITE_SOURCE = "https://nowcoast.noaa.gov/"
NOAA_RADAR_SOURCE = "https://nowcoast.noaa.gov/"
NOWCOAST_RADAR_WMS = "https://nowcoast.noaa.gov/geoserver/weather_radar/wms"
NOWCOAST_CAPABILITIES = (
    f"{NOWCOAST_RADAR_WMS}?service=WMS&version=1.3.0&request=GetCapabilities"
)
NWS_REFERENCE_WMS = (
    "https://mapservices.weather.noaa.gov/static/services/"
    "nws_reference_maps/nws_reference_map/MapServer/WMSServer"
)
NWS_POINT_URL = f"https://api.weather.gov/points/{REGIONAL_LAT},{REGIONAL_LON}"
NWS_SOURCE = (
    "https://forecast.weather.gov/MapClick.php?lat=32.2&lon=-110.9"
    "&unit=0&lg=english&FcstType=graphical"
)

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


def get_nws_forecast(now: datetime) -> dict:
    point = fetch_json(NWS_POINT_URL, NWS_HEADERS)["properties"]
    grid = fetch_json(point["forecastGridData"], NWS_HEADERS)["properties"]
    periods = fetch_json(point["forecast"], NWS_HEADERS)["properties"]["periods"]

    first_hour = now.astimezone(ARIZONA_TZ).replace(minute=0, second=0, microsecond=0)
    hours = [first_hour + timedelta(hours=offset) for offset in range(FORECAST_HOURS)]
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

    daily = []
    for index, period in enumerate(periods):
        if not period.get("isDaytime"):
            continue
        night = next(
            (
                candidate
                for candidate in periods[index + 1 :]
                if not candidate.get("isDaytime")
            ),
            None,
        )
        start = datetime.fromisoformat(period["startTime"]).astimezone(ARIZONA_TZ)
        day_name = "Today" if start.date() == first_hour.date() else start.strftime("%A")
        day_pop = period.get("probabilityOfPrecipitation", {}).get("value")
        night_pop = (
            night.get("probabilityOfPrecipitation", {}).get("value") if night else None
        )
        rain_values = [value for value in (day_pop, night_pop) if value is not None]
        daily.append(
            {
                "day": f"{day_name}  {start.strftime('%-m/%-d')}",
                "high": fmt(period.get("temperature"), "°F"),
                "low": fmt(night.get("temperature") if night else None, "°F"),
                "rain": fmt(max(rain_values) if rain_values else None, "%"),
            }
        )
        if len(daily) == 2:
            break

    update_time = grid.get("updateTime")
    updated = (
        datetime.fromisoformat(update_time.replace("Z", "+00:00"))
        if update_time
        else now
    )
    return {
        "updated_at": updated.astimezone(ARIZONA_TZ).isoformat(),
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


def nowcoast_satellite_url(timestamp: datetime) -> str:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": NOWCOAST_SATELLITE_LAYER,
        "STYLES": "",
        "SRS": "EPSG:4326",
        "BBOX": ",".join(str(value) for value in RADAR_BBOX),
        "WIDTH": RADAR_FRAME_SIZE,
        "HEIGHT": RADAR_FRAME_SIZE,
        "FORMAT": "image/png",
        "TRANSPARENT": "false",
        "TIME": timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return f"{NOWCOAST_SATELLITE_WMS}?{urlencode(params)}"


def nowcoast_radar_url(timestamp: datetime) -> str:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "conus_base_reflectivity_mosaic",
        "STYLES": "weather_radar_base_reflectivity",
        "SRS": "EPSG:4326",
        "BBOX": ",".join(str(value) for value in RADAR_BBOX),
        "WIDTH": RADAR_FRAME_SIZE,
        "HEIGHT": RADAR_FRAME_SIZE,
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
        "TIME": timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return f"{NOWCOAST_RADAR_WMS}?{urlencode(params)}"


def nws_reference_map_url() -> str:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "8,9",
        "STYLES": ",",
        "SRS": "EPSG:4326",
        "BBOX": ",".join(str(value) for value in RADAR_BBOX),
        "WIDTH": RADAR_FRAME_SIZE,
        "HEIGHT": RADAR_FRAME_SIZE,
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
    }
    return f"{NWS_REFERENCE_WMS}?{urlencode(params)}"


def get_imagery() -> dict:
    available_satellite_times = parse_wms_times(
        fetch_bytes(NOWCOAST_SATELLITE_CAPABILITIES),
        NOWCOAST_SATELLITE_LAYER,
    )
    radar_times = parse_wms_times(
        fetch_bytes(NOWCOAST_CAPABILITIES),
        "conus_base_reflectivity_mosaic",
    )
    aligned_satellite_times = [
        satellite_time
        for satellite_time in available_satellite_times
        if abs(
            min(
                radar_times,
                key=lambda candidate: abs(candidate - satellite_time),
            )
            - satellite_time
        )
        <= timedelta(minutes=3)
    ]
    satellite_times = select_four_hour_timeline(aligned_satellite_times)
    if not satellite_times:
        raise ValueError("NOAA did not publish aligned GOES and MRMS timestamps")
    frames = []
    for satellite_time in satellite_times:
        radar_time = min(
            radar_times,
            key=lambda candidate: abs(candidate - satellite_time),
        )
        offset = round(abs((radar_time - satellite_time).total_seconds()) / 60)
        frames.append(
            {
                "satellite_url": nowcoast_satellite_url(satellite_time),
                "satellite_timestamp": satellite_time.isoformat(),
                "radar_url": nowcoast_radar_url(radar_time),
                "radar_timestamp": radar_time.isoformat(),
                "offset_minutes": offset,
            }
        )

    radar_marker_x = (REGIONAL_LON - RADAR_BBOX[0]) / (RADAR_BBOX[2] - RADAR_BBOX[0])
    radar_marker_y = (RADAR_BBOX[3] - REGIONAL_LAT) / (RADAR_BBOX[3] - RADAR_BBOX[1])
    return {
        "frames": frames,
        "product": "NOAA GOES longwave satellite + MRMS reflectivity",
        "reference_map_url": nws_reference_map_url(),
        "markers": {
            "satellite": {"x": 311 / 600, "y": 302 / 600},
            "radar": {"x": radar_marker_x, "y": radar_marker_y},
        },
        "sources": {
            "satellite": NOAA_SATELLITE_SOURCE,
            "radar": NOAA_RADAR_SOURCE,
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

    for section, loader in (
        ("tempest", get_tempest_weather),
        ("forecast", lambda: get_nws_forecast(now)),
        ("imagery", get_imagery),
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
