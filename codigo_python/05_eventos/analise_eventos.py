#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análise por EVENTO — lê todas as planilhas auditáveis e produz
assets/data/eventos_analise.json com:

1) Catálogo de eventos canônicos (identificados pela DATA do pico, pois a
   numeração de eventos muda entre planilhas).
2) Por evento: dificuldade objetiva (NSE da persistência), desempenho das
   redes quando o evento foi TESTE, VALIDAÇÃO e no GERAL (mediana de NSE).
3) Séries completas (observado × RNA) de TODOS os eventos para os modelos
   campeões de cada horizonte — hidrograma + dispersão por evento no site.
4) "Curiosidades do geral": leituras automáticas (evento mais difícil/fácil,
   onde as redes mais ganham da persistência, alerta de teste fácil).

Uso:  python codigo_python/05_eventos/analise_eventos.py   (na raiz do repo)
"""
import json, os, re, glob
import openpyxl
from openpyxl.utils import column_index_from_string as ci
from statistics import median

WB_DIR = "assets/audit_workbooks"
OUT    = "assets/data/eventos_analise.json"
# campeões (1 por horizonte) p/ séries completas por evento
CAMPEOES = ["2h_alt_2H_ALT_C0472", "8h_alt_8H_ALT_C0241", "12h_alt", "8h_conv_8H_CONV_C0078"]

C = lambda L: ci(L)-1
def nse(pairs):
    obs=[o for o,_ in pairs];
    if len(obs)<3: return None
    mo=sum(obs)/len(obs)
    den=sum((o-mo)**2 for o in obs)
    if den==0: return None
    num=sum((o-p)**2 for o,p in pairs)
    return 1-num/den

def processa(fp):
    ws=openpyxl.load_workbook(fp, read_only=True, data_only=True)["DADOS"]
    it=ws.iter_rows(values_only=True)
    hdr=[str(h or '') for h in next(it)]
    ix={}
    for alvo,nomes in {"ev":["EVENTO"],"cj":["CONJUNTO"],"dh":["DATA_HORA"],
                       "na":["NIVEL_ATUAL_CM"],"obs":["OBSERVADO_CM_AUDITORIA","OBSERVADO_CM"],
                       "rna":["RNA_CM"],"pers":["PERS_BASE_NIVEL_ATUAL_CM","PERS_BASE_CM"]}.items():
        for nm in nomes:
            if nm in hdr: ix[alvo]=hdr.index(nm); break
    rows=list(it)
    evs={}
    for r in rows:
        try:
            ev=r[ix["ev"]]; cj=str(r[ix["cj"]] or '')
            dh=str(r[ix["dh"]]); obs=r[ix["obs"]]; rna=r[ix["rna"]]; pers=r[ix.get("pers",ix["na"])]
        except Exception: continue
        if ev is None or obs is None: continue
        try: obs=float(obs)
        except Exception: continue
        def fl(v):
            try: return float(v)
            except Exception: return None
        e=evs.setdefault(ev,{"conj":cj,"rows":[]})
        e["rows"].append((dh,fl(r[ix["na"]]) or 0,obs,fl(rna),fl(pers)))
    out={}
    for ev,e in evs.items():
        rs=e["rows"]
        peak=max(rs,key=lambda x:x[2])
        prna=[(o,p) for _,_,o,p,_ in rs if p is not None]
        pper=[(o,p) for _,_,o,_,p in rs if p is not None]
        out[ev]={"conj":e["conj"],"n":len(rs),
                 "pico_cm":round(peak[2]),"pico_data":peak[0][:10],
                 "nse_rna":nse(prna),"nse_pers":nse(pper),
                 "mae":round(sum(abs(o-p) for o,p in prna)/len(prna),1) if prna else None,
                 "rows":rs}
    return out

def main():
    files=sorted(glob.glob(os.path.join(WB_DIR,"*.xlsx")))
    print(f"{len(files)} planilhas")
    canon={}          # pico_data -> {registros por (modelo,conjunto)}
    campeao_series={}
    for i,fp in enumerate(files):
        name=os.path.basename(fp).replace("_AUDITAVEL_INPUTS_RNA.xlsx","")
        try: evs=processa(fp)
        except Exception as ex: print("erro",name,ex); continue
        eh_campeao=True  # séries completas para TODOS os modelos com planilha auditável
        for ev,d in evs.items():
            import datetime as _dt
            pd=_dt.date.fromisoformat(d["pico_data"])
            key=None
            for k in canon:
                if abs((_dt.date.fromisoformat(k)-pd).days)<=5: key=k; break
            if key is None: key=d["pico_data"]
            c=canon.setdefault(key,{"pico_cm":d["pico_cm"],"n_modelos":0,
                                    "nse_por_conj":{"Treino":[],"Validacao":[],"Teste":[]},
                                    "nse_pers":[]})
            c["pico_cm"]=max(c["pico_cm"],d["pico_cm"])
            c["n_modelos"]+=1
            cj="Treino" if d["conj"].lower().startswith("trein") else ("Teste" if d["conj"].lower().startswith("test") else "Validacao")
            if d["nse_rna"] is not None: c["nse_por_conj"][cj].append(round(d["nse_rna"],4))
            if d["nse_pers"] is not None: c["nse_pers"].append(round(d["nse_pers"],4))
            if eh_campeao and key not in campeao_series.get(name,{}):
                campeao_series.setdefault(name,{})[key]={
                    "conj":cj,"serie":[[r[0],round(r[2]),round(r[3],1) if r[3] is not None else None] for r in d["rows"]]}
        if (i+1)%20==0: print(f"  {i+1}/{len(files)}")

    eventos=[]
    for key,c in sorted(canon.items()):
        med=lambda a: round(median(a),3) if a else None
        eventos.append({"pico_data":key,"pico_cm":c["pico_cm"],"n_modelos":c["n_modelos"],
            "dificuldade_nse_pers":med(c["nse_pers"]),
            "nse_teste":med(c["nse_por_conj"]["Teste"]),
            "nse_validacao":med(c["nse_por_conj"]["Validacao"]),
            "nse_treino":med(c["nse_por_conj"]["Treino"]),
            "n_teste":len(c["nse_por_conj"]["Teste"]),
            "n_validacao":len(c["nse_por_conj"]["Validacao"])})

    # curiosidades do geral (leituras automáticas, baseadas nos números)
    com_dif=[e for e in eventos if e["dificuldade_nse_pers"] is not None]
    cur=[]
    if com_dif:
        dificil=min(com_dif,key=lambda e:e["dificuldade_nse_pers"])
        facil  =max(com_dif,key=lambda e:e["dificuldade_nse_pers"])
        cur.append(f"O evento mais difícil de prever é o de {dificil['pico_data']} (pico {dificil['pico_cm']/100:.1f} m): a persistência só alcança NSE {dificil['dificuldade_nse_pers']:.2f}.")
        cur.append(f"O evento mais fácil é o de {facil['pico_data']}: a persistência sozinha chega a NSE {facil['dificuldade_nse_pers']:.2f} — bons resultados de teste nele merecem leitura cautelosa.")
        ganho=[(e,(e['nse_teste'] or 0)-(e['dificuldade_nse_pers'] or 0)) for e in com_dif if e['nse_teste'] is not None]
        if ganho:
            g=max(ganho,key=lambda x:x[1])
            cur.append(f"Onde as redes mais ganham da persistência: evento de {g[0]['pico_data']} (+{g[1]:.2f} de NSE sobre o baseline no teste).")
        alerta=[e for e in com_dif if e['nse_teste'] is not None and e['dificuldade_nse_pers']>=0.9]
        if alerta:
            l=", ".join(e['pico_data'] for e in alerta)
            cur.append(f"Atenção: quando o teste caiu em evento 'fácil' ({l}), o NSE alto pode refletir a facilidade do evento, não a força da rede — compare sempre com o NSE da persistência.")

    json.dump({"gerado_de":len(files),"eventos":eventos,"curiosidades":cur,
               "campeoes":campeao_series},
              open(OUT,"w"),ensure_ascii=False)
    print("eventos canônicos:",len(eventos)," | campeões com séries:",len(campeao_series))
    print("OUT:",OUT, os.path.getsize(OUT)//1024,"KB")

if __name__=="__main__":
    main()
