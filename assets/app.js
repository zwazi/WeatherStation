"use strict";

const DATA_URL = "data/weather.json";
const ARIZONA_TIME_ZONE = "America/Phoenix";

const elements = {
  progress: document.querySelector("#route-progress"),
  lastRefresh: document.querySelector("#last-refresh"),
  pageError: document.querySelector("#page-error"),
  sectionWarnings: document.querySelector("#section-warnings"),
  heroTemperature: document.querySelector("#hero-temperature"),
  heroFeels: document.querySelector("#hero-feels"),
  heroHumidity: document.querySelector("#hero-humidity"),
  heroPressure: document.querySelector("#hero-pressure"),
  heroLightning: document.querySelector("#hero-lightning"),
  heroWind: document.querySelector("#hero-wind"),
  heroUv: document.querySelector("#hero-uv"),
  heroRain: document.querySelector("#hero-rain"),
  heroAirQuality: document.querySelector("#hero-air-quality"),
  heroCondition: document.querySelector("#hero-condition"),
  heroIcon: document.querySelector("#hero-icon"),
  details: document.querySelector("#condition-sections"),
  leafletMap: document.querySelector("#leaflet-map"),
  satelliteTime: document.querySelector("#satellite-time"),
  satelliteStatus: document.querySelector("#satellite-status"),
  imageryLoader: document.querySelector("#imagery-loader"),
  timeline: document.querySelector("#timeline"),
  timelineRange: document.querySelector("#timeline-range"),
  timelineOutput: document.querySelector("#timeline-output"),
  hourlyForecastToday: document.querySelector("#hourly-forecast-today"),
  hourlyForecastTomorrow: document.querySelector("#hourly-forecast-tomorrow"),
  dailyPrimary: document.querySelector("#daily-primary"),
  dailySecondary: document.querySelector("#daily-secondary"),
  forecastDetail: document.querySelector("#forecast-detail-table"),
};

const ICON_SVG = {
  humidity: '<path d="M12 2.5S5.5 9.4 5.5 14a6.5 6.5 0 0 0 13 0C18.5 9.4 12 2.5 12 2.5Z"/><path d="M9 15.5a3.5 3.5 0 0 0 3.5 2.5"/>',
  pressure: '<circle cx="12" cy="12" r="9"/><path d="M12 7v2m5-1-1.5 1.5M7 8l1.5 1.5M12 12l4-2"/><circle cx="12" cy="12" r="1" class="icon-fill"/>',
  lightning: '<path d="m13 2-7 12h6l-1 8 7-12h-6l1-8Z"/>',
  wind: '<path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  rain: '<path d="M12 2.5S6 9.2 6 14a6 6 0 0 0 12 0c0-4.8-6-11.5-6-11.5Z"/>',
  airQuality: '<path d="M12 3v9"/><path d="M10 8.5c-2-1-4 .4-5 3l-1.4 4.2C2.8 18.2 4.5 21 7 21c2.8 0 4-2.1 4-5V10"/><path d="M14 8.5c2-1 4 .4 5 3l1.4 4.2c.8 2.5-.9 5.3-3.4 5.3-2.8 0-4-2.1-4-5V10"/>',
  direction: '<path class="icon-fill" d="M12 2 18 21l-6-4-6 4 6-19Z"/>',
};

const state = {
  data: null,
  generatedAt: null,
  frames: [],
  frameIndex: 0,
  timer: null,
  imageryGeneration: 0,
  map: null,
  cloudLayer: null,
  radarLayer: null,
  stationMarker: null,
  imageryBounds: null,
  mapFitted: false,
  paused: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  loading: false,
};

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function vectorIcon(name, className = "") {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("aria-hidden", "true");
  icon.classList.add("vector-icon");
  if (className) icon.classList.add(...className.split(" "));
  icon.innerHTML = ICON_SVG[name] || ICON_SVG.wind;
  return icon;
}

function installMetricIcons() {
  for (const holder of document.querySelectorAll("[data-metric-icon]")) {
    holder.replaceChildren(vectorIcon(holder.dataset.metricIcon));
  }
}

function formatArizonaDateTime(isoString, includeSeconds = false) {
  if (!isoString) return "—";
  const value = new Date(isoString);
  if (Number.isNaN(value.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: ARIZONA_TIME_ZONE,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    timeZoneName: "short",
  }).format(value);
}

