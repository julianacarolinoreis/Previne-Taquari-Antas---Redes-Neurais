(function(){
  'use strict';
  const root=document.querySelector('[data-pv-dashboard]');
  if(!root)return;
  const qs=s=>root.querySelector(s), id=s=>document.getElementById(s);
  const station=root.dataset.station||'estação';
  const weatherUrl=root.dataset.weatherFeed, probabilityUrl=root.dataset.probFeed, liveUrl=root.dataset.liveFeed;
  const threshold=Number(root.dataset.threshold||0);
  const br=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const pct=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const state={weather:null,probability:null,live:null,mode:'rain',loadedAt:null,loading:false};
  const el=(sel)=>qs(sel);
  const safeNum=v=>v==null||!Number.isFinite(Number(v))?null:Number(v);
  const mm=v=>safeNum(v)==null?'—':br.format(v)+' mm';
  const cm=v=>safeNum(v)==null?'—':br.format(v)+' cm';
  const formatTime=v=>{const d=new Date(v||'');return Number.isFinite(d.getTime())?d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—'};
  const ageHours=v=>{const d=new Date(v||'');return Number.isFinite(d.getTime())?Math.max(0,(Date.now()-d.getTime())/3600000):Infinity};
  const labelHours=h=>`+${h} h`;
  function setText(sel,text){const node=el(sel);if(node)node.textContent=text;}
  function setHtml(sel,html){const node=el(sel);if(node)node.innerHTML=html;}
  function normalizeWeather(d){
    if(!d)return null;
    const obs=d.observation||{};
    const mapHorizon=h=>{
      const point=safeNum(h.rain_point_mm??h.target_santa_tereza_mm);
      const proxyIfs=safeNum(h.rain_ifs_proxy_mm??h.basin_mean_mm);
      const proxyGefs=safeNum(h.rain_gefs_proxy_mm);
      return {hours:Number(h.hours??h.horizon_hours),rain:point,basin:station==='mucum'?point:proxyIfs,proxy_ifs:proxyIfs,proxy_gefs:proxyGefs,max:safeNum(h.basin_max_mm),soil:safeNum(h.soil_moisture_model_mean_m3m3),prob:safeNum(h.flood_probability_percent??(h.flood_probability==null?null:Number(h.flood_probability)*100)),raw:h};
    };
    const horizons=Array.isArray(d.horizons)?d.horizons.map(mapHorizon).filter(h=>Number.isFinite(h.hours)).sort((a,b)=>a.hours-b.hours):[];
    if(d.forecast&&Array.isArray(d.forecast.horizons)){
      const f=d.forecast.horizons;
      horizons.splice(0,horizons.length,...f.map(mapHorizon).filter(h=>Number.isFinite(h.hours)).sort((a,b)=>a.hours-b.hours));
    }
    return {raw:d,generated:d.generated_at_utc,obs,level:safeNum(obs.level_cm),horizons,source:d.forecast_provider||d.forecast?.source||d.forecast_source||'feed meteorológico',soil:d.soil_moisture||d.soil||null,answer:d.answer_24h||null,risk:d.risk_model||d.rna||null};
  }
  function normalizeProbability(d){
    if(!d)return null;
    const hs=d.horizons||{};
    const rows=Object.keys(hs).map(k=>({hours:Number(k),prob:safeNum(hs[k].flood_probability_percent??(hs[k].probability==null?null:Number(hs[k].probability)*100))})).filter(x=>Number.isFinite(x.hours)&&x.prob!=null).sort((a,b)=>a.hours-b.hours);
    return {raw:d,generated:d.generated_at_utc,rows,calibrated:d.calibrated_for_current_source===true||d.calibrated===true,source:d.forecast_source||d.source||'GEFS/NOAA'};
  }
  function normalizeLive(d){
    if(!d)return null;
    const hs=d.horizontes||{};
    const rows=Object.keys(hs).filter(k=>/^(2h|4h)/.test(k)).map(k=>({key:k,label:k==='2h_versao_b'?'2 h B':k==='4h'?'4 h':'2 h',level:safeNum(hs[k].nivel_previsto_cm),now:safeNum(hs[k].nivel_rio_agora_cm),delta:safeNum(hs[k].delta_previsto_cm),status:hs[k].status||'sem status'})).filter(x=>x.level!=null);
    return {raw:d,rows,generated:d.gerado_em||d.consultado_em,telemetry:d.telemetria_ultima_em};
  }
  function setFeedState(){
    const node=el('#pv-feed-state');if(!node)return;
    const stamps=[state.weather?.generated,state.probability?.generated,state.live?.generated].filter(Boolean);
    const newest=stamps.length?Math.max(...stamps.map(v=>new Date(v).getTime()).filter(Number.isFinite)):NaN;
    const age=Number.isFinite(newest)?Math.max(0,(Date.now()-newest)/3600000):Infinity;
    const stale=!Number.isFinite(newest)||age>36;
    node.classList.toggle('stale',stale);
    node.textContent=stale?'Dados antigos / revisão necessária':`Atualizado ${Number.isFinite(age)?(age<1?'há menos de 1 h':`há ${br.format(age)} h`):'agora'}`;
    node.title=stale?'O painel conserva o valor para auditoria, mas não o trata como previsão atual.':'A idade é calculada a partir do timestamp do feed.';
  }
  function rainFor(h){return state.mode==='rain'?(h.basin??h.rain):(null)}
  function renderKpis(){
    const w=state.weather, hs=w?.horizons||[];
    const h72=hs.find(h=>h.hours===72)||hs.find(h=>h.hours>=72)||hs[hs.length-1];
    const h168=hs.find(h=>h.hours===168)||hs[hs.length-1];
    const now=state.live?.rows?.find(x=>x.key==='2h')||state.live?.rows?.[0];
    const latestProb=(state.probability?.rows||[]).find(x=>x.hours===168)||(w?.horizons||[]).find(x=>x.hours===168);
    const probFresh=state.probability&&ageHours(state.probability.generated)<=36;
    const probLabel=latestProb&&probFresh?`${pct.format(latestProb.prob)}%`:'STALE / sem valor atual';
    const probNote=state.probability?.calibrated?'calibrada em pesquisa · não é alerta':'não calibrada · não é alerta';
    setHtml('#pv-kpis',[
      ['Rio agora',cm(w?.level??now?.now),w?.obs?.state==='unknown_or_stale'?'leitura atrasada':'observado'],
      ['Chuva em 72 h',mm(h72?.basin??h72?.rain),station==='mucum'?'previsão no ponto de Muçum':'previsão acumulada no feed'],
      ['Chuva em 168 h',mm(h168?.basin??h168?.rain),station==='mucum'?'previsão no ponto de Muçum':'janela longa · não é média oficial da bacia'],
      ['Risco experimental',probLabel,probFresh?`estimativa GEFS · ${probNote}`:'rodada antiga · não usar como previsão']
    ].map((x,i)=>`<article class="pv-kpi"><span class="pv-kpi-label">${x[0]}</span><strong class="pv-kpi-value ${i===3?(probFresh?'warn':'unknown'):i===0?'good':''}">${x[1]}</strong><span class="pv-kpi-note">${x[2]}</span></article>`).join(''));
  }
  function renderBars(){
    const w=state.weather, hs=w?.horizons||[], node=el('#pv-bars');
    if(!node)return;
    if(state.mode==='river'){
      const rows=state.live?.rows||[];
      if(!rows.length){node.innerHTML='<div class="pv-empty">Feed ao vivo sem previsão curta disponível.</div>';return;}
      const vals=rows.map(x=>x.level).filter(v=>v!=null), lo=Math.min(...vals), hi=Math.max(...vals), span=Math.max(1,hi-lo);
      node.innerHTML=rows.map(x=>{const ratio=Math.max(8,((x.level-lo)/span)*100);return `<div class="pv-bar-col" data-tip="${x.label}: ${cm(x.level)} · agora ${cm(x.now)} · Δ ${x.delta==null?'—':(x.delta>0?'+':'')+cm(x.delta)}"><span class="pv-bar-value">${cm(x.level)}</span><span class="pv-bar-track"><span class="pv-bar-fill" style="height:${ratio}%"></span></span><span class="pv-bar-label">${x.label}</span><span class="pv-bar-caption">${x.status}</span></div>`}).join('');
      setText('#pv-chart-title','Nível previsto pelo robô ao vivo');setText('#pv-chart-unit','cm');setText('#pv-chart-subtitle','Comparação curta; não é probabilidade de inundação.');setText('#pv-chart-note','A linha de base é o nível observado mais recente; a leitura oficial continua ANA/SGB.');
      return;
    }
    if(!hs.length){node.innerHTML='<div class="pv-empty">Feed meteorológico sem horizontes disponíveis.</div>';return;}
    const vals=hs.map(h=>rainFor(h)).filter(v=>v!=null), max=Math.max(1,...vals);
    node.innerHTML=hs.map(h=>{const v=rainFor(h),ratio=v==null?0:Math.max(3,Math.min(100,(v/max)*100));const cls=v!=null&&v>=80?'high':v!=null&&v>=40?'warn':'';const detail=station==='mucum'?`${labelHours(h.hours)} · ponto de Muçum: ${mm(h.rain)}${h.proxy_ifs!=null?` · proxy IFS/célula: ${mm(h.proxy_ifs)}`:''}${h.proxy_gefs!=null?` · proxy GEFS/célula: ${mm(h.proxy_gefs)}`:''}`:`${labelHours(h.hours)} · bacia: ${mm(v)}${h.rain!=null&&h.basin!=null&&h.rain!==h.basin?` · ponto da estação: ${mm(h.rain)}`:''}`;return `<div class="pv-bar-col" data-tip="${detail}${h.prob!=null?` · estimativa experimental ${pct.format(h.prob)}%`:''}"><span class="pv-bar-value">${mm(v)}</span><span class="pv-bar-track"><span class="pv-bar-fill ${cls}" style="height:${ratio}%"></span></span><span class="pv-bar-label">${labelHours(h.hours)}</span><span class="pv-bar-caption">${v==null?'sem chuva':station==='mucum'?'ponto acumulado':'média acumulada'}</span></div>`}).join('');
    if(station==='mucum'){
      setText('#pv-chart-title','Chuva prevista no ponto de Muçum');setText('#pv-chart-unit','mm no ponto');setText('#pv-chart-subtitle','Acumulado previsto na estação; os proxies GEFS/IFS da célula aparecem apenas no detalhe.');setText('#pv-chart-note','Cada barra mostra a previsão pontual para Muçum. O proxy de célula/bacia é uma referência espacial e não deve ser lido como chuva prevista na estação.');
    }else{
      setText('#pv-chart-title','Chuva média prevista na bacia');setText('#pv-chart-unit','mm médios');setText('#pv-chart-subtitle','Média espacial estimada no recorte da bacia, acumulada até cada horizonte (IFS).');setText('#pv-chart-note','Cada barra é a média espacial prevista em milímetros — não é o volume total de água da bacia nem probabilidade de inundação. A chuva no ponto da estação aparece no detalhe.');
    }
  }
  function renderSide(){
    const w=state.weather, hs=w?.horizons||[], h24=hs.find(h=>h.hours===24)||hs[0], h168=hs.find(h=>h.hours===168)||hs[hs.length-1], now=state.live?.rows?.[0], prob=(state.probability?.rows||[]).find(x=>x.hours===168)||(hs.find(h=>h.hours===168)||{}), fresh=state.probability&&ageHours(state.probability.generated)<=36;
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
    if(fresh&&prob?.prob!=null)signals.push(['Probabilidade experimental',`${pct.format(prob.prob)}% até 168 h · ${state.probability?.calibrated?'calibrada em pesquisa; não é alerta':'não calibrada; não é alerta'}`,'warn']);
    else signals.push(['Probabilidade atual','sem valor utilizável: rodada antiga ou não calibrada','bad']);
    if(now?.level!=null)signals.push(['Robô ao vivo',`+${now.label.replace(/\D/g,'')} previsto: ${cm(now.level)}`,'good']);
    setHtml('#pv-signals',signals.map(s=>`<div class="pv-signal"><span class="pv-signal-dot ${s[2]}" aria-hidden="true"></span><div><strong>${s[0]}</strong><span>${s[1]}</span></div></div>`).join(''));
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
    setText('#pv-updated',`Feed meteorológico: ${formatTime(w?.generated)} · robô ao vivo: ${formatTime(state.live?.generated)}`);
  }
  function render(){setFeedState();renderKpis();renderBars();renderSide();renderSummary();}
  async function load(){
    if(state.loading)return;state.loading=true;const button=el('#pv-refresh');if(button){button.setAttribute('aria-busy','true');button.textContent='Atualizando…'}
    const get=url=>url?fetch(url+(url.includes('?')?'&':'?')+'cb='+Date.now(),{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null):Promise.resolve(null);
    const [weather,probability,live]=await Promise.all([get(weatherUrl),get(probabilityUrl),get(liveUrl)]);
    state.weather=normalizeWeather(weather);state.probability=normalizeProbability(probability);state.live=normalizeLive(live);state.loadedAt=new Date();render();state.loading=false;if(button){button.removeAttribute('aria-busy');button.textContent='Atualizar dados'}
  }
  document.addEventListener('click',e=>{const mode=e.target.closest('[data-pv-mode]');if(mode&&root.contains(mode)){state.mode=mode.dataset.pvMode;root.classList.toggle('pv-mode-river',state.mode==='river');root.querySelectorAll('[data-pv-mode]').forEach(b=>b.classList.toggle('active',b===mode));root.querySelectorAll('[data-pv-mode]').forEach(b=>b.setAttribute('aria-pressed',b===mode?'true':'false'));renderBars();renderSide();}});
  const refresh=el('#pv-refresh');if(refresh)refresh.addEventListener('click',load);
  const tip=document.createElement('div');tip.className='pv-tooltip';document.body.appendChild(tip);
  root.addEventListener('pointerover',e=>{const bar=e.target.closest('.pv-bar-col');if(!bar||!bar.dataset.tip)return;tip.textContent=bar.dataset.tip;tip.classList.add('visible');});
  root.addEventListener('pointermove',e=>{if(tip.classList.contains('visible')){tip.style.left=Math.min(window.innerWidth-250,e.clientX+12)+'px';tip.style.top=Math.min(window.innerHeight-70,e.clientY+12)+'px';}});
  root.addEventListener('pointerout',e=>{if(e.target.closest('.pv-bar-col'))tip.classList.remove('visible');});
  load();setInterval(load,300000);
})();
