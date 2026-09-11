#!/usr/bin/env python3
"""Validate the OpenStreetMap raster-tile contract used by public HTML pages."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
LEGACY_TEMPLATE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
REFERRER_POLICY = "strict-origin-when-cross-origin"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
CSP_META = re.compile(
    r"<meta\b[^>]*\bhttp-equiv=[\"']Content-Security-Policy[\"'][^>]*>",
    re.IGNORECASE,
)


def main() -> int:
    checked: list[str] = []
    errors: list[str] = []

    for path in sorted(ROOT.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        if "tile.openstreetmap.org" not in text:
            continue

        relative = path.relative_to(ROOT).as_posix()
        checked.append(relative)

        if LEGACY_TEMPLATE in text or "https://*.tile.openstreetmap.org" in text:
            errors.append(f"{relative}: usa host/subdomínios OSM antigos")
        if CANONICAL_TEMPLATE not in text:
            errors.append(f"{relative}: URL canônica de tiles OSM ausente")
        if REFERRER_POLICY not in text:
            errors.append(f"{relative}: referrerPolicy explícita ausente")
        if COPYRIGHT_URL not in text or "OpenStreetMap</a> contributors" not in text:
            errors.append(f"{relative}: atribuição OSM completa e vinculada ausente")

        csp_tags = CSP_META.findall(text)
        if csp_tags and not any("https://tile.openstreetmap.org" in tag for tag in csp_tags):
            errors.append(f"{relative}: CSP não permite o host canônico de tiles OSM")

    if not checked:
        errors.append("nenhuma página HTML com tiles OSM foi encontrada")

    result = {"paginas_osm": len(checked), "arquivos": checked, "status": "OK" if not errors else "ERRO"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise AssertionError("; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
