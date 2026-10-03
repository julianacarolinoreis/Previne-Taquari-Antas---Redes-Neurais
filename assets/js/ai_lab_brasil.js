(function(){
  'use strict';

  var FEED = 'assets/data/research_basin_screening_latest.json';
  var AUTO_TRAIN_LOCAL = 'assets/data/ai_lab/auto_training_v2_latest.json';
  var AUTO_TRAIN_RAW = 'https://raw.githubusercontent.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais/main/assets/data/ai_lab/auto_training_v2_latest.json';
  var AUTO_TRAIN_FALLBACK_LOCAL = 'assets/data/ai_lab/auto_training_latest.json';
  var AUTO_TRAIN_FALLBACK_RAW = 'https://raw.githubusercontent.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais/main/assets/data/ai_lab/auto_training_latest.json';
  var BRAZIL_BOUNDS = [[-34.8,-74.2],[5.7,-34.0]];
  var state = { feed:null, autoTraining:null, map:null, markers:[], stationIndex:[], selected:null };

  function el(id){ return document.getElementById(id); }
  function text(id,value){ var node=el(id); if(node) node.textContent=value; }
  function fmtNumber(value, digits){
    if(value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString('pt-BR',{maximumFractionDigits:digits === undefined ? 1 : digits});
  }
  function fmtLevel(cm){
    if(cm === null || cm === undefined || Number.isNaN(Number(cm))) return '—';
    return fmtNumber(Number(cm)/100,2) + ' m';
  }
  function fmtTime(value){
    if(!value) return '—';
    var d = new Date(value);
    if(Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function toast(message){
    var node=el('lab-toast');
    node.textContent=message;
    node.hidden=false;
    window.clearTimeout(toast.timer);
    toast.timer=window.setTimeout(function(){node.hidden=true;},5200);
  }
  function roleOf(model){
    var role=(model && model.role ? String(model.role) : '').toLowerCase();
    return role.indexOf('sombra') >= 0 ? 'sombra' : 'principal';
  }
  function availableModels(station){
    var rows=(station && station.live_horizons) || [];
    return rows.filter(function(row){ return row && row.available !== false; });
  }
  function initMap(){
    if(!window.L){ text('map-status','Mapa indisponível: biblioteca cartográfica não carregou.'); return; }
    state.map=L.map('brazil-map',{zoomControl:true,minZoom:3,maxZoom:12}).fitBounds(BRAZIL_BOUNDS);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
      maxZoom:19,
      attribution:'© OpenStreetMap'
    }).addTo(state.map);
    el('fit-brazil').addEventListener('click',function(){ state.map.fitBounds(BRAZIL_BOUNDS); });
  }
  function stationFromFeed(key,station){
    var coord=station && station.coordinates;
    if(!coord || coord.latitude === null || coord.longitude === null) return null;
    return {
      key:key,
      name:station.station_name || station.name || key,
      code:station.station_code || '',
      lat:Number(coord.latitude),
      lon:Number(coord.longitude),
      raw:station
    };
  }
  function addMarkers(){
    state.markers.forEach(function(m){ if(state.map) state.map.removeLayer(m); });
    state.markers=[];
    state.stationIndex=[];
    if(!state.feed || !state.feed.stations || !state.map) return;

    Object.keys(state.feed.stations).forEach(function(key){
      var item=stationFromFeed(key,state.feed.stations[key]);
      if(!item || Number.isNaN(item.lat) || Number.isNaN(item.lon)) return;
      state.stationIndex.push(item);
      var icon=L.divIcon({className:'lab-marker',html:'<div class="lab-marker-core"></div>',iconSize:[22,22],iconAnchor:[11,11]});
      var marker=L.marker([item.lat,item.lon],{icon:icon}).addTo(state.map);
      marker.bindPopup('<div class="lab-popup"><strong>'+item.name+'</strong><span>'+item.code+'</span><span>Clique para abrir o supervisor.</span></div>');
      marker.on('click',function(){ selectStation(item); });
      state.markers.push(marker);
    });
    text('map-status',state.stationIndex.length+' ponto(s) real(is) conectado(s) nesta versão · arquitetura preparada para expansão nacional');
    if(state.stationIndex.length){ selectStation(state.stationIndex[0]); }
  }
  function updateNetworkKpis(){
    var active=0, shadow=0;
    state.stationIndex.forEach(function(item){
      availableModels(item.raw).forEach(function(model){
        if(roleOf(model)==='sombra') shadow += 1; else active += 1;
      });
    });
    text('kpi-stations',String(state.stationIndex.length));
    text('kpi-active',String(active));
    text('kpi-shadow',String(shadow));
    text('kpi-updated',state.feed && state.feed.generated_at_utc ? fmtTime(state.feed.generated_at_utc) : '—');
  }
  function classifyFreshness(current){
    if(!current) return {label:'sem dado',cls:'neutral'};
    if(current.state==='fresh') return {label:'atual',cls:'good'};
    if(current.state==='stale') return {label:'atrasado',cls:'warn'};
    return {label:current.state || 'incerto',cls:'neutral'};
  }
  function setPill(node,info){
    node.textContent=info.label;
    node.className='pill '+info.cls;
  }
  function selectStation(item){
    state.selected=item;
    var s=item.raw || {};
    var current=s.current || {};
    text('station-name',item.name);
    text('station-meta',(item.code ? 'Estação '+item.code+' · ' : '') + ((state.feed && state.feed.basin && state.feed.basin.name) || 'bacia não informada'));
    text('station-level',fmtLevel(current.level_cm));
    text('station-time',fmtTime(current.observed_at_utc || current.last_observation));
    text('station-source',current.source || 'fonte não informada');
    setPill(el('station-freshness'),classifyFreshness(current));
    renderSupervisor(s);
    renderModels(s);
    updateTrainingRequest();
  }
  function renderSupervisor(station){
    var current=station.current || {};
    var models=availableModels(station);
    var primary=models.filter(function(m){return roleOf(m)==='principal';});
    var missing=models.reduce(function(total,m){return total + Number(m.inputs_missing || 0);},0);
    var freshness=classifyFreshness(current);
    var score=0;
    if(freshness.cls==='good') score += 2;
    if(primary.length) score += 2;
    if(models.length && missing===0) score += 2;
    var qualityBad=models.some(function(m){
      var q=String(m.quality_status || m.input_audit_status || '').toUpperCase();
      return q && q!=='NORMAL';
    });
    if(qualityBad) score -= 2;

    var sup={label:'insuficiente',cls:'bad'};
    if(score>=6 && !qualityBad) sup={label:'boa',cls:'good'};
    else if(score>=3) sup={label:'atenção',cls:'warn'};
    setPill(el('supervisor-state'),sup);

    var summary='O supervisor combina atualidade da telemetria, disponibilidade do modelo e integridade dos inputs. ';
    if(sup.cls==='good') summary += 'Os sinais básicos disponíveis nesta versão estão coerentes para acompanhamento experimental.';
    else if(sup.cls==='warn') summary += 'Há condição parcial; leia os gates antes de interpretar a previsão.';
    else summary += 'Faltam evidências mínimas para uma leitura operacional confiável.';
    text('supervisor-summary',summary);

    var checks=[
      {label:'Telemetria '+(freshness.cls==='good'?'atualizada':'não confirmada como atual'),cls:freshness.cls==='good'?'ok':'warn'},
      {label:primary.length+' modelo(s) principal(is) disponível(is)',cls:primary.length?'ok':'bad'},
      {label:missing===0?'Inputs declarados sem faltas nos modelos disponíveis':missing+' input(s) faltante(s) nos modelos disponíveis',cls:missing===0?'ok':'warn'},
      {label:qualityBad?'Há marca de qualidade diferente de NORMAL':'Auditoria de qualidade sem bloqueio explícito',cls:qualityBad?'warn':'ok'},
      {label:'Gate de promoção automática permanece bloqueado nesta versão',cls:'warn'}
    ];
    var box=el('supervisor-checks');
    box.innerHTML='';
    checks.forEach(function(c){
      var row=document.createElement('div'); row.className='check '+c.cls;
      row.innerHTML='<i aria-hidden="true"></i><span>'+c.label+'</span>';
      box.appendChild(row);
    });
  }
  function renderModels(station){
    var body=el('model-table-body');
    var rows=availableModels(station);
    if(!rows.length){
      body.innerHTML='<tr><td colspan="7" class="empty-cell">Nenhum modelo ao vivo publicado para este ponto.</td></tr>';
      return;
    }
    var selectedH=Number(el('horizon-select').value || 4);
    var sorted=rows.slice().sort(function(a,b){
      var ra=roleOf(a)==='principal'?0:1, rb=roleOf(b)==='principal'?0:1;
      if(ra!==rb) return ra-rb;
      return Number(a.hours||999)-Number(b.hours||999);
    });
    body.innerHTML='';
    sorted.forEach(function(m){
      var role=roleOf(m);
      var tr=document.createElement('tr');
      if(Number(m.hours)===selectedH) tr.style.background='#fbfdfb';
      var quality=m.quality_status || m.input_audit_status || m.status || '—';
      var err=m.mae_24h_cm!==null && m.mae_24h_cm!==undefined ? fmtNumber(m.mae_24h_cm,1)+' cm MAE' : '—';
      tr.innerHTML=
        '<td><span class="model-role '+(role==='principal'?'role-main':'role-shadow')+'">'+role+'</span></td>'+
        '<td>'+fmtNumber(m.hours,0)+' h</td>'+
        '<td>'+String(m.model || '—')+'</td>'+
        '<td>'+fmtLevel(m.level_forecast_cm)+'</td>'+
        '<td>'+fmtNumber(m.inputs_exact!==undefined?m.inputs_exact:m.inputs_total,0)+'/'+fmtNumber(m.inputs_total,0)+'</td>'+
        '<td>'+String(quality)+'</td>'+
        '<td>'+err+'</td>';
      body.appendChild(tr);
    });
  }

  function escapeHtml(value){
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g,function(ch){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
    });
  }
  function updateTrainingRequest(){
    var point=state.selected ? state.selected.name : 'ponto não selecionado';
    var horizon=el('horizon-select') ? el('horizon-select').value : '—';
    var variable=el('variable-select') && el('variable-select').value === 'vazao' ? 'vazão' : 'nível';
    text('training-request',point+' · '+variable+' +'+horizon+' h');
  }
  function renderAutoTraining(data){
    state.autoTraining=data;
    setPill(el('auto-training-status'),{label:'concluído',cls:'good'});
    text('training-experiment',data.label || data.experiment_id || '—');
    text('training-target',(data.station && data.station.code ? 'Estação '+data.station.code+' · ' : '')+(data.target || 'alvo')+' · +'+fmtNumber(data.horizon_hours,0)+' h');
    var seqAudit=data.sequence_audit || {};
    var rowCount=seqAudit.eligible_sequence_rows!==undefined ? seqAudit.eligible_sequence_rows : (data.data_audit && data.data_audit.finite_rows);
    text('training-rows',fmtNumber(rowCount,0));
    var featureSummary=fmtNumber(data.data_audit && data.data_audit.feature_count,0)+' entradas auditadas';
    if(seqAudit.max_lookback_h!==undefined) featureSummary += ' · janela comum '+fmtNumber(seqAudit.max_lookback_h,0)+' h';
    text('training-features',featureSummary);
    text('training-folds',fmtNumber((data.folds || []).length,0));
    text('training-shadow-count',fmtNumber((data.shadow_candidates || []).length,0));
    text('training-generated',fmtTime(data.generated_at_utc));
    var audit=data.data_audit || {};
    var duplicateCount=Number(audit.duplicate_event_timestamp_rows || 0);
    var skippedCount=Number(audit.skipped_rows || 0);
    var featureCount=Number(audit.feature_count || 0);
    var modelCount=(data.leaderboard || []).length;
    var foldCount=(data.folds || []).length;
    var eligibleCount=(data.leaderboard || []).filter(function(row){return row.shadow_eligible;}).length;
    text('agent-data',duplicateCount===0 ? fmtNumber(audit.finite_rows,0)+' linhas · 0 duplicidades' : duplicateCount+' duplicidades bloqueantes');
    text('agent-features',featureCount+' entradas · '+(seqAudit.max_lookback_h ? 'sequência '+seqAudit.max_lookback_h+' h · ' : '')+skippedCount+' linhas brutas descartadas');
    text('agent-train',modelCount+' famílias/configurações avaliadas');
    text('agent-validation',foldCount+' dobras causais por evento');
    text('agent-shadow',eligibleCount+' candidato(s) passaram aos gates básicos');
    [['agent-data-dot',duplicateCount===0],['agent-features-dot',featureCount>0],['agent-train-dot',modelCount>1],['agent-validation-dot',foldCount>=3],['agent-shadow-dot',eligibleCount>0]].forEach(function(pair){
      var dot=el(pair[0]); if(dot) dot.className=pair[1]?'agent-ok':'agent-warn';
    });
    var version=data.engine_version ? 'Motor '+data.engine_version+'. ' : '';
    text('training-message',version+'Rodada concluída. O leaderboard é evidência de pesquisa; candidatos aprovados seguem apenas para a próxima etapa de modo sombra.');
    var body=el('training-table-body');
    var allRows=(data.leaderboard || []);
    var bestOverall=allRows.length ? allRows[0] : null;
    var bestTemporal=allRows.find(function(row){return row.representation==='temporal_sequence';});
    var baseline=allRows.find(function(row){return row.model==='Persistência';});
    text('training-best-overall',bestOverall ? bestOverall.model : '—');
    text('training-best-overall-metric',bestOverall ? 'MAE '+fmtNumber(bestOverall.median_mae_cm,2)+' cm · '+(bestOverall.shadow_eligible?'gate sombra':'retido') : '—');
    text('training-best-temporal',bestTemporal ? bestTemporal.model : '—');
    text('training-best-temporal-metric',bestTemporal ? 'MAE '+fmtNumber(bestTemporal.median_mae_cm,2)+' cm · '+(bestTemporal.dominant_profile || 'perfil variável')+' · '+(bestTemporal.shadow_eligible?'gate sombra':'retido') : '—');
    text('training-baseline',baseline ? fmtNumber(baseline.median_mae_cm,2)+' cm MAE' : '—');
    var rows=(data.leaderboard || []).slice(0,16);
    if(!rows.length){
      body.innerHTML='<tr><td colspan="10" class="empty-cell">A rodada não publicou modelos.</td></tr>';
      return;
    }
    body.innerHTML=rows.map(function(row){
      var gate=row.shadow_eligible ? '<span class="training-gate pass">sombra</span>' : '<span class="training-gate hold">reter</span>';
      var kind=row.representation==='temporal_sequence' ? 'temporal' : (row.representation==='baseline' ? 'baseline' : 'estático');
      var profile=row.dominant_profile || '—';
      return '<tr'+(row.shadow_eligible?' class="shadow-pass"':'')+'>'+
        '<td>'+escapeHtml(row.rank)+'</td>'+
        '<td><strong>'+escapeHtml(row.model)+'</strong><small class="model-family-mini">'+escapeHtml(row.family || '')+'</small></td>'+
        '<td><span class="representation-tag '+(kind==='temporal'?'temporal':'')+'">'+kind+'</span></td>'+
        '<td>'+escapeHtml(profile)+'</td>'+
        '<td>'+fmtNumber(row.median_mae_cm,2)+' cm</td>'+
        '<td>'+fmtNumber(row.median_rmse_cm,2)+' cm</td>'+
        '<td>'+fmtNumber(row.median_nse,3)+'</td>'+
        '<td>'+fmtNumber(row.median_peak_abs_error_cm,2)+' cm</td>'+
        '<td>'+fmtNumber(row.median_peak_lag_abs_h,1)+' h</td>'+
        '<td>'+gate+'</td></tr>';
    }).join('');
  }
  async function loadAutoTraining(){
    setPill(el('auto-training-status'),{label:'consultando',cls:'neutral'});
    var sources=[AUTO_TRAIN_RAW,AUTO_TRAIN_LOCAL,AUTO_TRAIN_FALLBACK_RAW,AUTO_TRAIN_FALLBACK_LOCAL];
    var lastError=null;
    for(var i=0;i<sources.length;i++){
      try{
        var response=await fetch(sources[i],{cache:'no-store'});
        if(!response.ok) throw new Error('HTTP '+response.status);
        var data=await response.json();
        renderAutoTraining(data);
        return;
      }catch(err){ lastError=err; }
    }
    setPill(el('auto-training-status'),{label:'fila/sem resultado',cls:'warn'});
    text('training-message','O motor já está configurado, mas ainda não há um resultado publicado desta rodada. Abra a fila do GitHub para acompanhar a execução.');
    if(lastError) console.warn('AI Lab auto training:',lastError);
  }

  function searchStation(){
    var q=String(el('station-search').value||'').trim().toLowerCase();
    if(!q){ toast('Digite o nome ou código de uma estação conectada.'); return; }
    var found=state.stationIndex.find(function(item){
      return item.name.toLowerCase().indexOf(q)>=0 || String(item.code).toLowerCase().indexOf(q)>=0;
    });
    if(!found){
      text('search-help','Não encontrei esse ponto no feed piloto. A busca nacional ainda será ligada aos conectores.');
      toast('Ponto ainda não conectado nesta versão.');
      return;
    }
    text('search-help','Ponto encontrado no feed conectado.');
    if(state.map) state.map.setView([found.lat,found.lon],9);
    selectStation(found);
  }
  async function loadFeed(){
    text('hero-status-title','Atualizando feed piloto');
    try{
      var response=await fetch(FEED,{cache:'no-store'});
      if(!response.ok) throw new Error('HTTP '+response.status);
      state.feed=await response.json();
      addMarkers();
      updateNetworkKpis();
      text('hero-status-title','Feed piloto conectado');
      text('hero-status-note','Taquari-Antas atualizado em '+fmtTime(state.feed.generated_at_utc)+'.');
      var dot=document.querySelector('.status-dot');
      if(dot) dot.style.background='#17805a';
    }catch(err){
      text('hero-status-title','Feed piloto indisponível');
      text('hero-status-note','A interface nacional segue acessível, mas os dados não carregaram.');
      text('map-status','Não foi possível carregar o feed: '+err.message);
      toast('Falha ao carregar o feed piloto.');
    }
  }
  function wire(){
    el('refresh-feed').addEventListener('click',loadFeed);
    el('station-search-button').addEventListener('click',searchStation);
    el('station-search').addEventListener('keydown',function(ev){ if(ev.key==='Enter') searchStation(); });
    el('horizon-select').addEventListener('change',function(){ if(state.selected) renderModels(state.selected.raw); updateTrainingRequest(); });
    el('variable-select').addEventListener('change',function(){
      var value=el('variable-select').value;
      if(value==='vazao') toast('A estrutura para vazão já está prevista; este feed piloto publicado está orientado principalmente a nível.');
      updateTrainingRequest();
    });
    el('new-station').addEventListener('click',function(){
      toast('Próximo módulo: conector nacional de estações + descoberta automática de dados. A interface já está preparada para receber esse cadastro.');
    });
    el('new-training').addEventListener('click',function(){
      var section=el('auto-training');
      if(section) section.scrollIntoView({behavior:'smooth',block:'start'});
      toast('O treinamento automático já está ativo. A seção mostra a última rodada publicada e o link para executar uma nova fila.');
    });
  }
  document.addEventListener('DOMContentLoaded',function(){
    initMap();
    wire();
    loadFeed();
    loadAutoTraining();
    updateTrainingRequest();
  });
})();