function formatArizonaTime(isoString) {
  if (!isoString) return "—";
  const value = new Date(isoString);
  if (Number.isNaN(value.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: ARIZONA_TIME_ZONE,
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(value);
}

function setProgress(mode) {
  elements.progress.classList.remove("is-loading", "is-complete");
  if (mode) elements.progress.classList.add(mode);
}

function findCard(data, label) {
  return (data.cards || []).find((card) => card.label === label) || {};
}

function findDetail(data, sectionTitle, rowLabel) {
  const section = (data.details || []).find((item) => item.title === sectionTitle);
  const row = section?.rows?.find(([label]) => label === rowLabel);
  return row?.[1] || "—";
}

function roundedTemperature(value) {
  const match = String(value || "").match(/-?\d+(?:\.\d+)?/);
  const parsed = match ? Number.parseFloat(match[0]) : Number.NaN;
  return Number.isFinite(parsed) ? `${Math.round(parsed)}°` : "—°";
}

function iconClass(kind = "cloudy") {
  return `weather-icon--${kind}`;
}

function setWeatherIcon(element, kind) {
  for (const className of [...element.classList]) {
    if (className.startsWith("weather-icon--") && className !== "weather-icon--large") {
      element.classList.remove(className);
    }
  }
  element.classList.add(iconClass(kind));
}

function renderCurrent(data) {
  const temperature = findCard(data, "Temperature");
  const humidity = findCard(data, "Humidity");
  const wind = findCard(data, "Wind");
  const rain = findCard(data, "Rain Today");
  const lightning = findCard(data, "Lightning");
  const uv = findCard(data, "UV / Light");
  const direction = (wind.detail || "").split("·").at(-1)?.trim().split(" ")[0] || "";

  elements.heroTemperature.textContent = roundedTemperature(temperature.value);
  elements.heroFeels.textContent = roundedTemperature(temperature.detail);
  elements.heroHumidity.textContent = humidity.value || "—";
  elements.heroPressure.textContent = findDetail(data, "Pressure", "Sea-Level Pressure");
  elements.heroLightning.textContent = lightning.value === "0" ? "None" : `${lightning.value || "—"} strikes`;
  elements.heroWind.textContent = `${direction} ${wind.value || "—"}`.trim();
  elements.heroUv.textContent = uv.value || "—";
  elements.heroRain.textContent = rain.value || "—";
  const airQuality = data.air_quality || {};
  const aqi = Number(airQuality.us_aqi);
  elements.heroAirQuality.textContent = Number.isFinite(aqi)
    ? `${Math.round(aqi)} AQI · ${airQuality.category || "Current"}`
    : "— AQI";
  const pm25 = Number(airQuality.pm2_5);
  elements.heroAirQuality.parentElement.title = Number.isFinite(pm25)
    ? `Modeled PM2.5 ${pm25.toFixed(1)} µg/m³ · ${formatArizonaDateTime(airQuality.updated_at)}`
    : "Current U.S. Air Quality Index";

  const forecast = data.forecast || {};
  elements.heroCondition.textContent = forecast.current_summary || "Current conditions";
  setWeatherIcon(elements.heroIcon, forecast.current_icon || "cloudy");
}

function renderDetails(sections = []) {
  elements.details.replaceChildren();
  for (const section of sections) {
    const container = createElement("section", "detail-section");
    container.append(createElement("h3", "", section.title));
    const list = createElement("dl", "detail-list");
    for (const [label, value] of section.rows || []) {
      const row = createElement("div", "detail-row");
      row.append(createElement("dt", "", label), createElement("dd", "", value));
      list.append(row);
    }
    container.append(list);
    elements.details.append(container);
  }
}

function weatherIcon(kind, extraClass = "") {
  const icon = createElement("span", `weather-icon ${iconClass(kind)} ${extraClass}`.trim());
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

function metricWithIcon(className, iconName, text) {
  const metric = createElement("p", className);
  metric.append(vectorIcon(iconName), document.createTextNode(text));
  return metric;
}

function dailySummary(day) {
  const article = createElement("article", "daily-summary");
  const text = createElement("div", "daily-summary__text");
  text.append(
    createElement("h3", "", day.day || "Forecast"),
    createElement("p", "", day.summary || "Forecast available"),
  );
  const values = createElement("div", "daily-summary__values");
  values.append(
    metricWithIcon("daily-summary__rain", "rain", day.rain || "—"),
    createElement("p", "", `↓ ${day.low || "—"}`),
    createElement("p", "", `↑ ${day.high || "—"}`),
  );
  article.append(text, weatherIcon(day.icon || "cloudy", "weather-icon--daily"), values);
  return article;
}

function renderHourly(container, hours = []) {
  container.replaceChildren();
  for (const hour of hours) {
    const article = createElement("article", "hour-card");
    const rain = metricWithIcon("hour-card__metric", "rain", hour.precipitation || "—");
    const direction = Number(hour.wind_degrees);
    const hasDirection = Number.isFinite(direction) && hour.wind_direction;
    const windIcon = vectorIcon(hasDirection ? "direction" : "wind", "hour-card__wind-icon");
    if (hasDirection) {
      windIcon.style.transform = `rotate(${(direction + 180) % 360}deg)`;
    }
    const wind = createElement("p", "hour-card__metric hour-card__wind");
    wind.title = hasDirection ? `Wind from ${hour.wind_direction}` : "Wind speed";
    wind.append(
      windIcon,
      document.createTextNode(
        `${hasDirection ? `${hour.wind_direction} ` : ""}${hour.wind || "—"}`,
      ),
    );
    article.append(
      createElement("p", "hour-card__time", hour.time || "—"),
      createElement("p", "hour-card__day", hour.day || ""),
      weatherIcon(hour.icon || "cloudy", "weather-icon--hourly"),
      createElement("p", "hour-card__temperature", hour.temperature || "—"),
      rain,
      wind,
    );
    container.append(article);
  }
}

function buildDetailedForecast(forecast) {
  const table = createElement("table", "forecast-table");
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const metricHeader = createElement("th", "", "Metric");
  metricHeader.scope = "col";
  headerRow.append(metricHeader);
  for (const hour of forecast.hours || []) {
    const cell = createElement("th", "", `${hour.time} ${hour.day}`);
    cell.scope = "col";
    headerRow.append(cell);
  }
  head.append(headerRow);
  table.append(head);
  const body = document.createElement("tbody");
  for (const rowData of forecast.rows || []) {
    const row = document.createElement("tr");
    const label = createElement("th", "", rowData.label);
    label.scope = "row";
    row.append(label);
    for (const value of rowData.values || []) row.append(createElement("td", "", value));
    body.append(row);
  }
  table.append(body);
  return table;
}

function renderForecast(forecast) {
  elements.dailyPrimary.replaceChildren();
  elements.dailySecondary.replaceChildren();
  elements.hourlyForecastToday.replaceChildren();
  elements.hourlyForecastTomorrow.replaceChildren();
  elements.forecastDetail.replaceChildren();
  if (!forecast) {
    return;
  }
  const [today, tomorrow] = forecast.daily || [];
  if (today) elements.dailyPrimary.append(dailySummary(today));
  if (tomorrow) elements.dailySecondary.append(dailySummary(tomorrow));
  const hourly = forecast.hourly || [];
  renderHourly(
    elements.hourlyForecastToday,
    hourly.filter((hour) => !today?.date || hour.date === today.date),
  );
  renderHourly(
    elements.hourlyForecastTomorrow,
    hourly.filter((hour) => tomorrow?.date && hour.date === tomorrow.date),
  );
  elements.forecastDetail.append(buildDetailedForecast(forecast));
}

function initializeRadarMap() {
  if (!window.L) throw new Error("Leaflet could not be loaded");
  const map = window.L.map(elements.leafletMap, {
    zoomControl: false,
    attributionControl: true,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    touchZoom: false,
    zoomSnap: 0,
    preferCanvas: true,
  });
  const imageryAttribution = (
    'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Vantor, Earthstar '
    + 'Geographics, GIS User Community · Labels &copy; Esri, HERE, Garmin, '
    + '<a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
  );
  window.L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: imageryAttribution },
  ).addTo(map);
  map.createPane("cloudPane");
  map.getPane("cloudPane").style.zIndex = "350";
  map.getPane("cloudPane").style.pointerEvents = "none";
  map.createPane("radarPane");
  map.getPane("radarPane").style.zIndex = "360";
  map.getPane("radarPane").style.pointerEvents = "none";
  map.createPane("referencePane");
  map.getPane("referencePane").style.zIndex = "400";
  map.getPane("referencePane").style.pointerEvents = "none";
  window.L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, pane: "referencePane" },
  ).addTo(map);
  state.map = map;
}

