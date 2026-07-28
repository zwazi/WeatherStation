"use strict";

const DATA_URL = "data/weather.json";
const ARIZONA_TIME_ZONE = "America/Phoenix";

const elements = {
  progress: document.querySelector("#route-progress"),
  refresh: document.querySelector("#refresh-data"),
  pageError: document.querySelector("#page-error"),
  sectionWarnings: document.querySelector("#section-warnings"),
  stationNumber: document.querySelector("#station-number"),
  stationMeta: document.querySelector("#station-meta"),
  cards: document.querySelector("#current-cards"),
  details: document.querySelector("#condition-sections"),
  pause: document.querySelector("#pause-loop"),
  satelliteSource: document.querySelector("#satellite-source"),
  radarSource: document.querySelector("#radar-source"),
  nwsSource: document.querySelector("#nws-source"),
  satelliteImage: document.querySelector("#satellite-image"),
  radarImage: document.querySelector("#radar-image"),
  radarReference: document.querySelector("#radar-reference"),
  satelliteMarker: document.querySelector("#satellite-marker"),
  radarMarker: document.querySelector("#radar-marker"),
  satelliteTime: document.querySelector("#satellite-time"),
  radarTime: document.querySelector("#radar-time"),
  satelliteStatus: document.querySelector("#satellite-status"),
  radarStatus: document.querySelector("#radar-status"),
  timeline: document.querySelector("#timeline"),
  timelineRange: document.querySelector("#timeline-range"),
  timelineOutput: document.querySelector("#timeline-output"),
  forecastUpdated: document.querySelector("#forecast-updated"),
  hourlyForecast: document.querySelector("#hourly-forecast"),
  dailyForecast: document.querySelector("#daily-forecast"),
  generatedAt: document.querySelector("#generated-at"),
};

