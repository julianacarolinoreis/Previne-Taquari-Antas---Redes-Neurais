#!/usr/bin/env python3
"""Validate the Muçum live-feed schema before publication.

This is deliberately structural: it does not judge the experimental RNA
result and never rewrites the feed. A missing/failed model remains explicit in
the feed through its status instead of being silently published as a value.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "previsao_ao_vivo_mucum.json"
HISTORY = ROOT / "historico_previsoes_ao_vivo_mucum.json"
REQUIRED = {"2h", "4h", "4h_versao_b", "8h", "8h_versao_b"}
REQUIRED_FIELDS = {"horizonte", "horizonte_h", "modelo", "tipo", "status", "modelo_papel", "disponivel"}
EXPECTED_HOURS = {"2h": 2, "4h": 4, "4h_versao_b": 4, "8h": 8, "8h_versao_b": 8}
EXPECTED_INPUTS = {"2h": 14, "4h": 30, "4h_versao_b": 15, "8h": 26, "8h_versao_b": 28}


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
        if item.get("horizonte") != key or item.get("horizonte_h") != EXPECTED_HOURS[key]:
            raise SystemExit(f"horizonte inconsistente em {key}")
        if not str(item.get("modelo") or "").strip() or not str(item.get("tipo") or "").strip():
            raise SystemExit(f"modelo/tipo ausente em {key}")
        if item.get("nivel_previsto_cm") is not None and not item.get("status"):
            raise SystemExit(f"status ausente em {key} com previsão publicada")
        if key in {"4h", "8h"} and item.get("modelo_papel") != "principal":
            raise SystemExit(f"{key} precisa ser o modelo principal")
        if key in {"4h_versao_b", "8h_versao_b"} and item.get("modelo_papel") != "comparativo":
            raise SystemExit(f"{key} precisa ser o modelo comparativo")
        if key in {"4h", "8h"} and item.get("selection_rank") != 1:
            raise SystemExit(f"{key} precisa declarar selection_rank=1")
        if key in {"4h_versao_b", "8h_versao_b"} and item.get("selection_rank") != 2:
            raise SystemExit(f"{key} precisa declarar selection_rank=2")
        if item.get("inputs_total") is not None and int(item["inputs_total"]) <= 0:
            raise SystemExit(f"inputs_total inválido em {key}")
        if item.get("nivel_previsto_cm") is None:
            if item.get("disponivel") is not False:
                raise SystemExit(f"{key} sem previsão precisa declarar disponivel=false")
            if not str(item.get("status") or "").strip() or item.get("status") == "ok":
                raise SystemExit(f"{key} sem previsão precisa explicar o motivo no status")
            continue
        if item.get("disponivel") is not True:
            raise SystemExit(f"{key} com previsão precisa declarar disponivel=true")
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
        if len(item.get("input_labels") or []) != EXPECTED_INPUTS[key]:
            raise SystemExit(f"{key} precisa declarar exatamente {EXPECTED_INPUTS[key]} labels de input")
        if len(item.get("input_values_cm") or []) != EXPECTED_INPUTS[key]:
            raise SystemExit(f"{key} precisa publicar exatamente {EXPECTED_INPUTS[key]} inputs")
        if audit.get("usa_interpolacao_chuva") is not False or audit.get("usa_preenchimento_chuva") is not False:
            raise SystemExit(f"{key} não declarou chuva sem interpolação/preenchimento")


def parse_timestamp(value):
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))


def validate_history(data: dict) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("registros"), list):
        raise SystemExit("histórico Muçum precisa conter registros")
    for index, item in enumerate(data["registros"]):
        if not isinstance(item, dict) or item.get("status_auditoria") != "conferido":
            continue
        base = parse_timestamp(item.get("hora_modelo"))
        target = parse_timestamp(item.get("hora_alvo"))
        observed = parse_timestamp(item.get("observado_em"))
        if base is None or target is None or observed is None:
            raise SystemExit(f"histórico {index} conferido sem horários completos")
        if base.minute != 0 or base.second != 0 or target.minute != 0 or target.second != 0:
            raise SystemExit(f"histórico {index} conferido fora da hora cheia")
        if observed != target:
            raise SystemExit(f"histórico {index} conferido com observado diferente da hora-alvo")


def main() -> int:
    validate_data(json.loads(FEED.read_text(encoding="utf-8")))
    validate_history(json.loads(HISTORY.read_text(encoding="utf-8")))
    print("OK feed ao vivo Muçum: 2h + dois candidatos 4h + dois candidatos 8h; inputs exatos; histórico horário")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