function configureRadarMap(imagery) {
  if (!state.map || !Array.isArray(imagery?.bounds)) return false;
  const bounds = window.L.latLngBounds(imagery.bounds);
  if (!bounds.isValid()) return false;
  state.imageryBounds = bounds;
  if (!state.mapFitted) {
    state.map.fitBounds(bounds, { animate: false, padding: [0, 0] });
    state.mapFitted = true;
    window.requestAnimationFrame(() => state.map.invalidateSize({ animate: false }));
  }

  const location = imagery.location;
  if (Number.isFinite(location?.lat) && Number.isFinite(location?.lon)) {
    if (!state.stationMarker) {
      state.stationMarker = window.L.circleMarker([location.lat, location.lon], {
        radius: 6,
        color: "#f8f7f3",
        weight: 3,
        fillColor: "#ed1b24",
        fillOpacity: 1,
        pane: "markerPane",
      }).addTo(state.map);
    } else {
      state.stationMarker.setLatLng([location.lat, location.lon]);
    }
  }
  return true;
}

function clearAnimationTimer() {
  if (state.timer !== null) {
    window.clearTimeout(state.timer);
    state.timer = null;
  }
}

function frameLabel(timestamp) {
  return formatArizonaDateTime(timestamp).replace(", MST", " MST");
}

