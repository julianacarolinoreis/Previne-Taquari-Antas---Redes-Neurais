#!/usr/bin/env python3
"""Smoke-test the deployed vulnerability page without a browser dependency.

This is intentionally a small HTTP/contract check for CI or a post-Pages
release. It does not claim to replace visual or accessibility testing.
"""

from __future__ import annotations

import argparse
import gzip
import json
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_URL = "https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais/vulnerabilidade.html"
INITIAL_ASSETS = (
    "assets/data/vulnerabilidade/rs_contorno.geojson",
    "assets/data/vulnerabilidade/bacia.geojson",
    "assets/data/vulnerabilidade/municipios.geojson",
    "assets/data/vulnerabilidade/downloads/catalogo.json",
    "assets/data/servicos/contagem_municipios.json",
    "assets/data/icm_municipios.json",
    "assets/data/vulnerabilidade/referencias/resiliencia_municipios.json",
    "assets/data/vulnerabilidade/referencias/open_buildings_tiles.geojson",
    "assets/data/vulnerabilidade/referencias/obitos.geojson",
    "assets/data/vulnerabilidade/referencias/obitos_metadata.json",
    "assets/data/vulnerabilidade/referencias/obitos_source.zip",
    "assets/data/vulnerabilidade/referencias/README_OBITOS.md",
)


def get(url: str, *, head: bool = False):
    req = Request(url, method="HEAD" if head else "GET", headers={"Accept-Encoding": "gzip"})
    with urlopen(req, timeout=20) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return response.status, response.headers, body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expect-commit", help="Require this DATA_FALLBACK_COMMIT in the deployed HTML")
    args = parser.parse_args()

    status, headers, body = get(args.url)
    assert status == 200, f"page HTTP {status}"
    text = body.decode("utf-8")
    assert "Content-Security-Policy" in text, "CSP meta ausente"
    assert 'name="referrer"' in text, "referrer policy ausente"
    assert "Permissions-Policy" in text, "Permissions-Policy meta ausente"
    assert "integrity=" in text and "unpkg.com" in text, "Leaflet sem SRI/fallback"
    assert "Estradas DAER/RS" in text and "Open Buildings" in text and "Óbitos" in text and "resiliencia" in text, "referencias novas ausentes"
    assert 'id="locationPicker"' in text and 'id="startHere"' in text and "Encontre um dado em 3 passos" in text, "roteiro de primeira visita ausente"
    assert "número / valor" in text and "% na área" in text, "rótulos de modo ambíguos ausentes"
    if args.expect_commit:
        assert f'DATA_FALLBACK_COMMIT = "{args.expect_commit}"' in text, "fallback commit divergente"
    assert headers.get("Strict-Transport-Security"), "HSTS ausente"

    checks = []
    for asset in INITIAL_ASSETS:
        asset_status, asset_headers, asset_body = get(urljoin(args.url, asset))
        assert asset_status == 200, f"{asset}: HTTP {asset_status}"
        assert asset_body, f"{asset}: resposta vazia"
        checks.append({"asset": asset, "bytes": len(asset_body), "content_type": asset_headers.get_content_type()})

    print(json.dumps({"url": args.url, "html_bytes": len(body), "assets": checks, "status": "OK"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
