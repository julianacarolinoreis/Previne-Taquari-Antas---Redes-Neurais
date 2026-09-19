/* PREVINE — resumo público dos feeds já existentes.
   Pesquisa/protótipo: não cria alerta, decisão binária ou ordem de evacuação. */
(function(){
  'use strict';
  var cards = {
    santa: {
      file:'previsao_ao_vivo.json',
      place:'Santa Tereza',
      station:'86472600',
      map:'santa_tereza_previsao_inundacao.html',
      status:'pesquisa_status.html'
    },
    mucum: {
      file:'previsao_ao_vivo_mucum.json',
      place:'Muçum',
      station:'86510000',
      map:'mucum_previsao_inundacao.html',
      status:'pesquisa_status_mucum.html'
    }
  };

  function parseDate(v){
    if(!v) return null;
    var s=String(v).trim().replace(' ','T');
    if(!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += '-03:00';
    var d=new Date(s);
    return isNaN(d.getTime())?null:d;
  }
  function cm(v){
    if(v==null || isNaN(Number(v))) return '—';
    return Math.round(Number(v)).toLocaleString('pt-BR')+' cm';
  }
  function clock(v){
    var d=parseDate(v);
    return d?d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';
  }
  function ageMinutes(data){
    var explicit=Number(data&&data.idade_telemetria_min);
    if(Number.isFinite(explicit) && explicit>=0) return explicit;
    var d=parseDate(data&&(data.telemetria_ultima_em||data.nivel_rio_agora_em||data.consultado_em));
    return d?Math.max(0,(Date.now()-d.getTime())/60000):NaN;
  }
  function stateFor(data){
    if(!data) return {id:'unknown',label:'indisponível'};
    var age=ageMinutes(data);
    if(!Number.isFinite(age)) return {id:'unknown',label:'horário incerto'};
    if(age>180) return {id:'stale',label:'dado muito atrasado'};
    if(age>90) return {id:'delayed',label:'dado com atraso'};
    return {id:'recent',label:'dado recente'};
  }
  function horizon(data,key){
    var hs=data&&data.horizontes;
    if(hs&&hs[key]&&hs[key].nivel_previsto_cm!=null) return hs[key].nivel_previsto_cm;
    if(key==='2h'&&data&&data.horizonte_h===2) return data.nivel_previsto_cm;
    return null;
  }
  function deltaText(now,forecast,label){
    if(now==null||forecast==null||isNaN(Number(now))||isNaN(Number(forecast))) return 'Tendência '+label+': sem valor comparável.';
    var d=Math.round(Number(forecast)-Number(now));
    if(Math.abs(d)<2) return 'Tendência '+label+': praticamente estável.';
    return 'Tendência '+label+': '+(d>0?'subida de ':'queda de ')+Math.abs(d).toLocaleString('pt-BR')+' cm.';
  }
  function setText(id,value){
    var n=document.getElementById(id);
    if(n) n.textContent=value;
  }
  function render(id,data){
    var cfg=cards[id], card=document.querySelector('[data-situation-card="'+id+'"]');
    if(!card) return;
    var state=stateFor(data), now=data&&(data.telemetria_ultima_nivel_cm!=null?data.telemetria_ultima_nivel_cm:(data.nivel_rio_agora_cm!=null?data.nivel_rio_agora_cm:data.nivel_atual_cm));
    var h2=horizon(data,'2h'), h4=horizon(data,'4h');
    var age=ageMinutes(data);
    card.dataset.state=state.id;
    var chip=card.querySelector('.state-chip');
    if(chip){ chip.dataset.state=state.id; chip.textContent=state.label; }
    setText('sit-'+id+'-now',cm(now));
    setText('sit-'+id+'-2h',cm(h2));
    setText('sit-'+id+'-4h',cm(h4));
    setText('sit-'+id+'-trend',deltaText(now,h2,'até +2 h'));
    setText('sit-'+id+'-stamp','Observação '+clock(data&&(data.telemetria_ultima_em||data.nivel_rio_agora_em))+(Number.isFinite(age)?' · idade '+Math.round(age)+' min':'')+' · pesquisa');
    setText('sit-'+id+'-model',data&&data.modelo?'Modelo ativo: '+data.modelo:'Modelo: indisponível');
    var primary=card.querySelector('.primary');
    if(primary) primary.href=cfg.map;
    var status=card.querySelector('[data-status-link]');
    if(status) status.href=cfg.status;
  }
  function load(path){
    if(typeof PrevineLiveFeed==='object'&&PrevineLiveFeed.fetchLive) return PrevineLiveFeed.fetchLive(path).catch(function(){return null;});
    return fetch(path+'?cb='+Date.now(),{cache:'no-store'}).then(function(r){return r.ok?r.json():null}).catch(function(){return null});
  }
  function copySituation(id){
    var cfg=cards[id], card=document.querySelector('[data-situation-card="'+id+'"]');
    if(!card) return;
    var txt='PREVINE · '+cfg.place+'\n'+
      'Agora: '+(document.getElementById('sit-'+id+'-now')||{}).textContent+'\n'+
      '+2 h: '+(document.getElementById('sit-'+id+'-2h')||{}).textContent+'\n'+
      '+4 h: '+(document.getElementById('sit-'+id+'-4h')||{}).textContent+'\n'+
      (document.getElementById('sit-'+id+'-trend')||{}).textContent+'\n'+
      (document.getElementById('sit-'+id+'-stamp')||{}).textContent+'\n'+
      'Pesquisa/protótipo; não é alerta oficial.\n'+location.origin+location.pathname+'#situacao-agora';
    var msg=card.querySelector('.situation-message');
    function ok(){ if(msg) msg.textContent='Resumo copiado.'; }
    if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(ok).catch(function(){window.prompt('Copie o resumo:',txt);});
    else window.prompt('Copie o resumo:',txt);
  }
  document.querySelectorAll('[data-copy-situation]').forEach(function(btn){
    btn.addEventListener('click',function(){copySituation(btn.getAttribute('data-copy-situation'));});
  });
  Promise.all([load(cards.santa.file),load(cards.mucum.file)]).then(function(pair){
    render('santa',pair[0]);
    render('mucum',pair[1]);
  });
})();
