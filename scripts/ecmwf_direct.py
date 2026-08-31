"""Small, auditable reader for the public ECMWF IFS Open Data subset.

The ECMWF files are GRIB2 and large (roughly 140 MB per forecast step).  The
public portal also publishes a line-oriented index for every file, so this
module downloads only the ``tp`` message needed for one requested grid point
by HTTP byte range.  It is deliberately independent from the live level robot.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = "https://data.ecmwf.int/forecasts"
LATITUDE = -29.1672
LONGITUDE = -51.8686
HORIZONS = (24, 48, 72, 120, 168)
USER_AGENT = "PREVINE-Mucum-research/1.0 (+ECMWF Open Data audit)"


def _request(url: str, *, accept: str | None = None, byte_range: tuple[int, int] | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if byte_range is not None:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=60) as response:
        status = getattr(response, "status", response.getcode())
        payload = response.read()
        if byte_range is not None:
            expected = byte_range[1] - byte_range[0] + 1
            # A proxy that silently ignores Range would return the entire
            # 140-MB GRIB file.  Refuse that rather than waste the workflow.
            if status != 206 or len(payload) != expected:
                raise RuntimeError(
                    f"ECMWF byte range não confirmado: HTTP {status}, {len(payload)} bytes; esperado {expected}"
                )
        return payload


def _cycle_candidates(now: datetime) -> list[datetime]:
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cycles: list[datetime] = []
    for day_offset in range(0, 3):
        day = (base - timedelta(days=day_offset)).date()
        for hour in (18, 12, 6, 0):
            cycle = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
            if cycle <= base:
                cycles.append(cycle)
    return sorted(cycles, reverse=True)


def _cycle_prefix(cycle: datetime) -> str:
    return f"{ROOT}/{cycle:%Y%m%d}/{cycle:%Hz}/ifs/0p25/oper"


def _find_cycle(now: datetime) -> tuple[datetime, str, dict[str, str]]:
    errors: list[str] = []
    for cycle in _cycle_candidates(now):
        prefix = _cycle_prefix(cycle)
        try:
            listing = json.loads(_request(prefix + "/", accept="application/json").decode("utf-8"))
            names = {str(item.get("name")): item for item in listing if item.get("name")}
            files = {
                str(hours): f"{cycle:%Y%m%d%H}0000-{hours}h-oper-fc.grib2"
                for hours in HORIZONS
            }
            if all(name in names for name in files.values()):
                return cycle, prefix, files
            errors.append(f"{cycle:%Y-%m-%d %Hz}: horizontes incompletos")
        except (HTTPError, URLError, OSError, ValueError, TypeError, RuntimeError) as exc:
            errors.append(f"{cycle:%Y-%m-%d %Hz}: {exc}")
    raise RuntimeError("; ".join(errors[-6:]) or "nenhuma rodada IFS disponível")


def _find_tp_entry(index_text: str, hours: int) -> dict[str, Any]:
    for raw_line in index_text.splitlines():
        if not raw_line.strip():
            continue
        item = json.loads(raw_line)
        if str(item.get("param")) == "tp" and str(item.get("step")) == str(hours):
            return item
    raise RuntimeError(f"parâmetro tp no passo {hours} h não encontrado no índice ECMWF")


def _decode_point(
    payload: bytes,
    *,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
) -> dict[str, Any]:
    try:
        import eccodes  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runner libraries
        raise RuntimeError(f"ecCodes indisponível: {exc}") from exc

    handle = eccodes.codes_new_from_message(payload)
    try:
        values = eccodes.codes_get_array(handle, "values")
        try:
            ni = int(eccodes.codes_get(handle, "Ni"))
            nj = int(eccodes.codes_get(handle, "Nj"))
            lat1 = float(eccodes.codes_get(handle, "latitudeOfFirstGridPointInDegrees"))
            lon1 = float(eccodes.codes_get(handle, "longitudeOfFirstGridPointInDegrees"))
            di = abs(float(eccodes.codes_get(handle, "iDirectionIncrementInDegrees")))
            dj = abs(float(eccodes.codes_get(handle, "jDirectionIncrementInDegrees")))
            j_positive = int(eccodes.codes_get(handle, "jScansPositively")) == 1
            i_negative = int(eccodes.codes_get(handle, "iScansNegatively")) == 1
            j_consecutive = int(eccodes.codes_get(handle, "jPointsAreConsecutive")) == 1
            if not (ni > 0 and nj > 0 and di > 0 and dj > 0):
                raise ValueError("geometria regular inválida")
            target_lon = longitude % 360.0
            first_lon = lon1 % 360.0
            delta_lon = (target_lon - first_lon) % 360.0
            i = int(round(delta_lon / di))
            if i_negative:
                i = int(round(((first_lon - target_lon) % 360.0) / di))
            i %= ni
            j = int(round((latitude - lat1) / dj)) if j_positive else int(round((lat1 - latitude) / dj))
            j = max(0, min(nj - 1, j))
            idx = i * nj + j if j_consecutive else j * ni + i
            if idx < 0 or idx >= len(values):
                raise ValueError("índice fora do campo")
            grid_lat = lat1 + (j * dj if j_positive else -j * dj)
            grid_lon = (lon1 + (-i if i_negative else i) * di) % 360.0
        except Exception:
            # Fallback for an unexpected grid encoding.  The regular IFS grid
            # normally takes the fast path above; this keeps failures explicit.
            lats = eccodes.codes_get_array(handle, "latitudes")
            lons = eccodes.codes_get_array(handle, "longitudes")
            target_lon = longitude % 360.0
            idx = min(
                range(len(values)),
                key=lambda k: (float(lats[k]) - latitude) ** 2
                + (((float(lons[k]) % 360.0) - target_lon + 180.0) % 360.0 - 180.0) ** 2,
            )
            grid_lat = float(lats[idx])
            grid_lon = float(lons[idx])
        raw_value = float(values[idx])
        units = str(eccodes.codes_get(handle, "units"))
        if not math.isfinite(raw_value):
            value_mm = None
        elif units.lower() in {"m", "metre", "meter"}:
            value_mm = raw_value * 1000.0
        else:
            raise RuntimeError(f"unidade inesperada para tp: {units}")
        return {
            "rain_mm": round(value_mm, 2) if value_mm is not None else None,
            "raw_value": raw_value,
            "units": units,
            "grid_latitude": round(grid_lat, 4),
            "grid_longitude": round(((grid_lon + 180.0) % 360.0) - 180.0, 4),
        }
    finally:
        eccodes.codes_release(handle)


def fetch_ecmwf_direct(
    now: datetime | None = None,
    *,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    target_name: str = "Muçum",
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    try:
        cycle, prefix, files = _find_cycle(now)
        horizons: list[dict[str, Any]] = []
        for hours in HORIZONS:
            filename = files[str(hours)]
            file_url = f"{prefix}/{filename}"
            index_url = file_url.replace(".grib2", ".index")
            entry = _find_tp_entry(_request(index_url).decode("utf-8"), hours)
            offset = int(entry["_offset"])
            length = int(entry["_length"])
            payload = _request(file_url, byte_range=(offset, offset + length - 1))
            point = _decode_point(payload, latitude=latitude, longitude=longitude)
            horizons.append(
                {
                    "hours": hours,
                    "rain_point_mm": point["rain_mm"],
                    "grid_latitude": point["grid_latitude"],
                    "grid_longitude": point["grid_longitude"],
                    "source_file": filename,
                    "source_index": index_url,
                    "source_offset": offset,
                    "source_length": length,
                }
            )
        return {
            "status": "available",
            "provider": "ECMWF Open Data",
            "model": "IFS",
            "resolution": "0.25°",
            "cycle_time_utc": cycle.isoformat().replace("+00:00", "Z"),
            "source_root": ROOT,
            "parameter": "tp",
            "unit": "mm",
            "target": {"name": target_name, "latitude": latitude, "longitude": longitude},
            "horizons": horizons,
            "message": "Saída direta do IFS; usada como fonte de auditoria do ponto.",
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "provider": "ECMWF Open Data",
            "model": "IFS",
            "source_root": ROOT,
            "target": {"name": target_name, "latitude": latitude, "longitude": longitude},
            "horizons": [],
            "message": f"ECMWF direto indisponível nesta rodada: {exc}",
        }
