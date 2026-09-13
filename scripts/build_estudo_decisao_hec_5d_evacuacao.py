#!/usr/bin/env python3
"""Lock product decision: HEC+IFS ~5d is primary for evacuation lead time.

RNA stays as short-horizon nowcast. STZ without rating curve still blocks N@STZ via HEC.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "data" / "estudo_bacia_taquari_antas"
DECISION = OUT / "decisao_previsao_nivel_multi_alvo_latest.json"
README = OUT / "README.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "estudo_decisao_previsao_nivel_multi_alvo_v2",
        "generated_at_utc": utc_now(),
        "status": "decidido_hec_qpf_5d_primario_evacuacao_rna_curto",
        "purpose": "Decisão de produto após correção: antecedência ~5 dias para evacuação exige HEC+chuva prevista.",
        "decision": {
            "by": "Juliana (requisito de antecedência) + agente (arquitetura travada)",
            "question": "Como prever nível com antecedência útil para evacuar (~5 dias) em pontos da bacia?",
            "chosen_primary_multiday": "HEC_twin_plus_IFS_QPF",
            "chosen_short_horizon": "RNA_nivel_por_estacao_2h_4h_8h",
            "why_hec_for_5d": [
                "Evacuação precisa de dias de antecedência, não só 2–8 horas.",
                "HEC (gêmeo) transforma chuva prevista (IFS ~5–7 d) em hidrograma de vazão.",
                "Em Muçum, Q→N usa curva-chave oficial (vizinha no hunt) — nível multi-dia fica possível.",
                "RNA ao vivo atual não cobre horizonte de 5 dias.",
            ],
            "why_rna_still": [
                "Curto prazo (2h/4h/8h) em STZ e Muçum já opera e não depende de curva-chave.",
                "Complementa o HEC perto do pico / agora.",
            ],
            "stz_rating_curve": {
                "exists": False,
                "impact_on_hec_n_stz": "bloqueia_N_via_HEC",
                "impact_on_hec_q_stz": "apenas_diagnostico_nao_calibrado",
                "impact_on_rna_n_stz": "nenhum",
                "rule": "Não inventar N→Q. Para N em STZ no curto prazo: RNA. Para 5d em STZ: sem N HEC até curva oficial.",
            },
            "hec_role_now": "primario_previsao_multidia_mucum_pesquisa",
            "quality_bar": [
                "Pipeline fechado: IFS→sub-bacias→params eventwise→Q→N (Muçum).",
                "Análogo eventwise por chuva — não promover common-search/mediana.",
                "Rotular pesquisa; não alerta oficial.",
                "Proxy pontual IFS explícito (ainda sem máscara areal).",
            ],
        },
        "investment_next": [
            {
                "priority": 1,
                "id": "operar_pipeline_5d",
                "action": "Rodar e endurecer hec_twin_mucum_forward_5d (forçante IFS + ensemble análogo + Q→N).",
            },
            {
                "priority": 2,
                "id": "skill_holdout_5d",
                "action": "Validar skill em eventos históricos com chuva 'como se fosse previsão' (hindcast).",
            },
            {
                "priority": 3,
                "id": "mascara_areal_ifs",
                "action": "Substituir proxy pontual por máscara areal IFS por sub-bacia quando o recorte hidrológico fechar.",
            },
            {
                "priority": 4,
                "id": "stz_curva_ou_rna_longa",
                "action": "STZ 5d: curva oficial para N via HEC, ou RNA de horizonte longo só com evidência — sem inventar curva.",
            },
        ],
        "artifacts": {
            "forcing": "hec_twin_ifs_forcing_5d_latest.json",
            "forecast": "hec_twin_mucum_forward_5d_latest.json",
            "forecast_html": "hec_twin_mucum_forward_5d.html",
            "decision_json": "decisao_previsao_nivel_multi_alvo_latest.json",
        },
        "supersedes": {
            "status": "decidido_rna_nivel_multi_alvo_hec_estacionado",
            "reason": "Juliana exige ~5 dias de antecedência para evacuação; RNA curta não substitui HEC+QPF.",
        },
    }
    DECISION.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if README.exists():
        text = README.read_text(encoding="utf-8")
        block = (
            "\n## Decisão de previsão (multi-dia / evacuação)\n\n"
            "**Primário ~5 dias:** gêmeo HEC + chuva IFS (`hec_twin_mucum_forward_5d.html`).\n\n"
            "**Curto prazo:** RNA de nível STZ/Muçum.\n\n"
            "STZ sem curva-chave: HEC não publica N em STZ.\n\n"
            "```bash\n"
            "python3 scripts/build_hec_twin_ifs_forcing_5d.py\n"
            "python3 scripts/run_hec_twin_mucum_forward_5d.py\n"
            "```\n"
        )
        marker = "## Decisão de previsão (multi-dia / evacuação)"
        if marker in text:
            import re

            text = re.sub(
                r"\n## Decisão de previsão \(multi-dia / evacuação\).*?(?=\n## |\Z)",
                block,
                text,
                count=1,
                flags=re.S,
            )
        elif "## Decisão de previsão (nível multi-alvo)" in text:
            import re

            text = re.sub(
                r"\n## Decisão de previsão \(nível multi-alvo\).*?(?=\n## |\Z)",
                block,
                text,
                count=1,
                flags=re.S,
            )
        else:
            text = text.rstrip() + "\n" + block
        README.write_text(text, encoding="utf-8")

    print(f"wrote {DECISION}")
    print(f"status={payload['status']}")


if __name__ == "__main__":
    main()
