"""Lista negra fixa (causal): postos que o QC v3 excluiu nas janelas de CALIBRAÇÃO (versão avtelq3).

Critério: excluído em >= 2 janelas e em >= 1/3 das janelas de calibração em que tinha dados -> lista_negra.json.
Só usa janelas de calibração (avaliar_montante.JANELAS_CAL); a validação não informa a lista.
"""
import json
import sys
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI / "reuso"))
import avaliar_montante as am  # noqa: E402

exc, pres = Counter(), Counter()
for sim in am.JANELAS_CAL:
    d = json.loads((AQUI / "forc" / "avtelq3" / f"{sim}.json").read_text(encoding="utf-8"))
    ex = set(d.get("excluidos_qc") or [])
    for c in set(d["postos_usados"]) | ex:
        pres[c] += 1
    for c in ex:
        exc[c] += 1
lista = sorted(c for c in exc if exc[c] >= 2 and exc[c] >= pres[c] / 3)
det = {c: f"{exc[c]}/{pres[c]}" for c in sorted(exc, key=lambda c: -exc[c])}
(AQUI / "lista_negra.json").write_text(json.dumps(dict(lista=lista, excluidos_por_janela_cal=det,
                                                       janelas_cal=list(am.JANELAS_CAL)), indent=1, ensure_ascii=False),
                                       encoding="utf-8")
print(len(am.JANELAS_CAL), "janelas cal;", len(lista), "na lista:", lista)
print(det)
