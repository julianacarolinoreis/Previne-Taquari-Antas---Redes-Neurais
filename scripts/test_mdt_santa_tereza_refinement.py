"""Contrato do refinamento visual do MDT de Santa Tereza.

Os testes cobrem publicação, rastreabilidade, regressão da geometria desenhada
e controles essenciais da interface. Não certificam a exatidão hidrológica do
relevo nem da mancha HAND.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MDT = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt"


class SantaTerezaMdtRefinementTests(unittest.TestCase):
    def test_refined_assets_are_published_without_overwriting_original(self) -> None:
        original = MDT / "altitude_terreno_10m.json"
        refined = MDT / "altitude_terreno_10m_refinado.json"
        visual = MDT / "mdt_santa_tereza_10m_refinado_visual.png"
        report = ROOT / "assets" / "data" / "santa_tereza_inundacao" / "mdt_refinamento_santa_tereza.json"
        for path in (original, refined, visual, report):
            self.assertTrue(path.exists(), path)

        original_meta = json.loads(original.read_text(encoding="utf-8"))
        refined_meta = json.loads(refined.read_text(encoding="utf-8"))
        audit = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(original_meta["png"], "altitude_terreno_10m.png")
        self.assertEqual(refined_meta["original_web_grade"], original.name)
        self.assertEqual(refined_meta["product_type"], "research_visual_refinement")
        self.assertEqual(refined_meta["hydrologic_use"], "visualization_only")
        self.assertEqual(refined_meta["validation_status"], "pending_independent_water_mask_and_footprint_validation")
        self.assertGreater(refined_meta["changed_cells_2m"], 0)
        self.assertEqual(audit["celulas_corrigidas_2m"], refined_meta["changed_cells_2m"])

        with Image.open(visual) as image:
            self.assertEqual(image.size, (refined_meta["cols"], refined_meta["rows"]))
            self.assertEqual(image.mode, "RGBA")

    def test_santa_tereza_pages_use_refined_grade_and_expose_visual_layer(self) -> None:
        for name in ("santa_tereza_inundacao.html", "santa_tereza_previsao_inundacao.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("altitude_terreno_10m_refinado.json", text)
            self.assertIn("mdt_santa_tereza_10m_refinado_visual.png", text)
            self.assertIn("MDT refinado", text)
            self.assertIn("MIN_VISUAL_HOLE_M2=5000", text)
            self.assertNotIn("HIDE_ALL_VISUAL_HOLES", text)
            self.assertIn("poly.slice(1).filter(r=>ringAreaM2(r)>=MIN_VISUAL_HOLE_M2)", text)
            self.assertIn("visualFeature(feat)", text)
            self.assertIn("GeoJSON original e suas áreas não mudam", text)

    def test_visual_geometry_javascript_keeps_large_hole(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js não disponível para executar a função JavaScript real")
        for name in ("santa_tereza_inundacao.html", "santa_tereza_previsao_inundacao.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            start = text.index("const MIN_VISUAL_HOLE_M2=5000;")
            end = text.index("function setLayer", start)
            source = text[start:end] + r"""
const outer=[[0,0],[0.02,0],[0.02,0.02],[0,0.02],[0,0]];
const small=[[0.001,0.001],[0.0011,0.001],[0.0011,0.0011],[0.001,0.0011],[0.001,0.001]];
const large=[[0.005,0.005],[0.015,0.005],[0.015,0.015],[0.005,0.015],[0.005,0.005]];
const original={type:'Polygon',coordinates:[outer,small,large]};
const result=visualGeometry(original);
console.log(JSON.stringify({rendered:result.coordinates.length,raw:original.coordinates.length,keptArea:ringAreaM2(result.coordinates[1])}));
"""
            run = subprocess.run(
                [node, "-"], input=source, text=True, capture_output=True, check=False
            )
            self.assertEqual(run.returncode, 0, f"{name}: {run.stderr}")
            result = json.loads(run.stdout.strip())
            self.assertEqual(result["raw"], 3, name)
            self.assertEqual(result["rendered"], 2, name)
            self.assertGreaterEqual(result["keptArea"], 5000, name)

    def test_controls_have_unique_ids_and_accessible_names(self) -> None:
        for name in ("santa_tereza_inundacao.html", "santa_tereza_previsao_inundacao.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for control_id in ("play", "time", "bankfull"):
                self.assertEqual(text.count(f'id="{control_id}"'), 1, (name, control_id))
            self.assertIn('aria-label="Reproduzir linha do tempo"', text)
            self.assertIn('for="time"', text)
            self.assertIn('for="bankfull"', text)
            self.assertIn('aria-describedby="timeline-hint"', text)
            self.assertIn('aria-label="Mapa interativo', text)

    def test_real_geojson_keeps_large_holes_and_visual_area_is_consistent(self) -> None:
        def ring_area_m2(ring: list[list[float]]) -> float:
            if len(ring) < 4:
                return 0.0
            twice = 0.0
            latitude = 0.0
            count = 0
            for first, second in zip(ring, ring[1:]):
                twice += float(first[0]) * float(second[1]) - float(second[0]) * float(first[1])
                latitude += float(first[1])
                count += 1
            metres_x = 111320 * math.cos((latitude / count) * math.pi / 180)
            return abs(twice) * 0.5 * metres_x * 111320

        def polygons(geometry: dict) -> list:
            return [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]

        data_dir = ROOT / "assets" / "data" / "santa_tereza_inundacao"
        for filename in ("contornos_mancha.json", "contornos_extravasamento.json"):
            collection = json.loads((data_dir / filename).read_text(encoding="utf-8"))
            retained_large_holes = 0
            for feature in collection["features"]:
                visual_area_m2 = 0.0
                for polygon in polygons(feature["geometry"]):
                    outer = ring_area_m2(polygon[0])
                    large_holes = [ring_area_m2(ring) for ring in polygon[1:] if ring_area_m2(ring) >= 5000]
                    retained_large_holes += len(large_holes)
                    visual_area_m2 += outer - sum(large_holes)
                declared_ha = float(feature["properties"]["area_ha"])
                if declared_ha >= 50:
                    relative_error = abs(visual_area_m2 / 10000 - declared_ha) / declared_ha
                    self.assertLess(relative_error, 0.02, (filename, feature["properties"].get("nivel_m"), relative_error))
            self.assertGreater(retained_large_holes, 0, filename)

        overflow = json.loads((data_dir / "contornos_extravasamento.json").read_text(encoding="utf-8"))
        level_71 = next(f for f in overflow["features"] if abs(float(f["properties"]["nivel_m"]) - 7.1) < 0.01)
        large_holes = [ring_area_m2(ring) for polygon in polygons(level_71["geometry"]) for ring in polygon[1:] if ring_area_m2(ring) >= 5000]
        self.assertGreater(max(large_holes), 3_000_000)


if __name__ == "__main__":
    unittest.main()
