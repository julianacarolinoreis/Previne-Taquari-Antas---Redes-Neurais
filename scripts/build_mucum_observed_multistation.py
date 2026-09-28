#!/usr/bin/env python3
"""Observed rain + flow package for the current Muçum flood.

Window: 26/09/2026 00:00 America/Sao_Paulo -> now.
- Rain: every upstream station that has an actual valid observed series in the
  operational PREVINE CSV, plus rain returned by active upstream ANA telemetry
  and live INMET/CEMADEN sources when available.
- Flow/level: active upstream ANA/SGB telemetric stations used by the live robot,
  plus Muçum (86510000).
- Missing observations remain missing and are never converted to zero.
- Areal rain is IDW^2 from all valid gauges for each hour, clipped to the exact
  HEC-HMS two-zone geometry.
"""
from __future__ import annotations

import csv
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/data/estudo_bacia_taquari_antas"
RAIN_CATALOG = OUT / "pluviometria_g040.geojson"
FLOW_CATALOG = OUT / "postos_g040.geojson"
BASIN_PATH = ROOT / "assets/data/hec_hms_spatialized_mucum/watershed_86510000_srtm.geojson"
ZONES_PATH = ROOT / "assets/data/hec_hms_spatialized_mucum/thiessen_zones_86510000.geojson"
CHUVAS = ROOT / "assets/data/chuvas_horarias.csv"
LIVE_STZ = ROOT / "previsao_ao_vivo.json"
LIVE_MUC = ROOT / "previsao_ao_vivo_mucum.json"

JSON_OUT = OUT / "mucum_observed_multistation_latest.json"
RAIN_CSV = OUT / "mucum_observed_multistation_rain_hourly.csv"
FLOW_CSV = OUT / "mucum_observed_multistation_flow_hourly.csv"

BRT = timezone(timedelta(hours=-3))
UTC = timezone.utc
EVENT_START_LOCAL = datetime(2026, 9, 26, 0, 0)

ANA_PRIMARY = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ANA_MIRROR = "https://www.ana.gov.br/telemetria1ws/ServiceANA.asmx/DadosHidrometeorologicos"
INMET_URL = "https://apitempo.inmet.gov.br/estacao/{start}/{end}/{code}"
CEMADEN_URL = "https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/{station_id}/167"
CEMADEN_IDS = {"432040401A": "8928", "4320404010A": "8928"}

# Existing operational observed-rain archive. Canonical code -> CSV column.
CSV_RAIN_COLUMNS = {
    "86472600": "chuva_86472600",
    "86472000": "chuva_86472000",
    "2851044": "chuva_02851044",
    "2851072": "chuva_02851072",
    "A894": "chuva_inmet_A894",
    "432040401A": "chuva_cemaden_4320404010A",
}
# Extra upstream rain candidates used by current research/live models.
EXTRA_RAIN_CODES = {"86510000", "86160000"}

