"""Regressões de escrita e do contrato HAND de campo de Santa Tereza.

Os comandos reais rodam em uma cópia temporária dos scripts, com GeoTIFFs e
HTMLs sintéticos. Não se substituem funções geoespaciais nem operações de
escrita. Os sete HTMLs STZ e os dois contornos sentinelas precisam conservar
seus bytes, enquanto Muçum precisa produzir contornos e atualizar limiares.
Não certifica exatidão hidrológica, segurança de rota ou aprovação operacional.

Execute: python -B scripts/test_santa_tereza_hand_field_contract.py -v
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping, shape


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = Path("codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py")
MOSAIC_HELPER = GENERATOR.with_name("gerar_mancha_mosaico.py")
UPDATER = Path("scripts/refresh_spatial_30m_pages.py")
CONTRACT = Path("scripts/santa_tereza_hand_field_contract.py")
RECALC = Path("scripts/recalcular_painel_evacuacao_hand_campo.py")
QUEUE = Path("codigo_python/09_rota_fuga/gerar_fila_cidade.py")
PUBLISHER = Path("scripts/publicar_santa_tereza_mdt.ps1")
STZ_CONTOURS = Path("assets/data/santa_tereza_inundacao/contornos_mancha.json")
STZ_OVERFLOW = STZ_CONTOURS.with_name("contornos_extravasamento.json")
STZ_LEGACY = STZ_CONTOURS.with_name("contornos_mancha_mosaico_anadem_legacy.json")
MUCUM_CONTOURS = Path("assets/data/mucum_inundacao/contornos_mancha.json")
STZ_PAGES = (
    Path("santa_tereza_painel_evacuacao.html"),
    Path("pesquisas/santa-tereza-painel-evacuacao.html"),
    Path("pesquisas/santa-tereza-mapa-impacto.html"),
    Path("pesquisas/santa-tereza-mapa-margem.html"),
    Path("pesquisas/santa-tereza-rota-fuga-ruas.html"),
    Path("santa_tereza_rota_fuga_ruas_cenario.html"),
    Path("pesquisas/santa-tereza-rota-fuga-ruas-cenario.html"),
)
MUCUM_PAGES = (
    Path("pesquisas/mucum-mapa-impacto.html"),
    Path("pesquisas/mucum-mapa-margem.html"),
    Path("pesquisas/mucum-painel-evacuacao.html"),
    Path("mucum_painel_evacuacao.html"),
)
SOURCE_ID = "santa_tereza_lidar_campo_rio_principal_zero160_v1"
FIELD_LEVELS = [round(index / 10, 1) for index in range(251)]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def write_page(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!doctype html><html lang=\"pt-BR\"><body>"
        "<p>Fixture de pesquisa: não é alerta oficial.</p><script>\n"
        "const D=" + json.dumps(payload, ensure_ascii=False) + ";\n"
        "</script><p id=\"sentinel\">preservar conteúdo fora do payload</p>"
        "</body></html>\n",
        encoding="utf-8",
    )


def feature(level: float, geometry) -> dict:
    return {
        "type": "Feature",
        "properties": {"nivel_m": level, "area_ha": geometry.area * 100},
        "geometry": mapping(geometry),
    }


def field_metadata() -> dict:
    return {
        "cidade": "santa_tereza",
        "rio": "somente rio principal",
        "hand_zero_cm": 160,
        "source_id": SOURCE_ID,
        "fonte": "HAND 5 m derivado dos rasters novos de campo",
        "superficie_inundacao": "CLIP_MOSAICO_LIDAR_RS.tif (LiDAR bruto)",
        "superficie_roteamento": "FILL_CLIP_MOSAICO_LIDAR_RS.tif",
        "filtro_conectividade": (
            "barreira máxima no LiDAR bruto ao longo do caminho D8 + "
            "checagem 8-vizinhos conectada ao rio principal"
        ),
        "passo_vetor_m": 0.1,
        "mdt_preservado": True,
        "interpretacao": "fixture sintética de pesquisa; não é alerta oficial",
    }


def field_document() -> dict:
    return {
        "type": "FeatureCollection",
        "metadata": field_metadata(),
        "features": [
            feature(level, box(0, 0, 1 + index / 250, 1 + index / 250))
            for index, level in enumerate(FIELD_LEVELS)
        ],
    }


def raster_payload(values: np.ndarray | None = None, image_format: str = "PNG") -> dict:
    if values is None:
        values = np.array([[0, 1, 249], [250, 255, 20]], dtype="uint8")
    image = Image.fromarray(values)
    encoded = io.BytesIO()
    image.save(encoded, format=image_format)
    png = encoded.getvalue()
    return {
        **field_metadata(),
        "cols": image.width,
        "rows": image.height,
        "S": -29.2,
        "W": -51.8,
        "N": -29.1,
        "E": -51.7,
        "max_hand_m": 25.0,
        "nodata": 255,
        "saturated_value": 250,
        "crs": "EPSG:4326",
        "georeferencing": "reprojected_nearest_from_source_utm",
        "hand_png_b64": base64.b64encode(png).decode("ascii"),
        "hand_png_sha256": hashlib.sha256(png).hexdigest(),
    }


def mucum_payload() -> dict:
    return {
        "meta": {
            "municipio": "Muçum",
            "nivel_max_m": 15.0,
            "cobertura_espacial_m": 15.0,
            "gerado_em": "2000-01-01T00:00:00Z",
            "source_id": "synthetic_integration_fixture",
        },
        "nos": [[0.5, 0.5], [0.5, 1.5], [0.5, 3.5], [0.5, 9.0]],
        "cota_no": [99.0] * 4,
        "cota_alaga_m": [99.0] * 4,
        "cells": [
            {"id": "partial", "pop": 10, "cota": 99.0,
             "poly": [[0.2, 1.8], [0.2, 3.8], [0.8, 3.8], [0.8, 1.8]]},
            {"id": "outside", "pop": 20, "cota": 99.0,
             "poly": [[0.2, 9.0], [0.2, 10.0], [0.8, 10.0], [0.8, 9.0]]},
            {"id": "touch_only", "pop": 30, "cota": 99.0,
             "poly": [[0.2, 5.0], [0.2, 6.0], [0.8, 6.0], [0.8, 5.0]]},
            {"id": "fallback", "pop": 40, "cota": 99.0, "lat": 0.5, "lon": 3.5},
            {"id": "missing", "pop": 50, "cota": 99.0, "lat": None, "lon": None},
        ],
    }


class SpatialWriterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="previne-hand-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Path(self.temporary.name)
        # Copies retain the real destination selection and CLI entry points.
        # Their __file__ resolves ROOT/RAIZ entirely inside the temporary tree.
        for relative in (GENERATOR, MOSAIC_HELPER, UPDATER, CONTRACT, RECALC, QUEUE):
            target = self.sandbox / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        sentinel = field_document()
        write_json(self.sandbox / STZ_CONTOURS, sentinel)
        write_json(self.sandbox / STZ_OVERFLOW, {
            "type": "FeatureCollection", "features": [],
            "metadata": {"sentinel": "historical-overflow", "gerado_em": "2000-01-01"},
        })
        for relative in STZ_PAGES:
            write_page(self.sandbox / relative, {
                "meta": {"hand_zero_regua_m": 1.6, "nivel_max_m": 25.0,
                         "gerado_em": "2000-01-01T00:00:00Z", "sentinel": relative.as_posix()},
                "nos": [[0.5, 0.5]], "cota_no": [0.0], "cells": [],
            })
        self.protected = (*STZ_PAGES, STZ_CONTOURS, STZ_OVERFLOW)
        self.before = {path: digest(self.sandbox / path) for path in self.protected}
        for relative in MUCUM_PAGES:
            write_page(self.sandbox / relative, mucum_payload())

    def assert_stz_preserved(self) -> None:
        self.assertEqual(len(STZ_PAGES), 7)
        for relative, expected in self.before.items():
            with self.subTest(protected=relative.as_posix()):
                self.assertEqual(digest(self.sandbox / relative), expected,
                                 "STZ recebeu escrita ou estampa de metadados/data")

    def run_cli(self, relative: Path, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.sandbox / relative), *arguments],
            cwd=self.sandbox, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, check=False,
        )

    def assert_cli_ok(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])

    def make_rasters(self) -> None:
        for city in ("mucum", "santa_tereza"):
            directory = self.sandbox / "assets/data" / f"{city}_inundacao" / "mdt"
            directory.mkdir(parents=True, exist_ok=True)
            for suffix, size, resolution in (("mosaico_2m", 64, 0.00002),
                                             ("anadem_30m", 8, 0.00016)):
                columns = np.arange(size, dtype="float32")
                valley = np.maximum(np.abs(columns - (size - 1) / 2) - size / 16, 0)
                dem = np.tile(50.0 + valley * (32 / size), (size, 1)).astype("float32")
                path = directory / f"mdt_{city}_{suffix}.tif"
                with rasterio.open(
                    path, "w", driver="GTiff", width=size, height=size, count=1,
                    dtype="float32", crs="EPSG:4326", nodata=-9999.0,
                    transform=from_origin(-51.75, -29.16, resolution, resolution),
                ) as dataset:
                    dataset.write(dem, 1)

    def make_mucum_contours(self, maximum: float = 30.0) -> None:
        write_json(self.sandbox / MUCUM_CONTOURS, {
            "type": "FeatureCollection",
            "features": [feature(level, box(0, 0, width, 1))
                         for level, width in ((0.0, 1.0), (1.0, 2.0),
                                              (3.0, 4.0), (maximum, 5.0))],
            "metadata": {"fixture": "synthetic_mucum"},
        })

    def test_vectorizer_main_without_argument_writes_only_mucum_and_preserves_stz(self) -> None:
        self.make_rasters()
        self.assert_cli_ok(self.run_cli(GENERATOR))
        self.assert_stz_preserved()
        expected_levels = [round(index / 10, 1) for index in range(301)]
        self.assertFalse((self.sandbox / STZ_LEGACY).exists(), "não deve criar nem estampar produto STZ legado")
        for relative in (MUCUM_CONTOURS,):
            with self.subTest(output=relative.as_posix()):
                document = json.loads((self.sandbox / relative).read_text(encoding="utf-8"))
                self.assertEqual(document["type"], "FeatureCollection")
                self.assertEqual([item["properties"]["nivel_m"] for item in document["features"]],
                                 expected_levels)
                geometries = [shape(item["geometry"]) for item in document["features"]]
                self.assertTrue(all(not geom.is_empty and geom.is_valid for geom in geometries))
                for previous, current in zip(geometries, geometries[1:]):
                    self.assertLessEqual(previous.difference(current).area, previous.area * 1e-10)

    def test_vectorizer_explicit_stz_is_blocked_in_cli_and_function_without_any_write(self) -> None:
        self.make_rasters()
        self.make_mucum_contours()
        write_json(self.sandbox / STZ_LEGACY, {"sentinel": "existing_legacy", "generated_at": "2000-01-01"})
        protected = {path: digest(self.sandbox / path) for path in (MUCUM_CONTOURS, STZ_LEGACY)}
        code = (
            "import runpy,sys; from pathlib import Path; "
            f"path=Path({str(GENERATOR)!r}); sys.path.insert(0,str(path.parent)); "
            "runpy.run_path(str(path))['gera']('santa_tereza')"
        )
        for entry_point in ("cli", "function"):
            with self.subTest(entry_point=entry_point):
                result = self.run_cli(GENERATOR, "santa_tereza") if entry_point == "cli" else subprocess.run(
                    [sys.executable, "-X", "utf8", "-B", "-c", code], cwd=self.sandbox,
                    capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BLOQUEADO", result.stderr)
                self.assert_stz_preserved()
                for path, expected in protected.items():
                    self.assertEqual(digest(self.sandbox / path), expected)

    def test_updater_main_recalculates_all_mucum_pages_and_preserves_stz(self) -> None:
        self.make_mucum_contours()
        before = {path: digest(self.sandbox / path) for path in MUCUM_PAGES}
        self.assert_cli_ok(self.run_cli(UPDATER))
        self.assert_stz_preserved()
        functions = runpy.run_path(str(self.sandbox / UPDATER))
        for relative in MUCUM_PAGES:
            with self.subTest(page=relative.as_posix()):
                page = self.sandbox / relative
                self.assertNotEqual(digest(page), before[relative])
                html = page.read_text(encoding="utf-8")
                _, payload = functions["extract_payload"](html)
                self.assertEqual(payload["meta"]["nivel_max_m"], 30.0)
                self.assertEqual(payload["meta"]["cobertura_espacial_m"], 30.0)
                self.assertEqual(payload["cota_no"], [0.0, 1.0, 3.0, None])
                self.assertEqual(payload["cota_alaga_m"], [0.0, 1.0, 3.0, None])
                cells = {cell["id"]: cell for cell in payload["cells"]}
                self.assertEqual(cells["partial"]["cota"], 1.0)
                self.assertAlmostEqual(cells["partial"]["frac_area_primeiro_nivel"], 0.1)
                self.assertEqual(cells["partial"]["cota_metodo"], "intersecao_geometrica_celula_ibge")
                for cell_id in ("outside", "touch_only", "missing"):
                    self.assertIsNone(cells[cell_id]["cota"], cell_id)
                self.assertEqual(cells["fallback"]["cota"], 3.0)
                self.assertEqual(cells["fallback"]["cota_metodo"], "ponto_fallback")
                self.assertIn('id="sentinel">preservar conteúdo fora do payload', html)

    def test_updater_rejects_short_coverage_before_any_page_write(self) -> None:
        self.make_mucum_contours(maximum=25.0)
        before = {path: digest(self.sandbox / path) for path in MUCUM_PAGES}
        result = self.run_cli(UPDATER)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RuntimeError", result.stderr)
        self.assert_stz_preserved()
        for relative, expected in before.items():
            with self.subTest(page=relative.as_posix()):
                self.assertEqual(digest(self.sandbox / relative), expected)

    def test_updater_explicit_mucum_works_and_explicit_stz_is_rejected_without_writes(self) -> None:
        self.make_mucum_contours()
        self.assert_cli_ok(self.run_cli(UPDATER, "mucum"))
        self.assert_stz_preserved()
        extract = runpy.run_path(str(self.sandbox / UPDATER))["extract_payload"]
        for path in MUCUM_PAGES:
            _, data = extract((self.sandbox / path).read_text(encoding="utf-8"))
            self.assertEqual(data["cota_no"], [0.0, 1.0, 3.0, None])
        before = {path: digest(self.sandbox / path) for path in MUCUM_PAGES}
        result = self.run_cli(UPDATER, "santa_tereza")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inválida", result.stderr)
        self.assert_stz_preserved()
        for path, expected in before.items():
            self.assertEqual(digest(self.sandbox / path), expected)

    def prepare_route_pages(self, gauge_cm: float = 164.0) -> None:
        for relative in STZ_PAGES[4:]:
            write_page(self.sandbox / relative, {
                "meta": {"nivel": {"fonte": "cenario", "nivel_regua_cm": gauge_cm},
                         "gerado_em": "2000-01-01T00:00:00Z"},
                "nos": [[0.5, 1.002], [0.5, 1.003]],
                "edges": [[0, 1, 0]], "prox": [1, 1],
                "agua_m": [0.0, 0.0], "mancha": [],
            })
        self.before = {path: digest(self.sandbox / path) for path in self.protected}

    def test_recalc_main_writes_real_pages_and_selects_point_zero_four_as_point_one(self) -> None:
        self.prepare_route_pages()
        before = {path: digest(self.sandbox / path) for path in STZ_PAGES}
        self.assert_cli_ok(self.run_cli(RECALC))
        extract = runpy.run_path(str(self.sandbox / UPDATER))["extract_payload"]
        source_hashes = set()
        for relative in STZ_PAGES:
            with self.subTest(page=relative.as_posix()):
                self.assertNotEqual(digest(self.sandbox / relative), before[relative])
                _, payload = extract((self.sandbox / relative).read_text(encoding="utf-8"))
                meta = payload["meta"]
                self.assertEqual(meta["hand_zero_regua_m"], 1.6)
                self.assertEqual(meta["status"], "pesquisa_exercicio_nao_operacional")
                self.assertEqual(meta["hand_source"]["source_id"], SOURCE_ID)
                source_hashes.add(meta["hand_source"]["contours_sha256"])
                if relative in STZ_PAGES[4:]:
                    self.assertAlmostEqual(meta["hand_solicitado_m"], 0.04)
                    self.assertEqual(meta["hand_aplicado_m"], 0.1)
                    self.assertEqual(meta["nivel_projeto_m"], 0.1)
                    self.assertEqual(payload["edges"][0][2], 1)
                    self.assertGreater(payload["agua_m"][0], 0)
        self.assertEqual(len(source_hashes), 1)
        diagnostic = STZ_CONTOURS.with_name("painel_evacuacao_hand_campo_diagnostic.json")
        report = json.loads((self.sandbox / diagnostic).read_text(encoding="utf-8"))
        self.assertEqual(report["source_provenance"]["contours_sha256"], source_hashes.pop())
        for relative in (STZ_CONTOURS, STZ_OVERFLOW):
            self.assertEqual(digest(self.sandbox / relative), self.before[relative])

    def test_route_update_keeps_dry_islands_and_separates_hand_zero_from_bankfull(self) -> None:
        # Run the actual writer against an HTML file, then rebuild the geometry
        # from the persisted Leaflet payload, including every interior ring.
        original_path = sys.path[:]
        sys.path.insert(0, str(self.sandbox / "scripts"))
        try:
            recalc = runpy.run_path(str(self.sandbox / RECALC))
        finally:
            sys.path[:] = original_path

        first = box(-51.75, -29.17, -51.73, -29.15).difference(
            box(-51.745, -29.165, -51.735, -29.155)
        )
        second = box(-51.79, -29.17, -51.77, -29.15).difference(
            box(-51.785, -29.165, -51.775, -29.155)
        )
        page = self.sandbox / STZ_PAGES[4]
        # (Gauge metres, expected selected HAND level, overflow status).
        cases = ((1.64, 0.1, False), (14.99, 13.4, False),
                 (15.0, 13.4, False), (15.01, 13.5, True))
        for geometry in (first, MultiPolygon([first, second])):
            polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
            document = {"type": "FeatureCollection", "metadata": field_metadata(),
                        "features": [feature(level, geometry) for level in FIELD_LEVELS]}
            levels, geometries, provenance = recalc["validate_field_contours"](document)
            nodes, edges, prox, dry_points = [], [], [], []
            for polygon in polygons:
                west, south, east, north = polygon.bounds
                center = (west + east) / 2
                offset = len(nodes)
                # The first segment lies wholly inside the dry island; the
                # second lies wholly inside the surrounding inundation.
                nodes.extend([[south + (north - south) / 2, center - 0.002],
                              [south + (north - south) / 2, center + 0.002],
                              [south + 0.002, west + 0.002],
                              [south + 0.002, east - 0.002]])
                edges.extend([[offset, offset + 1, 1], [offset + 2, offset + 3, 0]])
                prox.extend([offset + 1, offset + 1, offset + 3, offset + 3])
                dry_points.append(Point(center, (south + north) / 2))

            for gauge_m, selected_hand_m, overflowing in cases:
                with self.subTest(geometry=geometry.geom_type, gauge_m=gauge_m):
                    write_page(page, {
                        "meta": {"nivel": {"fonte": "cenario", "nivel_regua_cm": gauge_m * 100,
                                           "bankfull_m": 1.6, "hand_zero_regua_m": 4.0,
                                           "transbordando": True}},
                        "nos": nodes, "edges": copy.deepcopy(edges), "prox": prox,
                        "agua_m": [-1.0] * len(nodes), "mancha": [],
                    })
                    summary = recalc["update_route_page"](page, geometries, levels, provenance)
                    _, _, payload = recalc["read_embedded_payload"](page)
                    leaflet = payload["mancha"]
                    self.assertEqual(len(leaflet), len(polygons))
                    restored_polygons = []
                    for rings, original in zip(leaflet, polygons):
                        self.assertEqual(len(rings), 1 + len(original.interiors))
                        for ring in rings:
                            self.assertEqual(ring[0], ring[-1])
                            self.assertGreaterEqual(len(ring), 4)
                        xy = [[(lon, lat) for lat, lon in ring] for ring in rings]
                        restored_polygons.append(Polygon(xy[0], xy[1:]))
                    restored = MultiPolygon(restored_polygons)
                    self.assertTrue(restored.is_valid)
                    self.assertAlmostEqual(restored.area, geometry.area, delta=1e-16)
                    self.assertLessEqual(restored.symmetric_difference(geometry).area, 1e-16)
                    self.assertTrue(all(not restored.covers(point) for point in dry_points))
                    self.assertEqual([edge[2] for edge in payload["edges"]], [0, 1] * len(polygons))
                    for offset in range(0, len(nodes), 4):
                        self.assertEqual(payload["agua_m"][offset], 0.0)
                        self.assertGreater(payload["agua_m"][offset + 2], 0.0)
                    meta = payload["meta"]
                    self.assertEqual(meta["hand_zero_regua_m"], 1.6)
                    self.assertEqual(meta["nivel"]["hand_zero_regua_m"], 1.6)
                    self.assertEqual(meta["nivel"]["bankfull_m"], 15.0)
                    self.assertIs(meta["nivel"]["transbordando"], overflowing)
                    self.assertEqual(meta["nivel_regua_cenario_m"], gauge_m)
                    self.assertEqual(meta["hand_solicitado_m"], round(gauge_m - 1.6, 6))
                    self.assertEqual(meta["hand_aplicado_m"], selected_hand_m)
                    self.assertEqual(meta["hand_source"], provenance)
                    self.assertEqual(meta["status"], "pesquisa_exercicio_nao_operacional")
                    self.assertEqual(summary["edges_intersecting_contour"], len(polygons))
                    self.assertIn('id="sentinel">preservar conteúdo fora do payload',
                                  page.read_text(encoding="utf-8"))

    def test_recalc_preflight_rejects_last_route_above_coverage_without_any_write(self) -> None:
        self.prepare_route_pages()
        page = self.sandbox / STZ_PAGES[-1]
        extract = runpy.run_path(str(self.sandbox / UPDATER))["extract_payload"]
        _, payload = extract(page.read_text(encoding="utf-8"))
        payload["meta"]["nivel"]["nivel_regua_cm"] = 2661.0  # HAND 25.01 m
        write_page(page, payload)
        self.before[STZ_PAGES[-1]] = digest(page)
        diagnostic = self.sandbox / STZ_CONTOURS.with_name("painel_evacuacao_hand_campo_diagnostic.json")
        write_json(diagnostic, {"status": "sentinel", "generated_at": "2000-01-01"})
        report_hash = digest(diagnostic)
        result = self.run_cli(RECALC)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sem cobertura HAND no intervalo", result.stderr)
        self.assert_stz_preserved()
        self.assertEqual(digest(diagnostic), report_hash)

    def test_recalc_preflight_rejects_broken_last_payload_without_partial_writes(self) -> None:
        self.prepare_route_pages()
        last_page = self.sandbox / STZ_PAGES[-1]
        last_page.write_text("<html>payload sintético ausente</html>\n", encoding="utf-8")
        self.before[STZ_PAGES[-1]] = digest(last_page)
        result = self.run_cli(RECALC)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("payload D", result.stderr)
        self.assert_stz_preserved()

    def test_recalc_prepares_all_seven_before_last_structure_or_serialization_failure(self) -> None:
        extract = runpy.run_path(str(self.sandbox / UPDATER))["extract_payload"]
        changes = (
            ("missing_edges", lambda data: data.pop("edges")),
            ("edge_out_of_range", lambda data: data.update(edges=[[0, 999, 0]])),
            ("short_prox", lambda data: data.update(prox=[1])),
            ("fractional_prox", lambda data: data.update(prox=[0.5, 1])),
            ("invalid_node", lambda data: data.update(nos=[[True, 0.5], [0.5, 1.003]])),
            ("invalid_population", lambda data: data.update(cells=[{
                "poly": [[0, 0], [0, 1], [1, 1], [1, 0]], "pop": "unknown"}])),
            ("nonfinite_unconsumed_field", lambda data: data.update(extra=float("nan"))),
        )
        for label, mutate in changes:
            with self.subTest(last_payload_failure=label):
                self.prepare_route_pages()
                last = self.sandbox / STZ_PAGES[-1]
                _, data = extract(last.read_text(encoding="utf-8"))
                mutate(data)
                write_page(last, data)
                self.before[STZ_PAGES[-1]] = digest(last)
                report = self.sandbox / STZ_CONTOURS.with_name("painel_evacuacao_hand_campo_diagnostic.json")
                write_json(report, {"status": "ok", "generated_at": "2000-01-01", "sentinel": "old_report"})
                previous_report = digest(report)
                result = self.run_cli(RECALC)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Error", result.stderr)
                self.assert_stz_preserved()
                self.assertEqual(digest(report), previous_report,
                                 "falha tardia não deve reestampar o relatório antigo")

    def test_recalc_rejects_legacy_metadata_without_field_stamp_or_report(self) -> None:
        self.prepare_route_pages()
        document = field_document()
        document["metadata"]["hand_zero_cm"] = 400
        write_json(self.sandbox / STZ_CONTOURS, document)
        self.before[STZ_CONTOURS] = digest(self.sandbox / STZ_CONTOURS)
        result = self.run_cli(RECALC)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fonte HAND incompatível", result.stderr)
        self.assert_stz_preserved()
        self.assertFalse((self.sandbox / STZ_CONTOURS.with_name(
            "painel_evacuacao_hand_campo_diagnostic.json")).exists())

    def prepare_queue_inputs(self) -> Path:
        cells = []
        for index in range(1, 5):
            # Cell begins between consecutive cumulative contours, so the
            # first positive overlap is exactly HAND 0.1/0.2/0.3/0.4 m.
            left = 1 + (index - 0.5) / 250
            cells.append({"type": "Feature", "properties": {"pop": 10},
                          "geometry": mapping(box(left, 0.2, left + 0.001, 0.3))})
        write_json(self.sandbox / "assets/data/vulnerabilidade/grade/4317251.geojson",
                   {"type": "FeatureCollection", "features": cells})
        write_json(self.sandbox / "assets/data/rota_fuga/rota_fuga_ruas_santa_tereza.json", {
            "nos": [[0.25, 1.01]], "dist_m": [10.0], "dest": ["exercise"], "prox": [0],
            "abrigos": [{"id": "exercise", "node": 0, "nome": "Destino de exercício",
                         "lat": 0.25, "lon": 1.01}],
        })
        return self.sandbox / "assets/data/rota_fuga/fila_cidade_santa_tereza.json"

    def test_queue_main_preserves_decimetre_thresholds_including_point_four(self) -> None:
        output = self.prepare_queue_inputs()
        self.assert_cli_ok(self.run_cli(QUEUE, "--cidade", "santa_tereza"))
        self.assert_stz_preserved()
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([cell["cota"] for cell in document["cells"]], [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(document["meta"]["zero_regua_m"], 1.6)
        self.assertEqual(document["meta"]["hand_source"]["source_id"], SOURCE_ID)
        self.assertEqual(document["meta"]["pop_total"], 40)
        self.assertTrue(all(cell["cobertura_status"] == "limiar_identificado"
                            for cell in document["cells"]))

    def test_queue_rejects_incompatible_source_before_replacing_old_output(self) -> None:
        output = self.prepare_queue_inputs()
        write_json(output, {"meta": {"zero_regua_m": 4.0, "sentinel": "historical"}})
        output_hash = digest(output)
        document = field_document()
        document["metadata"]["source_id"] = "legacy_mosaic_not_field_calibrated"
        write_json(self.sandbox / STZ_CONTOURS, document)
        self.before[STZ_CONTOURS] = digest(self.sandbox / STZ_CONTOURS)
        result = self.run_cli(QUEUE, "--cidade", "santa_tereza")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fonte HAND incompatível", result.stderr)
        self.assertEqual(digest(output), output_hash)
        self.assert_stz_preserved()


class PublisherIndexGuardTests(unittest.TestCase):
    def run_index_guard(self, staged: list[str], exit_code: int = 0) -> dict:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(powershell, "PowerShell é necessário para executar a guarda real do publisher")
        path = str(ROOT / PUBLISHER).replace("'", "''")
        fixture = json.dumps(staged).replace("'", "''")
        # Parse the real file, then execute ONLY its guard function. A local
        # function shadows git; no publisher body, native Git or index runs.
        script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) {{ throw ($parseErrors | Out-String) }}
$guard = @($ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-ProductOnlyStaged' }}, $true))
if ($guard.Count -ne 1) {{ throw 'guarda ausente ou duplicada' }}
Invoke-Expression $guard[0].Extent.Text
$global:FakePaths = @('{fixture}' | ConvertFrom-Json)
$global:GitCalls = @()
function global:git {{
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    $global:GitCalls += ,@($Args)
    $global:LASTEXITCODE = {exit_code}
    $global:FakePaths
}}
$blocked = $false; $message = ''
try {{ Assert-ProductOnlyStaged -Allowed @('santa_tereza_inundacao.html', 'assets/data/santa_tereza_inundacao/contornos_mancha.json') -Phase 'teste isolado' }}
catch {{ $blocked = $true; $message = $_.Exception.Message }}
@{{ blocked=$blocked; message=$message; calls=@($global:GitCalls); staged=@($global:FakePaths) }} | ConvertTo-Json -Depth 5 -Compress
"""
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip())
        self.assertEqual(report["calls"], [["-c", "core.quotepath=false", "diff", "--cached",
                                           "--name-only", "--no-renames"]])
        self.assertEqual(report["staged"], staged, "a guarda não deve remover entradas do índice")
        return report

    def test_publisher_guard_accepts_empty_or_only_product_index(self) -> None:
        for staged in ([], ["santa_tereza_inundacao.html"],
                       ["santa_tereza_inundacao.html", "assets/data/santa_tereza_inundacao/contornos_mancha.json"]):
            with self.subTest(staged=staged):
                self.assertFalse(self.run_index_guard(staged)["blocked"])

    def test_publisher_guard_rejects_foreign_staged_and_both_sides_of_rename(self) -> None:
        for staged in (["scripts/unrelated.py"],
                       ["santa_tereza_inundacao.html", "scripts/unrelated.py"],
                       ["foreign/original.html", "santa_tereza_inundacao.html"]):
            with self.subTest(staged=staged):
                report = self.run_index_guard(staged)
                self.assertTrue(report["blocked"])
                self.assertIn("staged alheio", report["message"])

    def test_publisher_guard_fails_closed_when_index_read_fails(self) -> None:
        report = self.run_index_guard([], exit_code=128)
        self.assertTrue(report["blocked"])
        self.assertIn("verificar o indice", report["message"])

    def test_publisher_orders_guards_before_fetch_generation_add_and_commit_and_keeps_consumers(self) -> None:
        text = (ROOT / PUBLISHER).read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", text)
        initial_guard = text.index('Assert-ProductOnlyStaged -Allowed $allowed -Phase "fetch/geracao"')
        first_fetch = text.index("Invoke-Git fetch origin")
        generator = text.index('& python "codigo_python/02_mdt_hand_mancha/gerar_hand_lidar_santa_tereza.py"')
        sync = text.index('& python "codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_santa_tereza.py"')
        recalc = text.index('& python "scripts/recalcular_painel_evacuacao_hand_campo.py"')
        self.assertLess(initial_guard, first_fetch)
        self.assertLess(first_fetch, generator)
        self.assertLess(generator, sync)
        self.assertLess(sync, recalc)
        self.assertLess(text.index('Assert-ProductOnlyStaged -Allowed $allowed -Phase "git add"'),
                        text.index("& git add -- $p"))
        self.assertLess(text.index('Assert-ProductOnlyStaged -Allowed $allowed -Phase "commit"'),
                        text.index("Invoke-Git commit -m"))
        for path in STZ_PAGES:
            self.assertIn('"' + path.as_posix() + '"', text)
        self.assertIn('"assets/data/santa_tereza_inundacao/contornos_extravasamento.json"', text)
        self.assertIn("contornos_extravasamento\\.json", text)


class HandFieldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # A missing implementation is an error, not a silently skipped guard.
        cls.api = runpy.run_path(str(ROOT / CONTRACT))

    def validate_contours(self, document: dict):
        return self.api["validate_field_contours"](document)

    def validate_raster(self, payload: dict):
        return self.api["validate_raster_payload"](payload)

    def test_synthetic_field_contours_return_geometry_and_bound_provenance(self) -> None:
        document = field_document()
        original = copy.deepcopy(document)
        levels, geometries, provenance = self.validate_contours(document)
        self.assertEqual(levels, FIELD_LEVELS)
        self.assertEqual(len(geometries), 251)
        self.assertTrue(geometries[0].equals(box(0, 0, 1, 1)))
        self.assertTrue(geometries[-1].equals(box(0, 0, 2, 2)))
        self.assertEqual(provenance["source_id"], SOURCE_ID)
        self.assertEqual(provenance["hand_zero_cm"], 160)
        self.assertEqual(provenance["max_hand_m"], 25.0)
        canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        self.assertEqual(provenance["contours_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(document, original, "validar não deve reparar ou reestampar a entrada")

    def test_contour_provenance_changes_when_source_geometry_changes(self) -> None:
        document = field_document()
        _, _, before = self.validate_contours(document)
        document["features"][-1]["geometry"] = mapping(box(0, 0, 2.1, 2.1))
        _, _, after = self.validate_contours(document)
        self.assertNotEqual(before["contours_sha256"], after["contours_sha256"])
        self.assertEqual(before["source_id"], after["source_id"])

    def test_missing_field_metadata_is_rejected_by_both_validators(self) -> None:
        keys = ("source_id", "cidade", "hand_zero_cm", "rio",
                "superficie_inundacao", "superficie_roteamento")
        for key in keys:
            with self.subTest(missing=key, product="contours"):
                document = field_document()
                del document["metadata"][key]
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)
            with self.subTest(missing=key, product="raster"):
                payload = raster_payload()
                del payload[key]
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)
        document = field_document()
        del document["metadata"]
        with self.assertRaises(RuntimeError):
            self.validate_contours(document)

    def test_incompatible_field_metadata_is_rejected_by_both_validators(self) -> None:
        cases = (
            ("source_id", "legacy_mosaic_not_field_calibrated"),
            ("cidade", "mucum"),
            ("hand_zero_cm", 400),
            ("hand_zero_cm", 1500),
            ("rio", "todos os cursos de água"),
            ("superficie_inundacao", "FILL_CLIP_MOSAICO_LIDAR_RS.tif"),
            ("superficie_inundacao", "HAND mosaico drone + ANADEM"),
            ("superficie_roteamento", "CLIP_MOSAICO_LIDAR_RS.tif (LiDAR bruto)"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value, product="contours"):
                document = field_document()
                document["metadata"][key] = value
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)
            with self.subTest(key=key, value=value, product="raster"):
                payload = raster_payload()
                payload[key] = value
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)

    def test_missing_duplicate_and_off_grid_levels_are_rejected(self) -> None:
        for index in (0, 1, 125, 250):
            with self.subTest(missing_level=FIELD_LEVELS[index]):
                document = field_document()
                del document["features"][index]
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)
        document = field_document()
        document["features"][1] = copy.deepcopy(document["features"][0])
        with self.assertRaises(RuntimeError):
            self.validate_contours(document)
        for replacement in (0.15, -0.1, 25.1):
            with self.subTest(off_grid=replacement):
                document = field_document()
                document["features"][1]["properties"]["nivel_m"] = replacement
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)

    def test_non_numeric_or_non_finite_levels_are_rejected(self) -> None:
        for value in (None, True, "0.1", float("nan"), float("inf"), -float("inf")):
            with self.subTest(level=value):
                document = field_document()
                document["features"][1]["properties"]["nivel_m"] = value
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)

    def test_invalid_empty_and_non_polygonal_geometry_are_rejected(self) -> None:
        cases = (
            None,
            {"type": "Polygon", "coordinates": []},
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
            {"type": "Point", "coordinates": [0, 0]},
        )
        for geometry in cases:
            with self.subTest(geometry=geometry):
                document = field_document()
                document["features"][1]["geometry"] = geometry
                with self.assertRaises(RuntimeError):
                    self.validate_contours(document)

    def test_cumulativity_rejects_shrinkage_and_spatial_loss_despite_area_growth(self) -> None:
        for geometry in (box(0, 0, 0.9904, 1), box(0.01, 0, 1.1, 1.1)):
            with self.subTest(area=geometry.area):
                document = field_document()
                document["features"][1]["geometry"] = mapping(geometry)
                with self.assertRaisesRegex(RuntimeError, "não cumulativos"):
                    self.validate_contours(document)

    def test_cumulativity_tolerance_is_explicit_and_only_allows_numeric_noise(self) -> None:
        self.assertEqual(self.api["CUMULATIVE_REL_TOL"], 1e-8)
        self.assertEqual(self.api["CUMULATIVE_ABS_TOL"], 1e-16)
        for loss, accepted in ((5e-9, True), (2e-8, False)):
            with self.subTest(relative_loss=loss):
                document = field_document()
                for item in document["features"]:
                    item["geometry"] = mapping(box(0, 0, 1, 1))
                document["features"][1]["geometry"] = mapping(box(loss, 0, 1, 1))
                if accepted:
                    levels, _, _ = self.validate_contours(document)
                    self.assertEqual(levels, FIELD_LEVELS)
                else:
                    with self.assertRaisesRegex(RuntimeError, "não cumulativos"):
                        self.validate_contours(document)

    def test_unsorted_features_are_ordered_by_their_actual_levels(self) -> None:
        document = field_document()
        document["features"].reverse()
        levels, geometries, _ = self.validate_contours(document)
        self.assertEqual(levels, FIELD_LEVELS)
        self.assertTrue(geometries[0].equals(box(0, 0, 1, 1)))

    def test_raster_digest_binds_png_bytes_and_preserves_nodata_and_saturation(self) -> None:
        payload = raster_payload()
        original = copy.deepcopy(payload)
        provenance = self.validate_raster(payload)
        png = base64.b64decode(payload["hand_png_b64"], validate=True)
        self.assertEqual(provenance["source_id"], SOURCE_ID)
        self.assertEqual(provenance["hand_png_sha256"], hashlib.sha256(png).hexdigest())
        self.assertEqual(provenance["hand_zero_cm"], 160)
        self.assertEqual(provenance["max_hand_m"], 25.0)
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(np.array(image).reshape(-1).tolist(), [0, 1, 249, 250, 255, 20])
        self.assertEqual(payload, original)

    def test_raster_rejects_missing_or_wrong_encoding_metadata(self) -> None:
        cases = (
            ("max_hand_m", 30.0), ("max_hand_m", 15.0),
            ("nodata", 0), ("saturated_value", 255),
            ("crs", "EPSG:31982"), ("georeferencing", "unknown"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                payload = raster_payload()
                payload[key] = value
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)
        for key in ("max_hand_m", "nodata", "saturated_value", "crs", "georeferencing"):
            with self.subTest(missing=key):
                payload = raster_payload()
                del payload[key]
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)

    def test_raster_rejects_invalid_bounds_and_dimensions(self) -> None:
        cases = (
            ("S", -29.0), ("W", -51.6), ("N", float("nan")),
            ("E", float("inf")), ("S", True), ("W", "-51.8"),
            ("rows", 0), ("cols", -1), ("rows", True), ("cols", 3.0),
            ("rows", 3), ("cols", 4),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                payload = raster_payload()
                payload[key] = value
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)

    def test_raster_rejects_spoofed_digest_and_changed_png(self) -> None:
        payload = raster_payload()
        del payload["hand_png_sha256"]
        with self.assertRaises(RuntimeError):
            self.validate_raster(payload)
        payload = raster_payload()
        payload["hand_png_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.validate_raster(payload)
        payload = raster_payload()
        changed = raster_payload(np.array([[0, 2, 249], [250, 255, 20]], dtype="uint8"))
        payload["hand_png_b64"] = changed["hand_png_b64"]
        with self.assertRaises(RuntimeError):
            self.validate_raster(payload)

    def test_raster_rejects_reserved_pixel_codes_and_wrong_color_mode(self) -> None:
        for value in range(251, 255):
            with self.subTest(reserved=value):
                payload = raster_payload(np.array([[value]], dtype="uint8"))
                with self.assertRaises(RuntimeError):
                    self.validate_raster(payload)
        payload = raster_payload(np.zeros((2, 3, 3), dtype="uint8"))
        with self.assertRaises(RuntimeError):
            self.validate_raster(payload)

    def test_raster_rejects_malformed_base64_and_non_image_bytes(self) -> None:
        payload = raster_payload()
        payload["hand_png_b64"] = "not-base64!"
        with self.assertRaises(ValueError):
            self.validate_raster(payload)
        payload = raster_payload()
        invalid = b"this is not a raster"
        payload["hand_png_b64"] = base64.b64encode(invalid).decode("ascii")
        payload["hand_png_sha256"] = hashlib.sha256(invalid).hexdigest()
        with self.assertRaises(OSError):
            self.validate_raster(payload)

    def test_raster_rejects_non_png_even_with_a_matching_digest(self) -> None:
        # JPEG can alter encoded HAND values and cannot satisfy a PNG contract.
        payload = raster_payload(np.zeros((2, 3), dtype="uint8"), image_format="JPEG")
        with self.assertRaises(RuntimeError):
            self.validate_raster(payload)

    def test_gauge_boundaries_and_decimetre_float_noise(self) -> None:
        for gauge, hand, selected in ((1.5, 0.0, 0.0), (1.6, 0.0, 0.0),
                                      (1.7, 0.1, 0.1)):
            with self.subTest(gauge_m=gauge):
                result = self.api["gauge_to_hand"](gauge)
                self.assertAlmostEqual(result, hand, places=12)
                self.assertEqual(self.api["select_hand_level"](FIELD_LEVELS, result), selected)
        for requested in (0.1 - 1e-15, 0.1, 0.1 + 1e-15):
            with self.subTest(hand_m=requested):
                self.assertEqual(self.api["select_hand_level"](FIELD_LEVELS, requested), 0.1)

    def test_level_selection_uses_upper_level_and_does_not_clamp_missing_coverage(self) -> None:
        for requested, expected in ((0.01, 0.1), (0.04, 0.1), (0.11, 0.2), (24.99, 25.0),
                                    (25.0, 25.0), (25.1, None), (-0.1, None),
                                    (float("nan"), None), (float("inf"), None), (True, None)):
            with self.subTest(hand_m=requested):
                self.assertEqual(self.api["select_hand_level"](FIELD_LEVELS, requested), expected)
        self.assertIsNone(self.api["select_hand_level"]([], 0.0))
        for value in (None, True, "1.6", float("nan"), float("inf")):
            with self.subTest(gauge_m=value):
                with self.assertRaises(ValueError):
                    self.api["gauge_to_hand"](value)

    def test_current_field_contours_meet_the_same_contract(self) -> None:
        path = ROOT / STZ_CONTOURS
        source_bytes = path.read_bytes()
        snapshot = hashlib.sha256(source_bytes).hexdigest()
        document = json.loads(source_bytes)
        try:
            levels, _, provenance = self.validate_contours(document)
        except RuntimeError as error:
            self.fail(f"{STZ_CONTOURS.as_posix()} sha256={snapshot}: {error}")
        self.assertEqual(levels, FIELD_LEVELS)
        self.assertEqual(provenance["source_id"], SOURCE_ID)
        diagnostic_path = path.with_name("painel_evacuacao_hand_campo_diagnostic.json")
        diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        self.assertEqual(diagnostic["source_provenance"]["contours_sha256"],
                         provenance["contours_sha256"],
                         "diagnóstico reestampado sem correspondência com os contornos atuais")


if __name__ == "__main__":
    unittest.main()
