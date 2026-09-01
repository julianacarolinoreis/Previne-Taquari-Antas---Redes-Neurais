"""Validate and convert an uploaded geospatial map to a mobile manifest.

The worker intentionally shells out to GDAL instead of silently approximating
CRS or georeferencing. The production image must provide gdalinfo and
gdal_translate, and failed validation must keep the map out of the ready state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


SUPPORTED = {'.pdf', '.tif', '.tiff', '.mbtiles', '.gpkg'}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run_gdal_info(source: Path) -> dict[str, Any]:
    executable = shutil.which('gdalinfo')
    if executable is None:
        raise RuntimeError('gdalinfo não está instalado no worker.')
    result = subprocess.run(
        [executable, '-json', str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def convert_to_mbtiles(source: Path, destination: Path) -> None:
    executable = shutil.which('gdal_translate')
    if executable is None:
        raise RuntimeError('gdal_translate não está instalado no worker.')
    subprocess.run(
        [
            executable,
            '-of',
            'MBTILES',
            '-co',
            'TILE_FORMAT=PNG',
            str(source),
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def ingest(source: Path, output_directory: Path) -> dict[str, Any]:
    source = source.resolve()
    if source.suffix.lower() not in SUPPORTED:
        raise ValueError(f'Formato não suportado: {source.suffix}')
    if not source.is_file():
        raise FileNotFoundError(source)

    output_directory.mkdir(parents=True, exist_ok=True)
    metadata = run_gdal_info(source)
    driver = metadata.get('driverShortName')
    spatial_reference = metadata.get('coordinateSystem', {})
    if not spatial_reference:
        raise ValueError('O arquivo não possui sistema de referência espacial.')

    tile_path = output_directory / f'{source.stem}.mbtiles'
    if source.suffix.lower() != '.mbtiles':
        convert_to_mbtiles(source, tile_path)
    else:
        shutil.copy2(source, tile_path)

    manifest = {
        'sourceFormat': source.suffix.lower().removeprefix('.'),
        'driver': driver,
        'checksumSha256': sha256(source),
        'tileObject': tile_path.name,
        'coordinateSystem': spatial_reference,
        'cornerCoordinates': metadata.get('cornerCoordinates'),
        'size': metadata.get('size'),
        'state': 'ready',
    }
    (output_directory / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(ingest(args.source, args.output_directory), ensure_ascii=False))


if __name__ == '__main__':
    main()