function loadImage(primaryUrl, fallbackUrl = null) {
  const image = new Image();
  image.decoding = "async";
  return new Promise((resolve) => {
    let activeUrl = primaryUrl;
    let triedFallback = false;
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      resolve({ image, url: activeUrl, ok, fallback: triedFallback });
    };
    const timeout = window.setTimeout(() => finish(false), 30_000);
    image.onload = () => finish(true);
    image.onerror = () => {
      if (fallbackUrl && !triedFallback) {
        triedFallback = true;
        activeUrl = fallbackUrl;
        image.src = fallbackUrl;
      } else {
        finish(false);
      }
    };
    image.src = primaryUrl;
  });
}

function prepareFrame(frame) {
  return Promise.all([
    loadImage(frame.satellite_url),
    loadImage(frame.radar_url, frame.radar_fallback_url),
  ]).then(([satellite, radar]) => ({
    metadata: frame,
    satellite,
    radar,
    ready: satellite.ok && radar.ok,
  }));
}

function showFrame(index) {
  if (!state.frames.length || !state.map || !state.imageryBounds) return;
  state.frameIndex = ((index % state.frames.length) + state.frames.length) % state.frames.length;
  const prepared = state.frames[state.frameIndex];
  const frame = prepared.metadata;
  if (!state.cloudLayer) {
    state.cloudLayer = window.L.imageOverlay(prepared.satellite.url, state.imageryBounds, {
      pane: "cloudPane",
      opacity: 0.96,
      alt: "NOAA GOES infrared cloud cover",
      interactive: false,
    }).addTo(state.map);
  } else {
    state.cloudLayer.setBounds(state.imageryBounds).setUrl(prepared.satellite.url);
  }
  if (!state.radarLayer) {
    state.radarLayer = window.L.imageOverlay(prepared.radar.url, state.imageryBounds, {
      pane: "radarPane",
      opacity: 0.92,
      alt: "NEXRAD rain intensity mosaic",
      interactive: false,
    }).addTo(state.map);
  } else {
    state.radarLayer.setBounds(state.imageryBounds).setUrl(prepared.radar.url);
  }
  elements.satelliteTime.textContent = (
    `${frameLabel(frame.satellite_timestamp)} · rain ${frameLabel(frame.radar_timestamp)} · Arizona`
  );
  const radarName = prepared.radar.fallback ? "NOAA MRMS fallback" : "IEM NEXRAD";
  elements.satelliteStatus.textContent = (
    `Frame ${state.frameIndex + 1} of ${state.frames.length} · NOAA clouds + ${radarName} · `
    + `${frame.offset_minutes} min offset · synchronized 4-hour loop`
  );
  elements.timelineRange.value = String(state.frameIndex);
  elements.timelineOutput.value = `${state.frameIndex + 1} / ${state.frames.length}`;
  elements.timelineOutput.textContent = elements.timelineOutput.value;
}

function scheduleNextFrame() {
  clearAnimationTimer();
  if (state.paused || state.frames.length < 2 || document.hidden) return;
  const delay = state.frameIndex === state.frames.length - 1 ? 1400 : 450;
  state.timer = window.setTimeout(() => {
    showFrame(state.frameIndex + 1);
    scheduleNextFrame();
  }, delay);
}

