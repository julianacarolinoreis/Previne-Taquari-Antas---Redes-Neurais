import json, os, urllib.request, csv
from collections import OrderedDict
from seg import segment

BASE = "https://raw.githubusercontent.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais"
OUTDIR = "clean_out"
os.makedirs(OUTDIR + "/datasets", exist_ok=True)
os.makedirs("wb_cache", exist_ok=True)

payload = json.load(open("payload-merged.json"))["models"]
fm = json.load(open("file_map.json"))["wb"]

def fam(m): return "ALT" if "ALT" in (m.get("familia") or "").upper() else "CONV"

# seleção: top 10 por PERS_teste em cada grupo (horizonte x família)
groups = OrderedDict()
for h in ["8h", "12h"]:
    for f in ["ALT", "CONV"]:
        xs = [m for m in payload if m.get("horizonte") == h and fam(m) == f and m.get("PERS_teste") is not None]
        xs.sort(key=lambda m: -m["PERS_teste"])
        groups[f"{h}_{f}"] = xs[:10]

import openpyxl

def download(model):
    key = model["modelo"].lower()
    commit, path = fm[key]
    local = "wb_cache/" + os.path.basename(path)
    if not os.path.exists(local) or os.path.getsize(local) < 1000:
        url = f"{BASE}/{commit}/{path}"
        urllib.request.urlretrieve(url, local)
    return local

def process(model):
    local = download(model)
    wb = openpyxl.load_workbook(local, read_only=True, data_only=True)
    ws = wb["DADOS"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = list(rows[0]); data = rows[1:]
    idx = {name: i for i, name in enumerate(hdr)}
    iEv = idx["EVENTO"]; iNiv = idx["NIVEL_ATUAL_CM"]; iConj = idx["CONJUNTO"]
    iSeq = idx.get("COD_SEQUENCIAL", None)
    # agrupa por evento, ordena por sequencial
    evs = OrderedDict()
    for r in data: evs.setdefault(r[iEv], []).append(r)
    if iSeq is not None:
        for ev in evs: evs[ev].sort(key=lambda r: (r[iSeq] if r[iSeq] is not None else 0))
    kept_rows = []
    ev_report = []
    conj_counts = {"Treino": [0, 0], "Validacao": [0, 0], "Teste": [0, 0]}  # [antes, depois]
    for ev, ers in evs.items():
        niv = [r[iNiv] for r in ers]
        keep, win = segment(niv)
        conj = ers[0][iConj]
        cc = conj_counts.setdefault(conj, [0, 0])
        cc[0] += len(ers)
        k = 0
        for r, kp in zip(ers, keep):
            if kp: kept_rows.append(r); k += 1
        cc[1] += k
        ev_report.append({"evento": ev, "conjunto": conj, "linhas": len(ers), "mantidas": k,
                          "descartadas": len(ers) - k,
                          "pico_cm": max(niv), "inicio_cm": (niv[win[0]] if win else None),
                          "descartado_inteiro": k == 0})
    return hdr, kept_rows, ev_report, conj_counts, os.path.basename(local)

report = {"criterio": "Mantém, por evento, a subida desde o início (mesmo abaixo de 5 m) ate o pico, "
          "e corta no primeiro ponto abaixo de 5 m (500 cm) apos o pico. Eventos que nunca passam de 5 m "
          "ou apenas um espetinho (<10 linhas acima do bloco) saem inteiros.", "grupos": {}}

for gname, models in groups.items():
    report["grupos"][gname] = []
    for m in models:
        hdr, kept_rows, ev_report, conj_counts, wbname = process(m)
        safe = m["modelo"].replace("/", "_")
        out_csv = f"{OUTDIR}/datasets/{gname}__{safe}.csv"
        with open(out_csv, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(hdr); w.writerows(kept_rows)
        tot_antes = sum(v[0] for v in conj_counts.values())
        tot_dep = sum(v[1] for v in conj_counts.values())
        report["grupos"][gname].append({
            "modelo": m["modelo"], "combo_id": m.get("combo_id"), "PERS_teste": m.get("PERS_teste"),
            "novo": m.get("novo", False), "workbook": wbname, "csv": os.path.basename(out_csv),
            "linhas_antes": tot_antes, "linhas_depois": tot_dep,
            "por_conjunto": {c: {"antes": v[0], "depois": v[1]} for c, v in conj_counts.items() if v[0] > 0},
            "eventos": ev_report,
        })
        print(f"  {gname:9} {m['modelo'][:44]:44} {tot_antes:5} -> {tot_dep:5} linhas")

json.dump(report, open(f"{OUTDIR}/relatorio_corte.json", "w"), indent=1, ensure_ascii=False)
print("OK. Relatorio em", f"{OUTDIR}/relatorio_corte.json")
