"""Monta operacional/dados/ a partir das fontes do PC (rodar só quando alguma delas mudar; o resultado vai para o git).

- subbacias.json: centróide e área (IDW da chuva observada, igual ao forcamento_v3) e pontos a 0,01° dentro de cada
  polígono (média na área da chuva prevista, igual a _analise_bacia145/chuva_prevista/grade.py).
- postos_ana.json: postos ANA da rede do forcamento_v3 (todos_postos sem CEMADEN/INMET) com coordenadas.
- curvas_telemetria.json: pares nível × vazão da telemetria (Muçum, Encantado, LJJ) de todas as janelas do catálogo,
  menos a de teste (X20260918) e a LIVE — a curva agregada de correcao/horaria/correcao_horaria.py (classe Curva).
- correcao.json: τ(h) da correção aditiva escolhidos na calibração (correcao/horaria/resultado_horaria.json).
- parametros/lr-g8-c038.json: membro mt-b1-c000 da biblioteca_mt-b1.json.
- parametros/md-val2-c002.json: o modelo novo, com o τ(h) da correção re-escolhido para ele (`preparar_dados.py c002`).
- postos_rede.json: rede ao vivo ANA + CEMADEN + INMET da frente de chuva (`preparar_dados.py rede`).
Uso: python preparar_dados.py [c002 | rede]
"""
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
CAL = AQUI.parent
DADOS = AQUI / "dados"
CODEX_HEC = Path(r"D:\PREVINE\hec_calibracao_20261005")
ANALISE = Path(r"D:\PREVINE\repo_hec_calib\_analise_bacia145")
TESTE = {"X20260918"}


def subbacias():
    geo = json.loads((CODEX_HEC / "geometria_subbacias.json").read_text(encoding="utf-8"))
    pts = json.loads((ANALISE / "chuva_prevista" / "subbacias_centroides.json").read_text(encoding="utf-8"))
    out = {g["sub_id"]: dict(lat=round(g["lat"], 6), lon=round(g["lon"], 6), area_km2=g["area_km2"],
                             pontos=pts[g["sub_id"]]["pontos"]) for g in geo}
    (DADOS / "subbacias.json.gz").write_bytes(gzip.compress(json.dumps(out, sort_keys=True).encode(), mtime=0))
    print("subbacias:", len(out))


def postos():
    os.environ["HEC_SEM_CEMADEN"] = "1"
    sys.path.insert(0, str(CODEX_HEC))
    os.chdir(CODEX_HEC)
    import forcamento_v3 as V3
    P = V3.todos_postos()
    ana = {c: dict(nome=v[0], lat=float(v[1]), lon=float(v[2])) for c, v in sorted(P.items())
           if not c.startswith(("CEM_", "INMET_"))}
    (DADOS / "postos_ana.json").write_text(json.dumps(ana, ensure_ascii=False, indent=0), encoding="utf-8")
    print("postos ANA:", len(ana))


def curvas():
    obs = CAL / "dados" / "observados"
    out = {}
    for nome, cod in (("MUCUM", "86510000"), ("ENCANTADO", "86720000"), ("LJJ", "86472000")):
        P, jan = [], []
        for f in sorted(obs.glob(f"{cod}_*.csv.gz")):
            sim = f.name[len(cod) + 1:-7]
            if sim in TESTE or sim == "LIVE":
                continue
            jan.append(sim)
            for ln in gzip.decompress(f.read_bytes()).decode("utf-8").splitlines()[1:]:
                _, n, q, _ = (ln.split(",") + ["", "", "", ""])[:4]
                if n and q and float(q) > 0:
                    P.append((float(n), float(q)))
        a = np.array(sorted(P))
        h, q = a[:, 0], np.maximum.accumulate(a[:, 1])
        _, i = np.unique(h, return_index=True)
        out[nome] = dict(codigo=cod, janelas=jan, nivel_cm=h[i].round(1).tolist(), vazao_m3s=q[i].round(2).tolist())
        print(nome, len(jan), "janelas,", len(i), "pares únicos, até", h[i][-1], "cm")
    (DADOS / "curvas_telemetria.json").write_text(json.dumps(out), encoding="utf-8")


