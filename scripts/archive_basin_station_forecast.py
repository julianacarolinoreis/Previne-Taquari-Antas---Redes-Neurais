"""Archive compact forecast points so later model-skill checks are possible.

The live map remains a current snapshot. This companion archive stores only
the forecast values needed to compare a model with later observed rain; it
does not claim a score until the target observation has actually arrived.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "assets/data/basin_station_forecast_latest.json"
DEFAULT_ARCHIVE = ROOT / "assets/data/basin_station_forecast_archive"


def archive_snapshot(
    feed_path: Path = DEFAULT_FEED,
    archive_dir: Path = DEFAULT_ARCHIVE,
) -> Path:
    with feed_path.open(encoding="utf-8") as handle:
        feed = json.load(handle)

    generated = str(feed.get("generated_at_utc") or "")
    try:
        stamp = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime(
            "%Y%m%dT%H%MZ"
        )
    except ValueError as exc:
        raise ValueError("Feed sem generated_at_utc válido.") from exc

    compact: dict[str, Any] = {
        "schema_version": 1,
        "feed_generated_at_utc": generated,
        "source_feed": "assets/data/basin_station_forecast_latest.json",
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
    target = archive_dir / f"{stamp}.json"
    serialized = json.dumps(compact, ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == serialized:
        return target
    target.write_text(serialized, encoding="utf-8")
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