const state = {
  data: null,
  generatedAt: null,
  frames: [],
  frameIndex: 0,
  timer: null,
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

function setProgress(mode) {
  elements.progress.classList.remove("is-loading", "is-complete");
  if (mode) elements.progress.classList.add(mode);
}

function renderHeader(data) {
  const station = data.station || {};
  elements.stationNumber.textContent = `Station ${station.id || "—"}`;
  elements.stationMeta.textContent = [
    `Updated ${formatArizonaDateTime(station.updated_at, true)}`,
    `Next data build ${formatArizonaDateTime(data.next_refresh_at)}`,
  ].join(" · ");
  elements.generatedAt.textContent = `Site data built ${formatArizonaDateTime(data.generated_at, true)}`;
}

function renderCards(cards = []) {
  elements.cards.replaceChildren();
  for (const card of cards) {
    const article = createElement("article", "signal-card");
    const header = createElement("div", "signal-card__header");
    header.append(
      createElement("p", "signal-card__label", card.label),
      createElement("p", "signal-card__code", card.signal),
    );
    article.append(
      header,
      createElement("p", "signal-card__value", card.value),
      createElement("p", "signal-card__detail", card.detail),
    );
    if (Number.isFinite(Number(card.meter))) {
      const meter = createElement("div", "signal-card__meter");
      const fill = createElement("span");
      fill.style.width = `${Math.max(0, Math.min(100, Number(card.meter)))}%`;
      meter.append(fill);
      article.append(meter);
    }
    elements.cards.append(article);
  }
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

function buildHourlyTable(forecast) {
  const table = createElement("table", "forecast-table forecast-table--hourly");
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const metricHeader = createElement("th", "", "Metric");
  metricHeader.scope = "col";
  headerRow.append(metricHeader);

  for (const hour of forecast.hours || []) {
    const heading = createElement("th", "hour-heading");
    heading.scope = "col";
    heading.append(
      createElement("span", "", hour.time),
      createElement("span", "", hour.day),
    );
    headerRow.append(heading);
  }
  head.append(headerRow);
  table.append(head);

  const body = document.createElement("tbody");
  for (const rowData of forecast.rows || []) {
    const row = document.createElement("tr");
    const label = createElement("th", "", rowData.label);
    label.scope = "row";
    row.append(label);
    for (const value of rowData.values || []) {
      row.append(createElement("td", "", value));
    }
    body.append(row);
  }
  table.append(body);
  return table;
}

function buildDailyTable(forecast) {
  const columns = [
    ["day", "Day"],
    ["high", "High temp"],
    ["low", "Low temp"],
    ["rain", "Rain % chance"],
  ];
  const table = createElement("table", "forecast-table forecast-table--daily");
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const [, label] of columns) {
    const cell = createElement("th", "", label);
    cell.scope = "col";
    headerRow.append(cell);
  }
  head.append(headerRow);
  table.append(head);

  const body = document.createElement("tbody");
  for (const day of forecast.daily || []) {
    const row = document.createElement("tr");
    for (const [key] of columns) row.append(createElement("td", "", day[key]));
    body.append(row);
  }
  table.append(body);
  return table;
}

function renderForecast(forecast) {
  elements.hourlyForecast.replaceChildren();
  elements.dailyForecast.replaceChildren();
  if (!forecast) {
    elements.forecastUpdated.textContent = "NWS forecast unavailable";
    return;
  }
  elements.forecastUpdated.textContent = `NWS grid updated ${formatArizonaDateTime(forecast.updated_at)}`;
  elements.hourlyForecast.append(buildHourlyTable(forecast));
  elements.dailyForecast.append(buildDailyTable(forecast));
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

function showFrame(index) {
  if (!state.frames.length) return;
  state.frameIndex = ((index % state.frames.length) + state.frames.length) % state.frames.length;
  const frame = state.frames[state.frameIndex];
  elements.satelliteImage.src = frame.satellite_url;
  elements.radarImage.src = frame.radar_url;
  elements.satelliteTime.textContent = `${frameLabel(frame.satellite_timestamp)} · Arizona`;
  elements.radarTime.textContent = `${frameLabel(frame.radar_timestamp)} · Arizona`;
  elements.satelliteStatus.textContent = (
    `Frame ${state.frameIndex + 1} of ${state.frames.length} · NOAA GOES GeoColor · synchronized 4-hour loop`
  );
  elements.radarStatus.textContent = (
    `Frame ${state.frameIndex + 1} of ${state.frames.length} · NOAA MRMS reflectivity · `
    + `${frame.offset_minutes} min from GOES`
  );
  elements.timelineRange.value = String(state.frameIndex);
  elements.timelineOutput.value = `${state.frameIndex + 1} / ${state.frames.length}`;
  elements.timelineOutput.textContent = elements.timelineOutput.value;
}

function scheduleNextFrame() {
  clearAnimationTimer();
  if (state.paused || state.frames.length < 2 || document.hidden) return;
  const delay = state.frameIndex === state.frames.length - 1 ? 1200 : 250;
  state.timer = window.setTimeout(() => {
    showFrame(state.frameIndex + 1);
    scheduleNextFrame();
  }, delay);
}

function updatePauseButton() {
  elements.pause.disabled = state.frames.length < 2;
  elements.pause.textContent = state.paused ? "Play" : "Pause";
  elements.pause.setAttribute("aria-pressed", String(state.paused));
}

function preloadFrames(frames) {
  for (const frame of frames) {
    const satellite = new Image();
    satellite.src = frame.satellite_url;
    const radar = new Image();
    radar.src = frame.radar_url;
  }
}

function renderImagery(imagery) {
  clearAnimationTimer();
  state.frames = imagery?.frames || [];
  state.frameIndex = 0;
  elements.timeline.hidden = state.frames.length < 2;
  elements.timelineRange.max = String(Math.max(0, state.frames.length - 1));

  if (!imagery || !state.frames.length) {
    elements.pause.disabled = true;
    elements.satelliteTime.textContent = "Satellite imagery unavailable";
    elements.radarTime.textContent = "Rain radar unavailable";
    elements.satelliteStatus.textContent = "Use the source button to view NOAA.";
    elements.radarStatus.textContent = "Use the source button to view NOAA nowCOAST.";
    return;
  }

  const { sources = {}, markers = {} } = imagery;
  if (sources.satellite) elements.satelliteSource.href = sources.satellite;
  if (sources.radar) elements.radarSource.href = sources.radar;
  if (sources.nws) elements.nwsSource.href = sources.nws;
  elements.radarReference.src = imagery.reference_map_url || "";
  positionMarker(elements.satelliteMarker, markers.satellite);
  positionMarker(elements.radarMarker, markers.radar);

  showFrame(0);
  updatePauseButton();
  scheduleNextFrame();
  window.setTimeout(() => preloadFrames(state.frames.slice(1)), 100);
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
  renderHeader(data);
  renderCards(data.cards || []);
  renderDetails(data.details || []);
  renderForecast(data.forecast);
  renderImagery(data.imagery);
  renderWarnings(data.errors);
}

async function loadData({ force = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  elements.refresh.disabled = true;
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
    elements.refresh.disabled = false;
    setProgress("is-complete");
    window.setTimeout(() => setProgress(null), 220);
  }
}

elements.pause.addEventListener("click", () => {
  state.paused = !state.paused;
  updatePauseButton();
  scheduleNextFrame();
});

elements.timelineRange.addEventListener("input", (event) => {
  showFrame(Number(event.target.value));
  scheduleNextFrame();
});

elements.refresh.addEventListener("click", () => loadData({ force: true }));

document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearAnimationTimer();
  else scheduleNextFrame();
});

loadData({ force: true });
window.setInterval(() => loadData(), 60_000);
