(function(){
  'use strict';
  const root=document.querySelector('[data-pv-dashboard]');
  if(!root)return;
  const qs=s=>root.querySelector(s), id=s=>document.getElementById(s);
  const station=root.dataset.station||'estação';
  const weatherUrl=root.dataset.weatherFeed, basinUrl=root.dataset.basinFeed, probabilityUrl=root.dataset.probFeed, liveUrl=root.dataset.liveFeed;
  const threshold=Number(root.dataset.threshold||0);
  const br=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const pct=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const state={weather:null,basin:null,probability:null,live:null,mode:'rain',loadedAt:null,loading:false};
  const el=(sel)=>qs(sel);
  const safeNum=v=>v==null||!Number.isFinite(Number(v))?null:Number(v);
  const parseFeedDate=v=>{
    if(v==null||v==='')return new Date('');
    const s=String(v).trim().replace(' ','T');
    if(/^\d{4}-\d{2}-\d{2}$/.test(s))return new Date(`${s}T00:00:00-03:00`);
    return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)?s:`${s}-03:00`);
  };
  const mm=v=>safeNum(v)==null?'—':br.format(v)+' mm';
  const cm=v=>safeNum(v)==null?'—':br.format(v)+' cm';
  const formatTime=v=>{const raw=String(v??'').trim(),assumed=raw!==''&&!/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw);const d=parseFeedDate(v);return Number.isFinite(d.getTime())?`${d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})} BRT${assumed?' · fuso assumido':''}`:'—'};
  const ageHours=v=>{const d=parseFeedDate(v);return Number.isFinite(d.getTime())?Math.max(0,(Date.now()-d.getTime())/3600000):Infinity};
  const labelHours=h=>`+${h} h`;
  function setText(sel,text){const node=el(sel);if(node)node.textContent=text;}
  function setHtml(sel,html){const node=el(sel);if(node)node.innerHTML=html;}
  function normalizeWeather(d){
    if(!d)return null;
    const obs=d.observation||{};
    const mapHorizon=h=>{
      const pointOpenMeteo=safeNum(h.rain_point_mm??(station==='mucum'?h.target_mucum_mm:h.target_santa_tereza_mm));
      const direct=safeNum(h.rain_ecmwf_direct_mm);
      const proxyIfs=safeNum(h.rain_ifs_proxy_mm??h.basin_mean_mm);
      const proxyGefs=safeNum(h.rain_gefs_proxy_mm);
      const point=station==='mucum'?(direct??pointOpenMeteo):pointOpenMeteo;
      return {hours:Number(h.hours??h.horizon_hours),rain:point,point_openmeteo:pointOpenMeteo,ecmwf_direct:direct,ecmwf_delta:safeNum(h.rain_ecmwf_direct_minus_openmeteo_mm),basin:station==='mucum'?point:proxyIfs,proxy_ifs:proxyIfs,proxy_gefs:proxyGefs,max:safeNum(h.basin_max_mm),soil:safeNum(h.soil_moisture_model_mean_m3m3),prob:safeNum(h.flood_probability_percent??(h.flood_probability==null?null:Number(h.flood_probability)*100)),raw:h};
    };
    const horizons=Array.isArray(d.horizons)?d.horizons.map(mapHorizon).filter(h=>Number.isFinite(h.hours)).sort((a,b)=>a.hours-b.hours):[];
    if(d.forecast&&Array.isArray(d.forecast.horizons)){
      const f=d.forecast.horizons;
      horizons.splice(0,horizons.length,...f.map(mapHorizon).filter(h=>Number.isFinite(h.hours)).sort((a,b)=>a.hours-b.hours));
    }
    return {raw:d,generated:d.generated_at_utc,obs,level:safeNum(obs.level_cm),horizons,source:d.forecast_provider||d.forecast?.source||d.forecast_source||'feed meteorológico',soil:d.soil_moisture||d.soil||null,answer:d.answer_24h||null,risk:d.risk_model||d.rna||null,ecmwfDirect:d.ecmwf_direct||null};
  }
  function normalizeBasin(d){
    if(!d)return null;
    const rows=Array.isArray(d.horizons)?d.horizons.map(h=>({
      hours:Number(h.hours??h.horizon_hours),
      mean:safeNum(h.basin_mean_mm??h.rain_ifs_proxy_mm),
      max:safeNum(h.basin_max_mm),
      point:safeNum(h.rain_ecmwf_direct_mm??h.rain_point_mm),
      coverage:safeNum(h.rain_hours_available),
      raw:h
    })).filter(h=>Number.isFinite(h.hours)).sort((a,b)=>a.hours-b.hours):[];
    return {raw:d,generated:d.generated_at_utc,horizons:rows,source:d.forecast_provider||d.forecast_model||d.forecast_source||'feed espacial',kind:d.forecast_kind||'recorte espacial',aggregation:d.basin_aggregation||null};
  }
  function normalizeProbability(d){
    if(!d)return null;
    const hs=d.horizons||{};
    const entries=Array.isArray(hs)?hs.map((h,i)=>[h?.hours??h?.horizon_hours??i,h]):Object.entries(hs);
    const rows=entries.map(([key,item])=>{const h=item||{};const fraction=safeNum(h.probability??h.flood_probability);return {hours:Number(h.hours??h.horizon_hours??key),prob:safeNum(h.flood_probability_percent??(fraction==null?null:fraction*100))};}).filter(x=>Number.isFinite(x.hours)&&x.prob!=null).sort((a,b)=>a.hours-b.hours);
    return {raw:d,generated:d.generated_at_utc,rows,calibrated:d.calibrated_for_current_source===true||d.calibrated===true,source:d.forecast_source||d.source||'GEFS/NOAA',directPoint:d.direct_mucum_point===true,threshold:safeNum(d.threshold_cm),status:d.calibration_status||'não informado'};
  }
  function normalizeLive(d){
    if(!d)return null;
    const hs=d.horizontes||{};
    const rows=Object.keys(hs).filter(k=>/^(2h|4h)/.test(k)).map(k=>({key:k,label:k==='2h_versao_b'?'2 h B':k==='4h'?'4 h':'2 h',level:safeNum(hs[k].nivel_previsto_cm),now:safeNum(hs[k].nivel_rio_agora_cm),delta:safeNum(hs[k].delta_previsto_cm),status:hs[k].status||'sem status',modelo:hs[k].modelo||hs[k].modelo_nome||'RNA ao vivo'})).filter(x=>x.level!=null);
    return {raw:d,rows,generated:d.gerado_em||d.consultado_em,telemetry:d.telemetria_ultima_em};
  }
  function setFeedState(){
    const node=el('#pv-feed-state'),chips=el('#pv-feed-chips');
    const feeds=[
      {key:'weather',label:'previsão',value:state.weather,limit:30},
      {key:'probability',label:'score',value:state.probability,limit:36},
      {key:'live',label:'robô ao vivo',value:state.live,limit:.5}
    ].map(f=>{const age=f.value?ageHours(f.value.generated):Infinity;const status=!f.value||!Number.isFinite(age)?'unknown':age<=f.limit?'fresh':'stale';return {...f,age,status};});
    const overall=feeds.some(f=>f.status==='unknown')?'unknown':feeds.some(f=>f.status==='stale')?'stale':'fresh';
    if(node){node.className=`pv-feed-state ${overall}`;node.textContent=overall==='fresh'?'Feeds atualizados':overall==='stale'?'Há feed atrasado':'Há feed sem horário';node.title=feeds.map(f=>`${f.label}: ${f.status==='fresh'?(f.age<1?'há menos de 1 h':`há ${br.format(f.age)} h`):f.status==='stale'?`atrasado (${br.format(f.age)} h)`:'indisponível'}`).join(' · ');}
    if(chips)chips.innerHTML=feeds.map(f=>{const text=f.status==='fresh'?(f.age<1?'há menos de 1 h':`há ${br.format(f.age)} h`):f.status==='stale'?`atrasado · ${br.format(f.age)} h`:'indisponível';return `<span class="pv-feed-chip ${f.status}"><b>${f.label}</b><span>${text}</span></span>`;}).join('');
  }
  function rainFor(h){return state.mode==='rain'?(h.basin??h.rain):(null)}
  function renderKpis(){
    const w=state.weather, hs=w?.horizons||[];
    const h24=hs.find(h=>h.hours===24)||hs[0];
    const h72=hs.find(h=>h.hours===72)||hs.find(h=>h.hours>=72)||hs[hs.length-1];
    const now=state.live?.rows?.find(x=>x.key==='2h')||state.live?.rows?.[0];
    const four=state.live?.rows?.find(x=>x.key==='4h');
    if(state.mode==='river'){
      setHtml('#pv-kpis',[
        ['Rio agora',cm(w?.level??now?.now),w?.obs?.age_minutes!=null?`observado · ${br.format(w.obs.age_minutes)} min`:'telemetria do robô'],
        ['Previsão pontual · +2 h',cm(now?.level),now?`${now.modelo||'RNA ao vivo'} · Δ ${now.delta==null?'—':(now.delta>0?'+':'')+cm(now.delta)}`:'sem rodada'],
        ['Previsão pontual · +4 h',cm(four?.level),four?`${four.modelo||'RNA ao vivo'} · Δ ${four.delta==null?'—':(four.delta>0?'+':'')+cm(four.delta)}`:'sem rodada'],
        ['Cota oficial da pesquisa',cm(threshold),w?.level!=null&&threshold?`${cm(threshold-w.level)} abaixo · não é previsão`:'limiar não disponível']
      ].map((x,i)=>`<article class="pv-kpi"><span class="pv-kpi-label">${x[0]}</span><strong class="pv-kpi-value ${i===0?'good':''}">${x[1]}</strong><span class="pv-kpi-note">${x[2]}</span></article>`).join(''));
      return;
    }
    const h168=hs.find(h=>h.hours===168)||hs[hs.length-1];
    const latestProb=(state.probability?.rows||[]).find(x=>x.hours===168);
    const probFresh=state.probability&&ageHours(state.probability.generated)<=36;
    const probLabel=latestProb&&probFresh?`${pct.format(latestProb.prob)}%*`:'UNKNOWN/STALE';
    const probNote=latestProb&&probFresh?`score experimental · ${state.probability?.calibrated?'calibração de pesquisa':'não calibrado'} · não é chance real`:'feed antigo ou sem valor atual';
    setHtml('#pv-kpis',[
      ['Rio agora',cm(w?.level??now?.now),w?.obs?.state==='unknown_or_stale'?'leitura atrasada':'observado'],
      ['Chuva prevista · +24 h',mm(h24?.basin??h24?.rain),station==='mucum'?'ECMWF IFS no ponto':'ECMWF IFS no recorte'],
      ['Chuva prevista · +72 h',mm(h72?.basin??h72?.rain),station==='mucum'?'ponto de Muçum':'média espacial do recorte'],
      ['Score experimental · +168 h',probLabel,probNote]
    ].map((x,i)=>`<article class="pv-kpi"><span class="pv-kpi-label">${x[0]}</span><strong class="pv-kpi-value ${i===3?(probFresh?'warn':'unknown'):i===0?'good':''}">${x[1]}</strong><span class="pv-kpi-note">${x[2]}</span></article>`).join(''));
  }
  function renderBars(){
    const w=state.weather, hs=w?.horizons||[], node=el('#pv-bars');
    if(!node)return;
    if(state.mode==='river'){
      const rows=state.live?.rows||[];
      if(!rows.length){node.innerHTML='<div class="pv-empty">Feed ao vivo sem previsão curta disponível.</div>';return;}
      const vals=rows.map(x=>x.level).filter(v=>v!=null), lo=Math.min(...vals), hi=Math.max(...vals), span=Math.max(1,hi-lo);
      node.innerHTML=rows.map(x=>{const ratio=Math.max(8,((x.level-lo)/span)*100),detail=`${x.label}: ${cm(x.level)} · agora ${cm(x.now)} · Δ ${x.delta==null?'—':(x.delta>0?'+':'')+cm(x.delta)} · ${x.modelo} · ${x.status}`;return `<div class="pv-bar-col" tabindex="0" aria-label="${detail}" data-tip="${detail}"><span class="pv-bar-value">${cm(x.level)}</span><span class="pv-bar-track"><span class="pv-bar-fill" style="height:${ratio}%"></span></span><span class="pv-bar-label">${x.label}</span><span class="pv-bar-caption">${x.status}</span></div>`}).join('');
      setText('#pv-chart-title','Nível previsto pelo robô ao vivo');setText('#pv-chart-unit','cm');setText('#pv-chart-subtitle','Previsão pontual de nível; não é probabilidade de inundação.');setText('#pv-chart-note','A linha de base é o nível observado mais recente; a cota oficial da pesquisa é '+cm(threshold)+'.');setText('#pv-chart-scale',`Escala visual desta rodada: ${br.format(lo)}–${br.format(hi)} cm · valores escritos nas barras.`);
      return;
    }
    if(!hs.length){node.innerHTML='<div class="pv-empty">Feed meteorológico sem horizontes disponíveis.</div>';return;}
    const vals=hs.map(h=>rainFor(h)).filter(v=>v!=null), max=Math.max(1,...vals), min=Math.min(0,...vals);
    node.innerHTML=hs.map(h=>{const v=rainFor(h),ratio=v==null?0:Math.max(3,Math.min(100,(v/max)*100));const cls=v!=null&&v>=80?'high':v!=null&&v>=40?'warn':'';const detail=station==='mucum'?`${labelHours(h.hours)} · ponto de Muçum: ${mm(h.rain)}${h.ecmwf_direct!=null?` · ECMWF direto: ${mm(h.ecmwf_direct)}`:''}${h.point_openmeteo!=null?` · IFS via Open-Meteo: ${mm(h.point_openmeteo)}`:''}${h.ecmwf_delta!=null?` · diferença direto−Open-Meteo: ${h.ecmwf_delta>0?'+':''}${mm(h.ecmwf_delta)}`:''}${h.proxy_ifs!=null?` · proxy IFS/célula: ${mm(h.proxy_ifs)}`:''}${h.proxy_gefs!=null?` · proxy GEFS/célula: ${mm(h.proxy_gefs)}`:''}`:`${labelHours(h.hours)} · recorte: ${mm(v)}${h.rain!=null&&h.basin!=null&&h.rain!==h.basin?` · ponto da estação: ${mm(h.rain)}`:''}`;return `<div class="pv-bar-col" tabindex="0" aria-label="${detail}" data-tip="${detail}"><span class="pv-bar-value">${mm(v)}</span><span class="pv-bar-track"><span class="pv-bar-fill ${cls}" style="height:${ratio}%"></span></span><span class="pv-bar-label">${labelHours(h.hours)}</span><span class="pv-bar-caption">${v==null?'sem valor':station==='mucum'?'ponto':'recorte'}</span></div>`}).join('');
    setText('#pv-chart-scale',`Escala visual da rodada: ${br.format(min)}–${br.format(max)} mm · detalhes com fonte e cobertura abaixo.`);
    if(station==='mucum'){
      const directReady=w?.ecmwfDirect?.status==='available'&&hs.some(h=>h.ecmwf_direct!=null);
      setText('#pv-chart-title',directReady?'Chuva prevista no ponto de Muçum · ECMWF direto':'Chuva prevista no ponto de Muçum');setText('#pv-chart-unit','mm no ponto');setText('#pv-chart-subtitle',directReady?'ECMWF Open Data direto é a barra principal; IFS via Open-Meteo e proxies ficam no detalhe.':'Acumulado previsto na estação; os proxies GEFS/IFS da célula aparecem apenas no detalhe.');setText('#pv-chart-note',directReady?'Cada barra usa o ponto mais próximo da grade ECMWF IFS Open Data. A saída via Open-Meteo e os proxies de célula aparecem no detalhe para comparação.':'Cada barra mostra a previsão pontual para Muçum. O proxy de célula/bacia é uma referência espacial e não deve ser lido como chuva prevista na estação.');
    }else{
      const directLabel=(w?.source||'').toLowerCase().includes('ecmwf')?' · ECMWF IFS direto':'';
      setText('#pv-chart-title','Chuva média prevista na bacia'+directLabel);setText('#pv-chart-unit','mm médios');setText('#pv-chart-subtitle',(directLabel?'ECMWF Open Data / IFS · ':'')+'Média espacial estimada no recorte da bacia, acumulada até cada horizonte.');setText('#pv-chart-note','Cada barra é a média espacial prevista em milímetros — não é o volume total de água da bacia nem probabilidade de inundação. A chuva no ponto da estação aparece no detalhe; a fonte está indicada no título.');
    }
  }
  function basinRow(rows,hours){
    if(!rows.length)return null;
    return rows.find(h=>h.hours===hours)||rows.find(h=>h.hours>=hours)||rows[rows.length-1];
  }
  function renderBasinContext(){
    const node=el('#pv-basin-context');
    if(!node)return;
    const basin=state.basin, rows=basin?.horizons||[], pointRows=state.weather?.horizons||[];
    if(!rows.length){
      setText('#pv-basin-state','Sem recorte espacial');
      setHtml('#pv-basin-kpis','<article class="pv-basin-empty">O feed espacial da bacia ainda não está disponível nesta rodada.</article>');
      setHtml('#pv-basin-horizons','<div class="pv-empty">Sem chuva espacial publicada.</div>');
      setText('#pv-basin-source','Aguardando uma rodada com média e máximo do recorte IFS.');
      return;
    }
    const reference=basinRow(rows,72)||rows[0];
    const point=basinRow(pointRows,reference.hours)||pointRows[0]||{};
    const mean=reference.mean, max=reference.max, pointValue=station==='mucum'?(point.ecmwf_direct??point.rain):point.rain;
    setText('#pv-basin-state',`Recorte publicado · ${formatTime(basin.generated)}`);
    const aggregation=basin.aggregation||{};
    const sharedMuçum=station==='mucum'&&String(basin.raw?.station_code||'')!=='86510000';
    setText('#pv-basin-subtitle',sharedMuçum?'Muçum compartilha a célula IFS do recorte montante publicado. A leitura separa a chuva espacial da chuva prevista diretamente no ponto.':'O ponto da estação é apenas uma célula. Aqui aparece o recorte montante usado para acompanhar a água que pode chegar à estação.');
    setHtml('#pv-basin-kpis',[
      `<article><span>Cabeceiras / montante</span><strong>${mm(mean)}</strong><small>média espacial IFS · +${reference.hours} h</small></article>`,
      `<article><span>Maior célula do recorte</span><strong>${mm(max)}</strong><small>máximo espacial IFS · +${reference.hours} h</small></article>`,
      `<article><span>${station==='mucum'?'Ponto de Muçum':'Ponto da estação'}</span><strong>${mm(pointValue)}</strong><small>IFS direto · +${reference.hours} h</small></article>`
    ].join(''));
    const maxScale=Math.max(1,...rows.flatMap(h=>[h.mean,h.max].filter(v=>v!=null)));
    setHtml('#pv-basin-horizons',rows.map(h=>{
      const meanWidth=h.mean==null?0:Math.max(3,Math.min(100,h.mean/maxScale*100));
      const maxWidth=h.max==null?0:Math.max(3,Math.min(100,h.max/maxScale*100));
      const p=basinRow(pointRows,h.hours)||{};
      const pv=station==='mucum'?(p.ecmwf_direct??p.rain):p.rain;
      return `<article class="pv-basin-horizon"><div class="pv-basin-horizon-head"><span>+${h.hours} h</span><b>${mm(h.mean)}</b></div><div class="pv-basin-meter"><span>média cabeceira</span><i><em style="width:${meanWidth.toFixed(1)}%"></em></i><strong>${mm(h.mean)}</strong></div><div class="pv-basin-meter max"><span>máximo recorte</span><i><em style="width:${maxWidth.toFixed(1)}%"></em></i><strong>${mm(h.max)}</strong></div><div class="pv-basin-point">ponto ${mm(pv)}</div></article>`;
    }).join(''));
    const coverage=reference.coverage==null?'cobertura não informada':`${reference.coverage}/${reference.hours} h disponíveis`;
    setText('#pv-basin-note',`A média e o máximo são proxies espaciais em milímetros para o recorte montante. No horizonte +${reference.hours} h: média ${mm(mean)}, máximo ${mm(max)} e ponto ${mm(pointValue)}. Isso ajuda a ver onde a chuva se concentra, mas não é volume total da bacia nem probabilidade de inundação.`);
    const cellNote=aggregation.basin_grid_cells_used==null?'':` ${aggregation.basin_grid_cells_used} células IFS representativas foram usadas${aggregation.target_station_excluded?' sem contar a estação-alvo na média.':''}`;
    setText('#pv-basin-source',`Fonte: ${basin.source} · tipo: ${basin.kind} · emitido: ${formatTime(basin.generated)} · ${coverage}.${cellNote} A geometria hidrológica e o tempo de propagação ainda não estão validados como máscara oficial de cabeceiras; por isso este é um proxy espacial de pesquisa.`);
  }
  function renderSide(){
    const w=state.weather, hs=w?.horizons||[], h24=hs.find(h=>h.hours===24)||hs[0], h168=hs.find(h=>h.hours===168)||hs[hs.length-1], now=state.live?.rows?.[0], prob=(state.probability?.rows||[]).find(x=>x.hours===168), fresh=state.probability&&ageHours(state.probability.generated)<=36;
    const rain=h168?.basin??h168?.rain, soil=h168?.soil, signals=[];
    if(station==='mucum'){
      const near=h24?.basin??h24?.rain;
      const nearLabel=near==null?'—':mm(near);
      const longLabel=rain==null?'—':mm(rain);
      const severity=(near!=null&&near>=40)||(rain!=null&&rain>=100)?'warn':'good';
      signals.push(['Chuva no ponto de Muçum',`+24 h: ${nearLabel} · +168 h: ${longLabel}`,severity]);
    }else if(rain==null)signals.push(['Chuva prevista','sem horizonte disponível','bad']);
    else if(rain>=100)signals.push(['Chuva prevista','volume elevado na janela longa','warn']);
    else if(rain>=40)signals.push(['Chuva prevista','volume moderado a alto','warn']);
    else signals.push(['Chuva prevista','volume baixo no feed atual','good']);
    if(w?.level!=null&&threshold){const gap=threshold-w.level;signals.push(['Margem até a cota de pesquisa',`${cm(gap)} abaixo de ${cm(threshold)}`,'good']);}
    if(soil!=null)signals.push(['Solo / umidade','proxy modelado: '+br.format(soil)+' m³/m³','warn']);
    else if(w?.soil?.message)signals.push(['Solo / umidade','sem sensor local; proxy indisponível','warn']);
    if(fresh&&prob?.prob!=null)signals.push(['Score experimental · +168 h',`${pct.format(prob.prob)}%* · não representa chance real`,'warn']);
    else signals.push(['Probabilidade atual','sem valor utilizável: rodada antiga ou não calibrada','bad']);
    if(now?.level!=null)signals.push(['Robô ao vivo',`+${now.label.replace(/\D/g,'')} previsto: ${cm(now.level)}`,'good']);
    setHtml('#pv-signals',signals.map(s=>`<div class="pv-signal"><span class="pv-signal-dot ${s[2]}" aria-hidden="true"></span><div><strong>${s[0]}</strong><span>${s[1]}</span></div></div>`).join(''));
  }
  function renderDetailTable(){
    const table=el('#pv-detail-table');if(!table)return;
    if(state.mode==='river'){
      const rows=state.live?.rows||[];
      table.innerHTML=`<thead><tr><th>Horizonte</th><th>Nível previsto (cm)</th><th>Agora (cm)</th><th>Variação (cm)</th><th>Modelo/estado</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${x.label}</td><td>${cm(x.level)}</td><td>${cm(x.now)}</td><td>${x.delta==null?'—':(x.delta>0?'+':'')+cm(x.delta)}</td><td>${x.modelo||'RNA ao vivo'} · ${x.status}</td></tr>`).join('')||'<tr><td colspan="5">Feed ao vivo indisponível.</td></tr>'}</tbody>`;
      return;
    }
    const rows=state.weather?.horizons||[];
    table.innerHTML=`<thead><tr><th>Horizonte</th><th>${station==='mucum'?'IFS no ponto':'Chuva no recorte'} (mm)</th><th>ECMWF direto (mm)</th><th>Proxy GEFS (mm)</th><th>Cobertura</th></tr></thead><tbody>${rows.map(h=>`<tr><td>${labelHours(h.hours)}</td><td>${mm(h.rain)}</td><td>${mm(h.ecmwf_direct)}</td><td>${mm(h.proxy_gefs)}</td><td>${h.raw?.rain_hours_available==null?'—':`${h.raw.rain_hours_available}/${h.hours} h`}</td></tr>`).join('')||'<tr><td colspan="5">Feed meteorológico indisponível.</td></tr>'}</tbody>`;
  }
  function renderSummary(){
    const w=state.weather, hs=w?.horizons||[], h24=hs.find(h=>h.hours===24)||hs[0], h72=hs.find(h=>h.hours===72)||hs[hs.length-1], h168=hs.find(h=>h.hours===168)||hs[hs.length-1], rain=h168?.basin??h168?.rain, fresh=state.probability&&ageHours(state.probability.generated)<=36;
    let headline='Sem dados atuais suficientes para sintetizar a janela.';
    if(station==='mucum'&&h24?.rain!=null){
      if(h24.rain<1&&rain!=null&&rain>=40)headline=`No ponto de Muçum, a previsão é de ${mm(h24.rain)} em 24 h; a chuva aparece apenas na janela longa (+168 h: ${mm(rain)}).`;
      else if(h24.rain<1)headline=`No ponto de Muçum, a previsão é de ${mm(h24.rain)} em 24 h; o robô continua acompanhando as próximas rodadas.`;
      else if(rain!=null&&rain>=100)headline=`Há chuva prevista no ponto de Muçum já em 24 h; a janela longa chega a ${mm(rain)}.`;
      else headline=`Há ${mm(h24.rain)} previstos no ponto de Muçum em 24 h; acompanhe a evolução do rio e a próxima rodada.`;
    }else if(rain!=null&&rain>=100)headline='A janela longa mostra chuva volumosa; a atenção aumenta entre 72 e 168 horas.';
    else if(rain!=null&&rain>=40)headline='Há chuva prevista na janela; acompanhe a evolução do rio e a próxima rodada.';
    else if(rain!=null)headline='A chuva prevista está baixa no recorte atual; o robô continua acompanhando.';
    if(!fresh)headline+=' A probabilidade experimental está antiga e não deve ser lida como previsão atual.';
    setText('#pv-summary',headline);
    setText('#pv-updated',`Fonte meteorológica: ${w?.source||'feed meteorológico'} · feed: ${formatTime(w?.generated)} · robô ao vivo: ${formatTime(state.live?.generated)}`);
  }
  function render(){setFeedState();renderKpis();renderBars();renderBasinContext();renderSide();renderDetailTable();renderSummary();}
  async function load(){
    if(state.loading)return;state.loading=true;const button=el('#pv-refresh');if(button){button.setAttribute('aria-busy','true');button.textContent='Atualizando…'}
    const get=url=>url?fetch(url+(url.includes('?')?'&':'?')+'cb='+Date.now(),{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null):Promise.resolve(null);
    const [weather,basin,probability,live]=await Promise.all([get(weatherUrl),get(basinUrl||weatherUrl),get(probabilityUrl),get(liveUrl)]);
    state.weather=normalizeWeather(weather);state.basin=normalizeBasin(basin||((station==='santa_tereza')?weather:null));state.probability=normalizeProbability(probability);state.live=normalizeLive(live);state.loadedAt=new Date();render();state.loading=false;if(button){button.removeAttribute('aria-busy');button.textContent='Atualizar dados'}
  }
  document.addEventListener('click',e=>{const mode=e.target.closest('[data-pv-mode]');if(mode&&root.contains(mode)){state.mode=mode.dataset.pvMode;root.classList.toggle('pv-mode-river',state.mode==='river');root.querySelectorAll('[data-pv-mode]').forEach(b=>{const active=b===mode;b.classList.toggle('active',active);b.setAttribute('aria-selected',active?'true':'false');b.setAttribute('aria-pressed',active?'true':'false');});render();}});
  const refresh=el('#pv-refresh');if(refresh)refresh.addEventListener('click',load);
  const tip=document.createElement('div');tip.className='pv-tooltip';document.body.appendChild(tip);
  root.addEventListener('pointerover',e=>{const bar=e.target.closest('.pv-bar-col');if(!bar||!bar.dataset.tip)return;tip.textContent=bar.dataset.tip;tip.classList.add('visible');});
  root.addEventListener('pointermove',e=>{if(tip.classList.contains('visible')){tip.style.left=Math.min(window.innerWidth-250,e.clientX+12)+'px';tip.style.top=Math.min(window.innerHeight-70,e.clientY+12)+'px';}});
  root.addEventListener('pointerout',e=>{if(e.target.closest('.pv-bar-col'))tip.classList.remove('visible');});
  load();setInterval(load,300000);
})();
