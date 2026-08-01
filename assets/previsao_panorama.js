(function(){
  'use strict';

  const SVG_NS='http://www.w3.org/2000/svg';
  const state={config:null,history:null,live:null,historyError:null,historyTimer:null};
  const nf0=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
  const nf1=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const nf2=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});

  function number(v){
    return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v):null;
  }

  function parseWhen(v){
    if(!v) return null;
    if(v instanceof Date) return Number.isFinite(v.getTime())?v:null;
    const raw=String(v).trim().replace(' ','T');
    const zoned=/[zZ]|[+-]\d\d:?\d\d$/.test(raw)?raw:raw+'-03:00';
    const d=new Date(zoned);
    return Number.isFinite(d.getTime())?d:null;
  }

  function fmtLevel(cm){
    return cm===null?'—':nf2.format(cm/100)+' m';
  }

  function fmtWhen(v){
    const d=parseWhen(v);
    return d?d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(',',' ·'):'—';
  }

  function addCacheBust(url){
    return url+(url.includes('?')?'&':'?')+'cb='+Date.now();
  }

  async function fetchJson(url){
    const r=await fetch(addCacheBust(url),{cache:'no-store'});
    if(!r.ok) throw new Error('HTTP '+r.status);
    return r.json();
  }

  async function loadHistory(){
    if(!state.config) return;
    const urls=[state.config.historyRawUrl,state.config.historyFile].filter(Boolean);
    let lastError=null;
    for(const url of urls){
      try{
        state.history=await fetchJson(url);
        state.historyError=null;
        render();
        return;
      }catch(e){ lastError=e; }
    }
    state.historyError=lastError||new Error('histórico indisponível');
    render();
  }

  function putPoint(points,when,value,priority,kind){
    const d=parseWhen(when),cm=number(value);
    if(!d||cm===null) return;
    const key=d.getTime();
    const old=points.get(key);
    if(!old||priority>=old.priority) points.set(key,{time:d,cm,priority,kind});
  }

  function observedPoints(history,live){
    const points=new Map();
    const rows=history&&Array.isArray(history.registros)?history.registros:[];
    rows.forEach(r=>{
      putPoint(points,r.hora_modelo,r.nivel_modelo_cm,1,'base do modelo');
      putPoint(points,r.observado_em,r.observado_cm,3,'observado');
    });
    if(live){
      putPoint(points,live.hora_modelo,live.nivel_modelo_cm,2,'base do modelo');
      putPoint(points,live.nivel_rio_agora_em,live.nivel_rio_agora_cm,4,'observado');
      putPoint(points,live.telemetria_ultima_em,live.telemetria_ultima_nivel_cm,5,'telemetria ANA');
    }
    let out=Array.from(points.values()).sort((a,b)=>a.time-b.time);
    if(!out.length) return out;
    const lastMs=out[out.length-1].time.getTime();
    const cutoff=lastMs-24*60*60*1000;
    const recent=out.filter(p=>p.time.getTime()>=cutoff);
    return recent.length>=4?recent:out.slice(-24);
  }

  function horizonHours(key,obj){
    const explicit=number(obj&&obj.horizonte_h);
    if(explicit!==null) return explicit;
    const m=String((obj&&obj.horizonte)||key||'').match(/(\d+)/);
    return m?Number(m[1]):null;
  }

  function forecasts(live,anchor){
    if(!live) return [];
    const hs=live.horizontes&&Object.keys(live.horizontes).length?live.horizontes:{[live.horizonte||'2h']:live};
    const picked=new Map();
    Object.entries(hs).forEach(([key,obj])=>{
      if(!obj||obj.disponivel===false) return;
      const cm=number(obj.nivel_previsto_cm),hours=horizonHours(key,obj);
      if(cm===null||hours===null||![2,4,8,12].includes(hours)) return;
      let target=parseWhen(obj.hora_alvo);
      const base=parseWhen(obj.hora_modelo)||(anchor&&anchor.time)||null;
      if(!target&&base) target=new Date(base.getTime()+hours*60*60*1000);
      if(!target) return;
      const exact=String(key).toLowerCase()===hours+'h';
      const candidate={hours,cm,time:target,key,model:obj.modelo||'',exact,alternate:/cascata/i.test(key)};
      const old=picked.get(hours);
      if(!old||candidate.exact||(!old.exact&&!candidate.alternate)) picked.set(hours,candidate);
    });
    return Array.from(picked.values()).sort((a,b)=>a.hours-b.hours);
  }

  function pointBefore(points,targetMs){
    for(let i=points.length-1;i>=0;i--){
      if(points[i].time.getTime()<=targetMs) return points[i];
    }
    return null;
  }

  function rate(a,b){
    if(!a||!b) return null;
    const hours=(a.time-b.time)/36e5;
    return hours>0.2&&hours<=3?(a.cm-b.cm)/hours:null;
  }

  function trendInfo(points){
    if(points.length<2) return {label:'Tendência indisponível',detail:'Ainda não há observações suficientes.',className:''};
    const last=points[points.length-1];
    const one=pointBefore(points,last.time.getTime()-45*60*1000)||points[points.length-2];
    const two=pointBefore(points,one.time.getTime()-45*60*1000);
    const current=rate(last,one),previous=rate(one,two);
    if(current===null) return {label:'Tendência indisponível',detail:'Não há leituras próximas o suficiente para inferir o ritmo recente.',className:''};
    const currentTxt=(current>0?'+':'')+nf0.format(current)+' cm/h';
    const previousTxt=previous===null?'sem janela anterior':(previous>0?'+':'')+nf0.format(previous)+' cm/h na hora anterior';
    let label='Nível estável',className='';
    if(Math.abs(current)<2) label='Nível praticamente estável';
    else if(current>0){
      className='up';
      if(previous!==null&&previous>0&&current<previous-2) label='Subida desacelerando';
      else if(previous!==null&&previous>0&&current>previous+2) label='Subida acelerando';
      else if(previous!==null&&previous<=0) label='Rio começou a subir';
      else label='Rio subindo';
    }else{
      className='down';
      if(previous!==null&&previous<0&&Math.abs(current)<Math.abs(previous)-2) label='Queda desacelerando';
      else if(previous!==null&&previous<0&&Math.abs(current)>Math.abs(previous)+2) label='Queda acelerando';
      else if(previous!==null&&previous>=0) label='Rio começou a baixar';
      else label='Rio baixando';
    }
    return {label,detail:`Ritmo recente: ${currentTxt}; ${previousTxt}.`,className};
  }

  function floodInfo(current,items,cota){
    if(current&&current.cm>=cota) return {label:'Acima da cota oficial',detail:`O nível observado está ${nf2.format((current.cm-cota)/100)} m acima da cota.`,alert:true};
    const crossing=items.find(p=>p.cm>=cota);
    if(crossing) return {label:`Ultrapassagem prevista em +${crossing.hours}h`,detail:'Previsão pontual da RNA; não é uma probabilidade.',alert:true};
    const maxPoint=[current,...items].filter(Boolean).sort((a,b)=>b.cm-a.cm)[0];
    const gap=maxPoint?Math.max(0,(cota-maxPoint.cm)/100):null;
    return {label:'Sem ultrapassagem na janela publicada',detail:gap===null?'Cota não comparável agora.':`Maior nível disponível ainda fica ${nf2.format(gap)} m abaixo da cota oficial.`,alert:false};
  }

  function svgNode(tag,attrs,text){
    const el=document.createElementNS(SVG_NS,tag);
    Object.entries(attrs||{}).forEach(([k,v])=>el.setAttribute(k,String(v)));
    if(text!==undefined) el.textContent=text;
    return el;
  }

  function drawChart(points,items,cota){
    const svg=document.getElementById('river-level-chart');
    const empty=document.getElementById('overview-empty');
    if(!svg) return;
    svg.replaceChildren();
    const anchor=points.length?points[points.length-1]:null;
    if(!points.length&&!items.length){
      if(empty){ empty.classList.add('show'); empty.textContent=state.historyError?'Histórico indisponível neste momento. A previsão ao vivo continua sendo consultada.':'Carregando histórico e previsão ao vivo…'; }
      return;
    }
    if(empty) empty.classList.remove('show');

    const W=960,H=320,m={l:68,r:28,t:28,b:48};
    const all=[...points,...items];
    const times=all.map(p=>p.time.getTime()).filter(Number.isFinite);
    let xMin=Math.min(...times),xMax=Math.max(...times);
    if(xMax<=xMin) xMax=xMin+4*36e5;
    let vals=all.map(p=>p.cm).filter(Number.isFinite);
    let rawMin=Math.min(...vals),rawMax=Math.max(...vals),rawSpan=Math.max(80,rawMax-rawMin);
    const showThreshold=cota>=rawMin-rawSpan*.25&&cota<=rawMax+rawSpan*1.25;
    if(showThreshold) vals.push(cota);
    let yMin=Math.max(0,Math.min(...vals)-Math.max(35,rawSpan*.16));
    let yMax=Math.max(...vals)+Math.max(35,rawSpan*.16);
    if(yMax<=yMin) yMax=yMin+100;
    const X=t=>m.l+(W-m.l-m.r)*(t-xMin)/(xMax-xMin);
    const Y=v=>m.t+(H-m.t-m.b)*(1-(v-yMin)/(yMax-yMin));
    const crossDay=new Date(xMin).toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo'})!==new Date(xMax).toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo'});

    const title=svgNode('title',{},'Nível do rio observado nas últimas 24 horas e previsões ativas da rede neural.');
    const desc=svgNode('desc',{},'Linha azul contínua para observações e linha laranja tracejada para previsões de duas, quatro e, quando publicadas, oito e doze horas.');
    svg.append(title,desc);

    for(let i=0;i<5;i++){
      const v=yMin+(yMax-yMin)*i/4,y=Y(v);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#dfe7e2','stroke-width':1}));
      svg.appendChild(svgNode('text',{x:m.l-10,y:y+4,'text-anchor':'end','font-size':11,fill:'#6c7a72'},nf1.format(v/100)+' m'));
    }
    for(let i=0;i<6;i++){
      const t=xMin+(xMax-xMin)*i/5,x=X(t),d=new Date(t);
      const label=d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',hour:'2-digit',minute:'2-digit'});
      const safeLabel=crossDay?d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(',',' '):label;
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:'#edf2ef','stroke-width':1}));
      svg.appendChild(svgNode('text',{x,y:H-m.b+22,'text-anchor':'middle','font-size':11,fill:'#6c7a72'},safeLabel));
    }
    svg.appendChild(svgNode('text',{x:16,y:(m.t+H-m.b)/2,transform:`rotate(-90 16 ${(m.t+H-m.b)/2})`,'text-anchor':'middle','font-size':11,fill:'#6c7a72'},'Nível do rio (m)'));

    if(showThreshold){
      const y=Y(cota);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#c0392b','stroke-width':1.5,'stroke-dasharray':'3 5'}));
      svg.appendChild(svgNode('text',{x:W-m.r,y:y-7,'text-anchor':'end','font-size':11,'font-weight':700,fill:'#a12d25'},'cota oficial '+fmtLevel(cota)));
    }

    if(points.length>1){
      const d=points.map((p,i)=>(i?'L':'M')+X(p.time.getTime()).toFixed(1)+','+Y(p.cm).toFixed(1)).join(' ');
      svg.appendChild(svgNode('path',{d,fill:'none',stroke:'#1e5fbf','stroke-width':3,'stroke-linejoin':'round','stroke-linecap':'round'}));
    }
    if(anchor){
      const x=X(anchor.time.getTime()),y=Y(anchor.cm);
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:'#1e5fbf','stroke-width':1,'stroke-dasharray':'2 4',opacity:.55}));
      const dot=svgNode('circle',{cx:x,cy:y,r:5.5,fill:'#1e5fbf',stroke:'#fff','stroke-width':2});
      dot.appendChild(svgNode('title',{},`Agora: ${fmtLevel(anchor.cm)} em ${fmtWhen(anchor.time)}`));
      svg.appendChild(dot);
      svg.appendChild(svgNode('text',{x:x+7,y:y-9,'font-size':11,'font-weight':700,fill:'#174f9b'},'agora'));
    }

    if(anchor&&items.length){
      const future=[anchor,...items];
      const d=future.map((p,i)=>(i?'L':'M')+X(p.time.getTime()).toFixed(1)+','+Y(p.cm).toFixed(1)).join(' ');
      svg.appendChild(svgNode('path',{d,fill:'none',stroke:'#e8730c','stroke-width':3,'stroke-dasharray':'8 6','stroke-linejoin':'round','stroke-linecap':'round'}));
      items.forEach((p,i)=>{
        const x=X(p.time.getTime()),y=Y(p.cm);
        const dot=svgNode('circle',{cx:x,cy:y,r:5,fill:'#fff',stroke:'#e8730c','stroke-width':3});
        dot.appendChild(svgNode('title',{},`Previsão +${p.hours}h: ${fmtLevel(p.cm)} para ${fmtWhen(p.time)}`));
        svg.appendChild(dot);
        const labelY=i%2?y+22:y-12;
        svg.appendChild(svgNode('text',{x,y:labelY,'text-anchor':'middle','font-size':11,'font-weight':750,fill:'#a55209'},`+${p.hours}h · ${fmtLevel(p.cm)}`));
      });
    }
  }

  function renderMetrics(current,items,trend,flood,cota){
    const box=document.getElementById('overview-metrics');
    if(!box) return;
    const cards=[];
    cards.push(`<article class="overview-metric"><span>Nível do rio agora</span><strong>${fmtLevel(current&&current.cm!==undefined?current.cm:null)}</strong><small>${current?fmtWhen(current.time):'aguardando telemetria'}</small></article>`);
    items.forEach(p=>cards.push(`<article class="overview-metric forecast"><span>Previsão +${p.hours}h</span><strong>${fmtLevel(p.cm)}</strong><small>para ${fmtWhen(p.time)}${p.alternate?' · modelo cascata':''}</small></article>`));
    if(!items.length) cards.push('<article class="overview-metric forecast"><span>Previsão da RNA</span><strong>Indisponível</strong><small>Nenhum horizonte ativo foi publicado agora.</small></article>');
    cards.push(`<article class="overview-metric ${flood.alert?'alert':''}"><span>Cota oficial</span><strong>${fmtLevel(cota)}</strong><small>${flood.label}</small></article>`);
    box.innerHTML=cards.join('');
    const badge=document.getElementById('overview-trend-badge');
    if(badge){ badge.textContent=trend.label; badge.className='trend-badge '+(flood.alert?'alert':trend.className); }
    const trendDetail=document.getElementById('overview-trend-detail');
    if(trendDetail) trendDetail.textContent=trend.detail;
    const floodLabel=document.getElementById('overview-flood-label');
    if(floodLabel) floodLabel.textContent=flood.label;
    const floodDetail=document.getElementById('overview-flood-detail');
    if(floodDetail) floodDetail.textContent=flood.detail;
  }

  function render(){
    if(!state.config) return;
    const points=observedPoints(state.history,state.live);
    const current=points.length?points[points.length-1]:null;
    const items=forecasts(state.live,current);
    const trend=trendInfo(points);
    const flood=floodInfo(current,items,state.config.cotaInundCm);
    drawChart(points,items,state.config.cotaInundCm);
    renderMetrics(current,items,trend,flood,state.config.cotaInundCm);

    const status=document.getElementById('overview-source-status');
    if(status){
      const telemetryWhen=state.live&&(state.live.telemetria_ultima_em||state.live.nivel_rio_agora_em);
      const modelWhen=state.live&&state.live.hora_modelo;
      const historyWhen=state.history&&state.history.atualizado_em;
      const freshness=[
        telemetryWhen?`Leitura mais recente do rio: ${fmtWhen(telemetryWhen)}`:'',
        modelWhen?`base da RNA: ${fmtWhen(modelWhen)}`:'',
        historyWhen?`histórico atualizado: ${fmtWhen(historyWhen)}`:''
      ].filter(Boolean).join(' · ');
      const prefix=state.historyError?'O histórico não carregou; os horizontes ao vivo continuam visíveis.':'Linha azul: níveis observados nas últimas 24 horas. Linha laranja: previsão pontual da RNA.';
      status.textContent=prefix+(freshness?' '+freshness+'.':'');
    }
    const accessible=document.getElementById('overview-accessible');
    if(accessible){
      const forecastText=items.length?items.map(p=>`mais ${p.hours} horas: ${fmtLevel(p.cm)}`).join('; '):'sem previsão ativa';
      accessible.textContent=`Nível atual ${fmtLevel(current?current.cm:null)}. ${forecastText}. ${trend.label}. ${flood.label}.`;
    }
  }

  function setMode(mode){
    const body=document.body;
    body.classList.toggle('tech',mode==='tech');
    body.classList.toggle('panorama',mode==='panorama');
    [['mode-s','simple'],['mode-t','tech'],['mode-p','panorama']].forEach(([id,value])=>{
      const b=document.getElementById(id);
      if(b){ b.classList.toggle('on',mode===value); b.setAttribute('aria-pressed',mode===value?'true':'false'); }
    });
    if(state.config&&typeof state.config.onLayout==='function') state.config.onLayout(mode);
    if(mode==='panorama') window.scrollTo({top:0,behavior:'smooth'});
  }

  function init(config){
    state.config=config;
    ['mode-s','mode-t','mode-p'].forEach(id=>{
      const b=document.getElementById(id);
      if(!b) return;
      const mode=id==='mode-s'?'simple':id==='mode-t'?'tech':'panorama';
      b.onclick=()=>setMode(mode);
    });
    setMode('simple');
    loadHistory();
    clearInterval(state.historyTimer);
    state.historyTimer=setInterval(loadHistory,5*60*1000);
    render();
  }

  function update(live){
    state.live=live||null;
    render();
  }

  window.PREVINE_PANORAMA={init,update,setMode};
})();
