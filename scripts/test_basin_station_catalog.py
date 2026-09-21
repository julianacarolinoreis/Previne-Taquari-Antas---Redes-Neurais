import json
import tempfile
import unittest
from pathlib import Path

from scripts import basin_station_catalog as catalog


class BasinStationCatalogTests(unittest.TestCase):
    def test_polygon_mask_accepts_inside_and_rejects_outside(self):
        polygon = [[[-52.0, -29.0], [-51.0, -29.0], [-51.0, -28.0], [-52.0, -28.0], [-52.0, -29.0]]]
        self.assertTrue(catalog._point_in_polygon_coordinates(-51.5, -28.5, polygon))
        self.assertFalse(catalog._point_in_polygon_coordinates(-50.5, -28.5, polygon))

    def test_cemaden_jsonp_is_unwrapped(self):
        payload = catalog._jsonp_payload(
            'estacoes([{"atualizado":"2026-09-21 17:00:00 UTC","estacao":[]}])'
        )
        self.assertEqual(payload["atualizado"], "2026-09-21 17:00:00 UTC")
        self.assertEqual(payload["estacao"], [])

    def test_sgb_panel_parser_keeps_report_link_and_coordinates(self):
        html = '''
        <iframe src="relatorio.php?apenas_grafico=sim&bacia=taquari&pm=32&s=54&sr=55"></iframe>
        const station = L.circleMarker([-29.10000, -51.70000], {}).bindTooltip("86472600 - Santa Tereza");
        '''
        stations = catalog._parse_sgb_stations(html)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0]["code"], "86472600")
        self.assertEqual(stations[0]["latitude"], -29.1)
        self.assertIn("relatorio.php", stations[0]["report_url"])

    def test_external_sources_merge_roles_without_duplicate_physical_station(self):
        with tempfile.TemporaryDirectory() as directory:
            geometry_path = Path(directory) / "ugs.geojson"
            geometry_path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[-52, -29], [-51, -29], [-51, -28], [-52, -28], [-52, -29]]],
                                },
                                "properties": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rain = 'estacoes([{"atualizado":"2026-09-21 17:00:00 UTC","estacao":[{"codestacao":"432000001A","nomeestacao":"Centro","latitude":-28.5,"longitude":-51.5,"status":0,"acumulado":2.5}]}])'
            hydro = 'estacoes([{"estacao":[{"codestacao":"432000001H","nomeestacao":"Rio","latitude":-28.6,"longitude":-51.6,"status":0,"nivel":3.2}]}])'
            sgb = '''
            <iframe src="relatorio.php?apenas_grafico=sim&bacia=taquari&pm=32&s=54&sr=55"></iframe>
            const station = L.circleMarker([-29.10000, -51.70000], {}).bindTooltip("86472600 - Santa Tereza");
            '''
            responses = {
                catalog.CEMADEN_RAIN_URL: rain,
                catalog.CEMADEN_HYDRO_URL: hydro,
                catalog.SGB_TAQUARI_URL: sgb,
            }
            stations = [
                {
                    "id": "ANA:86472600",
                    "code": "86472600",
                    "name": "SANTA TEREZA",
                    "network": "ANA",
                    "latitude": -29.1,
                    "longitude": -51.7,
                    "types": ["fluviometrica"],
                    "type_label": "fluviometrica",
                    "upgs": [],
                    "upg_label": "UPG",
                    "catalog_sources": ["base.json"],
                }
            ]
            result, metadata = catalog.augment_station_catalog(
                stations,
                geometry_path=geometry_path,
                fetcher=lambda url: responses[url],
            )

        self.assertEqual(len(result), 3)
        ana = next(item for item in result if item["code"] == "86472600")
        self.assertIn("SGB/SACE", ana["source_networks"])
        self.assertEqual(metadata["sources"]["cemaden_rain"]["added_station_count"], 1)
        self.assertEqual(metadata["sources"]["cemaden_hydro"]["added_station_count"], 1)
        self.assertTrue(metadata["complete"])


if __name__ == "__main__":
    unittest.main()
