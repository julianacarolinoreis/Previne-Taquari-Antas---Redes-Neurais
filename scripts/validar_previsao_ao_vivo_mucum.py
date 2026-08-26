#!/usr/bin/env python3
"""Validate the Muçum live-feed schema before publication.

This is deliberately structural: it does not judge the experimental RNA
result and never rewrites the feed. A missing/failed model remains explicit in
the feed through its status instead of being silently published as a value.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "previsao_ao_vivo_mucum.json"
REQUIRED = {"2h", "4h"}
REQUIRED_FIELDS = {"horizonte", "horizonte_h", "modelo", "tipo", "status"}
EXPECTED_INPUTS = {"2h": 10, "4h": 13}


def validate_data(data: dict) -> None:
    if not isinstance(data, dict):
        raise SystemExit("feed Muçum precisa ser objeto JSON")
    horizons = data.get("horizontes")
    if not isinstance(horizons, dict) or set(horizons) != REQUIRED:
        raise SystemExit(f"horizontes inesperados: {sorted(horizons or {})}; esperado {sorted(REQUIRED)}")
    if "cascata" in json.dumps(data, ensure_ascii=False).lower():
        raise SystemExit("feed Muçum ainda contém referência legada a cascata")
    for key in sorted(REQUIRED):
        item = horizons[key]
        if not isinstance(item, dict) or not REQUIRED_FIELDS.issubset(item):
            missing = sorted(REQUIRED_FIELDS - set(item)) if isinstance(item, dict) else sorted(REQUIRED_FIELDS)
            raise SystemExit(f"{key} sem campos obrigatórios: {missing}")
        if item.get("horizonte") != key or item.get("horizonte_h") != int(key[:-1]):
            raise SystemExit(f"horizonte inconsistente em {key}")
        if not str(item.get("modelo") or "").strip() or not str(item.get("tipo") or "").strip():
            raise SystemExit(f"modelo/tipo ausente em {key}")
        if item.get("nivel_previsto_cm") is not None and not item.get("status"):
            raise SystemExit(f"status ausente em {key} com previsão publicada")
        if item.get("inputs_total") is not None and int(item["inputs_total"]) <= 0:
            raise SystemExit(f"inputs_total inválido em {key}")
        if item.get("nivel_previsto_cm") is None:
            continue
        hora = str(item.get("hora_modelo") or "")
        minuto = int(hora[14:16]) if len(hora) >= 16 and hora[14:16].isdigit() else -1
        if minuto != 0:
            raise SystemExit(f"{key} fora da grade temporal hourly_exact: {hora}")
        if item.get("input_grade") != "hourly_exact":
            raise SystemExit(f"{key} sem grade hourly_exact")
        if item.get("input_contract_version") != "hourly_exact_v1":
            raise SystemExit(f"{key} sem contrato temporal hourly_exact_v1")
        audit = item.get("auditoria_inputs") or {}
        if audit.get("status") != "NORMAL" or audit.get("n_inputs_nao_exatos", 0) != 0:
            raise SystemExit(f"{key} publicou inputs não exatos ou sem auditoria NORMAL")
        if audit.get("usa_interpolacao_nivel") is not False or audit.get("usa_vizinho_nivel") is not False:
            raise SystemExit(f"{key} não declarou nível exato sem interpolação/vizinho")
        if len(item.get("input_values_cm") or []) != EXPECTED_INPUTS[key]:
            raise SystemExit(f"{key} precisa publicar exatamente {EXPECTED_INPUTS[key]} inputs")


def main() -> int:
    validate_data(json.loads(FEED.read_text(encoding="utf-8")))
    print("OK feed ao vivo Muçum: 2h/4h; sem legado cascata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
