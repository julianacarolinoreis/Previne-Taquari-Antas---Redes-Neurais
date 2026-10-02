#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"assets/data/vulnerabilidade/analises_spaciais"
HTML=ROOT/"vulnerabilidade.html"

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=set()
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if d.get("id"): self.ids.add(d["id"])

def main():
    analysis=json.loads((DATA/"analysis_vulnerabilidade_spatial_full.json").read_text(encoding="utf-8"))
    compact=json.loads((DATA/"lisa_classificacao_setores.json").read_text(encoding="utf-8"))
    geo=json.loads((DATA/"lisa_setores_bacia.geojson").read_text(encoding="utf-8"))
    assert analysis["n_sectors"]==3283
    w=analysis["weights"]
    assert w["main_k"]==6 and w["global_permutations"]==999 and w["local_permutations"]==9999
    assert "Benjamini-Hochberg" in w["multiple_testing_adjustment"]
    assert len(compact["sectors"])==3283
    assert geo.get("type")=="FeatureCollection" and len(geo.get("features",[]))==3283
    required={"lisa_fdr_income","lisa_fdr_water","lisa_fdr_sewage","lisa_fdr_child","lisa_fdr_elderly","lisa_fdr_blackbrown","structural_ll_count","elderly_hh_plus_structural"}
    sample=geo["features"][0]["properties"]
    assert required <= set(sample)
    assert all(v["global"]["p_sim"]<=0.001 for v in analysis["spatial_statistics"].values())
    assert analysis["spatial_statistics"]["sewage"]["global"]["I"]>0.6
    assert analysis["spatial_statistics"]["elderly"]["lisa_counts_fdr_bh"]["HH"]>=200
    st=analysis["santa_tereza_historical_events"]
    assert {e["event_label"] for e in st}=={"Set/2023","Nov/2023","Mai/2024"}
    assert all(e["sector_overlay"]["lisa_touched"]["elderly"].get("HH",0)==e["sector_overlay"]["sectors_touched"] for e in st)

    html=HTML.read_text(encoding="utf-8")
    p=Parser(); p.feed(html)
    ids={"analiseEspacial","spatialMetric","spatialFlood","spatialAnalysisLegend","spatialAnalysisStatus","spatialPresetElderlyFlood"}
    assert ids <= p.ids
    for path in (
        "assets/data/vulnerabilidade/analises_spaciais/lisa_setores_bacia.geojson",
        "assets/data/vulnerabilidade/analises_spaciais/lisa_classificacao_setores.json",
        "assets/data/vulnerabilidade/analises_spaciais/analysis_vulnerabilidade_spatial_full.json",
    ):
        assert path in html
    assert "9.999 permutações" in html and "Benjamini" in html and "FDR" in html
    assert "HH/LL não significam risco alto/baixo" in html
    assert "ainda não sobrepõe o perigo" not in html

    scripts=re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>",html,flags=re.S|re.I)
    inline="\n".join(s for s in scripts if s.strip())
    with tempfile.NamedTemporaryFile("w",suffix=".js",encoding="utf-8",delete=False) as fh:
        fh.write(inline); js=Path(fh.name)
    try:
        proc=subprocess.run(["node","--check",str(js)],capture_output=True,text=True)
        assert proc.returncode==0, proc.stderr
    finally:
        js.unlink(missing_ok=True)
    print(json.dumps({"status":"OK","setores":3283,"html_ids":len(p.ids),"spatial_ui":"OK"},ensure_ascii=False))

if __name__=="__main__":
    main()
