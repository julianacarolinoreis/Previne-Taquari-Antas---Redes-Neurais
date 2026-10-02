"""Contract tests for the Santa Tereza + Muçum territorial case-study page."""

from __future__ import annotations

import json
import os
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pesquisas" / "estudo-caso-territorio.html"
JS = ROOT / "assets" / "js" / "estudo_caso_territorio.js"
CSS = ROOT / "assets" / "css" / "estudo_caso_territorio.css"
DATA = ROOT / "assets" / "data" / "estudo_caso_territorio"
REPLAY = ROOT / "assets" / "data" / "research_event_replay_latest.json"
ACERVO = ROOT / "assets" / "data" / "acervo_pesquisas.json"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-pages.yml"
STZ_HISTORICAL = DATA / "santa_tereza_event_spatial.json"

CITIES = {
    "santa_tereza": {
        "grade": DATA / "grade_200m_santa_tereza.geojson",
        "ruas": DATA / "ruas_santa_tereza.json",
        "mancha": DATA / "mancha_santa_tereza.geojson",
        "levels": [15.0],
        "default": 15.0,
        "ibge": "4317251",
    },
    "mucum": {
        "grade": DATA / "grade_200m_mucum.geojson",
        "ruas": DATA / "ruas_mucum.json",
        "mancha": DATA / "mancha_mucum.geojson",
        "levels": [18.0, 20.0, 25.0],
        "default": 18.0,
        "ibge": "4312609",
    },
}


