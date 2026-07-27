#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Gera assets/data/rodadas_realizadas.json — metrica de ESFORCO/PROCESSO
("quantos dias de treino ja rodei"), separada da lista de modelos
QUALIFICADOS/publicados no site (essa continua vindo de
mucum_auditaveis_series.json e do payload embutido no index.html, sem
nenhuma mudanca). As duas coisas respondem perguntas diferentes:
"rodadas realizadas" conta TODO o historico de treino; "modelos
publicados" so conta o que passou no corte de equilibrio.

Varre as pastas de rodada em D:/PREVINE/redes_neurais/mucum e
D:/PREVINE/redes_neurais/santa tereza. Conta como "dia de rodada real"
qualquer pasta de topo cujo nome termina em _AAAA_MM_DD e que contem
sinal de treino de verdade — pelo menos um .mat (em qualquer
subpasta) ou um resultados*.csv com conteudo (>200 bytes, nao so
cabecalho). Pastas de preparacao/auditoria/relatorio/analise sem esse
sinal NAO contam (ex.: PREPARACAO_RNA_MUC_2026_07_11,
AUDITORIA_MUCUM_MODELOS_SITE_2026_07_23, RELATORIO_*, TOP50_*).

So roda LOCALMENTE — precisa do disco D:\PREVINE\redes_neurais, que
nao existe no runner do GitHub (mesmo motivo de
gerar_resultados_mucum.py nao rodar la). Rodar de novo a qualquer
momento atualiza o JSON com o estado atual do disco; git add/commit/
push continua manual, como o resto do projeto — nada aqui commita ou
publica sozinho.

Uso: python codigo_python/08_resultados_modelos/gerar_rodadas_realizadas.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

REDES_NEURAIS = Path(r"D:\PREVINE\redes_neurais")
CIDADES = {
    "mucum": REDES_NEURAIS / "mucum",
    "santa_tereza": REDES_NEURAIS / "santa tereza",
}
OUT = Path(r"D:\PREVINE\repo_site\assets\data\rodadas_realizadas.json")

DATA_RE = re.compile(r"(20\d{2})_(\d{2})_(\d{2})$")


def tem_treino_real(pasta: Path) -> bool:
    """Sinal de rodada de treino de verdade: .mat gerado, ou resultados*.csv com linhas de dado."""
    if any(pasta.glob("mat/*.mat")):
        return True
    if any(pasta.glob("**/*.mat")):
        return True
    for f in pasta.glob("resultados*.csv"):
        try:
            if f.stat().st_size > 200:
                return True
        except OSError:
            continue
    return False


def varre_cidade(raiz: Path) -> list[dict]:
    pastas = []
    if not raiz.exists():
        return pastas
    for p in sorted(raiz.iterdir()):
        if not p.is_dir():
            continue
        m = DATA_RE.search(p.name)
        if not m:
            continue
        if not tem_treino_real(p):
            continue
        data_iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        pastas.append({"pasta": p.name, "data": data_iso})
    return pastas


def main():
    cidades_out = {}
    todos_dias = set()
    for chave, raiz in CIDADES.items():
        pastas = varre_cidade(raiz)
        dias = sorted({p["data"] for p in pastas})
        cidades_out[chave] = {"dias": dias, "pastas": pastas}
        todos_dias.update(dias)

    payload = {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fonte": (
            "Varredura de pastas de rodada em D:/PREVINE/redes_neurais (mucum + santa tereza). "
            "Conta como rodada real qualquer pasta terminada em _AAAA_MM_DD que tenha pelo menos "
            "um .mat ou um resultados*.csv com conteudo — pastas de preparacao/auditoria/relatorio/"
            "analise sem esse sinal nao contam. Metrica de ESFORCO/PROCESSO: cobre TODO o historico "
            "de treino, nao so os modelos qualificados/publicados no site."
        ),
        "cidades": cidades_out,
        "dias_distintos_total": len(todos_dias),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Escrito {OUT}")
    for chave, info in cidades_out.items():
        print(f"  {chave}: {len(info['dias'])} dia(s) distinto(s), {len(info['pastas'])} pasta(s) de rodada")
    print(f"Total (uniao Mucum + Santa Tereza): {len(todos_dias)} dia(s) distinto(s)")


if __name__ == "__main__":
    main()