function renderImagery(imagery) {
  const generation = ++state.imageryGeneration;
  const hasCurrentFrames = state.frames.length > 0;
  if (!hasCurrentFrames) {
    clearAnimationTimer();
    state.frameIndex = 0;
    elements.timeline.hidden = true;
    elements.imageryLoader.hidden = false;
  } else {
    elements.imageryLoader.hidden = true;
  }

  const rawFrames = imagery?.frames || [];
  if (!imagery || !rawFrames.length) {
    if (!hasCurrentFrames) {
      elements.imageryLoader.hidden = true;
      elements.satelliteTime.textContent = "Combined imagery unavailable";
    }
    elements.satelliteStatus.textContent = hasCurrentFrames
      ? "New imagery unavailable; continuing the previous loop."
      : "Combined imagery unavailable.";
    return;
  }

  elements.satelliteStatus.textContent = (
    `Preloading ${rawFrames.length} matched satellite and radar frames in the background…`
  );

  Promise.all(rawFrames.map(prepareFrame)).then((preparedFrames) => {
    if (generation !== state.imageryGeneration) return;
    const nextFrames = preparedFrames.filter((frame) => frame.ready);
    elements.imageryLoader.hidden = true;
    if (!nextFrames.length) {
      if (!hasCurrentFrames) elements.satelliteTime.textContent = "Combined imagery unavailable";
      elements.satelliteStatus.textContent = hasCurrentFrames
        ? "New imagery could not load; continuing the previous loop."
        : "Satellite or radar images could not be loaded.";
      return;
    }
    clearAnimationTimer();
    if (!configureRadarMap(imagery)) {
      elements.satelliteTime.textContent = "Map geometry unavailable";
      elements.satelliteStatus.textContent = "The weather overlays did not include valid map bounds.";
      return;
    }
    state.frames = nextFrames;
    state.frameIndex = 0;
    elements.timeline.hidden = state.frames.length < 2;
    elements.timelineRange.max = String(Math.max(0, state.frames.length - 1));
    showFrame(0);
    scheduleNextFrame();
  });
}

function renderWarnings(errors = {}) {
  const sections = Object.keys(errors);
  if (!sections.length) {
    elements.sectionWarnings.hidden = true;
    elements.sectionWarnings.textContent = "";
    return;
  }
  elements.sectionWarnings.textContent = (
    `Some upstream sections could not refresh (${sections.join(", ")}). `
    + "The most recent available values are shown."
  );
  elements.sectionWarnings.hidden = false;
}

function render(data) {
  state.data = data;
  state.generatedAt = data.generated_at;
  elements.lastRefresh.dateTime = data.generated_at || "";
  elements.lastRefresh.textContent = `Last refresh ${formatArizonaTime(data.generated_at)}`;
  elements.lastRefresh.title = `Weather data built ${formatArizonaDateTime(data.generated_at, true)}`;
  renderCurrent(data);
  renderDetails(data.details || []);
  renderForecast(data.forecast);
  renderImagery(data.imagery);
  renderWarnings(data.errors);
}

async function loadData({ force = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  setProgress("is-loading");
  try {
    const separator = DATA_URL.includes("?") ? "&" : "?";
    const response = await fetch(`${DATA_URL}${separator}v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Weather data request returned ${response.status}`);
    const data = await response.json();
    if (force || data.generated_at !== state.generatedAt) render(data);
    elements.pageError.hidden = true;
    elements.pageError.textContent = "";
  } catch (error) {
    elements.pageError.textContent = `Could not load the generated weather data. ${error.message}`;
    elements.pageError.hidden = false;
  } finally {
    state.loading = false;
    setProgress("is-complete");
    window.setTimeout(() => setProgress(null), 220);
  }
}

elements.timelineRange.addEventListener("input", (event) => {
  showFrame(Number(event.target.value));
  scheduleNextFrame();
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearAnimationTimer();
  else scheduleNextFrame();
});

installMetricIcons();
try {
  initializeRadarMap();
  loadData({ force: true });
} catch (error) {
  elements.imageryLoader.hidden = true;
  elements.pageError.textContent = `Could not initialize the weather map. ${error.message}`;
  elements.pageError.hidden = false;
}
window.setInterval(() => loadData(), 60_000);
