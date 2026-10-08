#!/usr/bin/env python3
"""Observed rain + flow package for the current Muçum flood.

Window: 26/09/2026 00:00 America/Sao_Paulo -> now.
- Rain: every operational station in the basin inventory is queried; any station
  returning valid rain can contribute for that hour.
- Flow/level: every operational hydrometric station in the basin inventory is
  queried; valid observations are retained after QC.
- Missing observations remain missing and are never converted to zero.
- Areal rain is IDW^2 from all valid gauges for each hour, clipped to the exact
  HEC-HMS two-zone geometry.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
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
G040_OBS = ROOT / "assets/data/hec_hms_g040_full_basin/whole_basin_observed_rain_latest.json"

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

FAST_MODE = os.environ.get("OBS_FAST_MODE", "0").strip().lower() in {"1","true","yes"}
ANA_TIMEOUT = int(os.environ.get("OBS_ANA_TIMEOUT", "10" if FAST_MODE else "12"))
ANA_RETRIES = int(os.environ.get("OBS_ANA_RETRIES", "2" if FAST_MODE else "2"))
GRID_STEP = 0.05
ANA_CACHE: dict[str, dict[str, Any]] = {}
MAX_FETCH_WORKERS = int(os.environ.get("OBS_FETCH_WORKERS", "4" if FAST_MODE else "6"))
MAX_FLOW_M3S = 50000.0
MAX_RAIN_MM_H = 250.0
FRESH_FLOW_MINUTES = 120.0

def inventory_operational(st: dict[str, Any]) -> bool:
    """Inventory-driven eligibility; no hand-picked station list."""
    flag = str(st.get("operating_flag") or "").strip().lower()
    network = str(st.get("network") or "ANA").upper()
    if network == "CEMADEN":
        return True
    if network == "INMET":
        return flag not in {"pane", "inoperante", "0", "false", "não", "nao"}
    return flag not in {"0", "false", "inoperante", "desativada", "desativado"}

def qc_flow(v: Any) -> float | None:
    x = finite(v)
    if x is None or x < 0 or x > MAX_FLOW_M3S:
        return None
    return x

def qc_rain(v: Any) -> float | None:
    x = finite(v)
    if x is None or x < 0 or x > MAX_RAIN_MM_H:
        return None
    return x


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
            # ANA returns HTTP 429 under load. Back off instead of amplifying
            # the rate limit with simultaneous retries from multiple workers.
            time.sleep(min(15, 3 * (2 ** attempt)))
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
        rv = qc_rain(row.get("rain_mm"))
        qv = qc_flow(row.get("flow_m3s"))
        if rv is not None:
            b["rain"].append(rv)
        if qv is not None:
            b["flow"].append(qv)
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
            "station_type": str(props.get("tipo") or ""),
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
) -> float | None:
    """Area-weighted IDW^2 field using every station valid for the hour."""
    usable=[s for s in stations if values.get(s["code"]) is not None]
    if not usable or not points:
        return None
    total=0.0
    total_area=0.0
    for gx,gy,area_weight in points:
        distances=[]
        for st in usable:
            dx=(float(st["lon"])-gx)*math.cos(math.radians(gy))
            dy=float(st["lat"])-gy
            d2=dx*dx+dy*dy
            distances.append((d2,float(values[st["code"]])))
        exact=next((v for d2,v in distances if d2<1e-12),None)
        if exact is not None:
            value=exact
        else:
            weights=[1.0/d2 for d2,_ in distances]
            value=sum(w*v for w,(_,v) in zip(weights,distances))/sum(weights)
        total+=value*area_weight
        total_area+=area_weight
    return total/total_area if total_area else None

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
    # Fast cycles query only recent telemetry and merge it with the already
    # validated event history. Full calibration still queries 26/09->now.
    query_start = start
    if FAST_MODE and previous:
        query_start = max(start, end - timedelta(hours=8))

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

    # 2) Basin-complete dynamic inventory.
    # No station is selected because it appears in a PREVINE hand list.
    # Every operational gauge inside the watershed is a candidate. A station
    # only disappears from the effective network when it has no valid data.
    active_flow_meta = {
        code: dict(st)
        for code, st in flow_catalog.items()
        if inventory_operational(st)
    }
    rain_query_meta: dict[str, dict[str, Any]] = {}
    for source in (rain_catalog, flow_catalog):
        for code, st in source.items():
            if inventory_operational(st):
                rain_query_meta.setdefault(code, dict(st))

    # Query the complete eligible basin inventory with bounded concurrency.
    # Historical values already published are merged below, so transient source
    # failures never erase the event history.
    fetched: dict[str, dict[str, Any]] = {}
    all_query_meta = dict(active_flow_meta)
    all_query_meta.update(rain_query_meta)

    # G040 already retrieves the entire observed station network. For ten-minute
    # cycles with a fresh archive, rotate direct ANA queries rather than flood
    # its API; keep *all* stations in modeling via full archived observations.
    request_meta = dict(all_query_meta)
    refresh_audit = {
        "mode": "full_inventory", "eligible_count": len(all_query_meta),
        "requested_count": len(all_query_meta), "archive_age_hours": None,
    }
    if FAST_MODE and G040_OBS.exists() and previous:
        try:
            archive = load(G040_OBS)
            archived_at = datetime.fromisoformat(str(archive.get("generated_at_utc")).replace("Z", "+00:00"))
            age_h = (datetime.now(UTC) - archived_at.astimezone(UTC)).total_seconds() / 3600
            ready = archive.get("status") == "OBSERVED_RAIN_READY" and -0.25 <= age_h <= 3.0 and len(archive.get("stations") or []) >= 20
            if ready and all_query_meta:
                keys = sorted(all_query_meta)
                batch = max(8, int(os.environ.get("OBS_RECENT_REFRESH_BATCH", "32")))
                offset = (int(time.time() // 600) * batch) % len(keys)
                rotating = {keys[(offset+i) % len(keys)] for i in range(min(batch, len(keys)))}
                rotating.update(code for code in ("86472000","86472600","86500000","86510000") if code in all_query_meta)
                request_meta = {code: all_query_meta[code] for code in sorted(rotating)}
                refresh_audit.update({
                    "mode": "rotating_recent_fetch_plus_full_g040_archive",
                    "requested_count": len(request_meta), "rotation_batch": batch,
                    "archive_age_hours": round(age_h,2),
                    "not_fetched_in_this_cycle":len(all_query_meta)-len(request_meta),
                })
        except (TypeError, ValueError, OSError):
            refresh_audit["mode"] = "full_inventory_archive_check_failed"
    with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(fetch_network, st, query_start, end): code
            for code, st in request_meta.items()
        }
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                fetched[code] = fut.result()
            except Exception as exc:
                fetched[code] = {
                    "ok": False, "rows": [], "source": all_query_meta[code].get("network"),
                    "error": str(exc),
                }

    # Merge actual rainfall returned by active telemetry. CSV wins on overlap
    # because it is the operational archived source already used by PREVINE.
    for code, st in rain_query_meta.items():
        result = fetched.get(code) or {}
        hourly = aggregate_hourly(result.get("rows") or [])
        network_rain = {
            t: qc_rain(v.get("rain_mm"))
            for t, v in hourly.items()
            if qc_rain(v.get("rain_mm")) is not None
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

    # Reconcile the other independently collected G040 station archive.
    # G040 contains stations *downstream* of Muçum. Never import one merely
    # because it appears in G040: intersect station ID with the Muçum basin
    # inventory, eligibility, and watershed point geometry.
    # Keep fresh current/CVS data on overlap; only fill missing genuine hours.
    g040_fallback = {
        "source": str(G040_OBS.relative_to(ROOT)),
        "status": "unavailable",
        "gauges_considered_upstream": 0,
        "stations_filled": 0,
        "hours_filled": 0,
        "conflicts_preserved": 0,
        "excluded_downstream_or_ineligible": 0,
        "generated_at_utc": None,
    }
    if G040_OBS.exists():
        try:
            g040 = load(G040_OBS)
            if g040.get("status") != "OBSERVED_RAIN_READY":
                raise ValueError("G040 observed package is not ready")
            ts_raw = g040.get("generated_at_utc")
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            age_h = (datetime.now(UTC) - ts.astimezone(UTC)).total_seconds() / 3600
            if not (-0.25 <= age_h <= 12):
                raise ValueError("G040 observed archive is stale or future-dated")
            g040_fallback["generated_at_utc"] = ts_raw
            g040_fallback["age_hours"] = round(age_h, 2)
            for archived in g040.get("stations") or []:
                code = str(archived.get("code") or "").strip()
                st = rain_query_meta.get(code)
                if st is None or not inventory_operational(st):
                    g040_fallback["excluded_downstream_or_ineligible"] += 1
                    continue
                try:
                    inside = basin.covers(Point(float(st["lon"]), float(st["lat"])))
                except (TypeError, ValueError, KeyError):
                    inside = False
                if not inside:
                    g040_fallback["excluded_downstream_or_ineligible"] += 1
                    continue
                # Preserve station identity and coordinate from Muçum catalog,
                # not the broader G040 catalog.
                g040_fallback["gauges_considered_upstream"] += 1
                target = rain_series.setdefault(code, {})
                added = 0
                for row in archived.get("series") or []:
                    try:
                        t = datetime.fromisoformat(str(row["time_local"]))
                    except (TypeError, ValueError, KeyError):
                        continue
                    if not start <= t <= end:
                        continue
                    v = qc_rain(row.get("mm"))
                    if v is None:
                        continue
                    t = t.replace(minute=0, second=0, microsecond=0)
                    if t not in target:
                        target[t] = v
                        added += 1
                    elif abs(float(target[t]) - v) > 0.01:
                        # Disagreements are preserved for independent audit,
                        # rather than silently rewriting station measurements.
                        g040_fallback["conflicts_preserved"] += 1
                if added:
                    g040_fallback["stations_filled"] += 1
                    g040_fallback["hours_filled"] += added
                    rain_meta.setdefault(code, dict(st))
                    rain_sources.setdefault(code, "G040 ANA/CEMADEN observed archive")
            g040_fallback["status"] = "reconciled"
        except (ValueError, OSError, TypeError, KeyError) as exc:
            g040_fallback["status"] = "unavailable_or_invalid"
            g040_fallback["reason"] = str(exc)

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
                    "flow_m3s": qc_flow(row.get("flow_m3s")),
                    "level": finite(row.get("level")),
                    "rain_mm": None,
                },
            )
            # Fill individual missing variables without replacing fresher ones.
            cur = target[key]
            if cur.get("flow_m3s") is None and row.get("flow_m3s") is not None:
                cur["flow_m3s"] = qc_flow(row.get("flow_m3s"))
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
        latest_times = [
            t for t, v in hourly.items()
            if v.get("flow_m3s") is not None or v.get("level") is not None
        ]
        latest_t = max(latest_times) if latest_times else None
        age_min = None if latest_t is None else max(0.0, (end - latest_t).total_seconds() / 60.0)
        item.update(
            {
                "source": flow_sources.get(code),
                "valid_flow_hours": nq,
                "valid_level_hours": nl,
                "latest_observation_local": None if latest_t is None else iso(latest_t),
                "latest_age_minutes": None if age_min is None else round(age_min, 1),
                "fresh_for_current_state": bool(age_min is not None and age_min <= FRESH_FLOW_MINUTES),
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
        for code, st in request_meta.items()
        if not (fetched.get(code) or {}).get("ok")
    ]

    # Full-inventory audit: every station inside the watershed is accounted for.
    # This prevents a future regression to hidden hand-picked subsets.
    rain_inventory_union = dict(flow_catalog)
    rain_inventory_union.update(rain_catalog)
    rain_inventory_audit = []
    for code, st in sorted(rain_inventory_union.items()):
        eligible = inventory_operational(st)
        valid = code in rain_series and bool(rain_series.get(code))
        latest = max(rain_series[code]) if valid else None
        if valid:
            reason = "used_valid_rain"
        elif not eligible:
            reason = "inventory_inactive_or_inoperable"
        elif code in all_query_meta and code not in request_meta:
            reason = "not_refetched_this_cycle_uses_archive_if_available"
        elif code in request_meta and not (fetched.get(code) or {}).get("ok"):
            reason = "source_query_failed"
        else:
            reason = "no_valid_rain_returned"
        rain_inventory_audit.append({
            "code": code,
            "name": st.get("name"),
            "network": st.get("network"),
            "station_type": st.get("station_type"),
            "operating_flag": st.get("operating_flag"),
            "eligible": eligible,
            "used": valid,
            "latest_observation_local": None if latest is None else iso(latest),
            "reason": reason,
        })

    flow_inventory_audit = []
    for code, st in sorted(flow_catalog.items()):
        eligible = inventory_operational(st)
        hourly = flow_hourly.get(code) or {}
        valid = any(
            v.get("flow_m3s") is not None or v.get("level") is not None
            for v in hourly.values()
        )
        latest_times = [
            t for t, v in hourly.items()
            if v.get("flow_m3s") is not None or v.get("level") is not None
        ]
        latest = max(latest_times) if latest_times else None
        if valid:
            reason = "used_valid_hydrometry"
        elif not eligible:
            reason = "inventory_inactive_or_inoperable"
        elif code in all_query_meta and code not in request_meta:
            reason = "not_refetched_this_cycle_uses_archive_if_available"
        elif code in request_meta and not (fetched.get(code) or {}).get("ok"):
            reason = "source_query_failed"
        else:
            reason = "no_valid_flow_or_level_returned"
        flow_inventory_audit.append({
            "code": code,
            "name": st.get("name"),
            "network": st.get("network"),
            "station_type": st.get("station_type"),
            "operating_flag": st.get("operating_flag"),
            "eligible": eligible,
            "used": valid,
            "latest_observation_local": None if latest is None else iso(latest),
            "reason": reason,
        })

    # Explicit cumulative-rain audit. HEC forcing remains spatial (IDW by hour),
    # but operations also need the observed accumulated totals to diagnose
    # antecedent wetness and verify that no large rainfall episode was lost.
    station_observed_accumulations = []
    for st in rain_stations:
        code = st["code"]
        vals = list((rain_series.get(code) or {}).items())
        if not vals:
            continue
        vals.sort(key=lambda x: x[0])
        station_observed_accumulations.append({
            "code": code,
            "name": st.get("name"),
            "network": st.get("network"),
            "upg": st.get("upg"),
            "valid_hours": len(vals),
            "start_local": iso(vals[0][0]),
            "end_local": iso(vals[-1][0]),
            "accum_mm": round(sum(float(v) for _, v in vals), 3),
        })

    event_basin_accum = sum(
        float(row.get("basin_mean_mm") or 0.0)
        for row in areal_rows if row.get("basin_mean_mm") is not None
    )
    event_zone_accum = {
        code: round(sum(
            float(row.get(f"zone_{code}_mm") or 0.0)
            for row in areal_rows if row.get(f"zone_{code}_mm") is not None
        ), 3)
        for code in zones
    }
    continuous = [x for x in station_observed_accumulations if x["valid_hours"] >= 80]
    continuous_vals = sorted(float(x["accum_mm"]) for x in continuous)
    accum_audit = {
        "event_basin_areal_mm": round(event_basin_accum, 3),
        "event_by_zone_mm": event_zone_accum,
        "station_observed_accumulations": station_observed_accumulations,
        "continuous_station_count": len(continuous),
        "continuous_station_sum_mm_audit_only": round(sum(continuous_vals), 3) if continuous_vals else None,
        "continuous_station_mean_mm": round(sum(continuous_vals)/len(continuous_vals), 3) if continuous_vals else None,
        "continuous_station_median_mm": continuous_vals[len(continuous_vals)//2] if continuous_vals else None,
        "continuous_station_min_mm": continuous_vals[0] if continuous_vals else None,
        "continuous_station_max_mm": continuous_vals[-1] if continuous_vals else None,
        "note": "Soma de mm entre postos é auditoria das observações, não lâmina física. O HEC usa o campo espacial IDW por hora e por zona.",
    }

    payload = {
        "schema_version": "mucum_observed_multistation_v3_full_basin_inventory",
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
            "inventory_count_inside": len(rain_inventory_union),
            "pluviometric_inventory_count_inside": len(rain_catalog),
            "candidate_count_operational_inventory": len(rain_query_meta),
            "selection_policy": "inventário completo dentro da bacia; nenhuma lista manual de postos; entra na média horária todo posto candidato que retornou observação válida",
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
            "accumulations": accum_audit,
            "hourly_areal": [
                {
                    k: (None if v is None else round(v, 4) if isinstance(v, float) else v)
                    for k, v in row.items()
                }
                for row in areal_rows
            ],
            "stations": rain_payload,
            "inventory_audit": rain_inventory_audit,
        },
        "flow": {
            "inventory_count_inside": len(flow_catalog),
            "candidate_count_operational_inventory": len(active_flow_meta),
            "active_candidate_codes": sorted(active_flow_meta),
            "selection_policy": "todos os postos hidrométricos operacionais do inventário dentro da bacia; QC automático; sem escolha manual",
            "stations_with_flow_or_level": len(flow_stations),
            "stations_with_flow": sum(st["valid_flow_hours"] > 0 for st in flow_stations),
            "stations_with_level": sum(st["valid_level_hours"] > 0 for st in flow_stations),
            "stations": flow_payload,
            "inventory_audit": flow_inventory_audit,
        },
        "fetch_audit": {
            "queried_station_count": len(request_meta),
            "eligible_station_count": len(all_query_meta),
            "refresh_strategy": refresh_audit,
            "failed_count": len(failures),
            "failures": failures,
            "policy": "inventário completo da bacia; consultas concorrentes limitadas; ANA primário+espelho; CSV operacional e histórico publicado usados apenas como persistência; ausência não vira zero; vazão > 50000 m3/s e chuva > 250 mm/h são rejeitadas por QC",
            "fast_mode": FAST_MODE,
            "query_start_local": iso(query_start),
            "rain_fallback_station_codes": sorted(set(rain_fallback_codes)),
            "g040_upstream_archive_reconciliation": g040_fallback,
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
                "rain_inventory_inside": len(rain_inventory_union),
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
