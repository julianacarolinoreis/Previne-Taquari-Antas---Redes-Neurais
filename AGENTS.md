# AGENTS.md

## Cursor Cloud specific instructions

This repository is a **static website + Python "robots"** — there is no compiled backend, no
database, and no build step. The site is plain HTML/CSS/JS at the repo root (`index.html`,
`projeto.html`, `*_previsao_inundacao.html`, `vulnerabilidade.html`, etc.); the Python scripts in
`codigo_python/` and `previne/robo/` run on a schedule (GitHub Actions) to regenerate the committed
JSON/GeoJSON data files that the pages read at runtime.

### Running the site (dev)

- Serve the repo root over HTTP and open pages from there:
  `python3 -m http.server 8000` (from `/workspace`), then open `http://localhost:8000/index.html`.
- Do **not** open the pages via `file://` — they `fetch()` relative JSON/GeoJSON, which the browser
  blocks under `file://`. The committed data files make every page render without any robot running.
- Map pages load Leaflet from the `unpkg.com` CDN. With no internet they show a "Leaflet não carregou"
  banner but the rest of the page still works.

### Tests / validation

- `python3 scripts/validar_panorama_site.py` — structural checks on the forecast pages/JS/GeoJSON.
  It runs `git status` and asserts the four dynamic robot JSONs
  (`previsao_ao_vivo*.json`, `historico_previsoes_ao_vivo*.json`) were **not** modified, so run it
  from a clean working tree (or don't touch those files).
- `python3 codigo_python/01_previsao_ao_vivo/validar_forward_pass.py` — proves the Python forward-pass
  reproduces the trained MATLAB `.mat` network exactly (expects `RMSE = 0`). Uses only `numpy`/`scipy`.

### Robots / data pipelines

- The live-forecast and data-download robots (`previne/robo/gerar_previsao_ao_vivo.py`,
  `codigo_python/01_previsao_ao_vivo/*mucum*.py`, and the `06_*`/`07_*`/`10_*` pipelines) fetch from
  external Brazilian government APIs (ANA, INMET, CEMADEN, IBGE). These generally work in CI but are
  often unreachable/geo-blocked from the agent session, so they fail on the network fetch. Rely on the
  committed data files for local testing rather than running the robots live.
- Python dependencies are in `codigo_python/requirements.txt` (`numpy`, `scipy`, `rasterio`, `Pillow`,
  `openpyxl`). MATLAB is not needed — Python only runs the network forward-pass on the committed `.mat`
  files.
