"""Leitura conservadora de chuva observada do CSV operacional PREVINE.

Ausência nunca vira zero. Um acumulado só é publicado quando há cobertura
suficiente na janela e a última observação da série não está muito antiga.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BRT = timezone(timedelta(hours=-3))
DEFAULT_CSV = Path(__file__).resolve().parents[1] / "assets" / "data" / "chuvas_horarias.csv"


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _when(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M").replace(tzinfo=BRT)
    except (TypeError, ValueError):
        return None


def observed_accumulations(
    column: str,
    *,
    path: Path = DEFAULT_CSV,
    now: datetime | None = None,
    windows: tuple[int, ...] = (24, 72),
    min_coverage: float = 0.80,
    max_latest_age_hours: float = 4.0,
    source_label: str | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(BRT)
    result: dict[str, Any] = {
        "source": source_label or column,
        "column": column,
        "latest_at": None,
        "latest_age_hours": None,
        "status": "unavailable",
    }
    for hours in windows:
        result[f"rain_observed_{hours}h_mm"] = None
        result[f"rain_observed_{hours}h_coverage_hours"] = 0
        result[f"rain_observed_{hours}h_coverage_percent"] = 0.0

    if not path.exists():
        result["message"] = "CSV de chuva observada não disponível."
        return result

    rows: list[tuple[datetime, float]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if column not in (reader.fieldnames or []):
            result["message"] = f"Coluna {column} ausente no CSV."
            return result
        for row in reader:
            stamp = _when(row.get("COD_SEQUENCIAL", ""))
            value = _num(row.get(column))
            if stamp is None or value is None or stamp > now:
                continue
            rows.append((stamp, value))

    if not rows:
        result["message"] = "Nenhuma observação válida nesta fonte."
        return result

    latest = max(stamp for stamp, _ in rows)
    latest_age = max(0.0, (now - latest).total_seconds() / 3600.0)
    result["latest_at"] = latest.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result["latest_age_hours"] = round(latest_age, 2)

    enough_any = False
    for hours in windows:
        start = now - timedelta(hours=hours)
        selected = [value for stamp, value in rows if start < stamp <= now]
        count = len(selected)
        coverage = count / float(hours)
        result[f"rain_observed_{hours}h_coverage_hours"] = count
        result[f"rain_observed_{hours}h_coverage_percent"] = round(coverage * 100.0, 1)
        if coverage >= min_coverage and latest_age <= max_latest_age_hours:
            result[f"rain_observed_{hours}h_mm"] = round(sum(selected), 2)
            enough_any = True

    result["status"] = "available" if enough_any else ("stale" if latest_age > max_latest_age_hours else "partial")
    result["message"] = (
        "Acumulados observados publicados somente com cobertura suficiente; lacunas não são tratadas como zero."
    )
    return result
