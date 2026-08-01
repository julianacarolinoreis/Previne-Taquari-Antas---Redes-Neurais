(function(){
  'use strict';

  const SVG_NS='http://www.w3.org/2000/svg';
  const state={config:null,history:null,live:null,historyError:null,historyTimer:null,resizeObserver:null,resizeTimer:null};
  const nf0=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
  const nf1=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const nf2=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
  const FORECAST_STYLES={
    2:{variable:'--panorama-forecast-2',fallback:'#b85c00',dash:'9 6',shape:'circle'},
    4:{variable:'--panorama-forecast-4',fallback:'#6c3aa1',dash:'4 5',shape:'diamond'},
    8:{variable:'--panorama-forecast-8',fallback:'#087665',dash:'12 5',shape:'square'},
    12:{variable:'--panorama-forecast-12',fallback:'#a52f67',dash:'2 5',shape:'triangle'}
  };

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
    return Array.from(points.values()).sort((a,b)=>a.time-b.time);
  }

  function pointsInWindow(points,hours){
    if(!points.length) return [];
    const cutoff=points[points.length-1].time.getTime()-hours*60*60*1000;
    return points.filter(p=>p.time.getTime()>=cutoff);
  }

  function cssValue(variable,fallback){
    const value=getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
    return value||fallback;
  }

  function forecastStyle(hours){
    const style=FORECAST_STYLES[hours]||FORECAST_STYLES[12];
    return {...style,color:cssValue(style.variable,style.fallback)};
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

  function clamp(value,min,max){
    return Math.max(min,Math.min(max,value));
  }

  function boxesOverlap(a,b){
    const gap=5;
    return !(a.right+gap<b.left||a.left-gap>b.right||a.bottom+gap<b.top||a.top-gap>b.bottom);
  }

  function placePointLabel(entry,index,occupied,bounds){
    const width=clamp(entry.text.length*6.25+16,82,138),height=22;
    const lanes=[-30,32,-56,58,-82,84];
    const ordered=[...lanes.slice(index%lanes.length),...lanes.slice(0,index%lanes.length)];
    const shifts=[0,-width*.42,width*.42];
    let fallback=null;
    for(const offset of ordered){
      for(const shift of shifts){
        const cx=clamp(entry.x+shift,bounds.left+width/2,bounds.right-width/2);
        const cy=clamp(entry.y+offset,bounds.top+height/2,bounds.bottom-height/2);
        const box={left:cx-width/2,right:cx+width/2,top:cy-height/2,bottom:cy+height/2,cx,cy,width,height};
        fallback=box;
        if(!occupied.some(other=>boxesOverlap(box,other))){
          occupied.push(box);
          return box;
        }
      }
    }
    occupied.push(fallback);
    return fallback;
  }

  function drawPointLabel(svg,entry,index,occupied,bounds){
    const box=placePointLabel(entry,index,occupied,bounds);
    const edgeY=box.cy>entry.y?box.top:box.bottom;
    svg.appendChild(svgNode('line',{x1:entry.x,y1:entry.y,x2:box.cx,y2:edgeY,stroke:entry.color,'stroke-width':1.2,opacity:.72}));
    svg.appendChild(svgNode('rect',{x:box.left,y:box.top,width:box.width,height:box.height,rx:5,fill:'var(--panel, #fff)',stroke:entry.color,'stroke-width':1.4}));
    svg.appendChild(svgNode('text',{x:box.cx,y:box.cy+4,'text-anchor':'middle','font-size':11,'font-weight':700,fill:'var(--ink, #1b2c24)'},entry.text));
  }

  function forecastMark(point,x,y,color){
    let mark;
    const shape=forecastStyle(point.hours).shape;
    if(shape==='diamond') mark=svgNode('rect',{x:x-4.3,y:y-4.3,width:8.6,height:8.6,transform:`rotate(45 ${x} ${y})`,fill:'var(--panel, #fff)',stroke:color,'stroke-width':2.7});
    else if(shape==='square') mark=svgNode('rect',{x:x-5,y:y-5,width:10,height:10,rx:1,fill:'var(--panel, #fff)',stroke:color,'stroke-width':2.7});
    else if(shape==='triangle') mark=svgNode('polygon',{points:`${x},${y-5.8} ${x+5.5},${y+4.5} ${x-5.5},${y+4.5}`,fill:'var(--panel, #fff)',stroke:color,'stroke-width':2.7,'stroke-linejoin':'round'});
    else mark=svgNode('circle',{cx:x,cy:y,r:5,fill:'var(--panel, #fff)',stroke:color,'stroke-width':2.7});
    mark.appendChild(svgNode('title',{},`Previsão +${point.hours} h: ${fmtLevel(point.cm)} para ${fmtWhen(point.time)}`));
    return mark;
  }

  function axisTimeLabel(d,spanHours,crossDay){
    if(spanHours>72) return d.toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit'});
    if(crossDay) return d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(',',' ');
    return d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',hour:'2-digit',minute:'2-digit'});
  }

  function observedPath(points,X,Y){
    const maxGapMs=90*60*1000;
    return points.map((p,index)=>{
      const startsNew=index===0||p.time-points[index-1].time>maxGapMs;
      return (startsNew?'M':'L')+X(p.time.getTime()).toFixed(1)+','+Y(p.cm).toFixed(1);
    }).join(' ');
  }

  function drawChart(points,items,cota,options){
    const opts=Object.assign({svgId:'river-level-chart',emptyId:'overview-empty',periodLabel:'últimas 24 horas',tickCount:6,emptyText:'Carregando histórico e previsão ao vivo…'},options||{});
    const svg=document.getElementById(opts.svgId);
    const empty=document.getElementById(opts.emptyId);
    if(!svg) return;
    svg.replaceChildren();
    const anchor=points.length?points[points.length-1]:null;
    if(!points.length&&!items.length){
      if(empty){ empty.classList.add('show'); empty.textContent=state.historyError?'Histórico indisponível neste momento. A previsão ao vivo continua sendo consultada.':opts.emptyText; }
      return;
    }
    if(empty) empty.classList.remove('show');

    const measuredWidth=svg.getBoundingClientRect().width;
    const W=clamp(Math.round(measuredWidth||960),360,960),H=320;
    const compact=W<560,m={l:compact?56:68,r:compact?68:82,t:30,b:50};
    const tickCount=compact?4:opts.tickCount;
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
    const all=[...points,...items];
    const times=all.map(p=>p.time.getTime()).filter(Number.isFinite);
    let xMin=opts.windowHours&&anchor?anchor.time.getTime()-opts.windowHours*36e5:Math.min(...times);
    let xMax=Math.max(...times);
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

    const spanHours=(xMax-xMin)/36e5;
    const descText=items.length
      ?`Nível do rio observado nas ${opts.periodLabel}. A linha azul mostra observações e cada horizonte de previsão tem cor, traçado, marcador e rótulo próprios.`
      :`Nível do rio observado nas ${opts.periodLabel}, em linha azul. Lacunas de telemetria não são ligadas por linhas.`;
    const desc=svgNode('desc',{},descText);
    svg.append(desc);

    for(let i=0;i<5;i++){
      const v=yMin+(yMax-yMin)*i/4,y=Y(v);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'var(--panorama-grid, #dfe7e2)','stroke-width':1}));
      svg.appendChild(svgNode('text',{x:m.l-10,y:y+4,'text-anchor':'end','font-size':11,fill:'var(--muted, #6c7a72)'},nf1.format(v/100)+' m'));
    }
    for(let i=0;i<tickCount;i++){
      const t=xMin+(xMax-xMin)*i/(tickCount-1),x=X(t),d=new Date(t);
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:'var(--panorama-grid-soft, #edf2ef)','stroke-width':1}));
      svg.appendChild(svgNode('text',{x,y:H-m.b+22,'text-anchor':'middle','font-size':11,fill:'var(--muted, #6c7a72)'},axisTimeLabel(d,spanHours,crossDay)));
    }
    svg.appendChild(svgNode('text',{x:16,y:(m.t+H-m.b)/2,transform:`rotate(-90 16 ${(m.t+H-m.b)/2})`,'text-anchor':'middle','font-size':11,fill:'var(--muted, #6c7a72)'},'Nível do rio (m)'));

    if(showThreshold){
      const y=Y(cota);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'var(--panorama-threshold, #c0392b)','stroke-width':1.5,'stroke-dasharray':'3 5'}));
      svg.appendChild(svgNode('text',{x:W-m.r,y:y-7,'text-anchor':'end','font-size':11,'font-weight':700,fill:'var(--panorama-threshold, #a12d25)'},'cota oficial '+fmtLevel(cota)));
    }

    if(points.length>1){
      const d=observedPath(points,X,Y);
      svg.appendChild(svgNode('path',{d,fill:'none',stroke:'var(--panorama-observed, #1e5fbf)','stroke-width':3,'stroke-linejoin':'round','stroke-linecap':'round'}));
    }
    const labels=[];
    if(anchor){
      const x=X(anchor.time.getTime()),y=Y(anchor.cm);
      const observedColor=cssValue('--panorama-observed','#1e5fbf');
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:observedColor,'stroke-width':1,'stroke-dasharray':'2 4',opacity:.55}));
      const dot=svgNode('circle',{cx:x,cy:y,r:5.5,fill:observedColor,stroke:'var(--panel, #fff)','stroke-width':2});
      dot.appendChild(svgNode('title',{},`Agora: ${fmtLevel(anchor.cm)} em ${fmtWhen(anchor.time)}`));
      svg.appendChild(dot);
      labels.push({x,y,color:observedColor,text:`agora · ${fmtLevel(anchor.cm)}`});
    }

    if(anchor&&items.length){
      let previous=anchor;
      items.forEach(p=>{
        const x=X(p.time.getTime()),y=Y(p.cm);
        const px=X(previous.time.getTime()),py=Y(previous.cm),style=forecastStyle(p.hours);
        svg.appendChild(svgNode('line',{x1:px,y1:py,x2:x,y2:y,fill:'none',stroke:style.color,'stroke-width':3,'stroke-dasharray':style.dash,'stroke-linecap':'round'}));
        svg.appendChild(forecastMark(p,x,y,style.color));
        labels.push({x,y,color:style.color,text:`+${p.hours} h · ${fmtLevel(p.cm)}`});
        previous=p;
      });
    }
    const occupied=[];
    labels.forEach((entry,index)=>drawPointLabel(svg,entry,index,occupied,{left:m.l,right:W-m.r,top:m.t,bottom:H-m.b}));
  }

  function legendEntry(label,className){
    const span=document.createElement('span');
    const swatch=document.createElement('i');
    swatch.className='legend-line '+className;
    span.append(swatch,document.createTextNode(label));
    return span;
  }

  function renderLegend(items){
    const box=document.getElementById('overview-legend');
    if(!box) return;
    box.replaceChildren(legendEntry('Nível observado','observed'));
    items.forEach(point=>box.appendChild(legendEntry(`Previsão +${point.hours} h`,`forecast horizon-${point.hours}`)));
    box.appendChild(legendEntry('Cota oficial, quando próxima da escala','threshold'));
  }

  function renderWeekCoverage(points){
    const status=document.getElementById('overview-week-status');
    const accessible=document.getElementById('overview-week-accessible');
    if(!status&&!accessible) return;
    if(!points.length){
      if(status) status.textContent='Ainda não há observações disponíveis para esta janela.';
      if(accessible) accessible.textContent='Gráfico semanal sem observações disponíveis.';
      return;
    }
    const first=points[0],last=points[points.length-1];
    const desiredStart=last.time.getTime()-168*36e5;
    const missingStart=first.time.getTime()-desiredStart>90*60*1000;
    const gaps=[];
    for(let i=1;i<points.length;i++){
      if(points[i].time-points[i-1].time>90*60*1000) gaps.push([points[i-1],points[i]]);
    }
    const parts=[];
    if(missingStart) parts.push(`Histórico disponível desde ${fmtWhen(first.time)}; o trecho anterior da janela permanece vazio`);
    else parts.push('Janela de sete dias disponível');
    if(gaps.length) parts.push(`${gaps.length} ${gaps.length===1?'lacuna aparece':'lacunas aparecem'} sem linha para não simular dados ausentes`);
    if(status) status.textContent=parts.join('. ')+'.';
    if(accessible) accessible.textContent=`Histórico do nível do rio de ${fmtWhen(first.time)} até ${fmtWhen(last.time)}, com ${points.length} observações. ${parts.join('. ')}.`;
  }

  function renderMetrics(current,items,trend,flood,cota){
    const box=document.getElementById('overview-metrics');
    if(!box) return;
    const cards=[];
    cards.push(`<article class="overview-metric"><span>Nível do rio agora</span><strong>${fmtLevel(current&&current.cm!==undefined?current.cm:null)}</strong><small>${current?fmtWhen(current.time):'aguardando telemetria'}</small></article>`);
    items.forEach(p=>cards.push(`<article class="overview-metric forecast horizon-${p.hours}"><span>Previsão +${p.hours} h</span><strong>${fmtLevel(p.cm)}</strong><small>para ${fmtWhen(p.time)}${p.alternate?' · modelo cascata':''}</small></article>`));
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
    const allPoints=observedPoints(state.history,state.live);
    const points=pointsInWindow(allPoints,24);
    const weekPoints=pointsInWindow(allPoints,168);
    const current=allPoints.length?allPoints[allPoints.length-1]:null;
    const items=forecasts(state.live,current);
    const trend=trendInfo(points);
    const flood=floodInfo(current,items,state.config.cotaInundCm);
    drawChart(points,items,state.config.cotaInundCm,{windowHours:24});
    drawChart(weekPoints,[],state.config.cotaInundCm,{
      svgId:'river-week-chart',
      emptyId:'overview-week-empty',
      periodLabel:'últimos 7 dias',
      tickCount:8,
      windowHours:168,
      emptyText:'Ainda não há histórico observável para os últimos sete dias.'
    });
    renderLegend(items);
    renderWeekCoverage(weekPoints);
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
      const prefix=state.historyError?'O histórico não carregou; os horizontes ao vivo continuam visíveis.':'Linha azul: níveis observados. Cada horizonte da previsão pontual da RNA tem cor e marcador próprios.';
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
    requestAnimationFrame(render);
    if(mode==='panorama') window.scrollTo({top:0,behavior:'smooth'});
  }

  function scheduleResizeRender(){
    clearTimeout(state.resizeTimer);
    state.resizeTimer=setTimeout(render,80);
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
    if(state.resizeObserver) state.resizeObserver.disconnect();
    if('ResizeObserver' in window){
      state.resizeObserver=new ResizeObserver(scheduleResizeRender);
      ['river-level-chart','river-week-chart'].forEach(id=>{
        const svg=document.getElementById(id);
        if(svg&&svg.parentElement) state.resizeObserver.observe(svg.parentElement);
      });
    }
    render();
  }

  function update(live){
    state.live=live||null;
    render();
  }

  window.PREVINE_PANORAMA={init,update,setMode};
})();
