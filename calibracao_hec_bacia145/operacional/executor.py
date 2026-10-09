"""Executor do HEC-HMS para um ciclo: monta a pasta de trabalho como o fluxo da nuvem (código da calibração copiado,
observados em dados_ana/csv, forçamento em JSON) e roda um projeto por cenário com hec.rodar_lote.

Nada do motor é reescrito: o .basin sai de estrutura_v3.bacia_v3 (estado inicial pelo q0 observado no início da janela,
como na calibração), o DSS de chuva de hec.dss_chuva, a execução de hec._lote_jvm. Funciona no Windows (HEC do PC)
e no Linux (HEC_HMS_CMD apontando para o hec-hms.sh).
"""
import importlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CAL = AQUI.parent
CODIGO = CAL / "codigo"
_MOD = {}


def preparar(trabalho: Path, hec_cmd=None):
    """Cria <trabalho>/w (código + dados_ana/csv + forc) e importa comum/hec/estrutura_v3 de lá. Só uma vez por processo."""
    if _MOD:
        return _MOD
    w = trabalho / "w"
    (w / "dados_ana" / "csv").mkdir(parents=True, exist_ok=True)
    for f in CODIGO.glob("*.py"):
        shutil.copy2(f, w / f.name)
    env = {"HEC_BASIN_BASE": CAL / "dados" / "basin" / "a00_E27.basin",
           "HEC_MDT_CSV": CAL / "dados" / "mdt_trechos_atributos.csv",
           "HEC_MDT_SUB": CAL / "dados" / "mdt_subbacias_atributos.csv",
           "HEC_FORC": w / "forc", "HEC_FORC_PREV": w / "forc_prev", "HEC_RESULT": w / "resultados",
           "HEC_RUNS": trabalho / "runs"}
    for k, v in env.items():
        os.environ[k] = str(v)
    if hec_cmd:
        os.environ["HEC_HMS_CMD"] = str(hec_cmd)
    for k in ("HEC_CATALOGO", "HEC_PAPEIS", "HEC_PERDA"):
        os.environ.pop(k, None)
    (w / "forc").mkdir(exist_ok=True)
    sys.path.insert(0, str(w))
    for nome in ("comum", "hec", "bacia_inteira", "estrutura_v3"):
        assert nome not in sys.modules or Path(sys.modules[nome].__file__).parent == w, nome
        _MOD[nome] = importlib.import_module(nome)
    _MOD["w"] = w
    return _MOD


def gerar_bacia(parametros, sim):
    """Gerador do .basin indicado no conjunto de parâmetros ('modulo.funcao'); hoje só estrutura_v3.bacia_v3."""
    mod, fn = parametros.get("gerador", "estrutura_v3.bacia_v3").split(".")
    return getattr(_MOD.get(mod) or importlib.import_module(mod), fn)(parametros["p"], sim, parametros.get("rota", "mc"))


def diretorio(sim, cenario):
    return _MOD["comum"].RUNS / sim / cenario


def rodar(sim, ini, fim, observados, forcamentos, parametros, paralelo=None, salvar_em=None, estado_inicial=None,
          por_jvm=1):
    """observados: {cod: {t: (nivel, vazao, chuva)}}; forcamentos: {cenario: {'horas': [...], 'chuva_por_subbacia': {...}}}.
    salvar_em: instante do Save State (estado.py); estado_inicial: arquivo .state com instante = ini (Start State).
    Devolve ({cenario: {no: {t: q}} ou Exception}, tempos, q0); com salvar_em, o .state salvo fica em
    <trabalho>/runs/<sim>/<cenario>/basinStates/fim.state."""
    import estado
    import telemetria_ana as ta
    comum, hec, bi = _MOD["comum"], _MOD["hec"], _MOD["bacia_inteira"]
    w = _MOD["w"]
    for cod, reg in observados.items():
        ta.gravar_csv(reg, w / "dados_ana" / "csv" / f"{cod}_{sim}.csv")
    comum.SIMULACOES[sim] = dict(ini=ini, fim=fim)
    jobs = []
    for cen, f in forcamentos.items():
        nome = f"{sim}__{cen}"
        comum.SIMULACOES[nome] = dict(ini=ini, fim=fim, mae=sim)
        (comum.FORC / f"{nome}.json").write_text(json.dumps(dict(f, sim=nome)), encoding="utf-8")
        jobs.append((diretorio(sim, cen), nome))
    hec.NOS_EXTRA = sorted({c[1] for c in bi.CONTROLES.values()})
    t = time.time()
    txt = gerar_bacia(parametros, sim)          # o q0 vem dos observados da janela-base (iguais em todos os cenários)
    t_bacia = time.time() - t
    t = time.time()
    original = hec.escrever_projeto

    def escrever(d, nome, texto):
        original(d, nome, texto)
        estado.configurar(d, hec, salvar_em, estado_inicial)

    hec.escrever_projeto = escrever if (salvar_em is not None or estado_inicial is not None) else original
    try:
        res = hec.rodar_lote([(d, nome, txt) for d, nome in jobs], paralelo=paralelo or len(jobs), por_jvm=por_jvm)
    finally:
        hec.escrever_projeto = original
    t_hec = time.time() - t
    out = {cen: res[d] for (d, _), cen in zip(jobs, forcamentos)}
    q0 = _MOD["estrutura_v3"].q0_controles(sim)
    return out, dict(gerar_bacia_s=round(t_bacia, 1), hec_s=round(t_hec, 1)), q0
