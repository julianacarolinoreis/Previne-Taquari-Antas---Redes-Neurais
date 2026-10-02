#!/usr/bin/env python3
"""Parse raw ANA/HidroWeb/CPRM cross-section text exports.

The parser is deliberately provenance-first:
- reads common ISO-8859-1/Windows-1252/UTF-8 text exports;
- extracts station metadata and the Verticais table;
- preserves gauge-relative cota in centimetres;
- never converts gauge-relative cota to absolute elevation without an audited
  benchmark/gauge-zero relationship;
- never maps a profile to a HEC-RAS section automatically.

Usage:
  python scripts/parse_hidroweb_cross_section.py INPUT [OUTPUT_PREFIX]

Outputs:
  <prefix>.json  metadata/provenance summary
  <prefix>.csv   numeric verticals: point_id,distance_m,cota_cm
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path


def decode_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise UnicodeError(f"Could not decode {path}")


def num(value: str):
    value = value.strip().replace(".", "").replace(",", ".") if "," in value else value.strip()
    try:
        return float(value)
    except ValueError:
        return None


def field(lines, label):
    rx = re.compile(r"^" + re.escape(label) + r":\s*(.*)$", re.I)
    for line in lines:
        m = rx.match(line.strip())
        if m:
            return m.group(1).strip()
    return None


def parse(path: Path):
    text, encoding = decode_text(path)
    lines = text.splitlines()

    station = {
        "name": field(lines, "Nome"),
        "code": field(lines, "Código"),
        "river": field(lines, "Rio"),
        "municipality": field(lines, "Município"),
        "uf": field(lines, "UF"),
        "responsible": field(lines, "Responsável"),
        "operator": field(lines, "Operadora"),
        "drainage_area_km2": num(field(lines, "Área de drenagem (km2)") or ""),
        "consistency": field(lines, "Nível de consistência"),
        "survey_date": field(lines, "Data"),
        "survey_time": field(lines, "Hora"),
        "survey_number": field(lines, "Núm. do levantamento"),
        "section_type": field(lines, "Tipo de seção"),
        "pi_pf_distance_m": num(field(lines, "Distância PI-PF (m)") or ""),
        "x_min_m": num(field(lines, "Eixo X - Distância mínima (m)") or ""),
        "x_max_m": num(field(lines, "Eixo X - Distância máxima (m)") or ""),
        "y_min_cm": num(field(lines, "Eixo Y - Cota mínima (cm)") or ""),
        "y_max_cm": num(field(lines, "Eixo Y - Cota máxima (cm)") or ""),
    }

    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Verticais")
    except StopIteration:
        raise ValueError("Section 'Verticais' not found")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "Elementos Geométricos":
            end = i
            break

    pts = []
    for line in lines[start + 1:end]:
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        d = num(parts[1])
        z = num(parts[2])
        if d is None or z is None:
            continue
        pts.append({"point_id": int(parts[0]), "distance_m": d, "cota_cm": z})

    if not pts:
        raise ValueError("No numeric Verticais recovered")

    station["verticals_count"] = len(pts)
    station["distance_min_m_recovered"] = min(p["distance_m"] for p in pts)
    station["distance_max_m_recovered"] = max(p["distance_m"] for p in pts)
    station["cota_min_cm_recovered"] = min(p["cota_cm"] for p in pts)
    station["cota_max_cm_recovered"] = max(p["cota_cm"] for p in pts)

    result = {
        "schema_version": "hidroweb_cross_section_parser_v1",
        "source_file": path.name,
        "source_encoding": encoding,
        "station": station,
        "vertical_reference": "GAUGE_RELATIVE_COTA_CM_UNLESS_SOURCE_STATES_OTHERWISE",
        "absolute_elevation_ready": False,
        "hec_ras_section_mapping_ready": False,
        "safety_rule": (
            "Do not convert cota_cm to absolute elevation or assign the profile "
            "to a HEC-RAS section without audited station/gauge-zero and location mapping."
        ),
        "verticals": pts,
    }
    return result


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: parse_hidroweb_cross_section.py INPUT [OUTPUT_PREFIX]")
    src = Path(sys.argv[1])
    prefix = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix("")
    out_json = prefix.with_suffix(".json")
    out_csv = prefix.with_suffix(".csv")

    result = parse(src)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["point_id", "distance_m", "cota_cm"])
        w.writeheader()
        w.writerows(result["verticals"])

    print(json.dumps({
        "json": str(out_json),
        "csv": str(out_csv),
        "station": result["station"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
