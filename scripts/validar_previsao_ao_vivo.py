#!/usr/bin/env python3
"""Valida o contrato mínimo do feed ao vivo antes da publicação."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "previsao_ao_vivo.json"
B_MAT = ROOT / "previne/assets/mat/RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat"
B_SHA = "6AE75018344625E8D3035F43A50F6556694C4B96510AC47241348EA5235D72A2"
REQUIRED = {"2h", "2h_versao_b", "4h"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    data = json.loads(FEED.read_text(encoding="utf-8"))
    horizons = data.get("horizontes")
    if not isinstance(horizons, dict):
        raise SystemExit("feed sem objeto horizontes")
    keys = set(horizons)
    if keys != REQUIRED:
        raise SystemExit(f"horizontes inesperados: {sorted(keys)}; esperado {sorted(REQUIRED)}")
    if "cascata" in json.dumps(data, ensure_ascii=False).lower():
        raise SystemExit("feed ainda contem referencia legada a cascata")
    primary = horizons["2h"]
    shadow = horizons["2h_versao_b"]
    if primary.get("principal") is not True or primary.get("shadow_only"):
        raise SystemExit("2h principal com metadados inconsistentes")
    if shadow.get("shadow_only") is not True or shadow.get("principal"):
        raise SystemExit("2h versao B precisa permanecer em sombra")
    if shadow.get("modelo_sha256") != B_SHA or sha256(B_MAT) != B_SHA:
        raise SystemExit("hash da versao B nao confere")
    for key in REQUIRED:
        item = horizons[key]
        if item.get("horizonte") != key:
            raise SystemExit(f"horizonte inconsistente em {key}")
        if item.get("nivel_previsto_cm") is not None and item.get("status") is None:
            raise SystemExit(f"status ausente em {key}")
    print(f"OK feed ao vivo: {', '.join(sorted(keys))}; MAT B SHA={B_SHA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
