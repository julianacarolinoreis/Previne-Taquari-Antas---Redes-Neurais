"""Build the auditable Santa Tereza 2-hour RNA event replay package."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "data" / "auditaveis_series.json"
STATION_AUDIT = ROOT / "assets" / "data" / "hec_hms_audit" / "rainfall_station_audit_latest.json"
OUT = ROOT / "assets" / "data" / "santa_tereza_eventwise_replay_rna_2h"
MODEL_NAME = "001_alt_STZ_2H_R01_T12_V1-5-10-15-17-21"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event_rows(model: dict) -> tuple[list[dict], list[dict]]:
    metrics = []
    series = []
    for event in model["events"]:
        key = event["key"]
        values = model["series"][key]
        observed_peak = max(values, key=lambda row: float(row[1]))
        predicted_peak = max(values, key=lambda row: float(row[2]))
        observed_peak_time = datetime.fromisoformat(observed_peak[0])
        predicted_peak_time = datetime.fromisoformat(predicted_peak[0])
        obs_peak = float(event["obsPeak"])
        rna_peak = float(event["rnaPeak"])
        metrics.append({
            "evento": event["evento"],
            "conjunto": event["conjunto"],
            "papel_avaliacao": "teste_independente" if event["conjunto"] == "Teste" else ("validacao" if event["conjunto"] == "Validacao" else "treino_replay"),
            "n": event["n"],
            "inicio": event["start"],
            "fim": event["end"],
            "nivel_inicial_cm": event["obsStart"],
            "pico_observado_cm": obs_peak,
            "pico_rna_cm": rna_peak,
            "erro_pico_cm": round(rna_peak - obs_peak, 6),
            "erro_pico_abs_cm": round(abs(rna_peak - obs_peak), 6),
            "erro_pico_relativo_pct": round(abs(rna_peak - obs_peak) / obs_peak * 100, 6),
            "hora_pico_observado": observed_peak[0],
            "hora_pico_rna": predicted_peak[0],
            "atraso_pico_horas": round((predicted_peak_time - observed_peak_time).total_seconds() / 3600, 6),
            "subida_observada_cm": event["riseObs"],
            "subida_rna_cm": event["riseRna"],
            "erro_subida_abs_cm": round(abs(float(event["riseRna"]) - float(event["riseObs"])), 6),
            "mae_cm": event["mae"],
            "erro_maximo_abs_cm": event["maxErr"],
        })
        for row in values:
            series.append({
                "evento": event["evento"],
                "conjunto": event["conjunto"],
                "timestamp_local": row[0],
                "nivel_observado_cm": row[1],
                "nivel_rna_cm": row[2],
                "conjunto_codigo": row[3],
                "subida_observada_cm": row[4],
                "subida_rna_cm": row[5],
                "residuo_cm": row[6],
            })
    return metrics, series


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def replay_html(metrics: list[dict], series: list[dict]) -> str:
    payload = json.dumps({"metrics": metrics, "series": series}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Replay Santa Tereza · RNA 2h</title>
<style>
:root {{ --ink:#123047; --muted:#587184; --line:#d8e5ea; --mint:#e9f7f2; --blue:#1577c8; --orange:#eb8b35; --bg:#f5fafb; --card:#fff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(135deg,#eff8f8,#f8fbff); color:var(--ink); font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:1180px; margin:auto; padding:28px 18px 48px; }}
.hero {{ display:flex; gap:18px; align-items:flex-start; justify-content:space-between; margin-bottom:20px; }}
h1 {{ margin:0 0 6px; font-size:clamp(25px,4vw,42px); letter-spacing:-.03em; }}
h2 {{ margin:0 0 12px; font-size:18px; }}
p {{ margin:6px 0; color:var(--muted); }}
.eyebrow,.tag {{ display:inline-flex; border-radius:999px; padding:5px 10px; font-size:12px; font-weight:800; letter-spacing:.04em; }}
.eyebrow {{ background:#dcecff; color:#1263a7; }} .tag {{ background:#fff0e1; color:#9c541b; }}
.notice {{ max-width:330px; background:#fff5ea; border:1px solid #f2c994; border-radius:14px; padding:13px 15px; color:#77451d; font-weight:700; }}
.toolbar,.card,.chart-card,.table-card {{ background:var(--card); border:1px solid var(--line); border-radius:18px; box-shadow:0 10px 30px #1c49630d; }}
.toolbar {{ display:flex; gap:14px; align-items:end; padding:16px; margin-bottom:16px; flex-wrap:wrap; }}
label {{ display:grid; gap:5px; font-weight:800; font-size:13px; }}
select {{ min-width:250px; border:1px solid #b7cdd7; border-radius:10px; background:white; color:var(--ink); padding:11px 12px; font:inherit; }}
.toolbar small {{ color:var(--muted); max-width:640px; }}
.kpis {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-bottom:16px; }}
.card {{ padding:14px; min-height:100px; }}
.card .label {{ color:var(--muted); text-transform:uppercase; font-size:11px; font-weight:800; letter-spacing:.05em; }}
.card .value {{ margin-top:8px; font-size:24px; font-weight:850; letter-spacing:-.03em; }}
.card .sub {{ color:var(--muted); font-size:12px; }}
.chart-card {{ padding:16px; }}
.chart-head {{ display:flex; align-items:start; justify-content:space-between; gap:12px; margin-bottom:4px; }}
.legend {{ display:flex; gap:14px; color:var(--muted); font-size:12px; white-space:nowrap; }}
.legend span::before {{ content:""; display:inline-block; width:22px; height:3px; margin-right:6px; vertical-align:middle; border-radius:4px; background:var(--blue); }}
.legend span:last-child::before {{ background:var(--orange); }}
svg {{ display:block; width:100%; height:auto; min-height:250px; overflow:visible; }}
.chart-note {{ display:flex; justify-content:space-between; gap:12px; color:var(--muted); font-size:12px; margin-top:2px; flex-wrap:wrap; }}
.table-card {{ margin-top:16px; padding:16px; overflow:auto; }}
table {{ border-collapse:collapse; width:100%; min-width:760px; }}
th,td {{ text-align:left; padding:10px 9px; border-bottom:1px solid #e7eef1; white-space:nowrap; }}
th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
tbody tr {{ cursor:pointer; }} tbody tr:hover, tbody tr:focus {{ background:#f0f8fb; }}
.selected {{ background:#e8f5f2; }}
.pill {{ display:inline-block; padding:3px 7px; border-radius:999px; font-size:11px; font-weight:800; background:#edf1ff; color:#425c9c; }}
.foot {{ margin-top:18px; display:grid; gap:8px; padding:15px; border-left:4px solid #17a37f; background:var(--mint); border-radius:10px; }}
code {{ color:#1f5774; }}
@media (max-width:900px) {{ .kpis {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} .hero {{ display:block; }} .notice {{ max-width:none; margin-top:14px; }} }}
@media (max-width:560px) {{ main {{ padding:18px 12px 36px; }} .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }} .card {{ min-height:88px; padding:11px; }} .card .value {{ font-size:20px; }} .toolbar {{ align-items:stretch; }} select {{ width:100%; min-width:0; }} .chart-head {{ display:block; }} .legend {{ margin-top:10px; }} }}
</style>
</head>
<body>
<main>
  <section class="hero">
    <div><span class="eyebrow">PESQUISA · REPLAY HISTÓRICO</span><h1>Santa Tereza · RNA de 2 horas</h1><p>Escolha um evento para comparar o nível observado com a saída da rede neural.</p></div>
    <div class="notice">Não é alerta, ordem de evacuação, rota ou despacho. É uma ferramenta de estudo e validação.</div>
  </section>
  <section class="toolbar">
    <label for="event-select">Evento histórico<select id="event-select"></select></label>
    <span class="tag" id="split-tag">—</span>
    <small id="event-description">Os eventos destacados são cheias históricas do catálogo; o conjunto de avaliação aparece ao lado.</small>
  </section>
  <section class="kpis" aria-live="polite">
    <div class="card"><div class="label">Pico observado</div><div class="value" id="obs-peak">—</div><div class="sub">cm</div></div>
    <div class="card"><div class="label">Pico da RNA</div><div class="value" id="rna-peak">—</div><div class="sub">cm</div></div>
    <div class="card"><div class="label">Erro do pico</div><div class="value" id="peak-error">—</div><div class="sub">diferença absoluta</div></div>
    <div class="card"><div class="label">Atraso do pico</div><div class="value" id="peak-lag">—</div><div class="sub">RNA − observado</div></div>
    <div class="card"><div class="label">MAE</div><div class="value" id="mae">—</div><div class="sub">cm, no evento</div></div>
    <div class="card"><div class="label">Amostras</div><div class="value" id="sample-count">—</div><div class="sub" id="date-range">—</div></div>
  </section>
  <section class="chart-card">
    <div class="chart-head"><div><h2 id="chart-title">Nível observado × RNA</h2><p id="chart-subtitle">—</p></div><div class="legend"><span>observado</span><span>RNA</span></div></div>
    <svg id="chart" viewBox="0 0 1000 390" role="img" aria-label="Gráfico de nível observado e nível previsto pela RNA"></svg>
    <div class="chart-note"><span id="chart-start">—</span><span>horário local preservado na origem</span><span id="chart-end">—</span></div>
  </section>
  <section class="table-card"><h2>Todos os eventos da rotação</h2><table><thead><tr><th>Evento</th><th>Período</th><th>Conjunto</th><th>Pico observado</th><th>Pico RNA</th><th>Erro</th><th>Atraso</th></tr></thead><tbody id="events-body"></tbody></table></section>
  <section class="foot"><strong>Como interpretar</strong><span>O pacote contém o replay auditável da RNA e os CSVs originais derivados. Os eventos de setembro/2023, novembro/2023 e maio/2024 são úteis para estudar a resposta histórica, mas neste modelo pertencem ao treino. O evento E12 é o teste independente da rotação.</span><span>A calibração HEC-HMS de vazão em Santa Tereza permanece bloqueada até haver vazão/curva-chave reconciliada para a estação de resposta.</span></section>
</main>
<script id="replay-data" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('replay-data').textContent);
const select=document.getElementById('event-select');
const fmt=(v,d=1)=>v==null?'—':Number(v).toLocaleString('pt-BR',{{minimumFractionDigits:d,maximumFractionDigits:d}});
const signed=(v,d=1)=>v==null?'—':(Number(v)>0?'+':'')+fmt(v,d);
const metricMap=new Map(data.metrics.map(m=>[Number(m.evento),m]));
const groups={{4:'cheia de setembro de 2023',6:'cheia de novembro de 2023',9:'cheia de maio de 2024',12:'teste independente da rotação'}};
data.metrics.forEach(m=>{{const o=document.createElement('option');o.value=m.evento;o.textContent='E'+m.evento+' · '+m.inicio.slice(0,10)+' → '+m.fim.slice(0,10);select.appendChild(o);}});
function linePoints(values,x,y,w,h,minY,maxY,key){{return values.map((r,i)=>{{const xx=x+(i/(Math.max(1,values.length-1)))*w;const yy=y+h-((Number(r[key])-minY)/(maxY-minY))*h;return [xx,yy];}});}}
function drawChart(rows){{
  const svg=document.getElementById('chart'); svg.replaceChildren(); const W=1000,H=390,x=62,y=20,w=912,h=312;
  const all=rows.flatMap(r=>[Number(r.nivel_observado_cm),Number(r.nivel_rna_cm)]); let minY=Math.min(...all),maxY=Math.max(...all); const pad=Math.max(10,(maxY-minY)*.1);minY=Math.max(0,minY-pad);maxY=maxY+pad;if(maxY===minY)maxY=minY+1;
  const mk=(tag,attrs)=>{{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}};
  for(let i=0;i<5;i++){{const yy=y+h-(i/4)*h;svg.append(mk('line',{{x1:x,x2:x+w,y1:yy,y2:yy,stroke:'#dce8ed','stroke-width':'1'}}));const t=mk('text',{{x:x-10,y:yy+4,'text-anchor':'end',fill:'#6a8291','font-size':'12'}});t.textContent=fmt(minY+(i/4)*(maxY-minY),0);svg.append(t);}}
  const a=linePoints(rows,x,y,w,h,minY,maxY,'nivel_observado_cm'),b=linePoints(rows,x,y,w,h,minY,maxY,'nivel_rna_cm');
  const poly=(pts,color)=>mk('polyline',{{points:pts.map(p=>p.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':'3.5','stroke-linecap':'round','stroke-linejoin':'round'}});
  svg.append(poly(a,'#1577c8'),poly(b,'#eb8b35'));
  [0,Math.floor(rows.length/2),rows.length-1].forEach(i=>{{const t=mk('text',{{x:x+(i/Math.max(1,rows.length-1))*w,y:y+h+28,'text-anchor':i===0?'start':i===rows.length-1?'end':'middle',fill:'#6a8291','font-size':'12'}});t.textContent=rows[i].timestamp_local.slice(0,16);svg.append(t);}});
  const title=mk('text',{{x:W/2,y:382,'text-anchor':'middle',fill:'#6a8291','font-size':'12'}});title.textContent='tempo local';svg.append(title);
}}
function render(id=Number(select.value)){{const m=metricMap.get(id),rows=data.series.filter(r=>Number(r.evento)===id);select.value=id;
document.getElementById('split-tag').textContent=m.conjunto+' · '+m.papel_avaliacao.replaceAll('_',' ');document.getElementById('event-description').textContent=groups[id]||'evento do catálogo da RNA';
document.getElementById('obs-peak').textContent=fmt(m.pico_observado_cm);document.getElementById('rna-peak').textContent=fmt(m.pico_rna_cm);document.getElementById('peak-error').textContent=fmt(m.erro_pico_abs_cm)+' cm';document.getElementById('peak-lag').textContent=signed(m.atraso_pico_horas)+' h';document.getElementById('mae').textContent=fmt(m.mae_cm)+' cm';document.getElementById('sample-count').textContent=fmt(m.n,0);document.getElementById('date-range').textContent=m.inicio.slice(0,10)+' → '+m.fim.slice(0,10);
document.getElementById('chart-title').textContent='E'+id+' · nível observado × RNA';document.getElementById('chart-subtitle').textContent='pico observado '+m.hora_pico_observado+' · pico RNA '+m.hora_pico_rna;document.getElementById('chart-start').textContent=rows[0]?.timestamp_local||'—';document.getElementById('chart-end').textContent=rows.at(-1)?.timestamp_local||'—';drawChart(rows);
document.querySelectorAll('#events-body tr').forEach(tr=>tr.classList.toggle('selected',Number(tr.dataset.id)===id));}}
const body=document.getElementById('events-body');data.metrics.forEach(m=>{{const tr=document.createElement('tr');tr.dataset.id=m.evento;tr.tabIndex=0;tr.innerHTML='<td><strong>E'+m.evento+'</strong></td><td>'+m.inicio.slice(0,10)+' → '+m.fim.slice(0,10)+'</td><td><span class="pill">'+m.conjunto+'</span></td><td>'+fmt(m.pico_observado_cm)+' cm</td><td>'+fmt(m.pico_rna_cm)+' cm</td><td>'+fmt(m.erro_pico_abs_cm)+' cm</td><td>'+signed(m.atraso_pico_horas)+' h</td>';tr.onclick=()=>render(m.evento);tr.onkeydown=e=>{{if(e.key==='Enter'||e.key===' ')render(m.evento);}};body.appendChild(tr);}});
select.onchange=()=>render(Number(select.value));render(4);
</script>
</body></html>'''


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    model = next(item for item in source["models"] if item["name"] == MODEL_NAME)
    station_audit = json.loads(STATION_AUDIT.read_text(encoding="utf-8"))
    metrics, series = event_rows(model)
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "events_metrics.csv", metrics)
    write_csv(OUT / "series_hourly.csv", series)
    (OUT / "model_snapshot.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    station = next(item for item in station_audit["ana"] if item.get("telemetry_code") == "86472600")
    manifest = {
        "schema_version": "1.0",
        "generated_at": "2026-09-03",
        "package": "santa_tereza_eventwise_replay_rna_2h",
        "status": "research_replay_not_operational",
        "municipality": "Santa Tereza, RS",
        "purpose": "Replay histórico da RNA de nível em horizonte de 2 horas, com séries observadas e previstas preservadas por evento.",
        "selected_model": {
            "name": model["name"],
            "family": model["family"],
            "horizon": model["horizon"],
            "target": model["target"],
            "source_ref": model["sourceRef"],
            "source_json": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": sha256(SOURCE),
            "aggregate_metrics": model["metricsBySet"],
        },
        "event_scope": {
            "event_count": len(metrics),
            "series_point_count": len(series),
            "highlight_events": [
                {"evento": 4, "descricao": "cheia de setembro de 2023", "observacao": "treino_replay; não é teste independente"},
                {"evento": 6, "descricao": "cheia de novembro de 2023", "observacao": "treino_replay; não é teste independente"},
                {"evento": 9, "descricao": "cheia de maio de 2024", "observacao": "treino_replay; não é teste independente"},
                {"evento": 12, "descricao": "evento de junho/julho de 2025", "observacao": "teste independente da rotação"},
            ],
        },
        "variables": {
            "nivel_observado_cm": "cota/nível no arquivo auditável, em centímetros",
            "nivel_rna_cm": "saída prevista pela RNA, em centímetros",
            "timestamp_local": "horário local preservado na série de origem",
        },
        "station_identity": {
            "code": "86472600",
            "name": station["official_identity"]["name"],
            "river": station["official_identity"]["river"],
            "municipality": station["official_identity"]["municipality"],
            "operator": station["official_identity"]["operator"],
            "responsible": station["official_identity"]["responsible"],
            "local_audit_source": str(STATION_AUDIT.relative_to(ROOT)).replace("\\", "/"),
            "local_audit_sha256": sha256(STATION_AUDIT),
            "sep_2023_telemetry_in_audit": station["telemetry"],
        },
        "hydrologic_calibration_gate": {
            "status": "blocked_for_flow_calibration",
            "reason": "A estação 86472600 tem nível e chuva telemétricos auditados em janelas específicas, mas não há vazão horária reconciliada nem curva-chave anexada ao pacote.",
            "allowed_now": ["replay de nível da RNA", "comparação de pico e atraso por timestamp", "auditoria de cobertura e identidade"],
            "not_allowed_now": ["calibração HEC-HMS de vazão em Santa Tereza", "converter cm em m3/s por fórmula inventada", "usar o replay como ordem de evacuação ou despacho"],
            "next_evidence": ["série de vazão ou curva-chave oficial da estação 86472600", "janela de chuva reconciliada por evento", "validação independente fora do treino"],
        },
        "official_links": {
            "ana_station_inventory": "https://portal1.snirh.gov.br/server/rest/services/dados_abertos/Estacao_Fluviometrica_com_Medicao_de_Descarga/MapServer/0",
            "sgb_sace": "https://www.sgb.gov.br/sace/",
            "sgb_telemetry_consistency": "https://rigeo.sgb.gov.br/bitstream/doc/25767/1/consistencia_dados_telemetria_artigo.pdf",
        },
        "files": {
            "events_metrics": "events_metrics.csv",
            "series_hourly": "series_hourly.csv",
            "model_snapshot": "model_snapshot.json",
        },
    }
    (OUT / "eventwise_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "santa_tereza_event_replay.html").write_text(replay_html(metrics, series), encoding="utf-8")
    print(json.dumps({"package": str(OUT), "events": len(metrics), "series_points": len(series), "model": MODEL_NAME}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