ANA_TIMEOUT = 12
ANA_RETRIES = 2
GRID_STEP = 0.05
ANA_CACHE: dict[str, dict[str, Any]] = {}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_ana_time(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            pass
    return None


def request_bytes(url: str, timeout: int = ANA_TIMEOUT) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "previne-mucum-event/2.0",
            "Accept": "application/json,text/xml,application/xml,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def parse_ana_xml(raw: bytes, start: datetime, end: datetime) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    roots = [root]
    if (root.text or "").strip().startswith("<"):
        try:
            roots.append(ET.fromstring(root.text))
        except Exception:
            pass
    rows: list[dict[str, Any]] = []
    seen = set()
    for rt in roots:
        for node in rt.iter():
            fields = {lname(ch.tag): (ch.text or "") for ch in node}
            stamp = fields.get("DataHora") or fields.get("Data_Hora")
            if not stamp:
                continue
            dt = parse_ana_time(stamp)
            if dt is None or dt < start or dt > end:
                continue
            key = (dt, fields.get("Chuva"), fields.get("Vazao"), fields.get("Nivel"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "time_local": dt,
                    "rain_mm": finite(fields.get("Chuva") or fields.get("chuva") or fields.get("Precipitacao")),
                    "flow_m3s": finite(fields.get("Vazao") or fields.get("vazao")),
                    "level": finite(fields.get("Nivel") or fields.get("nivel")),
                }
            )
    return rows


def fetch_ana(code: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Same stable policy as the live robot: serial, primary+mirror, retry."""
    code = str(code).lstrip("0") if str(code).startswith("0") and len(str(code)) == 8 else str(code)
    if code in ANA_CACHE:
        return ANA_CACHE[code]
    params = urllib.parse.urlencode(
        {
            "codEstacao": code,
            "dataInicio": start.strftime("%d/%m/%Y"),
            "dataFim": end.strftime("%d/%m/%Y"),
        }
    )
    errors = []
    for attempt in range(ANA_RETRIES):
        for base in (ANA_PRIMARY, ANA_MIRROR):
            url = f"{base}?{params}"
            try:
                raw = request_bytes(url)
                rows = parse_ana_xml(raw, start, end)
                if rows:
                    result = {
                        "ok": True,
                        "rows": rows,
                        "source": "ANA/SGB DadosHidrometeorologicos",
                        "endpoint": base,
                    }
                    ANA_CACHE[code] = result
                    return result
                errors.append(f"{base}: resposta sem série válida")
            except urllib.error.HTTPError as exc:
                errors.append(f"{base}: HTTP {exc.code}")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        if attempt < ANA_RETRIES - 1:
            time.sleep(3)
    result = {"ok": False, "rows": [], "source": "ANA/SGB", "error": " | ".join(errors[-4:])}
    ANA_CACHE[code] = result
    return result


def parse_inmet_time(row: dict[str, Any]) -> datetime | None:
    d = str(row.get("DT_MEDICAO") or "").strip()
    h = str(row.get("HR_MEDICAO") or "").strip()
    if not d:
        return None
    try:
        return datetime.strptime(d + (h.zfill(4)[:4] if h else "0000"), "%Y-%m-%d%H%M")
    except ValueError:
        return None


def fetch_inmet(code: str, start: datetime, end: datetime) -> dict[str, Any]:
    try:
        url = INMET_URL.format(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            code=urllib.parse.quote(code),
        )
        data = json.loads(request_bytes(url, timeout=15).decode("utf-8", errors="replace") or "[]")
        if not isinstance(data, list):
            data = []
        rows = []
        for item in data:
            if not isinstance(item, dict):
                continue
            dt = parse_inmet_time(item)
            if dt is None or dt < start or dt > end:
                continue
            rain = finite(
                item.get("CHUVA")
                if item.get("CHUVA") not in (None, "")
                else item.get("PRECIPITACAO_TOTAL_HORARIO_MM")
            )
            rows.append({"time_local": dt, "rain_mm": rain, "flow_m3s": None, "level": None})
        return {"ok": bool(rows), "rows": rows, "source": "INMET API Tempo"}
    except Exception as exc:
        return {"ok": False, "rows": [], "source": "INMET", "error": str(exc)}


def fetch_cemaden(code: str, start: datetime, end: datetime) -> dict[str, Any]:
    sid = CEMADEN_IDS.get(code)
    if not sid:
        return {"ok": False, "rows": [], "source": "CEMADEN", "error": "id CEMADEN não mapeado"}
    try:
        payload = json.loads(
            request_bytes(CEMADEN_URL.format(station_id=sid), timeout=15).decode("utf-8", errors="replace")
            or "{}"
        )
        dates = payload.get("datas") if isinstance(payload, dict) else None
        vals = (
            payload.get("chuvas")
            or payload.get("valores")
            or payload.get("precipitacoes")
            or []
        ) if isinstance(payload, dict) else []
        rows = []
        if isinstance(dates, list):
            for i, raw_t in enumerate(dates):
                text = str(raw_t).replace("T", " ").replace("Z", "")
                dt = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        dt = datetime.strptime(text[:19], fmt)
                        break
                    except ValueError:
                        pass
                if dt is None or dt < start or dt > end:
                    continue
                rows.append(
                    {
                        "time_local": dt,
                        "rain_mm": finite(vals[i]) if i < len(vals) else None,
                        "flow_m3s": None,
                        "level": None,
                    }
                )
        return {"ok": bool(rows), "rows": rows, "source": "CEMADEN horário 167h"}
    except Exception as exc:
        return {"ok": False, "rows": [], "source": "CEMADEN", "error": str(exc)}


def aggregate_hourly(rows: list[dict[str, Any]]) -> dict[datetime, dict[str, float | None]]:
    buckets: dict[datetime, dict[str, list[float]]] = {}
    for row in rows:
        t = row["time_local"].replace(minute=0, second=0, microsecond=0)
        b = buckets.setdefault(t, {"rain": [], "flow": [], "level": []})
        if row.get("rain_mm") is not None and float(row["rain_mm"]) >= 0:
            b["rain"].append(float(row["rain_mm"]))
        if row.get("flow_m3s") is not None and float(row["flow_m3s"]) >= 0:
            b["flow"].append(float(row["flow_m3s"]))
        if row.get("level") is not None:
            b["level"].append(float(row["level"]))
    return {
        t: {
            "rain_mm": sum(b["rain"]) if b["rain"] else None,
            "flow_m3s": sum(b["flow"]) / len(b["flow"]) if b["flow"] else None,
            "level": sum(b["level"]) / len(b["level"]) if b["level"] else None,
        }
        for t, b in buckets.items()
    }


def basin_and_zones():
    basin = unary_union(
        [shape(f["geometry"]) for f in load(BASIN_PATH).get("features") or [] if f.get("geometry")]
    )
    zones = {}
    for feat in load(ZONES_PATH).get("features") or []:
        props = feat.get("properties") or {}
        if props.get("feature_type") == "thiessen_zone" and props.get("station"):
            zones[str(props["station"])] = shape(feat["geometry"]).intersection(basin)
    return basin, zones


def catalog_map(path: Path, basin) -> dict[str, dict[str, Any]]:
    out = {}
    for feat in load(path).get("features") or []:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = finite(coords[0]), finite(coords[1])
        code = str(props.get("codigo") or "").strip()
        if not code or lon is None or lat is None or not basin.covers(Point(lon, lat)):
            continue
        out[code] = {
            "code": code,
            "name": props.get("nome") or code,
            "network": str(props.get("rede") or "ANA").upper(),
            "lat": float(lat),
            "lon": float(lon),
            "upg": props.get("upg"),
            "in_previne_rain": bool(props.get("in_previne_rain")),
            "operating_flag": props.get("situacao") if props.get("situacao") is not None else props.get("operando"),
        }
    return out


def csv_observed_rain(start: datetime, end: datetime) -> dict[str, dict[datetime, float]]:
    series = {code: {} for code in CSV_RAIN_COLUMNS}
    if not CHUVAS.exists():
        return series
    with CHUVAS.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            raw = str(row.get("COD_SEQUENCIAL") or "").strip()
            try:
                t = datetime.strptime(raw, "%Y%m%d%H%M")
            except ValueError:
                continue
            if t < start or t > end:
                continue
            for code, col in CSV_RAIN_COLUMNS.items():
                v = finite(row.get(col))
                if v is not None and v >= 0:
                    series[code][t.replace(minute=0, second=0, microsecond=0)] = float(v)
    return series


def active_flow_codes() -> set[str]:
    codes = {"86510000"}
    if LIVE_STZ.exists():
        live = load(LIVE_STZ)
        for item in live.get("estacoes_status") or []:
            if not isinstance(item, dict):
                continue
            if item.get("ultima_leitura_bruta") and item.get("estacao"):
                codes.add(str(item["estacao"]))
    return codes


def fetch_network(station: dict[str, Any], start: datetime, end: datetime) -> dict[str, Any]:
    network = station.get("network", "ANA")
    if network == "INMET":
        return fetch_inmet(station["code"], start, end)
    if network == "CEMADEN":
        return fetch_cemaden(station["code"], start, end)
    return fetch_ana(station["code"], start, end)


def grid(geom) -> list[tuple[float, float, float]]:
    minx, miny, maxx, maxy = geom.bounds
    points = []
    y = math.floor(miny / GRID_STEP) * GRID_STEP + GRID_STEP / 2
    while y <= maxy:
        x = math.floor(minx / GRID_STEP) * GRID_STEP + GRID_STEP / 2
        while x <= maxx:
            if geom.covers(Point(x, y)):
                points.append((x, y, max(0.1, math.cos(math.radians(y)))))
            x += GRID_STEP
        y += GRID_STEP
    return points


def idw_mean(
    points: list[tuple[float, float, float]],
    stations: list[dict[str, Any]],
    values: dict[str, float],
    k: int = 6,
) -> float | None:
    usable = [s for s in stations if values.get(s["code"]) is not None]
    if not usable or not points:
        return None
    total = 0.0
    total_area = 0.0
    for gx, gy, area_weight in points:
        distances = []
        for s in usable:
            dx = (float(s["lon"]) - gx) * math.cos(math.radians(gy))
            dy = float(s["lat"]) - gy
            d2 = dx * dx + dy * dy
            distances.append((d2, float(values[s["code"]])))
        distances.sort(key=lambda x: x[0])
        nearest = distances[: min(k, len(distances))]
        if nearest[0][0] < 1e-12:
            value = nearest[0][1]
        else:
            ws = [1.0 / d2 for d2, _ in nearest]
            value = sum(w * v for w, (_, v) in zip(ws, nearest)) / sum(ws)
        total += value * area_weight
        total_area += area_weight
    return total / total_area if total_area else None


def iso(t: datetime) -> str:
    return t.isoformat(timespec="minutes")


def main() -> int:
    start = EVENT_START_LOCAL
    end = datetime.now(BRT).replace(tzinfo=None)
    # Preserve the last successfully published event observations. Public ANA
    # telemetry is intermittently unavailable; a transient API failure must
    # never erase observations already collected for this same flood.
    previous = {}
    if JSON_OUT.exists():
        try:
            previous = load(JSON_OUT)
        except Exception:
            previous = {}
    basin, zones = basin_and_zones()
    rain_catalog = catalog_map(RAIN_CATALOG, basin)
    flow_catalog = catalog_map(FLOW_CATALOG, basin)

    # 1) Operational archived rain is the non-negotiable baseline.
    csv_rain = csv_observed_rain(start, end)
    rain_series: dict[str, dict[datetime, float]] = {
        code: dict(series) for code, series in csv_rain.items() if series
    }
    rain_sources: dict[str, str] = {
        code: "PREVINE chuvas_horarias.csv" for code in rain_series
    }

    # Metadata for CSV rain stations can live in either rain or flow inventory.
    rain_meta: dict[str, dict[str, Any]] = {}
    for code in CSV_RAIN_COLUMNS:
        st = rain_catalog.get(code) or flow_catalog.get(code)
        if st:
            rain_meta[code] = dict(st)

    # 2) Query all active upstream flow stations from the live robot once.
    flow_codes = active_flow_codes()
    active_flow_meta = {
        code: flow_catalog[code]
        for code in flow_codes
        if code in flow_catalog
    }

    # 3) Add upstream rainfall candidates actually used by PREVINE/current models.
    rain_candidate_codes = {
        code for code, st in rain_catalog.items() if st.get("in_previne_rain")
    }
    rain_candidate_codes |= EXTRA_RAIN_CODES
    rain_candidate_codes |= set(active_flow_meta)
    rain_query_meta: dict[str, dict[str, Any]] = {}
    for code in sorted(rain_candidate_codes):
        st = rain_catalog.get(code) or flow_catalog.get(code)
        if st:
            rain_query_meta[code] = dict(st)

    # Fetch serially on purpose: this mirrors the stable policy of the live robot.
    fetched: dict[str, dict[str, Any]] = {}
    all_query_meta = dict(active_flow_meta)
    all_query_meta.update(rain_query_meta)
    for code, st in all_query_meta.items():
        fetched[code] = fetch_network(st, start, end)
        # Short courtesy pause prevents a burst against ANA public telemetry.
        if st.get("network", "ANA") == "ANA":
            time.sleep(0.15)

    # Merge actual rainfall returned by active telemetry. CSV wins on overlap
    # because it is the operational archived source already used by PREVINE.
    for code, st in rain_query_meta.items():
        result = fetched.get(code) or {}
        hourly = aggregate_hourly(result.get("rows") or [])
        network_rain = {
            t: float(v["rain_mm"])
            for t, v in hourly.items()
            if v.get("rain_mm") is not None
        }
        if network_rain:
            rain_meta[code] = dict(st)
            rain_sources.setdefault(code, result.get("source") or st.get("network") or "telemetria")
            target = rain_series.setdefault(code, {})
            for t, v in network_rain.items():
                target.setdefault(t, v)

    # Merge the last published valid station histories as a persistence
    # fallback. Fresh CSV/API values win on overlap; prior values only fill
    # holes caused by transient source outages.
    rain_fallback_codes = []
    for prev_st in ((previous.get("rain") or {}).get("stations") or []):
        if not isinstance(prev_st, dict):
            continue
        code = str(prev_st.get("code") or "").strip()
        if not code:
            continue
        st = rain_catalog.get(code) or flow_catalog.get(code)
        if st is None:
            st = {
                "code": code,
                "name": prev_st.get("name") or code,
                "network": prev_st.get("network") or "ANA",
                "lat": prev_st.get("lat"),
                "lon": prev_st.get("lon"),
                "upg": prev_st.get("upg"),
                "in_previne_rain": bool(prev_st.get("in_previne_rain")),
                "operating_flag": prev_st.get("operating_flag"),
            }
        if st.get("lat") is None or st.get("lon") is None:
            continue
        target = rain_series.setdefault(code, {})
        before = len(target)
        for row in prev_st.get("series") or []:
            if not isinstance(row, dict) or row.get("mm") is None:
                continue
            try:
                t = datetime.fromisoformat(str(row.get("time_local")))
            except (TypeError, ValueError):
                continue
            if start <= t <= end:
                target.setdefault(t.replace(minute=0, second=0, microsecond=0), float(row["mm"]))
        if len(target) > before:
            rain_fallback_codes.append(code)
            rain_meta.setdefault(code, dict(st))
            rain_sources.setdefault(code, "última observação válida publicada + fontes atuais")

    # Keep only gauges with at least one real observed value since 26/09.
    rain_series = {code: series for code, series in rain_series.items() if series}
    rain_stations = []
    for code in sorted(rain_series):
        st = rain_meta.get(code) or rain_catalog.get(code) or flow_catalog.get(code)
        if not st:
            continue
        item = dict(st)
        item["source"] = rain_sources.get(code)
        item["valid_hours"] = len(rain_series[code])
        rain_stations.append(item)

    # Flow/level: active upstream stations only, including Muçum. Start
    # from fresh telemetry, then fill missing historical hours from the last
    # published valid event package.
    flow_hourly: dict[str, dict[datetime, dict[str, float | None]]] = {}
    flow_sources: dict[str, str] = {}
    for code, st in active_flow_meta.items():
        result = fetched.get(code) or {}
        hourly = aggregate_hourly(result.get("rows") or [])
        if any(v.get("flow_m3s") is not None or v.get("level") is not None for v in hourly.values()):
            flow_hourly[code] = hourly
            flow_sources[code] = result.get("source") or "ANA/SGB"

    flow_fallback_codes = []
    for prev_st in ((previous.get("flow") or {}).get("stations") or []):
        if not isinstance(prev_st, dict):
            continue
        code = str(prev_st.get("code") or "").strip()
        if not code or code not in active_flow_meta:
            continue
        target = flow_hourly.setdefault(code, {})
        before = len(target)
        for row in prev_st.get("series") or []:
            if not isinstance(row, dict):
                continue
            if row.get("flow_m3s") is None and row.get("level") is None:
                continue
            try:
                t = datetime.fromisoformat(str(row.get("time_local")))
            except (TypeError, ValueError):
                continue
            if not (start <= t <= end):
                continue
            key = t.replace(minute=0, second=0, microsecond=0)
            old = target.get(key) or {}
            target.setdefault(
                key,
                {
                    "flow_m3s": finite(row.get("flow_m3s")),
                    "level": finite(row.get("level")),
                    "rain_mm": None,
                },
            )
            # Fill individual missing variables without replacing fresher ones.
            cur = target[key]
            if cur.get("flow_m3s") is None and row.get("flow_m3s") is not None:
                cur["flow_m3s"] = finite(row.get("flow_m3s"))
            if cur.get("level") is None and row.get("level") is not None:
                cur["level"] = finite(row.get("level"))
        if len(target) > before:
            flow_fallback_codes.append(code)
            flow_sources.setdefault(code, "última observação válida publicada + fontes atuais")

    flow_stations = []
    for code, hourly in sorted(flow_hourly.items()):
        st = active_flow_meta.get(code)
        if st is None:
            continue
        nq = sum(v.get("flow_m3s") is not None for v in hourly.values())
        nl = sum(v.get("level") is not None for v in hourly.values())
        if not nq and not nl:
            continue
        item = dict(st)
        item.update(
            {
                "source": flow_sources.get(code),
                "valid_flow_hours": nq,
                "valid_level_hours": nl,
            }
        )
        flow_stations.append(item)

    # Hourly areal rainfall by exact HEC zones.
    grids = {"basin": grid(basin), **{code: grid(geom) for code, geom in zones.items()}}
    hours = []
    t = start
    while t <= end.replace(minute=0, second=0, microsecond=0):
        hours.append(t)
        t += timedelta(hours=1)

    areal_rows = []
    for hour in hours:
        values = {
            code: series[hour]
            for code, series in rain_series.items()
            if hour in series
        }
        row: dict[str, Any] = {
            "time_local": iso(hour),
            "valid_station_count": len(values),
            "valid_station_codes": sorted(values),
            "basin_mean_mm": idw_mean(grids["basin"], rain_stations, values),
        }
        for code in zones:
            row[f"zone_{code}_mm"] = idw_mean(grids[code], rain_stations, values)
        areal_rows.append(row)

    with RAIN_CSV.open("w", encoding="utf-8", newline="") as fh:
        fields = [
            "time_local",
            "valid_station_count",
            "valid_station_codes",
            "basin_mean_mm",
            *[f"zone_{code}_mm" for code in zones],
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in areal_rows:
            writer.writerow(
                {
                    k: (
                        ";".join(v)
                        if isinstance(v, list)
                        else ""
                        if v is None
                        else round(v, 4)
                        if isinstance(v, float)
                        else v
                    )
                    for k, v in row.items()
                }
            )

    with FLOW_CSV.open("w", encoding="utf-8", newline="") as fh:
        fields = ["code", "name", "upg", "time_local", "flow_m3s", "level"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for st in flow_stations:
            for hour, values in sorted(flow_hourly[st["code"]].items()):
                if values.get("flow_m3s") is None and values.get("level") is None:
                    continue
                writer.writerow(
                    {
                        "code": st["code"],
                        "name": st["name"],
                        "upg": st.get("upg"),
                        "time_local": iso(hour),
                        "flow_m3s": "" if values.get("flow_m3s") is None else round(float(values["flow_m3s"]), 4),
                        "level": "" if values.get("level") is None else round(float(values["level"]), 4),
                    }
                )

    rain_payload = []
    for st in rain_stations:
        code = st["code"]
        rain_payload.append(
            {
                **st,
                "series": [
                    {"time_local": iso(t), "mm": round(v, 4)}
                    for t, v in sorted(rain_series[code].items())
                ],
            }
        )

    flow_payload = []
    for st in flow_stations:
        code = st["code"]
        flow_payload.append(
            {
                **st,
                "series": [
                    {
                        "time_local": iso(t),
                        "flow_m3s": None if v.get("flow_m3s") is None else round(float(v["flow_m3s"]), 4),
                        "level": None if v.get("level") is None else round(float(v["level"]), 4),
                    }
                    for t, v in sorted(flow_hourly[code].items())
                    if v.get("flow_m3s") is not None or v.get("level") is not None
                ],
            }
        )

    failures = [
        {"code": code, "network": st.get("network"), "error": (fetched.get(code) or {}).get("error")}
        for code, st in all_query_meta.items()
        if not (fetched.get(code) or {}).get("ok")
    ]

    payload = {
        "schema_version": "mucum_observed_multistation_v2",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event_window": {
            "start_local": iso(start),
            "end_local": iso(end),
            "timezone": "America/Sao_Paulo",
        },
        "watershed": {
            "outlet_station": "86510000",
            "scope": "bacia contribuinte até Muçum; estações a jusante excluídas",
        },
        "rain": {
            "inventory_count_inside": len(rain_catalog),
            "valid_station_count": len(rain_stations),
            "valid_station_codes": [st["code"] for st in rain_stations],
            "valid_by_network": {
                net: sum(st.get("network") == net for st in rain_stations)
                for net in ("ANA", "INMET", "CEMADEN")
            },
            "spatial_method": (
                "IDW^2 por hora em grade 0.05° sobre a bacia e zonas HEC; "
                "usa todos os postos com observação válida; ausência permanece ausente, nunca zero"
            ),
            "hourly_areal": [
                {
                    k: (None if v is None else round(v, 4) if isinstance(v, float) else v)
                    for k, v in row.items()
                }
                for row in areal_rows
            ],
            "stations": rain_payload,
        },
        "flow": {
            "active_candidate_codes": sorted(active_flow_meta),
            "stations_with_flow_or_level": len(flow_stations),
            "stations_with_flow": sum(st["valid_flow_hours"] > 0 for st in flow_stations),
            "stations_with_level": sum(st["valid_level_hours"] > 0 for st in flow_stations),
            "stations": flow_payload,
        },
        "fetch_audit": {
            "queried_station_count": len(all_query_meta),
            "failed_count": len(failures),
            "failures": failures,
            "policy": "serial ANA queries; primary+mirror; 2 retries; operational CSV baseline; last published valid event observations persist through transient API outages",
            "rain_fallback_station_codes": sorted(set(rain_fallback_codes)),
            "flow_fallback_station_codes": sorted(set(flow_fallback_codes)),
        },
        "artifacts": {
            "rain_csv": str(RAIN_CSV.relative_to(ROOT)),
            "flow_csv": str(FLOW_CSV.relative_to(ROOT)),
        },
        "research_only": True,
    }
    JSON_OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "rain_inventory_inside": len(rain_catalog),
                "rain_valid": len(rain_stations),
                "rain_codes": [st["code"] for st in rain_stations],
                "rain_valid_by_network": payload["rain"]["valid_by_network"],
                "flow_active_candidates": len(active_flow_meta),
                "flow_valid": len(flow_stations),
                "flow_with_q": payload["flow"]["stations_with_flow"],
                "failures": len(failures),
                "event_start": payload["event_window"]["start_local"],
                "event_end": payload["event_window"]["end_local"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
