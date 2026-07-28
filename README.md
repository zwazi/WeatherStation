# WeatherStation

A GitHub Pages version of the regional Tempest weather dashboard. It combines
current WeatherFlow observations, a 12-hour numeric National Weather Service
forecast, a two-day outlook, and synchronized NOAA GOES/MRMS imagery.

The intended Pages URL is:

```text
https://zwazi.github.io/WeatherStation/
```

## What the site includes

- Six current-condition cards for temperature, humidity, wind, rain,
  lightning, and UV/light
- Full condition, wind, pressure, rain, lightning, and light detail sections
- A 12-hour NWS numeric grid and two-day high/low/rain table
- 24 NOAA GOES longwave frames covering approximately four hours
- Transparent NOAA nowCOAST/MRMS reflectivity composited over every GOES frame
- Shared EPSG:4326 geometry for satellite, rain, boundaries, and regional marker
- One pause/play control, frame scrubber, and responsive square composite
- A restrained Neotron-inspired graphite, warm-white, yellow, and red theme
- Automatic in-browser polling so an open page adopts each newly deployed build

## Data and deployment design

GitHub Pages is static, so it cannot protect an API token placed in browser
JavaScript. The repository therefore separates collection from presentation:

```text
GitHub Actions secret
        │
        ▼
scripts/update_weather.py ──► data/weather.json
        │                            │
        └─ NWS + NOAA metadata       ▼
                              static Pages site
```

`data/weather.json` contains display-ready observations and public NOAA source
URLs. It never contains the Tempest token. The browser does not call the
WeatherFlow API directly. The satellite and transparent rain images stay as
separate browser layers so they can be synchronized precisely, but appear as a
single composited map.

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

## GitHub setup

After pushing the repository:

1. Open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `TEMPEST_TOKEN`.
3. Optionally add repository variables named `TEMPEST_STATION_ID` and
   `TEMPEST_DEVICE_ID`. The workflow currently defaults to station `000000`
   and device `000000`.
4. Open **Settings → Pages** and select **GitHub Actions** as the source.
5. Run **Refresh weather and deploy Pages** once from the Actions tab, or wait
   for the next scheduled minute.

The workflow uses the current official GitHub Pages artifact flow:
`configure-pages`, `upload-pages-artifact`, and `deploy-pages`.

## Local development

Set the Tempest credential only in your shell, then build the local snapshot:

```bash
export TEMPEST_TOKEN='your-token'
export TEMPEST_STATION_ID='000000'
export TEMPEST_DEVICE_ID='000000'
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
├── data/weather.json                   # sanitized generated snapshot
├── scripts/update_weather.py           # Tempest/NWS/NOAA collector
├── tests/test_update_weather.py        # deterministic collector tests
└── index.html                          # static application shell
```

## Data sources

- [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/)
- [National Weather Service API](https://www.weather.gov/documentation/services-web-api)
- [NOAA nowCOAST satellite and radar services](https://nowcoast.noaa.gov/)