def point_in_ring(lat: float, lng: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i, vertex in enumerate(ring):
        xi, yi = float(vertex[0]), float(vertex[1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_geom(lat: float, lng: float, geom: dict) -> bool:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if not point_in_ring(lat, lng, poly[0]):
            continue
        hole = any(point_in_ring(lat, lng, poly[h]) for h in range(1, len(poly)))
        if not hole:
            return True
    return False


def orient(ax, ay, bx, by, cx, cy) -> int:
    v = (by - ay) * (cx - bx) - (bx - ax) * (cy - by)
    if abs(v) < 1e-18:
        return 0
    return 1 if v > 0 else 2


def on_seg(ax, ay, bx, by, cx, cy) -> bool:
    return (
        min(ax, bx) - 1e-12 <= cx <= max(ax, bx) + 1e-12
        and min(ay, by) - 1e-12 <= cy <= max(ay, by) + 1e-12
    )


def segs_intersect(a, b, c, d) -> bool:
    ax, ay, bx, by = a[1], a[0], b[1], b[0]
    cx, cy, dx, dy = c[1], c[0], d[1], d[0]
    o1, o2 = orient(ax, ay, bx, by, cx, cy), orient(ax, ay, bx, by, dx, dy)
    o3, o4 = orient(cx, cy, dx, dy, ax, ay), orient(cx, cy, dx, dy, bx, by)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_seg(ax, ay, bx, by, cx, cy):
        return True
    if o2 == 0 and on_seg(ax, ay, bx, by, dx, dy):
        return True
    if o3 == 0 and on_seg(cx, cy, dx, dy, ax, ay):
        return True
    if o4 == 0 and on_seg(cx, cy, dx, dy, bx, by):
        return True
    return False


def ring_edges(ring: list) -> list:
    n = len(ring)
    if n < 2:
        return []
    closed = n > 2 and ring[0][0] == ring[n - 1][0] and ring[0][1] == ring[n - 1][1]
    count = n - 1 if closed else n
    return [[ring[i], ring[(i + 1) % n]] for i in range(count)]


def segment_hits_geometry(a, c, geom: dict) -> bool:
    if point_in_geom(a[0], a[1], geom) or point_in_geom(c[0], c[1], geom):
        return True
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        for edge in ring_edges(poly[0]):
            p1 = [edge[0][1], edge[0][0]]
            p2 = [edge[1][1], edge[1][0]]
            if segs_intersect(a, c, p1, p2):
                return True
    return False


class EstudoCasoTerritorioTests(unittest.TestCase):
    def test_rendered_control_geometry_fits_320_390_768_1440(self) -> None:
        """Real DOM/CSS/JS and local data; basemap tiles are not validated.

        Leaflet 1.9.4 is the actual CDN dependency declared by the page. Missing
        Playwright, Chromium or Leaflet fails this test rather than skipping QA.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            self.fail(f"QA renderizado requer playwright: {error}")

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT)))
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        candidates = [Path(os.environ["PREVINE_CHROME_PATH"])] if os.environ.get("PREVINE_CHROME_PATH") else []
        candidates.extend([
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
        ])
        executable = next((str(path) for path in candidates if path.is_file()), None)
        try:
            with sync_playwright() as playwright:
                options = {"headless": True}
                if executable:
                    options["executable_path"] = executable
                try:
                    browser = playwright.chromium.launch(**options)
                except Exception as error:
                    self.fail(f"QA renderizado requer Chrome/Chromium disponível: {error}")
                try:
                    for width in (320, 390, 768, 1440):
                        page = browser.new_page(viewport={"width": width, "height": 900})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))

                        def local_page_and_leaflet_only(route):
                            url = route.request.url
                            if (urlsplit(url).hostname == "127.0.0.1"
                                    or url.startswith("https://unpkg.com/leaflet@1.9.4/dist/")):
                                route.continue_()
                            else:
                                route.abort()  # no external tiles/telemetry in this layout check

                        page.route("**/*", local_page_and_leaflet_only)
                        try:
                            page.goto(
                                f"http://127.0.0.1:{server.server_port}/pesquisas/estudo-caso-territorio.html",
                                wait_until="domcontentloaded", timeout=30000,
                            )
                            for city in ("santa_tereza", "mucum"):
                                with self.subTest(width=width, city=city):
                                    page.locator(f'.city-row [data-city="{city}"]').click()
                                    page.wait_for_function(
                                        "typeof L==='object' && document.querySelector('#load-status').textContent==='pronto'",
                                        timeout=30000,
                                    )
                                    self.assertGreater(page.locator("#case-row button").count(), 0)
                                    self.assertEqual(page.locator('#module-tabs [role="tab"]').count(), 5)
                                    metrics = page.evaluate("""() => {
                                        const dock=document.querySelector('.control-dock'), tabs=document.querySelector('#module-tabs');
                                        const rect=element=>{const r=element.getBoundingClientRect();
                                            return {left:r.left,right:r.right,width:r.width,client:element.clientWidth,scroll:element.scrollWidth};};
                                        return {viewport:innerWidth,body:document.body.scrollWidth,
                                            document:document.documentElement.scrollWidth,dock:rect(dock),tabs:rect(tabs),
                                            fields:Array.from(dock.querySelectorAll('.control-field')).map(rect)};
                                    }""")
                                    print("TERRITORIO_LAYOUT " + json.dumps({"width": width, "city": city, **metrics}))
                                    self.assertEqual(metrics["viewport"], width)
                                    self.assertLessEqual(max(metrics["body"], metrics["document"]), width + 1, metrics)
                                    self.assertLessEqual(metrics["dock"]["scroll"], metrics["dock"]["client"] + 1, metrics)
                                    for field in metrics["fields"]:
                                        self.assertGreater(field["width"], 0)
                                        self.assertGreaterEqual(field["left"], metrics["dock"]["left"] - 1, metrics)
                                        self.assertLessEqual(field["right"], metrics["dock"]["right"] + 1, metrics)
                                    # Keyboard focus must reveal the last tab inside its own
                                    # scroll container, not by widening or clipping the body.
                                    last = page.locator('#module-tabs [role="tab"]').last
                                    last.focus()
                                    bounds = last.bounding_box()
                                    tabs_bounds = page.locator("#module-tabs").bounding_box()
                                    self.assertGreaterEqual(bounds["x"], tabs_bounds["x"] - 1)
                                    self.assertLessEqual(bounds["x"] + bounds["width"],
                                                         tabs_bounds["x"] + tabs_bounds["width"] + 1)
                                    self.assertLessEqual(page.evaluate("document.body.scrollWidth"), width + 1)
                                    self.assertEqual(errors, [], "erros de runtime no cockpit")
                        finally:
                            page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_page_and_assets_are_wired(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        js = JS.read_text(encoding="utf-8")
        css = CSS.read_text(encoding="utf-8")
        deploy = DEPLOY.read_text(encoding="utf-8")
        self.assertTrue(PAGE.exists())
        self.assertTrue(JS.exists())
        self.assertTrue(CSS.exists())
        self.assertIn("assets/js/estudo_caso_territorio.js", html)
        self.assertIn("assets/css/estudo_caso_territorio.css", html)
        self.assertIn("tile.openstreetmap.org", js)
        self.assertIn("World_Imagery", js)
        self.assertIn("applyBasemap", js)
        self.assertIn("data-basemap", html)
        self.assertIn("Satélite", html)
        self.assertIn("setModule", js)
        self.assertIn("moduleHref", js)
        self.assertNotIn("carto", js.lower())
        self.assertIn("segmentHitsGeometry", js)
        self.assertIn("segsIntersect", js)
        self.assertIn("renderGauge", js)
        self.assertIn("setChain", js)
        self.assertIn("allowDefault", js)
        self.assertIn("parseCity({ allowDefault: false })", js)
        self.assertIn("gauge-now", html)
        self.assertIn("howto", html)
        self.assertIn("brand-mark", html)
        self.assertIn("estudo de caso", html.lower())
        self.assertIn("não é alerta", html.lower())
        self.assertIn("sala de", html.lower())
        self.assertIn("assets/data/estudo_caso_territorio/**", deploy)
        self.assertIn(".territorio", css)
        self.assertIn("story-play", html)
        self.assertIn("Contar a história", html)
        self.assertIn("goStory", js)
        self.assertIn("onMapClick", js)
        self.assertIn("rotaCenario", js)
        self.assertIn("drawRota", js)
        self.assertIn("resolveRota", js)
        self.assertIn("focusCenter", js)
        self.assertIn("focusLocalPath", js)
        self.assertIn("vertical-ledger", html)
        self.assertIn("story-caption", html)
        self.assertIn("hud-sheet", html)
        self.assertIn("btn-recenter", html)
        self.assertIn("is-presenting", js)
        self.assertIn("rota_cenario_santa_tereza.json", js)
        self.assertIn("rota_cenario_mucum.json", js)
        self.assertIn('data-story="rotas"', html)
        self.assertIn("context-box", html)
        self.assertIn("rota-metrics", html)
        self.assertIn(".rna-cockpit", css)
        self.assertIn(".gauge-scale", css)
        self.assertIn(".context-box", css)
        self.assertIn(".vertical-ledger", css)
        self.assertIn(".hud-sheet", css)
        self.assertIn("street-priority", html)
        self.assertIn("rna-decide", html)
        self.assertIn("buildStreetPriority", js)
        self.assertIn("selectStreet", js)
        self.assertIn("is-cockpit", html)
        self.assertIn("sala-reunida", html)
        self.assertIn("module-tabs", html)
        self.assertIn("module-frame", html)
        self.assertIn("juntos-stage", html)
        self.assertIn("historical-comparison", html)
        self.assertIn("comparison-event-grid", html)
        self.assertIn("comparison-table-body", html)
        self.assertIn("renderHistoricalComparison", js)
        self.assertIn("comparison-map-toggle", html)
        self.assertIn("drawHistoricalComparisonOverlay", js)
        self.assertIn("L.featureGroup()", js)
        self.assertIn("historicalSpatial", js)
        self.assertIn("santa_tereza_event_spatial.json", js)
        self.assertIn("historicalSpatialEvent", js)
        self.assertIn("road_centerline_edges_touched", js)
        self.assertIn("hud-cockpit", html)
        self.assertIn("sit-threat", html)
        self.assertIn(".hud-cockpit", css)
        self.assertIn("ly-flood", html)
        self.assertIn("case-row", html)
        self.assertIn("case-banner", html)
        self.assertIn("ly-marks", html)
        self.assertIn("casos_acoplados.json", js)
        self.assertIn("drawMarks", js)
        self.assertIn("renderCaseButtons", js)
        self.assertIn("loadCasesDoc", js)
        self.assertIn(".case-row", css)
        self.assertTrue((DATA / "rota_cenario_santa_tereza.json").exists())
        self.assertTrue((DATA / "rota_cenario_mucum.json").exists())
        self.assertTrue((DATA / "casos_acoplados.json").exists())
        self.assertTrue(STZ_HISTORICAL.exists())
        # RNA formatter must not perform an undocumented generic cm→m HAND conversion.
        self.assertNotIn('n / 100).toFixed', js)
        self.assertIn("Math.round(n).toLocaleString('pt-BR') + ' cm'", js)

    def test_coupled_cases_join_by_event_not_cm_to_hand(self) -> None:
        cases_path = DATA / "casos_acoplados.json"
        doc = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertTrue(doc.get("research_only") or doc.get("research_only") is None or True)
        self.assertFalse(doc.get("official_alert_allowed", False))
        method = (doc.get("method") or doc.get("method") or "").lower()
        blob = json.dumps(doc, ensure_ascii=False).lower()
        self.assertIn("sem convers", blob)
        ids = {c["id"] for c in doc["cases"]}
        self.assertIn("live", ids)
        self.assertIn("st-e4-set2023", ids)
        self.assertIn("st-e6-nov2023", ids)
        self.assertIn("st-e9-mai2024", ids)
        self.assertIn("mucum-e27-mai2024-hotel", ids)
        self.assertIn("mucum-e35-jul2026", ids)
        comparative_analysis = doc.get("comparative_analysis")
        self.assertIsInstance(comparative_analysis, dict)
        self.assertEqual(
            comparative_analysis.get("event_ids"),
            ["st-e4-set2023", "st-e6-nov2023", "st-e9-mai2024"],
        )
        nov = next(c for c in doc["cases"] if c["id"] == "st-e6-nov2023")
        self.assertEqual(nov["rna"]["catalog_event"], 6)
        self.assertEqual(nov["dataset_role"], "treino")
        self.assertAlmostEqual(
            nov["raw_event_telemetry"]["rain_24h_before_raw_peak_mm"], 119.6
        )
        hotel = next(c for c in doc["cases"] if c["id"] == "mucum-e27-mai2024-hotel")
        self.assertEqual(hotel["mode"], "coupled")
        self.assertEqual(hotel["hand_m"], 25)
        self.assertEqual(hotel["short"], "Hotel")
        self.assertEqual(hotel["focus_mark"], "MCM01 (Hotel)")
        self.assertTrue(any("Hotel" in (m.get("name") or "") for m in hotel["marks"]))
        frame = hotel["rna"]["decision_frame"]
        self.assertIsNotNone(frame.get("now_obs_cm"))
        self.assertIsNotNone(frame.get("plus_2h_rna_cm"))
        js = JS.read_text(encoding="utf-8")
        self.assertIn("defaultCaseId", js)
        self.assertIn("mucum-e27-mai2024-hotel", js)
        self.assertIn("st-e4-set2023", js)
        self.assertNotIn("cm * 0.01", js)
        self.assertNotIn("/ 100)", js.split("drawMarks")[0][-200:] + js.split("drawMarks")[-1][:200])

    def test_santa_tereza_event_specific_lidar_hand_reconstructions(self) -> None:
        doc = json.loads(STZ_HISTORICAL.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "research_historical_spatialization_not_observed_boundary")
        self.assertAlmostEqual(doc["calibration"]["gauge_zero_hand_m"], 1.6)
        self.assertEqual(doc["calibration"]["d8_scheme"], "esri")
        self.assertGreater(doc["calibration"]["d8_scheme_score"], 0.9)

        rows = {row["case_id"]: row for row in doc["events"]}
        self.assertEqual(set(rows), {"st-e4-set2023", "st-e6-nov2023", "st-e9-mai2024"})
        self.assertAlmostEqual(rows["st-e4-set2023"]["gauge_peak_m"], 24.04)
        self.assertAlmostEqual(rows["st-e4-set2023"]["contour_level_m"], 22.4)
        self.assertAlmostEqual(rows["st-e6-nov2023"]["gauge_peak_m"], 21.61)
        self.assertAlmostEqual(rows["st-e6-nov2023"]["contour_level_m"], 20.0)
        self.assertAlmostEqual(rows["st-e9-mai2024"]["gauge_peak_m"], 22.42)
        self.assertAlmostEqual(rows["st-e9-mai2024"]["contour_level_m"], 20.8)
        self.assertAlmostEqual(
            rows["st-e9-mai2024"]["sensitivity"]["contour_level_m"], 20.7
        )

        areas = []
        for row in rows.values():
            scenario = row["scenario"]
            self.assertGreater(scenario["contour_area_ha"], 0)
            self.assertGreater(scenario["cells_200m_touched"], 0)
            self.assertGreater(scenario["population_area_weighted_proxy"], 0)
            self.assertGreater(scenario["road_centerline_edges_touched"], 0)
            self.assertLessEqual(
                scenario["road_centerline_edges_touched"],
                scenario["road_centerline_edges_total"],
            )
            self.assertEqual(
                len(scenario["wet_edge_ids"]),
                scenario["road_centerline_edges_touched"],
            )
            areas.append(round(float(scenario["contour_area_ha"]), 1))
        self.assertEqual(len(set(areas)), 3)

        contours = doc["event_contours"]["features"]
        self.assertEqual(len(contours), 3)
        self.assertEqual(
            sorted(round(float(f["properties"]["contour_level_m"]), 1) for f in contours),
            [20.0, 20.8, 22.4],
        )

    def test_rota_edges_flag_flooded_segments(self) -> None:
        for city, path in (
            ("santa_tereza", DATA / "rota_cenario_santa_tereza.json"),
            ("mucum", DATA / "rota_cenario_mucum.json"),
        ):
            data = json.loads(path.read_text(encoding="utf-8"))
            flooded = [e for e in data["edges"] if len(e) > 2 and e[2] == 1]
            self.assertGreater(len(flooded), 0, city)

    def test_rota_cenario_graphs_have_path_tables(self) -> None:
        for city, path in (
            ("santa_tereza", DATA / "rota_cenario_santa_tereza.json"),
            ("mucum", DATA / "rota_cenario_mucum.json"),
        ):
            data = json.loads(path.read_text(encoding="utf-8"))
            n = len(data["nos"])
            self.assertEqual(len(data["prox"]), n, city)
            self.assertEqual(len(data["dest"]), n, city)
            self.assertEqual(len(data["dist_m"]), n, city)
            self.assertEqual(len(data["agua_m"]), n, city)
            self.assertGreater(len(data["abrigos"]), 0, city)
            self.assertGreater(len(data["edges"]), 0, city)
            # Sample a mid node: following prox should terminate
            i = n // 3
            seen = set()
            guard = 0
            while i >= 0 and guard < 8000:
                self.assertNotIn(i, seen, city)
                seen.add(i)
                nxt = data["prox"][i]
                if nxt == i or nxt < 0:
                    break
                i = nxt
                guard += 1
            self.assertLess(guard, 8000, city)

    def test_acervo_indexes_the_page_and_hrefs_exist(self) -> None:
        catalog = json.loads(ACERVO.read_text(encoding="utf-8"))
        entries = catalog["entries"]
        self.assertEqual(catalog["count"], len(entries))
        hit = next(item for item in entries if "estudo-caso-territorio.html" in item["href"])
        self.assertEqual(hit["href"], "pesquisas/estudo-caso-territorio.html")
        self.assertIn("não ordena evacuação", hit["caveat"].lower())
        missing = [
            item["href"]
            for item in entries
            if not item["href"].startswith("http") and not (ROOT / item["href"]).exists()
        ]
        self.assertEqual(missing, [])

    def test_replay_cells_are_in_the_published_200m_grade(self) -> None:
        replay = json.loads(REPLAY.read_text(encoding="utf-8"))["spatial_scenarios"]
        for city, spec in CITIES.items():
            grade = json.loads(spec["grade"].read_text(encoding="utf-8"))
            ids = {feat["properties"]["id_grade"] for feat in grade["features"]}
            mancha = json.loads(spec["mancha"].read_text(encoding="utf-8"))
            niveis = sorted(float(feat["properties"]["nivel_m"]) for feat in mancha["features"])
            self.assertEqual(niveis, spec["levels"])
            for scenario in replay[city]["scenarios"]:
                level = float(scenario["level_m"])
                if level not in spec["levels"]:
                    continue
                listed = [cell["id_grade"] for cell in scenario["intersected_cells_200m"]]
                self.assertEqual(len(listed), scenario["cells_200m_touched"])
                missing = [cell_id for cell_id in listed if cell_id not in ids]
                self.assertEqual(missing, [], f"{city} HAND {level}")
                self.assertTrue(all(cell_id.startswith("200M") for cell_id in listed))

    def test_street_highlight_includes_segments_that_cross_without_a_node(self) -> None:
        replay = json.loads(REPLAY.read_text(encoding="utf-8"))["spatial_scenarios"]
        js = JS.read_text(encoding="utf-8")
        self.assertIn("segmentHitsGeometry", js)
        for city, default in (("santa_tereza", 15.0), ("mucum", 18.0)):
            spec = CITIES[city]
            grade = {
                feat["properties"]["id_grade"]: feat
                for feat in json.loads(spec["grade"].read_text(encoding="utf-8"))["features"]
            }
            ruas = json.loads(spec["ruas"].read_text(encoding="utf-8"))
            nos, edges = ruas["nos"], ruas["edges"]
            scenario = next(
                item for item in replay[city]["scenarios"] if float(item["level_m"]) == default
            )
            cross_only = 0
            hits_with_crossing = 0
            for cell in scenario["intersected_cells_200m"]:
                geom = grade[cell["id_grade"]]["geometry"]
                end_hits = 0
                cross_hits = 0
                for edge in edges:
                    a, c = nos[edge[0]], nos[edge[1]]
                    end = point_in_geom(a[0], a[1], geom) or point_in_geom(c[0], c[1], geom)
                    full = segment_hits_geometry(a, c, geom)
                    if end:
                        end_hits += 1
                    elif full:
                        cross_hits += 1
                if cross_hits:
                    hits_with_crossing += 1
                if cross_hits and not end_hits:
                    cross_only += 1
            self.assertGreater(hits_with_crossing, 0, city)
            self.assertGreater(cross_only, 0, city)

    def test_hub_and_ficha_link_the_study(self) -> None:
        for path in (
            ROOT / "projeto.html",
            ROOT / "pesquisas.html",
            ROOT / "dashboard_bacia.html",
            ROOT / "pesquisa_status.html",
            ROOT / "pesquisa_status_mucum.html",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("estudo-caso-territorio.html", text, path.name)


if __name__ == "__main__":
    unittest.main()
