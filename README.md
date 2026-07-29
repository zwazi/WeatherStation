# WeatherStation

A GitHub Pages version of the Tucson Tempest weather dashboard. It combines
current WeatherFlow observations, hourly National Weather Service forecasts
for today and tomorrow, and synchronized NOAA GOES/NEXRAD imagery over a
Leaflet map.

The intended Pages URL is:

```text
https://zwazi.github.io/WeatherStation/
```

## What the site includes

- Current temperature, humidity, wind, pressure, rain, lightning, and UV/light
  measurements
- Full condition, wind, pressure, rain, lightning, and light detail sections
- A compact current-condition hero, horizontally scrolling hourly forecast,
  and two-day summaries modeled after a modern weather app
- Separate hourly strips for the Arizona calendar dates Today and Tomorrow
- A complete expandable NWS numeric grid through the end of tomorrow
- Up to 24 NOAA GOES ABI Band 13 cloud frames covering approximately four hours
- A full-width Tucson-centered Leaflet/OpenStreetMap base with clear land,
  roads, borders, city labels, and a labeled Tempest station marker
- Transparent 1400×600 NOAA-derived cloud masks and IEM-served NOAA NEXRAD
  rain intensity mosaics aligned in Leaflet's Web Mercator projection
- Automatic NOAA nowCOAST/MRMS fallback if an IEM frame is unavailable
- Shared EPSG:3857 geometry for the NOAA cloud and rain overlays
- Background satellite/radar preloading that keeps the old loop visible until
  every replacement frame is ready
- A compact frame scrubber and responsive wide composite
- A non-layout-shifting Arizona timestamp for the latest completed refresh
- A restrained black, dark-plum, warm-white, yellow, and red theme
- Automatic in-browser polling so an open page adopts each newly deployed build

## Data and deployment design

GitHub Pages is static, so it cannot protect an API token placed in browser
JavaScript. The repository therefore separates collection from presentation:

```text
GitHub Actions secret
        │
        ▼
scripts/update_weather.py ──► data/weather.json
        │                    └─► data/imagery/*.webp
        │                                  │
        └─ NWS + NOAA metadata             ▼
                                    static Pages site
```

`data/weather.json` contains display-ready observations and public radar source
URLs. The build converts NOAA ABI Band 13 images into transparent WebP cloud
frames, so the opaque NOAA imagery never replaces the higher-quality map. The
data never contains the Tempest token, and the browser does not call the
WeatherFlow API directly. Leaflet keeps the base map, cloud cover, and rain
intensity as separate aligned layers while displaying them as one animation.

The workflow in `.github/workflows/deploy-pages.yml` runs at these Arizona
wall-clock minutes:

```text
:01  :11  :21  :31  :41  :51
```

Each run refreshes every data section, tests the project, assembles a static
artifact, and deploys it through GitHub Pages. GitHub may queue scheduled jobs
under load, so `:01`, `:11`, and so on are trigger times rather than guaranteed
deployment-completion times. An open dashboard checks once per minute for the
new artifact.

Because GitHub's hosted scheduler can substantially delay or omit scheduled
runs, this workstation also enables `weatherstation-refresh.timer`. The user
timer dispatches the same GitHub workflow at the six exact Arizona minute marks
with one-second timer accuracy. The hosted cron remains enabled as a backup.

Install or refresh the local dispatcher with:

```bash
cp systemd/weatherstation-refresh.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now weatherstation-refresh.timer
```

## GitHub setup

After pushing the repository:

1. Open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `TEMPEST_TOKEN`.
3. Optionally add repository variables named `TEMPEST_STATION_ID` and
   `TEMPEST_DEVICE_ID`. The workflow currently defaults to station `217249`
   and device `1221453`.
4. Open **Settings → Pages** and select **GitHub Actions** as the source.
5. Run **Refresh weather and deploy Pages** once from the Actions tab, or wait
   for the next scheduled minute.

The workflow uses the current official GitHub Pages artifact flow:
`configure-pages`, `upload-pages-artifact`, and `deploy-pages`.

## Local development

Set the Tempest credential only in your shell, then build the local snapshot:

```bash
export TEMPEST_TOKEN='your-token'
export TEMPEST_STATION_ID='217249'
export TEMPEST_DEVICE_ID='1221453'
python3 -m pip install -r requirements.txt
python3 scripts/update_weather.py
```

Serve the repository root so `fetch()` can load the generated JSON:

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/`. Opening `index.html` directly with a `file://`
URL will usually block the JSON request because of browser origin rules.

## Verification

Run all repository checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/update_weather.py
node --check assets/app.js
```

The data builder retains the last available section when an individual
upstream service fails and adds a sanitized warning to the JSON. Any token-like
query parameter is redacted before an error can be serialized.

## Project structure

```text
.
├── .github/workflows/deploy-pages.yml  # scheduled refresh and Pages deploy
├── assets/app.js                       # rendering and composited animation
├── assets/styles.css                   # responsive Neotron-inspired theme
├── data/imagery/                       # generated transparent cloud frames
├── data/weather.json                   # sanitized generated snapshot
├── requirements.txt                    # data-builder image dependency
├── scripts/update_weather.py           # Tempest/NWS/NOAA collector
├── systemd/                             # exact local workflow dispatcher
├── tests/test_update_weather.py        # deterministic collector tests
└── index.html                          # static application shell
```

## Data sources

- [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/)
- [National Weather Service API](https://www.weather.gov/documentation/services-web-api)
- [NOAA/NESDIS ABI Band 13 ImageServer](https://satellitemaps.nesdis.noaa.gov/arcgis/rest/services/ABI13_Last_24hr/ImageServer)
- [Iowa Environmental Mesonet NEXRAD mosaics](https://mesonet.agron.iastate.edu/docs/nexrad_mosaic/)
- [NOAA nowCOAST radar fallback](https://nowcoast.noaa.gov/)
- [Leaflet](https://leafletjs.com/)
- [OpenStreetMap](https://www.openstreetmap.org/copyright)
