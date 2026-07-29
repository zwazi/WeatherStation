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
  heroCondition: document.querySelector("#hero-condition"),
  heroIcon: document.querySelector("#hero-icon"),
  details: document.querySelector("#condition-sections"),
  satelliteImage: document.querySelector("#satellite-image"),
  radarImage: document.querySelector("#radar-image"),
  radarReference: document.querySelector("#radar-reference"),
  satelliteMarker: document.querySelector("#satellite-marker"),
  satelliteTime: document.querySelector("#satellite-time"),
  satelliteStatus: document.querySelector("#satellite-status"),
  imageryLoader: document.querySelector("#imagery-loader"),
  timeline: document.querySelector("#timeline"),
  timelineRange: document.querySelector("#timeline-range"),
  timelineOutput: document.querySelector("#timeline-output"),
  hourlyForecast: document.querySelector("#hourly-forecast"),
  dailyPrimary: document.querySelector("#daily-primary"),
  dailySecondary: document.querySelector("#daily-secondary"),
  forecastDetail: document.querySelector("#forecast-detail-table"),
};

const state = {
  data: null,
  generatedAt: null,
  frames: [],
  frameIndex: 0,
  timer: null,
  imageryGeneration: 0,
  paused: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  loading: false,
};

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
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

function dailySummary(day, label = null) {
  const article = createElement("article", "daily-summary");
  const text = createElement("div", "daily-summary__text");
  text.append(
    createElement("h3", "", label || day.day || "Forecast"),
    createElement("p", "", day.summary || "Forecast available"),
  );
  const values = createElement("div", "daily-summary__values");
  values.append(
    createElement("p", "daily-summary__rain", `● ${day.rain || "—"}`),
    createElement("p", "", `↓ ${day.low || "—"}`),
    createElement("p", "", `↑ ${day.high || "—"}`),
  );
  article.append(text, weatherIcon(day.icon || "cloudy", "weather-icon--daily"), values);
  return article;
}

function tomorrowLabel(dayLabel = "") {
  const date = String(dayLabel).match(/\b\d{1,2}\/\d{1,2}\b/)?.[0];
  return date ? `Tomorrow  ${date}` : "Tomorrow";
}

function renderHourly(hours = []) {
  elements.hourlyForecast.replaceChildren();
  for (const hour of hours) {
    const article = createElement("article", "hour-card");
    article.append(
      createElement("p", "hour-card__time", hour.time || "—"),
      createElement("p", "hour-card__day", hour.day || ""),
      weatherIcon(hour.icon || "cloudy", "weather-icon--hourly"),
      createElement("p", "hour-card__temperature", hour.temperature || "—"),
      createElement("p", "hour-card__metric", `● ${hour.precipitation || "—"}`),
      createElement("p", "hour-card__metric hour-card__wind", `➤ ${hour.wind || "—"}`),
    );
    elements.hourlyForecast.append(article);
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
  elements.hourlyForecast.replaceChildren();
  elements.forecastDetail.replaceChildren();
  if (!forecast) {
    return;
  }
  const [today, ...laterDays] = forecast.daily || [];
  if (today) elements.dailyPrimary.append(dailySummary(today));
  laterDays.forEach((day, index) => {
    elements.dailySecondary.append(dailySummary(day, index === 0 ? tomorrowLabel(day.day) : null));
  });
  renderHourly(forecast.hourly || []);
  elements.forecastDetail.append(buildDetailedForecast(forecast));
}

function positionMarker(element, marker) {
  if (!marker) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.style.left = `${marker.x * 100}%`;
  element.style.top = `${marker.y * 100}%`;
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
  if (!state.frames.length) return;
  state.frameIndex = ((index % state.frames.length) + state.frames.length) % state.frames.length;
  const prepared = state.frames[state.frameIndex];
  const frame = prepared.metadata;
  elements.satelliteImage.src = prepared.satellite.url;
  elements.radarImage.src = prepared.radar.url;
  elements.satelliteTime.textContent = (
    `${frameLabel(frame.satellite_timestamp)} · rain ${frameLabel(frame.radar_timestamp)} · Arizona`
  );
  const radarName = prepared.radar.fallback ? "NOAA MRMS fallback" : "IEM NEXRAD";
  elements.satelliteStatus.textContent = (
    `Frame ${state.frameIndex + 1} of ${state.frames.length} · GeoColor + ${radarName} · `
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
  clearAnimationTimer();
  const generation = ++state.imageryGeneration;
  state.frames = [];
  state.frameIndex = 0;
  elements.timeline.hidden = true;
  elements.imageryLoader.hidden = false;

  const rawFrames = imagery?.frames || [];
  if (!imagery || !rawFrames.length) {
    elements.imageryLoader.hidden = true;
    elements.satelliteTime.textContent = "Combined imagery unavailable";
    elements.satelliteStatus.textContent = "Use the source buttons to view the imagery providers.";
    return;
  }

  const { markers = {} } = imagery;
  elements.radarReference.src = imagery.reference_map_url || "";
  positionMarker(elements.satelliteMarker, markers.radar || markers.satellite);
  elements.satelliteStatus.textContent = `Preloading ${rawFrames.length} matched satellite and radar frames…`;

  Promise.all(rawFrames.map(prepareFrame)).then((preparedFrames) => {
    if (generation !== state.imageryGeneration) return;
    state.frames = preparedFrames.filter((frame) => frame.ready);
    elements.imageryLoader.hidden = true;
    if (!state.frames.length) {
      elements.satelliteTime.textContent = "Combined imagery unavailable";
      elements.satelliteStatus.textContent = "Satellite or radar images could not be loaded.";
      return;
    }
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

loadData({ force: true });
window.setInterval(() => loadData(), 60_000);
