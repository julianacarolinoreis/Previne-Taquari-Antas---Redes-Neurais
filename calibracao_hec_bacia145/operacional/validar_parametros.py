"""Confere que o executor gera o mesmo modelo que a calibração: roda um conjunto de parâmetros numa janela do catálogo
com a chuva do forcamento_v3 e compara a vazão (10 min) com a vazao.csv da rodada da nuvem (artefato do lote).

Uso: python validar_parametros.py parametros/md-val2-c002.json S2023_11 <pasta dos artefatos> [--id md-val2-c002]
  <pasta dos artefatos>: onde estão lote-*/<id>/<janela>/vazao.csv (gh run download <run> -p "lote-*").
Não use janelas de teste (X20260918).
"""
import argparse
import gzip
import json
import sys
from datetime import timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import executor           # noqa: E402
import vazao_observada as vo  # noqa: E402

CAL = AQUI.parent
TESTE = {"X20260918"}


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("parametros")
    ap.add_argument("janela")
    ap.add_argument("artefatos")
    ap.add_argument("--id", default=None, help="id do candidato na rodada (padrão: o id do arquivo de parâmetros)")
    ap.add_argument("--trabalho", default=str(Path.home() / "hec_aovivo_trabalho" / "validar"))
    a = ap.parse_args()
    if a.janela in TESTE:
        raise SystemExit("janela de teste: fechada")
    par = json.loads(Path(a.parametros).read_text(encoding="utf-8"))
    cid = a.id or par["id"]
    ref = next(Path(a.artefatos).glob(f"*/{cid}/{a.janela}/vazao.csv"), None)
    if ref is None:
        raise SystemExit(f"sem {cid}/{a.janela}/vazao.csv em {a.artefatos}")
    mods = executor.preparar(Path(a.trabalho))
    comum, hec, bi = mods["comum"], mods["hec"], mods["bacia_inteira"]
    cat = json.loads((CAL / "dados" / "catalogo_ampliado.json").read_text(encoding="utf-8"))
    for s in cat["simulacoes"]:
        comum.SIMULACOES.setdefault(s["sim"], dict(ini=comum.T(s["ini"]), fim=comum.T(s["fim"])))
    ini, fim = comum.SIMULACOES[a.janela]["ini"], comum.SIMULACOES[a.janela]["fim"]
    cods = sorted({c[0] for c in bi.CONTROLES.values()})
    regs, _ = vo.ArquivoObservados(a.janela, CAL / "dados" / "observados").obter(cods, ini - timedelta(days=1), fim)
    forc = json.loads(gzip.decompress((CAL / "dados" / "forcamento_v3" / f"{a.janela}.json.gz").read_bytes()))
    sim = f"VAL_{a.janela}"
    res, tempos, _ = executor.rodar(sim, ini, fim, regs, {"v3": {"horas": forc["horas"],
                                                                 "chuva_por_subbacia": forc["chuva_por_subbacia"]}}, par)
    r = res["v3"]
    if isinstance(r, Exception):
        raise SystemExit(f"HEC falhou: {r}")
    nuvem = hec.ler_vazao(ref.parent)
    out = {}
    for nome, (_cod, no, *_r) in bi.CONTROLES.items():
        if no not in nuvem or no not in r:
            continue
        d = [abs(r[no][t] - q) for t, q in nuvem[no].items() if t in r[no]]
        out[nome] = dict(no=no, n=len(d), max_abs_m3s=round(max(d), 3), pico_local=round(max(r[no].values()), 1),
                         pico_nuvem=round(max(nuvem[no].values()), 1))
        print(f"{nome:13s} {no}: {len(d)} passos, |local − nuvem| máx {max(d):.3f} m³/s; pico {out[nome]['pico_local']}"
              f" × {out[nome]['pico_nuvem']}")
    print("HEC:", tempos)
    return out


if __name__ == "__main__":
    main()
