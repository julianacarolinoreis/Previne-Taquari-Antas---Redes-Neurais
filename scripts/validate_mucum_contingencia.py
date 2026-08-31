"""Auditoria estrutural do cadastro municipal usado no piloto de Muçum.

O relatório confirma consistência documental da ficha local. Ele não valida
ocupação, abertura, integridade estrutural, rota segura ou despacho real.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "data" / "mucum_contingencia_202607.json"
REPORT = ROOT / "assets" / "data" / "mucum_contingencia_qa_latest.json"


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    meta = data["meta"]
    shelters = data["abrigos"]
    bridges = data["pontes"]
    routes = data["rotas_plano"]
    resources = data["recursos"]
    summary = data["resumo_capacidade"]

    capacity_quadro_13 = sum(int(item["capacidade_quadro_13"]) for item in shelters)
    capacity_ficha = sum(int(item["capacidade_ficha_tecnica"]) for item in shelters)
    missing_coordinates = sum(
        1
        for item in shelters
        if item.get("lat") is None or item.get("lon") is None
    )
    issues = []

    if len(shelters) != summary["alojamentos_quadro_13"]:
        issues.append({"code": "shelter_count_mismatch", "severity": "high"})
    if capacity_quadro_13 != summary["capacidade_quadro_13_pessoas"]:
        issues.append({"code": "capacity_sum_mismatch", "severity": "high"})
    if capacity_quadro_13 != summary["capacidade_quadro_2_pessoas"]:
        issues.append({"code": "capacity_quadro_conflict", "severity": "medium"})
    if capacity_ficha != summary["capacidade_anexo_5_pessoas"]:
        issues.append({"code": "capacity_ficha_sum_mismatch", "severity": "high"})
    if missing_coordinates:
        issues.append({"code": "shelter_without_coordinate", "severity": "medium", "count": missing_coordinates})
    if not all(item.get("status_operacional") == "desconhecido" for item in shelters):
        issues.append({"code": "shelter_operational_status_not_unknown", "severity": "high"})
    if not all(item.get("status_operacional") == "desconhecido" for item in bridges):
        issues.append({"code": "bridge_operational_status_not_unknown", "severity": "high"})
    if not all(item.get("status") == "geometria_observada" for item in (b.get("remote_sensing", {}) for b in bridges)):
        issues.append({"code": "remote_sensing_status_unexpected", "severity": "high"})
    if sum(int(item["quantidade"]) for item in resources if "Embarcações" in item["nome"]) != 0:
        issues.append({"code": "aquatic_resource_not_zero", "severity": "high"})

    report = {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "source": {
            "path": "assets/data/mucum_contingencia_202607.json",
            "document": meta["documento"],
            "version": meta["versao"],
        },
        "status": "PASS_WITH_KNOWN_CONFLICTS" if not any(item["severity"] == "high" for item in issues) else "FAIL",
        "operational_gate": "blocked",
        "scope": "integridade documental do cadastro do piloto",
        "counts": {
            "shelters": len(shelters),
            "bridges": len(bridges),
            "routes": len(routes),
            "resource_types": len(resources),
            "shelters_without_coordinates": missing_coordinates,
        },
        "capacity_check": {
            "quadro_13_sum": capacity_quadro_13,
            "quadro_13_declared": summary["capacidade_quadro_13_pessoas"],
            "ficha_tecnica_sum": capacity_ficha,
            "anexo_5_declared": summary["capacidade_anexo_5_pessoas"],
            "quadro_2_declared": summary["capacidade_quadro_2_pessoas"],
            "known_conflict": True,
        },
        "issues": issues,
        "known_limits": [
            "ocupação, abertura e vagas atuais desconhecidas",
            "pontes sem vistoria estrutural e status operacional desconhecido",
            "rotas são referências do plano e não foram liberadas para navegação",
            "sensoriamento remoto observa geometria aparente, não certifica estrutura ou segurança",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MUCUM_CONTINGENCIA_QA={report['status']} issues={len(issues)} report={REPORT}")
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
