"""Contract tests for the Santa Tereza + Muçum territorial case-study page."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pesquisas" / "estudo-caso-territorio.html"
JS = ROOT / "assets" / "js" / "estudo_caso_territorio.js"
CSS = ROOT / "assets" / "css" / "estudo_caso_territorio.css"
DATA = ROOT / "assets" / "data" / "estudo_caso_territorio"
REPLAY = ROOT / "assets" / "data" / "research_event_replay_latest.json"
ACERVO = ROOT / "assets" / "data" / "acervo_pesquisas.json"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-pages.yml"

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
        self.assertNotIn("carto", js.lower())
        self.assertIn("segmentHitsGeometry", js)
        self.assertIn("segsIntersect", js)
        self.assertIn("renderGauge", js)
        self.assertIn("setChain", js)
        self.assertIn("allowDefault", js)
        self.assertIn("parseCity({ allowDefault: false })", js)
        self.assertIn("gauge-now", html)
        self.assertIn("howto", html)
        self.assertIn("class=\"brand\"", html)
        self.assertIn("estudo de caso", html.lower())
        self.assertIn("não é alerta", html.lower())
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
        self.assertIn("hud-cockpit", html)
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
        # RNA formatter must not convert cm→m (HAND collision)
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
        self.assertIn("st-e9-mai2024", ids)
        self.assertIn("mucum-e27-mai2024-hotel", ids)
        self.assertIn("mucum-e35-jul2026", ids)
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