def correcao():
    r = json.loads((ANALISE / "correcao" / "horaria" / "resultado_horaria.json").read_text(encoding="utf-8"))
    out = {"fonte": "_analise_bacia145/correcao/horaria (escolha só nos eventos de calibração, lr-g8-c038)",
           "metodo": "adit_h: Q = S + e(tv)*exp(-(t-tv)/tau(h)), h = t - t0 (1..48 h; depois de 48 h, tau(48))",
           "busca_ultimo_valido_h": 72,
           "tau_h": {a: r["escolha"][a]["adit_h"]["tau"] for a in ("MUCUM", "ENCANTADO", "LJJ")},
           "tau_unico": {a: r["escolha"][a]["adit"]["tau"] for a in ("MUCUM", "ENCANTADO", "LJJ")}}
    (DADOS / "correcao.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def parametros():
    lib = json.loads((ANALISE / "montante" / "biblioteca_mt-b1.json").read_text(encoding="utf-8"))
    m = next(x for x in lib["membros"] if x["membro"] == "mt-b1-c000")
    p = dict(id="lr-g8-c038", membro_mt_b1=m["membro"], familia=m["familia"], rota=m["rota"],
             gerador="estrutura_v3.bacia_v3", J_cal=m["J_cal"], p=m["p"],
             origem="_analise_bacia145/montante/biblioteca_mt-b1.json (melhor J de calibração e de validação, lrdc)")
    p["sha256_p"] = hashlib.sha256(json.dumps(m["p"], sort_keys=True).encode()).hexdigest()[:16]
    (AQUI / "parametros").mkdir(exist_ok=True)
    (AQUI / "parametros" / "lr-g8-c038.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


AOVIVO = Path(r"D:\PREVINE\repo_hec_aovivo\_analise_aovivo")


def rede():
    """Postos da rede ao vivo recomendada pela frente de chuva (branch cursor/hec-bacia145-aovivo,
    postos_recomendados.json: universo v3 ∩ vivos em 09/10/2026 − lista negra), com o nome público do CEMADEN
    (cemaden_ao_vivo.json: casamento por município + nome, porque o JSON público não traz o código)."""
    rec = json.loads((AOVIVO / "postos_recomendados.json").read_text(encoding="utf-8"))
    cem = json.loads((AOVIVO / "cemaden_ao_vivo.json").read_text(encoding="utf-8"))
    postos = {}
    for p in rec["postos"]:
        c = p["codigo"]
        d = dict(fonte=p["fonte"], lat=p["lat"], lon=p["lon"])
        if p["fonte"] == "CEMADEN":
            d.update(nome_publico=cem[c]["casado_com"], municipio=cem[c]["municipio"])
            assert d["nome_publico"], c
        postos[c] = d
    out = dict(fonte="repo_hec_aovivo/_analise_aovivo/postos_recomendados.json + cemaden_ao_vivo.json",
               descricao=rec["descricao"], lista_negra=rec["lista_negra"], por_fonte=rec["por_fonte"], postos=postos)
    (DADOS / "postos_rede.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print("rede:", rec["por_fonte"])


MODELO = Path(r"D:\PREVINE\repo_hec_modelo")
TAU_C002 = AQUI.parents[1] / "_analise_sistema" / "tau_c002" / "resultado_horaria.json"


def parametros_c002():
    """md-val2-c002 (frente do modelo, branch cursor/hec-bacia145-modelo): lrdc puro, calha trapezoidal, rota mc.
    ie/atc/ar/nob do pedido são neutros nessa rota/família (atc = ar = 0, sem seções) e ficam de fora. A correção vai
    junto: τ(h) re-escolhido com correcao_horaria.py (só calibração) sobre as vazões da rodada md-val2."""
    ped = json.loads((MODELO / "calibracao_hec_bacia145" / "rodadas" / "PEDIDO.json").read_text(encoding="utf-8"))
    c = next(x for x in ped["candidatos"] if x["id"] == "md-val2-c002")
    assert c["rota"] == "mc" and c["p"]["atc"] == 0 and c["p"]["ar"] == 0
    p = {k: v for k, v in c["p"].items() if k not in ("ie", "atc", "ar", "nob")}
    r = json.loads(TAU_C002.read_text(encoding="utf-8"))
    out = dict(id="md-val2-c002", familia="lrdc", rota="mc", gerador="estrutura_v3.bacia_v3",
               J_cal=6.731490621901747, J_val=6.998, J_pico_val=7.176, p=p,
               origem="repo_hec_modelo/_analise_modelo/LEIAME.md (rodada md-val2, decomposição do md-w2-c016)",
               correcao={"fonte": "correcao_horaria.py com o membro md-val2-c002 (vazões da rodada md-val2; escolha só "
                                  "nos eventos de calibração)",
                         "busca_ultimo_valido_h": 72,
                         "tau_h": {a: r["escolha"][a]["adit_h"]["tau"] for a in ("MUCUM", "ENCANTADO", "LJJ")},
                         "tau_unico": {a: r["escolha"][a]["adit"]["tau"] for a in ("MUCUM", "ENCANTADO", "LJJ")}})
    out["sha256_p"] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    (AQUI / "parametros" / "md-val2-c002.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")


if __name__ == "__main__":
    DADOS.mkdir(exist_ok=True)
    if sys.argv[1:] == ["c002"]:
        parametros_c002()
        sys.exit()
    if sys.argv[1:] == ["rede"]:
        rede()
        sys.exit()
    subbacias()
    curvas()
    correcao()
    parametros()
    postos()
