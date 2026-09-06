/* Source for the self-contained research room. Pure functions also run in Node QA. */
(function () {
  'use strict';
  const HOUR = 3600000;
  const number = value => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const time = value => {
    let iso = String(value).replace(' ', 'T');
    if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) iso += '-03:00';
    return Date.parse(iso);
  };
  const html = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  function zoomWindow(start, end, a, b, count) {
    const low = Math.max(0, Math.min(1, Math.min(a, b)));
    const high = Math.max(0, Math.min(1, Math.max(a, b)));
    return [Math.max(0, start + Math.round((end-start)*low)), Math.min(count-1, start + Math.round((end-start)*high))];
  }
  function nearestIndex(series, timestamp) {
    let best = 0;
    series.forEach((row, i) => { if (Math.abs(time(row[0])-timestamp) < Math.abs(time(series[best][0])-timestamp)) best=i; });
    return best;
  }
  function gaps(series) {
    let missingHours=0, missingValues=0, invalidOrder=0;
    series.forEach((r,i) => {
      if (number(r[1]) === null || number(r[2]) === null) missingValues++;
      if (i) { const delta=(time(r[0])-time(series[i-1][0]))/HOUR; if (delta>1.5) missingHours+=Math.max(0,Math.round(delta)-1); if (!(delta>0)) invalidOrder++; }
    });
    return {missingHours,missingValues,invalidOrder};
  }
  const contourAt = (city, level) => city.contours.find(c => c.level===level) || null;
  function aspect(bounds) { return (bounds.east-bounds.west)*Math.cos((bounds.north+bounds.south)*Math.PI/360)/(bounds.north-bounds.south); }
  const api = {number,time,html,zoomWindow,nearestIndex,gaps,contourAt,aspect};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  if (typeof document === 'undefined') return;

  const $ = id => document.getElementById(id), canvas=$('chart'), ctx=canvas.getContext('2d');
  const formats = [0,1,2,3].map(d => new Intl.NumberFormat('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d}));
  const f = (v,d=1) => number(v)===null ? '—' : formats[d].format(Number(v));
  const dateFmt = new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  const stamp = value => Number.isFinite(time(value)) ? dateFmt.format(time(value)) : 'horário inválido';
  const state = {key:DATA.events.some(e=>e.key==='mucum-E24')?'mucum-E24':DATA.events[0].key,city:'all',start:0,end:0,hover:null,drag:null,mapCity:null,level:18,selectedCell:null,selectedService:null,map:{scale:1,tx:0,ty:0}};
  const current = () => DATA.events.find(e=>e.key===state.key);
  const city = () => DATA.spatial[current().city_key];
  const visible = () => current().series.slice(state.start,state.end+1);
  const filtered = () => DATA.events.filter(e=>state.city==='all'||state.city===e.city_key);
  const niceStatus = e => e.status==='fechado' ? 'ajuste por evento' : e.status;
  const statusClass = e => e.status.includes('independente')?'pill test':'pill warn';
  function text(id,value) { $(id).textContent=value; }
  function renderSummary() {
    text('totalEvents',DATA.events.length); text('mucumEvents',DATA.events.filter(e=>e.city_key==='mucum').length);
    text('santaEvents',DATA.events.filter(e=>e.city_key==='santa_tereza').length);
    text('independentEvents',DATA.events.filter(e=>e.status.includes('independente')).length);
    const c=DATA.calibration,a=c.incremental_area_events||[],t=c.target_rain_events||[],best=c.two_station_best||{};
    text('calibrationStatus',`Generalização ainda não demonstrada. Apenas ${a.length} evento(s) com entradas completas para as três áreas incrementais. Bons ajustes individuais abaixo não substituem validação com parâmetros comuns.`);
    text('incrementalAreaCount',a.length);text('incrementalAreaDetail',a.length?a.join(', '):'nenhum evento completo');
    text('targetRainCount',t.length);text('targetRainDetail',(t.map(x=>String(x).startsWith('E')?x:`E${x}`).join(', ')||'nenhum evento completo')+` · ${c.target_rain_status==='diagnostic_only'?'somente diagnóstico':'status não reconciliado'}. ${c.target_rain_reason||''}`);
    text('twoStationScore',f(best.mean_nse,2));
    text('twoStationDetail',`NSE médio · erro temporal absoluto médio ${f(best.mean_abs_peak_lag_hours)} h · erro de pico ${f(number(best.mean_peak_relative_error)===null?null:best.mean_peak_relative_error*100,1)}%. Experimento distinto dos ajustes por evento.`);
  }
  function populateEvents() {
    const select=$('eventSelect');select.replaceChildren();
    for (const label of [...new Set(filtered().map(e=>e.municipality))]) {
      const group=document.createElement('optgroup');group.label=label;
      filtered().filter(e=>e.municipality===label).forEach(e=>{const o=document.createElement('option');o.value=e.key;o.textContent=`${e.id} · ${e.period.split(' ')[0]} · ${e.model}`;group.append(o);});
      select.append(group);
    }
    if (!filtered().some(e=>e.key===state.key)) state.key=filtered()[0].key;
    select.value=state.key;
  }
  function peakDate(e,col) {
    const candidates=e.series.filter(r=>number(r[col])!==null);
    return candidates.length?stamp(candidates.reduce((a,b)=>b[col]>a[col]?b:a)[0]):'—';
  }
  function renderEvent() {
    const e=current(),m=e.metrics;state.start=0;state.end=Math.max(0,e.series.length-1);state.hover=null;state.drag=null;
    text('eventTitle',`${e.municipality} · ${e.id}`);text('eventSubtitle',`${e.period} · ${e.model} · ${e.variable}`);
    text('eventStatus',niceStatus(e));$('eventStatus').className=statusClass(e);
    text('obsPeak',f(m.observed_peak));text('modelPeak',f(m.model_peak));text('unitObs',e.unit);text('unitModel',e.unit);
    text('peakError',number(m.peak_error)===null?'—':f(m.peak_error*100,2)+'%');text('peakLag',number(m.lag)===null?'—':(m.lag>0?'+':'')+f(m.lag)+' h');
    text('pairs',f(m.pairs,0));text('fitMetric',m.nse==null?f(m.mae):f(m.nse,2));text('fitLabel',m.nse==null?'MAE · '+e.unit:'NSE');
    text('chartTitle',`Observado × ${e.model}`);text('modelLegend',e.model);
    text('peakDates',`Picos nos dados disponíveis: observado ${peakDate(e,1)} · modelo ${peakDate(e,2)} (BRT)`);
    text('reading',e.city_key==='mucum' ?
      (niceStatus(e)==='ajuste por evento'?'Ajuste retrospectivo de um evento, no pacote agregado de Muçum. Não é resultado do novo corredor BHO6 nem validação entre eventos.':'Diagnóstico histórico não promovido. Leia as lacunas e os erros antes de interpretar este resultado.')+
      ' Os indicadores usam o evento completo; zoom não recalcula a calibração. Erro temporal zero não demonstra antecipação de uma cheia.' :
      `Santa Tereza: ${niceStatus(e)} da RNA de nível, não HEC-HMS de vazão. A separação declarada no pacote não equivale a validação operacional. Indicadores do evento completo.`);
    text('selectionNote',e.selection_note||'');$('selectionNote').hidden=!e.selection_note;$('selectionNote').style.display=e.selection_note?'block':'none';
    $('metricsLink').href='../'+e.metrics_source;$('seriesLink').href='../'+e.series_source;
    $('manifestLink').href='../assets/data/'+(e.city_key==='mucum'?'mucum_eventwise_replay_calibrated':'santa_tereza_eventwise_replay_rna_2h')+'/eventwise_manifest.json';
    if (state.mapCity!==e.city_key) {state.mapCity=e.city_key;state.level=Math.min(e.city_key==='mucum'?18:15,city().level_max);state.map={scale:1,tx:0,ty:0};state.selectedCell=null;state.selectedService=null;}
    renderMap();renderEventsTable();syncRange();resize();
  }
  function renderEventsTable() {
    $('eventRows').replaceChildren();text('tableScope',`${filtered().length} eventos`);
    filtered().forEach(e=>{const tr=document.createElement('tr'),m=e.metrics;tr.classList.toggle('selected',e.key===state.key);
      tr.innerHTML=`<td><button class="event-button" type="button" ${e.key===state.key?'aria-current="true"':''}>${html(e.municipality)} · ${html(e.id)}</button></td><td>${html(e.municipality)}</td><td>${html(e.model)}</td><td>${html(e.period.split(' → ')[0])}</td><td>${f(m.observed_peak)} ${html(e.unit)}</td><td>${f(m.model_peak)} ${html(e.unit)}</td><td>${m.peak_error==null?'—':f(m.peak_error*100,2)+'%'}</td><td><span class="tiny-pill warn">${html(niceStatus(e))}</span></td>`;
      tr.addEventListener('click',()=>{state.key=e.key;$('eventSelect').value=e.key;renderEvent();$('eventTitle').focus();});$('eventRows').append(tr);
    });
  }
  function syncRange() {
    ['chartStart','chartEnd'].forEach((id,i)=>{const el=$(id);el.max=Math.max(0,current().series.length-1);el.value=i?state.end:state.start;el.disabled=current().series.length<2;el.setAttribute('aria-valuetext',current().series[Number(el.value)]?stamp(current().series[Number(el.value)][0])+' BRT':'sem série');});
    const s=visible(),g=gaps(s);
    text('chartQuality',`${g.missingHours} hora(s) ausente(s) entre registros · ${g.missingValues} registro(s) sem par completo. Linhas são interrompidas nas lacunas; nenhum valor é preenchido.${g.invalidOrder?' Atenção: ordem temporal inconsistente.':''}`);
    text('seriesCaption',`${current().municipality} · ${current().id} · ${current().unit} · horários BRT do intervalo`);
    $('seriesRows').innerHTML=s.map(r=>`<tr><td>${html(r[0].replace('T',' '))}</td><td>${f(r[1])}</td><td>${f(r[2])}</td></tr>`).join('');
    text('srSummary',`${current().model}. Pico observado ${f(current().metrics.observed_peak)} ${current().unit}; pico modelo ${f(current().metrics.model_peak)} ${current().unit}. ${s.length} registros no intervalo; ${g.missingHours} horas ausentes.`);
    text('pointReadout','Selecione um horário com as setas no gráfico.');draw();
  }
  function plot() {
    const w=canvas.clientWidth,h=canvas.clientHeight,pad={l:57,r:18,t:20,b:45},s=visible(),first=s.length?time(s[0][0]):0,last=s.length?time(s[s.length-1][0]):1;
    const vals=s.flatMap(r=>[...($('showObserved').checked?[number(r[1])]:[]),...($('showModel').checked?[number(r[2])]:[])]).filter(v=>v!==null);
    const lo=Math.min(0,...vals),hi=Math.max(1,...vals)*1.08;
    return {w,h,pad,s,first,last,x:t=>pad.l+(t-first)/Math.max(1,last-first)*(w-pad.l-pad.r),y:v=>pad.t+(hi-v)/(hi-lo)*(h-pad.t-pad.b),lo,hi};
  }
  function draw() {
    const {w,h,pad,s,first,last,x,y,lo,hi}=plot();if(!w||!h)return;ctx.clearRect(0,0,w,h);$('tip').style.display='none';
    ctx.font='12px system-ui';ctx.textAlign='left';ctx.setLineDash([]);ctx.lineWidth=1;
    if (!s.length) {ctx.fillStyle='#405c65';ctx.fillText('Sem série disponível para este evento.',12,40);text('rangeText','sem série');return;}
    for(let i=0;i<=4;i++){const val=hi-(hi-lo)*i/4,yy=y(val);ctx.strokeStyle='#dcebed';ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle='#465e67';ctx.fillText(f(val,0),3,yy+4);}
    const ticks=Math.max(1,Math.floor((w-pad.l-pad.r)/140));
    for(let i=0;i<=ticks;i++){const t=first+(last-first)*i/ticks,xx=x(t);ctx.fillStyle='#465e67';ctx.textAlign=i===0?'left':i===ticks?'right':'center';ctx.fillText(dateFmt.format(t),xx,h-16);}
    ctx.textAlign='left';
    for (const [col,color,show] of [[1,'#0879c9',$('showObserved').checked],[2,'#d86613',$('showModel').checked]]) {
      if(!show)continue;ctx.beginPath();let previous=null;
      for(const r of s){const value=number(r[col]),t=time(r[0]);if(value===null){previous=null;continue;}const xx=x(t),yy=y(value);if(previous===null||t-previous>1.5*HOUR||t<=previous)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy);previous=t;}
      ctx.strokeStyle=color;ctx.lineWidth=2.6;ctx.lineJoin='round';ctx.stroke();
    }
    if(state.drag){ctx.fillStyle='#0879c925';ctx.fillRect(Math.min(...state.drag),pad.t,Math.abs(state.drag[1]-state.drag[0]),h-pad.t-pad.b);}
    if(state.hover!==null&&s[state.hover]) {
      const r=s[state.hover],xx=x(time(r[0]));ctx.strokeStyle='#244c62';ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,h-pad.b);ctx.stroke();ctx.setLineDash([]);
      for(const [col,color,show] of [[1,'#0879c9',$('showObserved').checked],[2,'#d86613',$('showModel').checked]])if(show&&number(r[col])!==null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(xx,y(r[col]),4,0,Math.PI*2);ctx.fill();}
      const msg=`${stamp(r[0])} BRT · observado ${f(r[1])} · ${current().model} ${f(r[2])} ${current().unit}`;text('pointReadout',msg);
    }
    text('rangeText',`${stamp(s[0][0])} → ${stamp(s[s.length-1][0])} BRT · ${s.length} registros`);
  }
  function resize(){const d=window.devicePixelRatio||1;canvas.width=Math.max(1,Math.round(canvas.clientWidth*d));canvas.height=Math.max(1,Math.round(canvas.clientHeight*d));ctx.setTransform(d,0,0,d,0,0);draw();fitMap();}
  function indexAt(pixel){const p=plot(),t=p.first+Math.max(0,Math.min(1,(pixel-p.pad.l)/(p.w-p.pad.l-p.pad.r)))*(p.last-p.first);return nearestIndex(p.s,t);}
  canvas.addEventListener('pointermove',ev=>{const px=ev.clientX-canvas.getBoundingClientRect().left;if(state.drag)state.drag[1]=px;else state.hover=indexAt(px);draw();});
  canvas.addEventListener('pointerdown',ev=>{state.hover=indexAt(ev.clientX-canvas.getBoundingClientRect().left);if(ev.pointerType==='mouse'){const px=ev.clientX-canvas.getBoundingClientRect().left;state.drag=[px,px];canvas.setPointerCapture(ev.pointerId);}draw();});
  canvas.addEventListener('pointerup',ev=>{if(!state.drag)return;const [a,b]=state.drag;if(Math.abs(b-a)>18){const old=state.start,ia=indexAt(a),ib=indexAt(b);state.start=old+Math.min(ia,ib);state.end=old+Math.max(ia,ib);}state.drag=null;state.hover=null;if(canvas.hasPointerCapture(ev.pointerId))canvas.releasePointerCapture(ev.pointerId);syncRange();});
  canvas.addEventListener('pointercancel',()=>{state.drag=null;draw();});
  canvas.addEventListener('pointerleave',()=>{if(!state.drag){state.hover=null;draw();}});
  canvas.addEventListener('dblclick',()=>$('resetZoom').click());
  canvas.addEventListener('keydown',ev=>{const n=visible().length;if(ev.key==='Escape'){$('resetZoom').click();return;}if(!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key)||!n)return;ev.preventDefault();state.hover=ev.key==='Home'?0:ev.key==='End'?n-1:Math.max(0,Math.min(n-1,(state.hover??-1)+(ev.key==='ArrowRight'?1:-1)));draw();text('srSummary',$('pointReadout').textContent);});
  $('chartStart').addEventListener('input',()=>{state.start=Math.min(Number($('chartStart').value),state.end);state.hover=null;syncRange();});
  $('chartEnd').addEventListener('input',()=>{state.end=Math.max(Number($('chartEnd').value),state.start);state.hover=null;syncRange();});

  function svg(tag,attrs={}) {const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e;}
  function point(lon,lat){const b=city().bounds,height=1000/aspect(b);return {x:(lon-b.west)/(b.east-b.west)*1000,y:(b.north-lat)/(b.north-b.south)*height};}
  function geometry(g){const rings=g.type==='Polygon'?g.coordinates:g.coordinates.flat();return rings.map(r=>r.map((p,i)=>{const q=point(...p);return `${i?'L':'M'}${q.x.toFixed(2)},${q.y.toFixed(2)}`;}).join(' ')+'Z').join(' ');}
  function fitMap(){const v=$('mapViewport'),r=aspect(city().bounds),w=Math.min(v.clientWidth,v.clientHeight*r),h=w/r,c=$('mapContent');c.style.width=w+'px';c.style.height=h+'px';c.style.left=(v.clientWidth-w)/2+'px';c.style.top=(v.clientHeight-h)/2+'px';c.style.transform=`translate(${state.map.tx}px,${state.map.ty}px) scale(${state.map.scale})`;}
  function ensureMapControls(){
    const panel=$('mapViewport').parentElement;
    if(!$('showContour')){
      const tools=document.createElement('div');tools.className='map-tools';tools.innerHTML='<span class="map-tools-title">Camadas</span><label><input id="showContour" type="checkbox" checked> Contorno</label><label><input id="showGrid" type="checkbox" checked> Grade 200 m</label><label><input id="showServices" type="checkbox" checked> Inventário de serviços</label><label><input id="showLabels" type="checkbox"> Nomes</label>';
      panel.insertBefore(tools,$('mapViewport'));panel.insertBefore(document.querySelector('.level-box'),tools);
      const badge=$('mapBadge');panel.insertBefore(badge,$('mapViewport'));
      const controls=document.querySelector('.map-controls');panel.insertBefore(controls,$('mapViewport'));
      for(const [label,dx,dy] of [['Mover mapa à esquerda',50,0],['Mover mapa à direita',-50,0],['Mover mapa para cima',0,50],['Mover mapa para baixo',0,-50]]){const b=document.createElement('button');b.className='button pan-button';b.type='button';b.textContent=dx?dx>0?'←':'→':dy>0?'↑':'↓';b.setAttribute('aria-label',label);b.addEventListener('click',()=>{state.map.tx+=dx;state.map.ty+=dy;fitMap();});controls.append(b);}
      const list=document.createElement('div');list.id='mapPointList';list.className='map-point-list';list.setAttribute('aria-label','Inventário, sem confirmação de disponibilidade');panel.insertBefore(list,$('cellInfo'));
      ['showContour','showGrid','showServices','showLabels'].forEach(id=>$(id).addEventListener('change',renderMap));
    }
  }
  function renderMap(){
    ensureMapControls();const c=city(),root=$('mapSvg'),level=state.level,contour=contourAt(c,level),pub=c.published[String(level)];
    text('mapTitle',`${c.label} · território em estudo`);text('mapSubtitle',`${c.background_label} · ${c.crs}. Fundo de terreno, não imagem de satélite.`);
    $('mapBg').src=c.background;$('mapBg').alt=`${c.label}: terreno para referência, não profundidade de inundação`;
    root.setAttribute('viewBox',`0 0 1000 ${1000/aspect(c.bounds)}`);root.replaceChildren();root.classList.toggle('show-labels',$('showLabels').checked);
    $('levelRange').min=c.level_min;$('levelRange').max=c.level_max;$('levelRange').value=level;text('levelValue',f(level)+' m');
    $('levelRange').setAttribute('aria-valuetext',`${level} metros, cenário manual independente do gráfico`);
    if(contour&&$('showContour').checked)root.append(svg('path',{d:geometry(contour.geometry),class:'flood','fill-rule':'evenodd','pointer-events':'none','aria-hidden':'true'}));
    const grid=svg('g',{'aria-label':'Grade estatística de 200 metros'});
    if($('showGrid').checked)c.grid.forEach((cell,i)=>{const active=state.selectedCell===i||(state.selectedCell===null&&i===0),p=svg('path',{d:geometry(cell.geometry),class:'grid-cell'+(state.selectedCell===i?' selected':''),'fill-rule':'evenodd',role:'button',tabindex:active?'0':'-1','aria-label':`${cell.id||'Célula '+(i+1)}; população agregada ${f(cell.pop,0)}`});p.dataset.cell=String(i);p.addEventListener('click',()=>selectCell(i));p.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();selectCell(i);}else if(['ArrowLeft','ArrowUp','ArrowRight','ArrowDown'].includes(ev.key)){ev.preventDefault();const paths=[...root.querySelectorAll('.grid-cell')],next=(paths.indexOf(p)+(ev.key==='ArrowLeft'||ev.key==='ArrowUp'?-1:1)+paths.length)%paths.length;paths.forEach(item=>item.tabIndex=-1);paths[next].tabIndex=0;paths[next].focus();}});grid.append(p);});root.append(grid);
    const select=$('cellSelect'),previous=state.selectedCell;select.replaceChildren(new Option('Selecione uma célula',''));
    c.grid.forEach((cell,i)=>select.append(new Option(`${cell.id||'Célula '+(i+1)} · população ${f(cell.pop,0)}`,String(i))));select.value=previous===null?'':String(previous);
    const points=svg('g',{'aria-label':'Inventário de serviços'}),list=$('mapPointList');list.replaceChildren();
    if($('showServices').checked)c.points.forEach((p,i)=>{
      if(number(p.lon)===null||number(p.lat)===null)return;const q=point(p.lon,p.lat),kind=p.kind.toLowerCase(),cls=kind.includes('abrigo')?'shelter':kind.includes('bombeiro')?'fire':kind.includes('saúde')||kind.includes('hospital')?'health':'school';
      const group=svg('g',{'data-service':i,class:'service-group',role:'button',tabindex:'0','aria-label':`${p.kind}: ${p.name}; cadastro sem disponibilidade confirmada`}),hit=svg('circle',{cx:q.x,cy:q.y,r:27,fill:'transparent'}),circle=svg('circle',{cx:q.x,cy:q.y,r:14,class:`service ${cls}${state.selectedService===i?' selected':''}`});
      const index=svg('text',{x:q.x,y:q.y,class:'service-index'});index.textContent=i+1;group.append(hit,circle,index);group.addEventListener('click',()=>showPoint(i));group.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();showPoint(i);}});
      const label=svg('text',{x:q.x+19,y:q.y+5,class:'service-label','pointer-events':'none'});label.textContent=p.name.length>28?p.name.slice(0,27)+'…':p.name;group.append(label);points.append(group);
      const button=document.createElement('button');button.type='button';button.className='map-point-button';button.setAttribute('aria-pressed',String(state.selectedService===i));button.textContent=`${i+1} · ${p.kind}: ${p.name}`;button.addEventListener('click',()=>showPoint(i));list.append(button);
    });root.append(points);
    document.querySelectorAll('[data-legend="contour"]').forEach(el=>el.hidden=!$('showContour').checked);document.querySelectorAll('[data-legend="grid"]').forEach(el=>el.hidden=!$('showGrid').checked);document.querySelectorAll('[data-legend="services"]').forEach(el=>el.hidden=!$('showServices').checked);
    text('mapStatus',`Fonte disponível: ${c.level_min}–${c.level_max} m. Não é o limite de subida do rio.`);
    $('mapBadge').innerHTML=`<strong>${contour?'Cenário manual':'Sem geometria para o cenário'} · ${f(level)} m · ${$('showContour').checked?'contorno visível':'contorno oculto'}</strong>`+
      (contour?(pub?`${f(pub.contour_area_ha)} ha · ${f(pub.cells_200m_touched,0)} células tocadas · até ${f(pub.population_upper_bound_whole_touched_cells,0)} moradores nas células inteiras (limite superior, não pessoas atingidas confirmadas).`:'Geometria disponível; sem estimativa agregada publicada para este nível.'):'Nenhum outro contorno é substituído automaticamente.');
    const outsideGrid=(c.grid_total??c.grid.length)-c.grid.length,outsidePoints=(c.points_total??c.points.length)-c.points.length;
    text('spatialNote',`A cor azul do fundo indica terreno na imagem de origem, não água prevista. O contorno não vem da curva HEC-HMS/RNA. Datum vertical e conversão régua–MDT/HAND não reconciliados. Acima de ${c.level_max} m, esta fonte não fornece mancha; isso não significa que o rio pare nesse nível. O seletor mostra ${c.grid.length} células e ${c.points.length} serviços que cruzam este enquadramento; ${outsideGrid} células e ${outsidePoints} serviços do cadastro municipal ficaram fora da imagem. Serviços cadastrados não confirmam abrigo disponível, rota ou capacidade.`);
    if(state.selectedCell!==null)selectCell(state.selectedCell);else if(state.selectedService!==null)showPoint(state.selectedService);else $('cellInfo').innerHTML='<strong>Explore o território</strong><p>Toque numa célula ou use o seletor. Os números representam população agregada, não casas ou pessoas localizadas. Os serviços estão listados por nome abaixo do mapa.</p>';
    fitMap();
  }
  function selectCell(index){const c=city().grid[index];if(!c)return;state.selectedCell=index;state.selectedService=null;$('cellSelect').value=String(index);document.querySelectorAll('.grid-cell').forEach(p=>{const chosen=Number(p.dataset.cell)===index;p.classList.toggle('selected',chosen);p.tabIndex=chosen?0:-1;});document.querySelectorAll('.service').forEach(p=>p.classList.remove('selected'));document.querySelectorAll('.map-point-button').forEach(p=>p.setAttribute('aria-pressed','false'));$('cellInfo').innerHTML=`<strong>${html(c.id||'Célula '+(index+1))}</strong><p>População agregada: <b>${f(c.pop,0)}</b> · domicílios: <b>${f(c.dom,0)}</b> · completude: <b>${html(c.pop_completude??'não informada')}</b>. Não é cadastro individual nem confirmação de exposição ao cenário.</p>`;}
  function showPoint(index){const p=city().points[index];if(!p)return;state.selectedService=index;state.selectedCell=null;$('cellSelect').value='';document.querySelectorAll('.grid-cell').forEach(p=>p.classList.remove('selected'));document.querySelectorAll('.service-group').forEach(g=>g.querySelector('.service').classList.toggle('selected',Number(g.dataset.service)===index));document.querySelectorAll('.map-point-button').forEach(b=>b.setAttribute('aria-pressed',String(b.textContent.startsWith((index+1)+' ·'))));$('cellInfo').innerHTML=`<strong>${index+1} · ${html(p.kind)}: ${html(p.name)}</strong><p>Fonte: ${html(p.source.split('/').pop())}. Cadastro não confirma abertura, capacidade, acessibilidade ou segurança durante a cheia. Não é destino de evacuação validado.</p>`;}
  $('cellSelect').addEventListener('change',()=>{if($('cellSelect').value!=='')selectCell(Number($('cellSelect').value));});
  $('mapZoomIn').addEventListener('click',()=>{state.map.scale=Math.min(6,state.map.scale*1.3);fitMap();});
  $('mapZoomOut').addEventListener('click',()=>{state.map.scale=Math.max(1,state.map.scale/1.3);if(state.map.scale===1){state.map.tx=0;state.map.ty=0;}fitMap();});
  $('mapReset').addEventListener('click',()=>{state.map={scale:1,tx:0,ty:0};fitMap();});
  let mapDrag=null;
  $('mapViewport').addEventListener('pointerdown',ev=>{if(ev.pointerType!=='mouse'||ev.target.closest('.grid-cell,.service-group'))return;mapDrag=[ev.clientX,ev.clientY];$('mapViewport').setPointerCapture(ev.pointerId);});
  $('mapViewport').addEventListener('pointermove',ev=>{if(!mapDrag)return;state.map.tx+=ev.clientX-mapDrag[0];state.map.ty+=ev.clientY-mapDrag[1];mapDrag=[ev.clientX,ev.clientY];fitMap();});
  ['pointerup','pointercancel'].forEach(type=>$('mapViewport').addEventListener(type,()=>mapDrag=null));
  $('levelRange').addEventListener('input',()=>{state.level=Number($('levelRange').value);renderMap();});
  $('citySelect').addEventListener('change',()=>{state.city=$('citySelect').value;populateEvents();renderEvent();});
  $('eventSelect').addEventListener('change',()=>{state.key=$('eventSelect').value;renderEvent();});
  ['showObserved','showModel'].forEach(id=>$(id).addEventListener('change',draw));
  $('resetZoom').addEventListener('click',()=>{state.start=0;state.end=Math.max(0,current().series.length-1);state.hover=null;syncRange();});
  $('mapBg').addEventListener('error',()=>text('mapSubtitle','Fundo de terreno indisponível. Consulte as fontes antes de interpretar as geometrias.'));
  window.addEventListener('resize',resize);renderSummary();populateEvents();renderEvent();
})();
