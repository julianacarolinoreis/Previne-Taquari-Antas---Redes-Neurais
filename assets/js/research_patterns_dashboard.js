(function(){
  'use strict';
  var root=document.querySelector('[data-pattern-dashboard]');
  if(!root)return;
  var q=function(s){return root.querySelector(s);};
  var feed=root.getAttribute('data-pattern-feed');
  var pt=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:0,maximumFractionDigits:1});
  var p0=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
  var p2=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:0,maximumFractionDigits:2});
  var p1=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  var p3=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3});
  var esc=function(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
  var finite=function(v){return typeof v==='number'&&Number.isFinite(v);};
  var n=function(v,d){return finite(Number(v))?(d===0?p0:d===3?p3:d===2?p2:d===1?p1:pt).format(Number(v)):'—';};
  var pct=function(v){return finite(Number(v))?p2.format(Number(v))+'%':'—';};
  var date=function(v){if(!v)return '—';var s=String(v).replace('T',' ').replace('Z','');return s.length>16?s.slice(0,16):s;};
  var titleCase=function(v){return String(v||'').replace(/_/g,' ').replace(/\b\w/g,function(x){return x.toUpperCase();});};
  var color=function(kind){return kind==='gefs'?'gefs':kind==='risk'?'risk':kind==='rna'?'rna':'';};
  var fill=function(value,max,kind){var x=finite(Number(value))&&max>0?Math.max(0,Math.min(100,Number(value)/max*100)):0;return '<div class="pattern-model-track"><div class="pattern-model-fill '+color(kind)+'" style="width:'+x.toFixed(1)+'%"></div></div>';};
  var bar=function(label,value,max,kind,unit,decimals){return '<div class="pattern-bar-row"><span>'+esc(label)+'</span><div class="pattern-bar-track"><div class="pattern-bar-fill '+(kind||'')+'" style="width:'+(finite(Number(value))&&max>0?Math.max(0,Math.min(100,Number(value)/max*100)):0).toFixed(1)+'%"></div></div><b>'+n(value,decimals==null?1:decimals)+' '+esc(unit||'')+'</b></div>';};
  var scoreLabel=function(v){var n=Number(v);return Number.isFinite(n)?p2.format(n)+'% exp.':'sem score atual';};
  var sourceState=function(d,key){return ((d.source_quality||{})[key]||{}).state||'unknown';};
  var sourceAge=function(d,key){var x=Number(((d.source_quality||{})[key]||{}).age_hours);return Number.isFinite(x)?x:null;};
  var ageText=function(h){return h==null?'idade desconhecida':h>=48?p1.format(h/24)+' dias':p1.format(h)+' h';};
  var setText=function(sel,html){var el=q(sel);if(el)el.innerHTML=html;};
  function renderKpis(d){
    var s=d.summary||{}, events=Array.isArray(d.events)?d.events:[], hs=Array.isArray(d.horizons)?d.horizons:[], loc=d.location;
    var cards=[];
    cards.push('<div class="pattern-kpi blue"><strong>'+n(s.event_count||events.length)+'</strong><span>eventos comparados antes das cheias</span></div>');
    cards.push('<div class="pattern-kpi"><strong>'+n(s.peak_max_cm)+' cm</strong><span>maior pico observado · cota '+n(d.threshold_cm)+' cm</span></div>');
    if(loc==='mucum'){
      cards.push('<div class="pattern-kpi accent"><strong>'+n(s.rain_72h_median_mm,1)+' mm</strong><span>mediana de chuva antecedente em 72 h</span></div>');
      cards.push('<div class="pattern-kpi purple"><strong>'+n(s.api_72h_median_mm,1)+' mm-eq.</strong><span>mediana de memória da bacia (API 72 h)</span></div>');
    }else{
      cards.push('<div class="pattern-kpi accent"><strong>'+n(s.model_card_event_count||events.length)+'</strong><span>eventos no cartão de validação</span></div>');
      var latest=hs.length?hs[hs.length-1]:{}, pstate=sourceState(d,'probability'), page=sourceAge(d,'probability');
      if(pstate==='fresh'){
        cards.push('<div class="pattern-kpi purple"><strong>'+pct(latest.probability_percent)+'</strong><span>score GEFS experimental no horizonte de '+n(latest.hours)+' h</span></div>');
      }else{
        cards.push('<div class="pattern-kpi purple"><strong>desatualizado</strong><span>score GEFS ocultado · última fonte há '+esc(ageText(page))+'</span></div>');
      }
    }
    setText('#pattern-kpis',cards.join(''));
    var upd=q('.pattern-updated');if(upd){var ps=sourceState(d,'probability'),pa=sourceAge(d,'probability');upd.textContent='Feed visual · '+date(d.generated_at_utc)+' UTC'+(ps==='stale'?' · GEFS antigo ocultado ('+ageText(pa)+')':'');}
  }
  function renderMucumEvents(events){
    var max=0;events.forEach(function(e){['rain_24h_mm','rain_72h_mm','rain_168h_mm','api_72h_mm'].forEach(function(k){if(finite(Number(e[k])))max=Math.max(max,Number(e[k]));});});
    if(!events.length){setText('#pattern-events','<div class="pattern-empty">Nenhum evento antecedente disponível.</div>');return;}
    setText('#pattern-events',events.map(function(e){
      return '<article class="pattern-event"><div class="pattern-event-head"><strong>'+esc(e.id.replace('MUCUM-CAND-','Evento '))+'</strong><span>'+esc(date(e.date))+'</span></div><div class="pattern-event-peak">'+n(e.peak_cm)+' cm <small>pico observado</small></div><div class="pattern-bars">'+bar('24 h',e.rain_24h_mm,max,'rain24','mm',1)+bar('72 h',e.rain_72h_mm,max,'rain72','mm',1)+bar('168 h',e.rain_168h_mm,max,'rain168','mm',1)+bar('API 72 h',e.api_72h_mm,max,'api','mm-eq.',1)+'</div><div class="pattern-status">'+esc(e.soil_status||'Solo: proxy/sem sensor local.')+'<br><strong>'+esc(e.status||'Revisão pendente')+'</strong></div></article>';
    }).join(''));
  }
  function renderSantaEvents(events){
    if(!events.length){setText('#pattern-events','<div class="pattern-empty">Nenhum pico acima da cota de pesquisa no catálogo visível.</div>');return;}
    setText('#pattern-events',events.map(function(e){
      var difficulty=finite(Number(e.difficulty))?pct(Number(e.difficulty)*100):'—';
      return '<article class="pattern-event"><div class="pattern-event-head"><strong>'+esc(date(e.date))+'</strong><span>'+n(e.model_count)+' modelos</span></div><div class="pattern-event-peak">'+n(e.peak_cm)+' cm <small>pico observado</small></div><div class="pattern-bars">'+bar('Dificuldade',Number(e.difficulty)*100,100,'rain168','%',1)+bar('Modelos',e.model_count,Math.max.apply(null,events.map(function(x){return Number(x.model_count)||0;})),'rain72','',0)+'</div><div class="pattern-status">'+esc(e.status||'Pico acima da cota de pesquisa')+'<br><strong>Dificuldade do evento: '+difficulty+'</strong></div></article>';
    }).join(''));
  }
  function row(label,value,max,kind,unit,decimals){return '<div class="pattern-model-row"><span>'+esc(label)+'</span>'+fill(value,max,kind)+'<strong>'+n(value,decimals==null?1:decimals)+' '+esc(unit||'')+'</strong></div>';}
  function statusRow(label,text){return '<div class="pattern-model-row"><span>'+esc(label)+'</span><div class="pattern-model-track"></div><strong>'+esc(text)+'</strong></div>';
  function renderModels(d){
    var hs=Array.isArray(d.horizons)?d.horizons:[],loc=d.location,probState=sourceState(d,'probability'),probAge=sourceAge(d,'probability');
    if(!hs.length){setText('#pattern-models','<div class="pattern-empty">Nenhuma rodada de modelos disponível.</div>');return;}
    var html=hs.map(function(h){
      var rows=[];
      if(loc==='mucum'){
        var rainMax=Math.max(Number(h.ifs_direct_mm)||0,Number(h.ifs_proxy_mm)||0,Number(h.gefs_proxy_mm)||0,1);
        rows.push(row('IFS direto',h.ifs_direct_mm,rainMax,'','mm',1));
        rows.push(row('IFS proxy',h.ifs_proxy_mm,rainMax,'','mm',1));
        rows.push(row('GEFS proxy',h.gefs_proxy_mm,rainMax,'gefs','mm',1));
        rows.push(row('Risco logístico',h.probability_percent,100,'risk','%',2));
        rows.push('<div class="pattern-model-row"><span>Solo modelado</span><div class="pattern-model-track"><div class="pattern-model-fill rna" style="width:'+Math.max(0,Math.min(100,(Number(h.soil_moisture_m3m3)||0)*100)).toFixed(1)+'%"></div></div><strong>'+n(h.soil_moisture_m3m3,3)+' m³/m³</strong></div>');
      }else{
        var rainMax=Math.max(Number(h.ifs_mean_mm)||0,Number(h.ifs_max_mm)||0,Number(h.point_mm)||0,1);
        rows.push(row('IFS média',h.ifs_mean_mm,rainMax,'','mm',1));
        rows.push(row('IFS máximo',h.ifs_max_mm,rainMax,'gefs','mm',1));
        rows.push(row('IFS ponto',h.point_mm,rainMax,'','mm',1));
        rows.push(row('RNA IFS',h.rna_score_percent,100,'rna','%',2));
        rows.push(probState==='fresh'?row('Score GEFS',h.probability_percent,100,'risk','%',2):statusRow('Score GEFS','desatualizado'));
      }
      var hasScore=Number.isFinite(Number(h.probability_percent)),score=scoreLabel(h.probability_percent),dc=hasScore?'risk':'';
      var scoreText=hasScore?score+' · experimental':(probState==='stale'?'GEFS desatualizado':'sem score GEFS atual');
      return '<div class="pattern-horizon"><div class="pattern-horizon-head"><strong>+'+n(h.hours)+' h</strong><span class="'+dc+'">'+esc(scoreText)+'</span></div>'+rows.join('')+'</div>';
    }).join('');
    setText('#pattern-models',html);
    var legend=loc==='mucum'?'<span>Chuva IFS</span><span class="gefs">GEFS</span><span class="risk">Risco logístico</span><span class="rna">Solo modelado</span>':'<span>Chuva IFS</span><span class="gefs">IFS máximo</span><span class="risk">Score GEFS experimental</span><span class="rna">RNA do feed</span>';
    setText('#pattern-model-legend',legend);
  }
  function render(d){
    var loc=d.location,summary=d.summary||{},events=Array.isArray(d.events)?d.events:[];
    renderKpis(d);
    if(loc==='mucum')renderMucumEvents(events);else renderSantaEvents(events);
    renderModels(d);
    setText('#pattern-insight','<strong>O padrão encontrado:</strong> '+esc(summary.pattern_text||'O feed ainda não tem síntese textual.')+' <span>Os valores mostram sinais e divergências entre fontes; não transformam proxy em certeza de inundação.</span>');
    var ps=sourceState(d,'probability'),pa=sourceAge(d,'probability');
    setText('#pattern-source','Feed visual gerado em '+esc(date(d.generated_at_utc))+' UTC · '+(ps==='stale'?'score GEFS experimental ocultado porque a fonte tem '+esc(ageText(pa)):'fontes atuais dentro da janela definida')+' · modelos: '+esc((d.models||[]).map(function(x){return x.name;}).join(' · '))+'.');
  }
  function fail(){setText('#pattern-kpis','<div class="pattern-empty">Feed visual indisponível no momento.</div>');setText('#pattern-events','');setText('#pattern-models','');setText('#pattern-insight','<strong>Sem leitura atual:</strong> o feed de padrões não carregou. Isso não significa “não vai inundar”.');}
  fetch(feed+'?cb='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw Error('feed');return r.json();}).then(render).catch(fail);
})();
