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
ALLOWED_EXTRA = {"8h", "8h_v002"}
REQUIRED_FIELDS = {"horizonte", "horizonte_h", "modelo", "tipo", "status"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_data(data: dict, *, b_mat: Path = B_MAT) -> None:
    """Validate the public-feed contract without writing a feed."""
    if not isinstance(data, dict):
        raise SystemExit("feed precisa ser objeto JSON")
    horizons = data.get("horizontes")
    if not isinstance(horizons, dict):
        raise SystemExit("feed sem objeto horizontes")
    keys = set(horizons)
    if not REQUIRED.issubset(keys):
        raise SystemExit(f"horizontes faltando: {sorted(REQUIRED - keys)}; veio {sorted(keys)}")
    extra = keys - REQUIRED - ALLOWED_EXTRA
    if extra:
        raise SystemExit(f"horizontes inesperados: {sorted(extra)}; esperado {sorted(REQUIRED | ALLOWED_EXTRA)}")
    if "cascata" in json.dumps(data, ensure_ascii=False).lower():
        raise SystemExit("feed ainda contem referencia legada a cascata")
    for key in sorted(keys):
        if not isinstance(horizons[key], dict):
            raise SystemExit(f"{key} precisa ser objeto")
    primary = horizons["2h"]
    shadow = horizons["2h_versao_b"]
    if primary.get("principal") is not True or primary.get("shadow_only"):
        raise SystemExit("2h principal com metadados inconsistentes")
    if shadow.get("shadow_only") is not True or shadow.get("principal"):
        raise SystemExit("2h versao B precisa permanecer em sombra")
    if shadow.get("modelo_sha256") != B_SHA or sha256(b_mat) != B_SHA:
        raise SystemExit("hash da versao B nao confere")
    for key in sorted(keys):
        item = horizons[key]
        if not isinstance(item, dict) or not REQUIRED_FIELDS.issubset(item):
            missing = sorted(REQUIRED_FIELDS - set(item)) if isinstance(item, dict) else sorted(REQUIRED_FIELDS)
            raise SystemExit(f"{key} sem campos obrigatorios: {missing}")
        if item.get("horizonte") != key:
            raise SystemExit(f"horizonte inconsistente em {key}")
        if key.startswith("2h"):
            expected_hours = 2
        elif key.startswith("4h"):
            expected_hours = 4
        elif key.startswith("8h"):
            expected_hours = 8
        else:
            expected_hours = None
        if expected_hours is not None and item.get("horizonte_h") != expected_hours:
            raise SystemExit(f"horizonte_h inconsistente em {key}")
        if not str(item.get("modelo") or "").strip() or not str(item.get("tipo") or "").strip():
            raise SystemExit(f"modelo/tipo ausente em {key}")
        if item.get("nivel_previsto_cm") is not None and item.get("status") is None:
            raise SystemExit(f"status ausente em {key}")
    four = horizons["4h"]
    four_input_audit = four.get("auditoria_inputs") or {}
    if four.get("nivel_previsto_cm") is None:
        if four.get("status") is None:
            raise SystemExit("4h indisponivel sem status explicito")
        if four_input_audit and four_input_audit.get("status") not in {"INVALIDO", "ATENCAO"}:
            raise SystemExit("4h indisponivel com auditoria de inputs inconsistente")
    if four.get("nivel_previsto_cm") is not None:
        hora = str(four.get("hora_modelo") or "")
        if len(hora) < 16 or hora[14:16] != "00":
            raise SystemExit(f"4h fora da grade horaria exata: {hora}")
        audit = four_input_audit
        if audit.get("formula_conferida_com_montador") is not True:
            raise SystemExit("4h com formula de inputs nao conferida")
        if audit.get("n_inputs_nao_exatos", 0) != 0:
            raise SystemExit("4h publicou inputs interpolados/vizinhos")
        vals = four.get("input_values_cm") or []
        # O V01/R00 em produção recebe 26 sinais: os diferenciais e
        # acelerações, mais os dois níveis-âncora montantes. O validador
        # antigo exigia 24 e fazia uma rodada correta falhar após gerar o feed.
        if len(vals) != 26 or four.get("inputs_total") != 26:
            raise SystemExit("4h precisa publicar exatamente 26 inputs")
        if four.get("input_contract_version") != "hourly_exact_v1":
            raise SystemExit("4h sem contrato temporal hourly_exact_v1")
    audit = four.get("auditoria") or {}
    if audit.get("n_conferidas", 0) and audit.get("auditoria_versao") not in (None, "target_exact_v2"):
        raise SystemExit("auditoria 4h com versao de comparacao desconhecida")


def main() -> int:
    data = json.loads(FEED.read_text(encoding="utf-8"))
    validate_data(data)
    print(f"OK feed ao vivo: {', '.join(sorted(data['horizontes']))}; MAT B SHA={B_SHA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
