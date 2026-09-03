"""Build the standalone interactive HEC-HMS replay viewer for Muçum.

The generated HTML embeds the audited event series so it works from a local
file and from GitHub Pages without a runtime fetch or a third-party library.
HEC-HMS time values are minutes from 1899-12-31 and are preserved as local
clock labels for this research replay.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "assets" / "data" / "mucum_eventwise_replay_calibrated"
EVENTS = ("E24", "E27", "E28")
HEC_EPOCH = datetime(1899, 12, 31)


def number(value: str) -> float:
    return float(value)


def timestamp_label(value: str) -> str:
    dt = HEC_EPOCH + timedelta(minutes=float(value))
    return dt.strftime("%Y-%m-%dT%H:%M:00")


def read_event(event_id: str, manifest_event: dict[str, object]) -> dict[str, object]:
    event_dir = PACKAGE / f"event_{event_id}"
    with (event_dir / "metrics.csv").open(encoding="utf-8", newline="") as handle:
        metrics = next(csv.DictReader(handle))
    with (event_dir / "series.csv").open(encoding="utf-8", newline="") as handle:
        series = [
            [
                timestamp_label(row["time_value"]),
                number(row["observed_m3s"]),
                number(row["simulated_m3s"]),
            ]
            for row in csv.DictReader(handle)
        ]
    return {
        "id": event_id,
        "period": manifest_event.get("period", ""),
        "metrics": {
            key: number(metrics[key])
            for key in (
                "pairs",
                "mae_m3s",
                "rmse_m3s",
                "nse",
                "observed_peak_m3s",
                "simulated_peak_m3s",
                "peak_lag_hours",
                "peak_relative_error",
            )
        },
        "series": series,
    }


def load_data() -> dict[str, object]:
    manifest = json.loads((PACKAGE / "eventwise_manifest.json").read_text(encoding="utf-8"))
    manifest_events = {item["id"]: item for item in manifest["events"]}
    events = {event_id: read_event(event_id, manifest_events[event_id]) for event_id in EVENTS}
    return {
        "events": events,
        "tradeoffs": "E24_timing_peak_tradeoffs.csv",
        "source": "assets/data/mucum_eventwise_replay_calibrated",
        "station": "86510000",
        "area_km2": 16000,
    }


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muçum · visualizador HEC-HMS</title>
<style>
:root{--ink:#102f3a;--muted:#5f7480;--line:#d8e6e8;--panel:#fff;--bg:#eef7f7;--blue:#0879c9;--orange:#f07828;--teal:#087d77;--amber:#ad6911;--shadow:0 16px 34px rgba(17,64,78,.09)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#fff5e9 0,transparent 32%),linear-gradient(145deg,#edf8f7,#f8fbff 62%,#fffaf2);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}main{max-width:1180px;margin:auto;padding:22px 18px 48px}.shell{background:var(--panel);border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow);padding:24px}.eyebrow{color:var(--teal);font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(27px,5vw,45px);line-height:1.02;letter-spacing:-.045em;margin:7px 0 10px}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:0 0 6px}.muted{color:var(--muted)}.notice{margin-top:16px;padding:12px 14px;border-left:4px solid var(--amber);background:#fff7e7;color:#70480d;border-radius:10px}.toolbar{display:flex;gap:14px;align-items:end;flex-wrap:wrap;margin-top:22px;padding:16px;border:1px solid var(--line);border-radius:16px;background:#f8fcfc}.field{display:flex;flex-direction:column;gap:6px;min-width:210px}.field label,.check-label{font-weight:800;font-size:12px}.field select{border:1px solid #a9cbd0;border-radius:10px;background:#fff;padding:10px 12px;color:var(--ink);font-weight:800;font-size:15px}.checks{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding-bottom:9px}.check-label{display:flex;gap:7px;align-items:center;color:var(--ink)}input[type=checkbox]{accent-color:var(--blue);width:17px;height:17px}.button{border:1px solid #a9cbd0;border-radius:10px;padding:10px 13px;background:#fff;color:var(--blue);font-weight:900;cursor:pointer}.button:hover,.button:focus-visible{background:#edf7ff;outline:3px solid #bfe2f5}.event-meta{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:18px 2px 10px;flex-wrap:wrap}.event-meta strong{font-size:21px}.pill{display:inline-flex;align-items:center;border-radius:999px;background:#e9f5f3;color:var(--teal);padding:5px 10px;font-size:12px;font-weight:900}.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.kpi{border:1px solid var(--line);border-radius:14px;padding:13px 12px;background:linear-gradient(145deg,#fff,#f6fbfb);min-width:0}.kpi .label{font-size:10px;font-weight:900;text-transform:uppercase;color:var(--muted);letter-spacing:.04em}.kpi .value{font-size:clamp(19px,2.5vw,27px);font-weight:950;margin-top:4px;white-space:nowrap}.kpi .unit{font-size:11px;color:var(--muted)}.chart-panel{margin-top:14px;border:1px solid var(--line);border-radius:18px;background:#fff;padding:16px 16px 11px}.chart-head{display:flex;justify-content:space-between;gap:12px;align-items:start;flex-wrap:wrap}.legend{display:flex;gap:13px;font-size:12px;color:var(--muted);font-weight:800}.legend span{display:inline-flex;gap:6px;align-items:center}.dot{display:inline-block;width:22px;height:4px;border-radius:5px}.observed{background:var(--blue)}.simulated{background:var(--orange)}.chart-wrap{position:relative;height:440px;margin-top:4px}.chart-wrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair}.tip{position:absolute;display:none;pointer-events:none;z-index:2;min-width:190px;background:#12343e;color:#fff;border-radius:10px;padding:9px 11px;box-shadow:0 10px 22px #12343e35;font-size:12px}.tip strong{display:block;color:#fff5bc;margin-bottom:3px}.chart-foot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:11px}.below{display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-top:14px}.info{border:1px solid var(--line);border-radius:16px;padding:16px;background:#fbfefe}.info p{margin:4px 0 0;color:var(--muted);font-size:13px}.info a{color:var(--blue);font-weight:900}.metric-line{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #e7f0f0;padding:7px 0;font-size:13px}.metric-line:last-child{border-bottom:0}.metric-line b{font-weight:900}.small{font-size:12px;color:var(--muted)}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}@media(max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}.below{grid-template-columns:1fr}}@media(max-width:560px){main{padding:10px 8px 28px}.shell{padding:16px;border-radius:18px}.toolbar{align-items:stretch}.field{min-width:100%;}.checks{padding:0}.chart-wrap{height:330px}.kpis{grid-template-columns:repeat(2,1fr)}.kpi .value{font-size:21px}.chart-panel{padding:12px 8px 9px}.legend{gap:8px}.tip{min-width:160px}}
</style></head>
<body><main><section class="shell">
<div class="eyebrow">HEC-HMS · replay histórico · Muçum</div>
<h1>Veja o que o modelo simulou</h1>
<p class="muted">Vazão observada e vazão simulada pelo HEC-HMS no posto de resposta <strong>86510000</strong>. Escolha um evento e explore a série — passe o dedo ou o mouse no gráfico; arraste para ampliar.</p>
<div class="notice"><strong>Pesquisa, não operação.</strong> Este replay não é alerta, previsão ao vivo, ordem de evacuação, rota ou despacho.</div>
<div class="toolbar"><div class="field"><label for="eventSelect">Evento histórico</label><select id="eventSelect"></select></div><div class="checks"><label class="check-label"><input id="showObserved" type="checkbox" checked> observado</label><label class="check-label"><input id="showSimulated" type="checkbox" checked> HEC-HMS</label></div><button class="button" id="resetZoom" type="button">Redefinir zoom</button></div>
<div class="event-meta"><div><strong id="eventTitle">E24</strong><div class="small" id="eventPeriod"></div></div><span class="pill">série auditada · horas pareadas</span></div>
<div class="kpis" aria-label="Métricas do evento"><div class="kpi"><div class="label">Pico observado</div><div class="value" id="obsPeak">—</div><div class="unit">m³/s</div></div><div class="kpi"><div class="label">Pico HEC-HMS</div><div class="value" id="simPeak">—</div><div class="unit">m³/s</div></div><div class="kpi"><div class="label">Erro do pico</div><div class="value" id="peakError">—</div><div class="unit">diferença relativa</div></div><div class="kpi"><div class="label">Atraso do pico</div><div class="value" id="peakLag">—</div><div class="unit">HEC-HMS − observado</div></div><div class="kpi"><div class="label">NSE</div><div class="value" id="nse">—</div><div class="unit">ajuste da série</div></div><div class="kpi"><div class="label">Amostras</div><div class="value" id="pairs">—</div><div class="unit">horas pareadas</div></div></div>
<section class="chart-panel" aria-labelledby="chartTitle"><div class="chart-head"><div><h2 id="chartTitle">E24 · observado × HEC-HMS</h2><div class="small" id="peakDates"></div></div><div class="legend"><span><i class="dot observed"></i>observado</span><span><i class="dot simulated"></i>HEC-HMS</span></div></div><div class="chart-wrap"><canvas id="chart" aria-label="Gráfico de vazão observada e simulada pelo HEC-HMS"></canvas><div class="tip" id="tip"></div></div><div class="chart-foot"><span id="rangeText"></span><span>Arraste horizontalmente para ampliar · duplo clique para voltar</span></div><div class="sr-only" id="srSummary" aria-live="polite"></div></section>
<div class="below"><section class="info"><h2>Leitura rápida</h2><div class="metric-line"><span>O que comparar</span><b>forma, pico e horário</b></div><div class="metric-line"><span>Posto de resposta</span><b>86510000 · Muçum</b></div><div class="metric-line"><span>Área usada no modelo</span><b>16.000 km²</b></div><div class="metric-line"><span>Fonte da chuva</span><b>ANA 86472000</b></div></section><section class="info"><h2>Arquivos do HEC-HMS</h2><p><a id="metricsLink" href="event_E24/metrics.csv">Métricas do evento</a></p><p><a id="seriesLink" href="event_E24/series.csv">Série observada × simulada</a></p><p><a href="eventwise_manifest.json">Manifesto auditável</a> · <a href="E24_timing_peak_tradeoffs.csv">comparação E24</a></p><p style="margin-top:10px">O modelo é um replay histórico de pesquisa; lacunas não foram preenchidas e timestamps não foram deslocados artificialmente.</p></section></div>
</section></main>
<script>
const DATA = __DATA__;
const state={event:"E24",start:0,end:0,dragStart:null,dragCurrent:null,hover:null};
const $=id=>document.getElementById(id), canvas=$("chart"), ctx=canvas.getContext("2d"), tip=$("tip");
const fmt0=new Intl.NumberFormat("pt-BR",{maximumFractionDigits:0}), fmt1=new Intl.NumberFormat("pt-BR",{minimumFractionDigits:1,maximumFractionDigits:1});
const fmtDate=new Intl.DateTimeFormat("pt-BR",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
function current(){return DATA.events[state.event]}
function val(v,d=0){return Number.isFinite(Number(v))?Number(v):d}
function metricText(){const m=current().metrics;return `Pico observado ${fmt1.format(m.observed_peak_m3s)} m³/s; HEC-HMS ${fmt1.format(m.simulated_peak_m3s)} m³/s; erro ${fmt1.format(m.peak_relative_error*100)}%; atraso ${m.peak_lag_hours>0?"+":""}${fmt1.format(m.peak_lag_hours)} h; NSE ${fmt1.format(m.nse)}.`}
function setEvent(){state.event=$("eventSelect").value;state.start=0;state.end=current().series.length-1;render();}
function populate(){for(const id of Object.keys(DATA.events)){const o=document.createElement("option");o.value=id;o.textContent=`${id} · ${DATA.events[id].period.split(" to ")[0]||"evento"}`;$("eventSelect").append(o)}$("eventSelect").value=state.event;$("eventSelect").addEventListener("change",setEvent);$("showObserved").addEventListener("change",draw);$("showSimulated").addEventListener("change",draw);$("resetZoom").addEventListener("click",()=>{state.start=0;state.end=current().series.length-1;draw()});state.end=current().series.length-1}
function render(){const e=current(),m=e.metrics;$('eventTitle').textContent=e.id+' · '+(e.id==='E24'?'novembro de 2023':e.id==='E27'?'maio de 2024':'junho de 2024');$('eventPeriod').textContent=e.period;$('chartTitle').textContent=`${e.id} · observado × HEC-HMS`;$('obsPeak').textContent=fmt1.format(m.observed_peak_m3s);$('simPeak').textContent=fmt1.format(m.simulated_peak_m3s);$('peakError').textContent=fmt1.format(m.peak_relative_error*100)+'%';$('peakLag').textContent=(m.peak_lag_hours>0?'+':'')+fmt1.format(m.peak_lag_hours)+' h';$('nse').textContent=fmt1.format(m.nse);$('pairs').textContent=fmt0.format(m.pairs);$('metricsLink').href=`event_${e.id}/metrics.csv`;$('seriesLink').href=`event_${e.id}/series.csv`;$('peakDates').textContent=`Pico observado e HEC-HMS: ${peakDate(e,1)} · ${peakDate(e,2)}`;$('srSummary').textContent=metricText();draw()}
function peakDate(e,col){let i=0;for(let j=1;j<e.series.length;j++)if(e.series[j][col]>e.series[i][col])i=j;return fmtDate.format(new Date(e.series[i][0]))}
function bounds(){const s=current().series.slice(state.start,state.end+1);let ys=[];if($("showObserved").checked)ys=ys.concat(s.map(x=>x[1]));if($("showSimulated").checked)ys=ys.concat(s.map(x=>x[2]));if(!ys.length)ys=[0,1];let lo=Math.min(0,...ys),hi=Math.max(...ys);return {lo,hi:hi+(hi-lo)*.08||1}}
function resize(){const r=canvas.getBoundingClientRect(),d=window.devicePixelRatio||1,w=Math.max(1,Math.round(r.width*d)),h=Math.max(1,Math.round(r.height*d));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}ctx.setTransform(d,0,0,d,0,0);draw()}
function draw(){const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;ctx.clearRect(0,0,w,h);const pad={l:58,r:14,t:20,b:40},pw=w-pad.l-pad.r,ph=h-pad.t-pad.b,e=current(),series=e.series.slice(state.start,state.end+1),b=bounds();const x=i=>pad.l+(i/(Math.max(1,series.length-1)))*pw,y=v=>pad.t+(b.hi-v)/(b.hi-b.lo)*ph;ctx.font="11px system-ui";ctx.strokeStyle="#dbe9eb";ctx.fillStyle="#607681";ctx.lineWidth=1;for(let g=0;g<=4;g++){const yy=pad.t+ph*g/4;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillText(fmt0.format(b.hi-(b.hi-b.lo)*g/4),8,yy+4)}const ticks=Math.min(6,Math.max(2,Math.floor(pw/125)));for(let k=0;k<=ticks;k++){const i=Math.round((series.length-1)*k/ticks),xx=x(i);ctx.strokeStyle="#e8f0f1";ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,pad.t+ph);ctx.stroke();ctx.fillStyle="#607681";ctx.fillText(fmtDate.format(new Date(series[i][0])),Math.max(pad.l,xx-34),h-14)}function line(col,index){ctx.beginPath();series.forEach((p,i)=>{const xx=x(i),yy=y(p[index]);if(i===0)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)});ctx.strokeStyle=col;ctx.lineWidth=2.5;ctx.lineJoin="round";ctx.lineCap="round";ctx.stroke()}if($("showObserved").checked)line("#0879c9",1);if($("showSimulated").checked)line("#f07828",2);if(state.dragStart!==null&&state.dragCurrent!==null){const a=Math.min(state.dragStart,state.dragCurrent),z=Math.max(state.dragStart,state.dragCurrent);ctx.fillStyle="#0879c922";ctx.fillRect(a,pad.t,z-a,ph);ctx.strokeStyle="#0879c9";ctx.strokeRect(a,pad.t,z-a,ph)}if(state.hover!==null&&series[state.hover]){const p=series[state.hover],xx=x(state.hover),yy1=y(p[1]),yy2=y(p[2]);ctx.strokeStyle="#153d4880";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,pad.t+ph);ctx.stroke();ctx.setLineDash([]);if($("showObserved").checked){ctx.fillStyle="#0879c9";ctx.beginPath();ctx.arc(xx,yy1,4,0,Math.PI*2);ctx.fill()}if($("showSimulated").checked){ctx.fillStyle="#f07828";ctx.beginPath();ctx.arc(xx,yy2,4,0,Math.PI*2);ctx.fill()}showTip(p,xx,yy1,yy2,w,h)}else tip.style.display="none";$('rangeText').textContent=`${fmtDate.format(new Date(series[0][0]))} → ${fmtDate.format(new Date(series[series.length-1][0]))} · ${series.length} horas exibidas`}
function showTip(p,xx,yy1,yy2,w,h){const left=Math.min(Math.max(8,xx+12),w-205),top=Math.min(Math.max(8,Math.min(yy1,yy2)-64),h-94);tip.style.left=left+"px";tip.style.top=top+"px";tip.innerHTML=`<strong>${fmtDate.format(new Date(p[0]))}</strong><div style="color:#9ed8ff">observado: ${fmt1.format(p[1])} m³/s</div><div style="color:#ffc297">HEC-HMS: ${fmt1.format(p[2])} m³/s</div><div>diferença: ${fmt1.format(p[2]-p[1])} m³/s</div>`;tip.style.display="block"}
function indexAt(clientX){const r=canvas.getBoundingClientRect(),w=canvas.clientWidth,padL=58,padR=14,px=Math.max(padL,Math.min(w-padR,clientX-r.left));const n=state.end-state.start+1;return Math.round((px-padL)/(w-padL-padR)*Math.max(0,n-1))}
canvas.addEventListener("pointermove",ev=>{const i=indexAt(ev.clientX);if(state.dragStart!==null){state.dragCurrent=ev.clientX-canvas.getBoundingClientRect().left;draw()}else{state.hover=i;draw()}});canvas.addEventListener("pointerleave",()=>{if(state.dragStart===null){state.hover=null;draw()}});canvas.addEventListener("pointerdown",ev=>{state.dragStart=ev.clientX-canvas.getBoundingClientRect().left;state.dragCurrent=state.dragStart;canvas.setPointerCapture(ev.pointerId)});canvas.addEventListener("pointerup",ev=>{if(state.dragStart===null)return;const r=canvas.getBoundingClientRect(),a=Math.min(state.dragStart,state.dragCurrent),z=Math.max(state.dragStart,state.dragCurrent),w=canvas.clientWidth,padL=58,padR=14;if(Math.abs(z-a)>18){const n=current().series.length,oldN=state.end-state.start+1;const ia=Math.round((a-padL)/(w-padL-padR)*Math.max(0,oldN-1)),ib=Math.round((z-padL)/(w-padL-padR)*Math.max(0,oldN-1));state.start=Math.max(0,state.start+Math.min(ia,ib));state.end=Math.min(n-1,state.start+Math.max(ia,ib))}state.dragStart=null;state.dragCurrent=null;draw();try{canvas.releasePointerCapture(ev.pointerId)}catch{}});canvas.addEventListener("dblclick",()=>{$("resetZoom").click()});window.addEventListener("resize",resize);populate();render();resize();
</script></body></html>'''


def main() -> None:
    payload = json.dumps(load_data(), ensure_ascii=False, separators=(",", ":"))
    output = PACKAGE / "index.html"
    output.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    print(f"wrote {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
