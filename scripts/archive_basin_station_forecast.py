"""Archive compact forecast points so later model-skill checks are possible.

The live map remains a current snapshot. This companion archive stores only
the forecast values needed to compare a model with later observed rain; it
does not claim a score until the target observation has actually arrived.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "assets/data/basin_station_forecast_latest.json"
DEFAULT_ARCHIVE = ROOT / "assets/data/basin_station_forecast_archive"


def archive_snapshot(
    feed_path: Path = DEFAULT_FEED,
    archive_dir: Path = DEFAULT_ARCHIVE,
) -> Path:
    source_bytes = feed_path.read_bytes()
    feed = json.loads(source_bytes)

    generated = str(feed.get("generated_at_utc") or "")
    try:
        instant = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("Horário sem fuso não identifica uma rodada UTC.")
        stamp = instant.astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")
    except ValueError as exc:
        raise ValueError("Feed sem generated_at_utc válido.") from exc

    compact: dict[str, Any] = {
        "schema_version": 1,
        "feed_generated_at_utc": generated,
        "source_feed": "assets/data/basin_station_forecast_latest.json",
        "source_feed_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "research_only": True,
        "official_alert": False,
        "skill_target": "chuva observada publicada posteriormente",
        "stations": [],
    }
    for station in feed.get("stations") or []:
        forecast = station.get("forecast") or {}
        observed = station.get("observed_rain") or {}
        if forecast.get("state") != "available" or observed.get("state") != "available":
            continue
        models: dict[str, Any] = {}
        for model_id, model in (forecast.get("models") or {}).items():
            models[model_id] = {
                "precipitation": model.get("precipitation") or [],
                "precipitation_windows": model.get("precipitation_windows") or {},
            }
        compact["stations"].append(
            {
                "id": station.get("id"),
                "code": station.get("code"),
                "name": station.get("name"),
                "latitude": station.get("latitude"),
                "longitude": station.get("longitude"),
                "observed_rain_source": observed.get("source"),
                "observed_points_at_archive": observed.get("available_points", 0),
                "times": forecast.get("times") or [],
                "models": models,
            }
        )

    archive_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(compact, ensure_ascii=False, indent=2) + "\n"
    # Content addressing is necessary even when the directory is sparse and
    # older remote snapshots are absent from the working tree. A minute-only
    # name can otherwise overwrite an unseen snapshot when Git stages it.
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    target = archive_dir / f"{stamp}-{digest}.json"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    except FileExistsError:
        if target.read_text(encoding="utf-8") != serialized:
            raise ValueError("Colisão no arquivo histórico; snapshot anterior preservado.")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, default=DEFAULT_FEED)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    target = archive_snapshot(args.feed, args.archive_dir)
    print("forecast archive written:", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
