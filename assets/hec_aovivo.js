(function(){
  'use strict';

  // PESQUISA — não é alerta oficial. Lê o JSON do executor HEC-HMS ao vivo (produto previne-hec-bacia145-aovivo,
  // versao_esquema 1) e desenha o painel. Campos desconhecidos de versões novas são ignorados; campos ausentes viram “—”.
  const SVG_NS='http://www.w3.org/2000/svg';
  const CONFIG_URL='assets/data/hec_aovivo/config.json';
  const DEFAULTS={
    latest:'assets/data/hec_aovivo/latest.json',
    latest_raw:'',
    horas_desatualizada:8,
    horas_sem_previsao:24,
    esquema_suportado:1,
    mancha_santa_tereza:false,
    bankfull_santa_tereza_cm:400,
    curva_santa_tereza:'assets/data/hec_aovivo/curva_mucum_santa_tereza.json',
    contornos_santa_tereza:'assets/data/santa_tereza_inundacao/contornos_extravasamento.json'
  };
  const LOCAL=/^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  const PARAMS=new URLSearchParams(location.search);
  const H_MS=36e5;

  const PONTOS={
    MUCUM:{label:'Muçum',estacao:'86510000'},
    ENCANTADO:{label:'Encantado',estacao:'86720000'},
    LJJ:{label:'Linha José Júlio',estacao:'86472000'},
    SANTA_TEREZA:{label:'Santa Tereza',estacao:'86472600'},
    ESTRELA:{label:'Estrela',estacao:'86879300'}
  };
  const ORDEM_PONTOS=['MUCUM','ENCANTADO','LJJ','SANTA_TEREZA'];
  const CEN_ESTILO={
    ecmwf:{label:'ECMWF',cor:'--hec-ecmwf',fb:'#e8730c',w:3.4,dash:null,papel:'principal'},
    gfs:{label:'GFS',cor:'--hec-gfs',fb:'#6c3aa1',w:2.5,dash:'8 6',papel:'secundário'},
    zero:{label:'sem chuva',cor:'--hec-zero',fb:'#6f7f77',w:2.6,dash:'2 5',papel:'piso'}
  };
  const CORES_EXTRA=['#a52f67','#087665','#b85c00','#3b6ea8'];
  const COTA_ROTULO={
    atencao_5m:'Atenção · 5 m',
    alerta_10m:'Alerta · 10 m',
    limite_curva_15m:'Limite da curva-chave · 15 m',
    inundacao_18m:'Inundação · 18 m'
  };
  const COTA_ZONA={atencao_5m:'var(--hec-atencao)',alerta_10m:'var(--hec-alerta)'};

  const nf0=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
  const nf1=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const nf2=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});

  const S={cfg:Object.assign({},DEFAULTS),d:null,fonte:null,erro:null,ponto:'MUCUM',grandeza:'nivel',
    fresh:null,horas:[],t0:null,st:{curva:null,contornos:null,map:null,layers:null,cen:'ecmwf',idx:null,carregando:false},
    resizeTimer:null};

  // ---------- utilidades ----------
  const $=id=>document.getElementById(id);
  function num(v){ return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v):null; }
  function esc(v){ return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
  function cssVar(name,fb){ const v=getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v||fb; }
  function parseWhen(v){
    if(!v) return null;
    const raw=String(v).trim().replace(' ','T');
    const ms=Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(raw)?raw:raw+'-03:00');
    return Number.isFinite(ms)?ms:null;
  }
  function fmtWhen(ms,comAno){
    if(ms==null) return '—';
    const o={timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'};
    if(comAno) o.year='numeric';
    return new Date(ms).toLocaleString('pt-BR',o).replace(',','');
  }
  function fmtDia(ms){ return new Date(ms).toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit'}); }
  function fmtIdade(h){
    if(h==null) return '—';
    if(h<1) return Math.max(0,Math.round(h*60))+' min';
    if(h<48) return nf1.format(h).replace(/,0$/,'')+' h';
    return nf0.format(h/24)+' dias';
  }
  function fmtM(cm){ return cm==null?'—':nf2.format(cm/100)+' m'; }
  function fmtQ(q){ return q==null?'—':nf0.format(q)+' m³/s'; }
  function fmtVal(v,grandeza){ return grandeza==='vazao'?fmtQ(v):fmtM(v); }
  function agoraMs(){
    if(LOCAL&&PARAMS.get('agora')){ const t=parseWhen(PARAMS.get('agora')); if(t!=null) return t; }
    return Date.now();
  }
  function svgNode(tag,attrs,text){
    const el=document.createElementNS(SVG_NS,tag);
    Object.entries(attrs||{}).forEach(([k,v])=>{ if(v!==null&&v!==undefined) el.setAttribute(k,String(v)); });
    if(text!==undefined) el.textContent=text;
    return el;
  }
  async function fetchJson(url){
    const r=await fetch(url+(url.includes('?')?'&':'?')+'cb='+Date.now(),{cache:'no-store'});
    if(!r.ok) throw new Error('HTTP '+r.status);
    return r.json();
  }

  // ---------- carregamento ----------
  async function carregarConfig(){
    try{ Object.assign(S.cfg,await fetchJson(CONFIG_URL)); }catch(e){ /* fica no padrão: mancha desligada */ }
  }
  function urlsPrevisao(){
    if(LOCAL&&PARAMS.get('fonte')) return [PARAMS.get('fonte')];
    const urls=[];
    if(!LOCAL&&S.cfg.latest_raw) urls.push(S.cfg.latest_raw);
    urls.push(S.cfg.latest);
    return urls;
  }
  function validar(d){
    if(!d||typeof d!=='object') return 'arquivo vazio';
    if(d.produto&&!/^previne-hec/.test(String(d.produto))) return 'produto inesperado: '+d.produto;
    if(!Array.isArray(d.horas)||!d.horas.length) return 'sem eixo de horas';
    if(!d.pontos||typeof d.pontos!=='object') return 'sem pontos';
    if(parseWhen(d.emitido_em)==null) return 'sem horário de emissão';
    return null;
  }
  async function carregarPrevisao(){
    let ultimoErro=null;
    for(const url of urlsPrevisao()){
      try{
        const d=await fetchJson(url);
        const problema=validar(d);
        if(problema) throw new Error(problema);
        S.d=d; S.fonte=url; S.erro=null;
        S.horas=d.horas.map(parseWhen);
        S.t0=parseWhen(d.t0);
        return;
      }catch(e){ ultimoErro=e; }
    }
    S.d=null; S.fonte=null; S.erro=ultimoErro;
  }
  function frescor(){
    const d=S.d;
    if(!d) return {estado:'none',idadeH:null};
    const emit=parseWhen(d.emitido_em);
    const idadeH=(agoraMs()-emit)/H_MS;
    const estado=idadeH>S.cfg.horas_sem_previsao?'none':(idadeH>S.cfg.horas_desatualizada?'stale':'ok');
    return {estado,idadeH,emit};
  }

  // ---------- cenários ----------
  function cenarios(){
    const lista=(S.d&&Array.isArray(S.d.cenarios))?S.d.cenarios:[];
    const peso={principal:0,secundario:1,'secundário':1,referencia:2,'referência':2};
    return lista.filter(c=>c&&c.id&&!c.grupo)
      .sort((a,b)=>(peso[a.papel]??5)-(peso[b.papel]??5));
  }
  function grupos(){
    const g={};
    ((S.d&&S.d.cenarios)||[]).forEach(c=>{ if(c&&c.grupo){ (g[c.grupo]=g[c.grupo]||[]).push(c); } });
    return g;
  }
  function estiloCen(id,i){
    const e=CEN_ESTILO[id];
    if(e) return Object.assign({id},e,{cor:cssVar(e.cor,e.fb)});
    return {id,label:String(id).toUpperCase(),cor:CORES_EXTRA[i%CORES_EXTRA.length],w:2.2,dash:'5 4',papel:''};
  }
  function idxT0(){
    const t0=S.t0;
    if(t0==null) return -1;
    let k=-1; S.horas.forEach((t,i)=>{ if(t!=null&&t<=t0) k=i; });
    return k;
  }

  // ---------- séries ----------
  function pontosDisponiveis(){
    const p=(S.d&&S.d.pontos)||{};
    const chaves=[...ORDEM_PONTOS.filter(k=>p[k]),...Object.keys(p).filter(k=>!ORDEM_PONTOS.includes(k))];
    return chaves.filter(k=>p[k]&&(p[k].nivel_previsto_cm||p[k].corrigido));
  }
  function serieValida(arr){ return Array.isArray(arr)&&arr.some(v=>num(v)!=null); }
  function seriesDoPonto(chave,grandeza){
    const p=S.d.pontos[chave]||{};
    const obs=grandeza==='vazao'?(p.observado&&p.observado.vazao_m3s):(p.observado&&p.observado.nivel_cm);
    const fonteFc=grandeza==='vazao'?(p.corrigido||p.simulado||{}):(p.nivel_previsto_cm||{});
    const semCorrecao=grandeza==='vazao'&&!p.corrigido;
    const out=[];
    if(serieValida(obs)) out.push({id:'obs',label:'observado (ANA)',cor:cssVar('--hec-obs','#1e5fbf'),w:3,vals:obs,tipo:'obs'});
    if(grandeza==='vazao'){
      const ref=cenarios().find(c=>p.simulado&&serieValida(p.simulado[c.id]));
      if(ref&&!semCorrecao) out.push({id:'sim',label:'simulado sem correção ('+estiloCen(ref.id,0).label+')',cor:cssVar('--hec-sim','#9aa3a0'),w:1.8,dash:'5 4',vals:p.simulado[ref.id],tipo:'sim'});
    }
    cenarios().forEach((c,i)=>{
      const vals=fonteFc[c.id];
      if(!serieValida(vals)) return;
      const e=estiloCen(c.id,i);
      out.push({id:c.id,label:e.label+(semCorrecao?' (sem correção)':''),cor:e.cor,w:e.w,dash:e.dash,vals,tipo:'prev',cen:c});
    });
    return out;
  }
  function quantilPonderado(vs,ws,q){
    const o=vs.map((v,i)=>[v,ws[i]]).filter(x=>x[0]!=null).sort((a,b)=>a[0]-b[0]);
    if(!o.length) return null;
    const tot=o.reduce((s,x)=>s+x[1],0); let acc=0;
    for(const [v,w] of o){ acc+=w/tot; if(acc>=q) return v; }
    return o[o.length-1][0];
  }
  function faixasConjunto(chave,grandeza){
    const p=S.d.pontos[chave]||{};
    const out=[];
    Object.entries(grupos()).forEach(([g,membros])=>{
      if(membros.length<2) return;
      const pronto=p.conjunto&&p.conjunto[g]&&p.conjunto[g].quantis_vazao_corrigida;
      let lo,hi;
      if(grandeza==='vazao'&&pronto){ lo=pronto.p10; hi=pronto.p90; }
      else{
        const fonte=grandeza==='vazao'?p.corrigido:p.nivel_previsto_cm;
        if(!fonte) return;
        const ws=membros.map(m=>num(m.peso)||1);
        lo=S.horas.map((_,i)=>quantilPonderado(membros.map(m=>num((fonte[m.id]||[])[i])),ws,.1));
        hi=S.horas.map((_,i)=>quantilPonderado(membros.map(m=>num((fonte[m.id]||[])[i])),ws,.9));
      }
      if(serieValida(lo)&&serieValida(hi)) out.push({grupo:g,membros:membros.length,lo,hi});
    });
    return out;
  }
  function cotasDoPonto(chave){
    const p=S.d.pontos[chave]||{};
    const cp=p.cotas_previstas||{};
    const primeiro=Object.values(cp).find(x=>x&&x.cotas);
    if(!primeiro) return [];
    return Object.entries(primeiro.cotas).map(([k,c])=>({chave:k,cm:num(c.cota_cm),indicativo:!!c.indicativo,rotulo:COTA_ROTULO[k]||k.replace(/_/g,' ')}))
      .filter(c=>c.cm!=null).sort((a,b)=>a.cm-b.cm);
  }
  function pico(vals,de){
    let best=null;
    (vals||[]).forEach((v,i)=>{ const n=num(v); if(i>de&&n!=null&&(best==null||n>best.v)) best={v:n,i}; });
    return best;
  }

  // ---------- gráfico ----------
  function niceStep(span,alvo){
    const bruto=span/Math.max(1,alvo), p=Math.pow(10,Math.floor(Math.log10(bruto)));
    const f=bruto/p; return (f<1.5?1:f<3?2:f<7?5:10)*p;
  }
  function desenharGrafico(svg,o){
    svg.replaceChildren();
    const larg=svg.getBoundingClientRect().width||o.Wpadrao||960;
    const W=clamp(Math.round(larg),300,1100), compact=W<560;
    const H=o.H||(compact?300:360);
    const m={l:compact?44:60,r:compact?10:22,t:o.compactTop?12:24,b:compact?38:40};
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
    const horas=S.horas;
    const xMin=o.xMin, xMax=o.xMax;
    const dentro=i=>horas[i]!=null&&horas[i]>=xMin&&horas[i]<=xMax;
    const vals=[];
    o.series.forEach(s=>s.vals.forEach((v,i)=>{ const n=num(v); if(n!=null&&dentro(i)) vals.push(n); }));
    (o.faixas||[]).forEach(b=>{ b.lo.forEach((v,i)=>{ if(num(v)!=null&&dentro(i)) vals.push(num(v)); }); b.hi.forEach((v,i)=>{ if(num(v)!=null&&dentro(i)) vals.push(num(v)); }); });
    if(!vals.length) return null;
    let lo=Math.min(...vals), hi=Math.max(...vals);
    const span=Math.max(o.spanMin||1,hi-lo);
    const linhas=[], acima=[];
    (o.linhas||[]).forEach(l=>{ if(l.v>=lo-span*.35&&l.v<=hi+span*.45) linhas.push(l); else if(l.v>hi) acima.push(l); });
    linhas.forEach(l=>{ lo=Math.min(lo,l.v); hi=Math.max(hi,l.v); });
    const pad=Math.max(o.padMin||0,(hi-lo)*.08);
    let yMin=o.yZero?0:Math.max(0,lo-pad), yMax=hi+pad;
    if(yMax<=yMin) yMax=yMin+1;
    const X=t=>m.l+(W-m.l-m.r)*(t-xMin)/(xMax-xMin);
    const Y=v=>m.t+(H-m.t-m.b)*(1-(v-yMin)/(yMax-yMin));
    const defs=svgNode('defs');
    const uid=svg.id||'g';
    defs.innerHTML=`<pattern id="${uid}-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="rgba(120,130,125,.06)"/><line x1="0" y1="0" x2="0" y2="7" stroke="rgba(120,130,125,.28)" stroke-width="2.4"/></pattern>`;
    svg.appendChild(defs);
    if(o.desc) svg.appendChild(svgNode('desc',{},o.desc));

    // zonas entre cotas
    (o.zonas||[]).forEach(z=>{
      const a=Math.max(yMin,z.de), b=Math.min(yMax,z.ate==null?yMax:z.ate);
      if(b<=a) return;
      svg.appendChild(svgNode('rect',{x:m.l,y:Y(b),width:W-m.l-m.r,height:Y(a)-Y(b),fill:z.fill}));
    });
    let yLim=null;
    if(o.limite!=null&&o.limite<yMax){
      yLim=Y(Math.max(o.limite,yMin));
      svg.appendChild(svgNode('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:yLim-m.t,fill:`url(#${uid}-hatch)`}));
      svg.appendChild(svgNode('text',{x:m.l+8,y:m.t+14,'font-size':compact?10:11,'font-weight':700,fill:'#4b5a52'},'acima de '+fmtVal(o.limite,o.grandeza)+': só indicativo (fora da curva-chave)'));
    }
    // grade
    const passo=niceStep(yMax-yMin,compact?4:5);
    for(let v=Math.ceil(yMin/passo)*passo;v<=yMax+1e-9;v+=passo){
      const y=Y(v);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:cssVar('--hec-grid','#dfe7e2'),'stroke-width':1}));
      svg.appendChild(svgNode('text',{x:m.l-7,y:y+4,'text-anchor':'end','font-size':compact?10:11,fill:'#6c7a72'},o.fmtEixo(v)));
    }
    const offset=3*H_MS, passoDia=(xMax-xMin)/H_MS>(compact?100:200)?48*H_MS:24*H_MS;
    for(let t=Math.ceil((xMin-offset)/(24*H_MS))*24*H_MS+offset;t<=xMax;t+=passoDia){
      const x=X(t);
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:cssVar('--hec-grid-soft','#edf2ef'),'stroke-width':1}));
      svg.appendChild(svgNode('text',{x,y:H-m.b+18,'text-anchor':'middle','font-size':compact?10:11,fill:'#6c7a72'},fmtDia(t)));
    }
    if(o.rotuloY&&!compact) svg.appendChild(svgNode('text',{x:13,y:(m.t+H-m.b)/2,transform:`rotate(-90 13 ${(m.t+H-m.b)/2})`,'text-anchor':'middle','font-size':11,fill:'#6c7a72'},o.rotuloY));
    // linhas de cota
    linhas.forEach(l=>{
      const y=Y(l.v);
      svg.appendChild(svgNode('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:l.cor||'#c0392b','stroke-width':1.5,'stroke-dasharray':l.dash||'3 5'}));
      svg.appendChild(svgNode('text',{x:W-m.r-4,y:y-5,'text-anchor':'end','font-size':compact?10:11,'font-weight':700,fill:l.cor||'#a12d25',stroke:'#fbfdfc','stroke-width':3,'paint-order':'stroke'},l.rotulo));
    });
    if(acima.length) svg.appendChild(svgNode('text',{x:m.l+8,y:m.t+(yLim!=null?30:14),'font-size':compact?9.5:10.5,'font-weight':700,fill:'#6c7a72'},(compact?'↑ ':'↑ cotas acima da escala: ')+acima.map(l=>l.curto||l.rotulo).join(' · ')));
    // linhas verticais (emissão, agora)
    (o.verticais||[]).forEach(v=>{
      if(v.t<xMin||v.t>xMax) return;
      const x=X(v.t);
      svg.appendChild(svgNode('line',{x1:x,y1:m.t,x2:x,y2:H-m.b,stroke:v.cor,'stroke-width':1.2,'stroke-dasharray':'2 4'}));
      svg.appendChild(svgNode('text',{x:x+(v.lado==='esq'?-5:5),y:H-m.b-6,'text-anchor':v.lado==='esq'?'end':'start','font-size':compact?9.5:10.5,'font-weight':700,fill:v.cor},v.rotulo));
    });
    // faixas de conjunto
    (o.faixas||[]).forEach(b=>{
      const pts=[];
      for(let i=0;i<horas.length;i++){ if(dentro(i)&&num(b.lo[i])!=null&&num(b.hi[i])!=null) pts.push(i); }
      if(pts.length<2) return;
      const d='M'+pts.map(i=>X(horas[i]).toFixed(1)+','+Y(num(b.hi[i])).toFixed(1)).join('L')+'L'+pts.slice().reverse().map(i=>X(horas[i]).toFixed(1)+','+Y(num(b.lo[i])).toFixed(1)).join('L')+'Z';
      svg.appendChild(svgNode('path',{d,fill:b.fill||'rgba(232,115,12,.16)',stroke:'none'}));
    });
    // séries
    const caminho=vals=>{
      let d='',aberto=false;
      vals.forEach((v,i)=>{
        const n=num(v);
        if(n==null||!dentro(i)){ aberto=false; return; }
        d+=(aberto?'L':'M')+X(horas[i]).toFixed(1)+','+Y(n).toFixed(1); aberto=true;
      });
      return d;
    };
    if(yLim!=null){
      defs.insertAdjacentHTML('beforeend',`<clipPath id="${uid}-baixo"><rect x="0" y="${yLim}" width="${W}" height="${H-yLim}"/></clipPath><clipPath id="${uid}-cima"><rect x="0" y="0" width="${W}" height="${yLim}"/></clipPath>`);
    }
    o.series.forEach(s=>{
      const d=caminho(s.vals);
      if(!d) return;
      const base={d,fill:'none',stroke:s.cor,'stroke-width':s.w||2,'stroke-dasharray':s.dash||null,'stroke-linejoin':'round','stroke-linecap':'round',opacity:s.opacity!=null?s.opacity:1};
      if(yLim!=null&&s.tipo==='prev'){
        svg.appendChild(svgNode('path',Object.assign({},base,{'clip-path':`url(#${uid}-baixo)`})));
        svg.appendChild(svgNode('path',Object.assign({},base,{'clip-path':`url(#${uid}-cima)`,'stroke-dasharray':'3 4',opacity:(base.opacity||1)*.55})));
      }else svg.appendChild(svgNode('path',base));
    });
    (o.marcas||[]).forEach(mk=>{
      if(mk.t<xMin||mk.t>xMax||mk.v==null) return;
      const c=svgNode('circle',{cx:X(mk.t),cy:Y(mk.v),r:mk.r||4.5,fill:'#fff',stroke:mk.cor,'stroke-width':2.6});
      c.appendChild(svgNode('title',{},mk.titulo||''));
      svg.appendChild(c);
    });
    return {X,Y,W,H,m,xMin,xMax,dentro,hachura:yLim!=null};
  }

  function ligarTooltip(svg,geo,series,grandeza){
    const tip=$('hec-tip'); const shell=svg.parentElement;
    tip.style.display='none';
    if(!geo) return;
    const guia=svgNode('line',{x1:0,y1:geo.m.t,x2:0,y2:geo.H-geo.m.b,stroke:'#132019','stroke-width':1,opacity:0});
    svg.appendChild(guia);
    const capa=svgNode('rect',{x:geo.m.l,y:geo.m.t,width:geo.W-geo.m.l-geo.m.r,height:geo.H-geo.m.t-geo.m.b,fill:'transparent'});
    svg.appendChild(capa);
    const mostrar=ev=>{
      const r=svg.getBoundingClientRect(); const escala=geo.W/r.width;
      const x=(ev.clientX-r.left)*escala;
      const t=geo.xMin+(x-geo.m.l)/(geo.W-geo.m.l-geo.m.r)*(geo.xMax-geo.xMin);
      let i=0,best=Infinity; S.horas.forEach((h,k)=>{ if(h!=null&&Math.abs(h-t)<best){ best=Math.abs(h-t); i=k; } });
      if(!geo.dentro(i)){ esconder(); return; }
      const linhas=series.map(s=>{ const v=num(s.vals[i]); return v==null?'':`<div><i style="background:${s.cor}"></i>${esc(s.label)}: <b>${fmtVal(v,grandeza)}</b></div>`; }).join('');
      if(!linhas){ esconder(); return; }
      const gx=geo.X(S.horas[i]);
      guia.setAttribute('x1',gx); guia.setAttribute('x2',gx); guia.setAttribute('opacity',.35);
      tip.innerHTML=`<div class="tt">${fmtWhen(S.horas[i])}${S.t0!=null&&S.horas[i]>S.t0?` · +${Math.round((S.horas[i]-S.t0)/H_MS)} h`:''}</div>${linhas}`;
      tip.style.display='block';
      const px=gx/escala, sw=shell.clientWidth, tw=tip.offsetWidth;
      tip.style.left=clamp(px+(px>sw/2?-tw-12:12),4,sw-tw-4)+'px';
      tip.style.top='10px';
    };
    const esconder=()=>{ tip.style.display='none'; guia.setAttribute('opacity',0); };
    capa.addEventListener('pointermove',mostrar);
    capa.addEventListener('pointerdown',mostrar);
    capa.addEventListener('pointerleave',esconder);
  }

  // ---------- render principal ----------
  function renderStatus(){
    const el=$('hec-status'), f=S.fresh;
    el.className='hec-status '+(f.estado==='ok'?'':f.estado);
    if(!S.d){
      $('hec-status-text').innerHTML='<b>Sem previsão recente.</b> O arquivo da previsão HEC ainda não foi publicado ou não pôde ser lido'+(S.erro?` (${esc(S.erro.message)})`:'')+'.';
      $('hec-status-sp').textContent='';
      return;
    }
    const emit=fmtWhen(f.emit,true), idade=fmtIdade(f.idadeH);
    if(f.estado==='ok') $('hec-status-text').innerHTML=`Previsão emitida em <b>${emit}</b> (há ${idade}) · base t0 <b>${fmtWhen(S.t0)}</b>`;
    else if(f.estado==='stale') $('hec-status-text').innerHTML=`<b>Previsão desatualizada:</b> emitida em <b>${emit}</b>, há ${idade}. O ciclo normal é a cada ~6 h; trate os números com cautela.`;
    else $('hec-status-text').innerHTML=`<b>Sem previsão recente.</b> A última emissão é de <b>${emit}</b> (há ${idade}); ela não é mostrada como previsão.`;
    const v=num(S.d.versao_esquema);
    $('hec-status-sp').textContent=`modelo ${S.d.parametros&&S.d.parametros.id||'—'} · esquema v${v!=null?v:'?'}`;
  }

  function renderAbas(){
    const box=$('hec-pontos');
    const pts=S.d?pontosDisponiveis():[];
    if(!pts.includes(S.ponto)) S.ponto=pts[0]||'MUCUM';
    box.style.display=pts.length?'':'none';
    box.innerHTML=pts.map(k=>`<button role="tab" data-ponto="${esc(k)}" class="${k===S.ponto?'on':''}" aria-selected="${k===S.ponto}">${esc((PONTOS[k]||{label:k}).label)}</button>`).join('');
    box.querySelectorAll('button').forEach(b=>b.onclick=()=>{ S.ponto=b.dataset.ponto; renderTudo(); });
    document.querySelectorAll('#hec-var button').forEach(b=>{
      const on=b.dataset.var===S.grandeza; b.classList.toggle('on',on); b.setAttribute('aria-pressed',on);
    });
  }

  function vazio(msg,det){
    const e=$('hec-chart-empty'); e.classList.add('show');
    e.innerHTML=`<div><b>${esc(msg)}</b>${det?esc(det):''}</div>`;
    $('hec-chart').replaceChildren(); $('hec-legend').innerHTML=''; $('hec-metrics').innerHTML='';
    $('hec-tip').style.display='none';
  }

  function renderGrafico(){
    const ponto=S.ponto, nome=(PONTOS[ponto]||{label:ponto}).label;
    $('hec-chart-title').textContent=S.grandeza==='vazao'?`Vazão em ${nome}`:`Nível do rio em ${nome}`;
    if(!S.d){ vazio('Sem previsão recente','O painel volta sozinho quando o robô publicar a próxima rodada do HEC.'); return; }
    if(S.fresh.estado==='none'){ vazio('Sem previsão recente',`Última emissão: ${fmtWhen(S.fresh.emit,true)} (há ${fmtIdade(S.fresh.idadeH)}). Previsões antigas não são exibidas.`); return; }
    const p=S.d.pontos[ponto]||{};
    const series=seriesDoPonto(ponto,S.grandeza);
    if(!series.some(s=>s.tipo==='prev')){ vazio('Sem previsão para este posto nesta rodada'); return; }
    $('hec-chart-empty').classList.remove('show');
    const stale=S.fresh.estado==='stale';
    series.forEach(s=>{ if(s.tipo==='prev'&&stale) s.opacity=.5; });
    const k0=idxT0();
    const horasAntes=$('hec-chart').getBoundingClientRect().width<560?36:72;
    const xMin=Math.max(S.horas[0],(S.t0!=null?S.t0:S.horas[0])-horasAntes*H_MS);
    const xMax=S.horas[S.horas.length-1];
    const linhas=[], zonas=[];
    let limite=null;
    if(S.grandeza==='nivel'){
      const cotas=cotasDoPonto(ponto);
      cotas.forEach((c,i)=>{
        linhas.push({v:c.cm,rotulo:c.rotulo+(c.indicativo?' (indicativa)':''),curto:fmtM(c.cm),cor:c.cm>=1000?'#c0392b':'#b0700f',dash:c.indicativo?'2 4':'5 4'});
        if(COTA_ZONA[c.chave]){ const prox=cotas[i+1]; zonas.push({de:c.cm,ate:prox?prox.cm:null,fill:COTA_ZONA[c.chave]}); }
      });
      limite=num(p.limite_curva_cm);
    }
    const faixas=faixasConjunto(ponto,S.grandeza).map(b=>({lo:b.lo,hi:b.hi,fill:'rgba(232,115,12,.16)',grupo:b.grupo,membros:b.membros}));
    const verticais=[];
    if(S.t0!=null) verticais.push({t:S.t0,rotulo:horasAntes<72?'t0':'emissão (t0)',cor:'#1e5fbf',lado:'esq'});
    const agora=agoraMs();
    if(S.t0!=null&&agora-S.t0>1.5*H_MS) verticais.push({t:agora,rotulo:'agora',cor:'#132019'});
    const marcas=[];
    series.filter(s=>s.tipo==='prev').forEach(s=>{
      const pk=pico(s.vals,k0); if(pk) marcas.push({t:S.horas[pk.i],v:pk.v,cor:s.cor,titulo:`Pico ${s.label}: ${fmtVal(pk.v,S.grandeza)} em ${fmtWhen(S.horas[pk.i])}`});
    });
    const svg=$('hec-chart');
    const geo=desenharGrafico(svg,{
      series,faixas,linhas,zonas,limite,verticais,marcas,xMin,xMax,grandeza:S.grandeza,
      spanMin:S.grandeza==='vazao'?200:120,padMin:S.grandeza==='vazao'?50:30,
      fmtEixo:v=>S.grandeza==='vazao'?nf0.format(v):nf0.format(v/100)+' m',
      rotuloY:S.grandeza==='vazao'?'Vazão (m³/s)':'Nível na régua (m)',
      desc:`${$('hec-chart-title').textContent}: observado até a emissão e previsto por cenário de chuva.`
    });
    ligarTooltip(svg,geo,series,S.grandeza);
    // legenda
    const leg=[];
    series.forEach(s=>{
      const cls=s.tipo==='obs'?'':s.tipo==='sim'?'sim':(CEN_ESTILO[s.id]?s.id:'');
      const st=cls?'':` style="border-color:${s.cor}"`;
      const papel=s.cen&&CEN_ESTILO[s.id]?` · ${CEN_ESTILO[s.id].papel}`:'';
      leg.push(`<span><i class="ln ${cls}"${st}></i>${esc(s.label)}${papel}</span>`);
    });
    faixas.forEach(b=>leg.push(`<span><i class="bx ens"></i>${esc(b.grupo)} · p10–p90 (${b.membros} membros)</span>`));
    if(linhas.length) leg.push('<span><i class="ln cota"></i>cotas de referência</span>');
    if(geo&&geo.hachura) leg.push('<span><i class="bx ind"></i>acima do limite da curva-chave: indicativo</span>');
    $('hec-legend').innerHTML=leg.join('');
    // texto acessível
    const prin=series.find(s=>s.tipo==='prev');
    const pk=prin?pico(prin.vals,k0):null;
    $('hec-chart-acc').textContent=pk?`Pico previsto no cenário ${prin.label}: ${fmtVal(pk.v,S.grandeza)} em ${fmtWhen(S.horas[pk.i])}.`:'';
    renderMetricas(series,k0);
  }

  function renderMetricas(series,k0){
    const ponto=S.ponto, p=S.d.pontos[ponto]||{}, g=S.grandeza;
    const cards=[];
    const u=p.ultimo_observado_valido;
    if(u&&u.t){
      const v=g==='vazao'?num(u.vazao_m3s):num(u.nivel_cm);
      const outro=g==='vazao'?fmtM(num(u.nivel_cm)):fmtQ(num(u.vazao_m3s));
      cards.push(`<article class="metric obs"><span class="k">Último observado válido</span><strong>${fmtVal(v,g)}</strong><small>${fmtWhen(parseWhen(u.t))} · ${outro}${num(u.idade_h)!=null&&u.idade_h>0?` · ${fmtIdade(u.idade_h)} antes de t0`:''}</small></article>`);
    }else{
      cards.push(`<article class="metric warn"><span class="k">Último observado válido</span><strong>—</strong><small>sem leitura válida até 72 h antes de t0: previsão <b>sem correção</b> neste posto</small></article>`);
    }
    const cp=p.cotas_previstas||{};
    series.filter(s=>s.tipo==='prev').forEach(s=>{
      const pk=pico(s.vals,k0);
      if(!pk) return;
      const c=cp[s.id];
      const ant=Math.round((S.horas[pk.i]-S.t0)/H_MS);
      let extra='';
      if(c&&c.cotas){
        const cruzadas=Object.entries(c.cotas).filter(([,x])=>x&&x.cruza).map(([k,x])=>`${(COTA_ROTULO[k]||k).split('·').pop().trim()} em ${fmtWhen(parseWhen(x.primeiro_cruzamento))}`);
        extra=cruzadas.length?`<br>cruza ${esc(cruzadas.join('; '))}`:'<br>não cruza nenhuma cota';
      }
      const lim=num(p.limite_curva_cm);
      const pill=g==='nivel'&&lim!=null&&pk.v>lim?'<span class="pill ind">acima da curva · indicativo</span>':'';
      cards.push(`<article class="metric ${CEN_ESTILO[s.id]?s.id:''}"><span class="k">Pico · ${esc(s.label)}</span><strong>${fmtVal(pk.v,g)}</strong><small>${fmtWhen(S.horas[pk.i])} (+${ant} h)${extra}</small>${pill}</article>`);
    });
    const e=p.erro_em_tv_m3s;
    if(e&&u&&u.t){
      const v=num(Object.values(e)[0]);
      const k=S.horas.findIndex(t=>t===parseWhen(u.t));
      const prin=cenarios()[0];
      const sim=k>=0&&prin&&p.simulado?num((p.simulado[prin.id]||[])[k]):null;
      const obsQ=num(u.vazao_m3s);
      const razao=sim!=null&&obsQ?sim/obsQ:null;
      const warn=razao!=null&&(razao>=1.5||razao<=1/1.5);
      cards.push(`<article class="metric ${warn?'warn':''}"><span class="k">Correção pelo observado</span><strong>${v!=null?(v>0?'+':'')+nf0.format(v)+' m³/s':'—'}</strong><small>${razao!=null?`modelo sem correção estava em <b>${nf1.format(razao)}×</b> o observado (${nf0.format(sim)} × ${nf0.format(obsQ)} m³/s)`:'diferença entre observado e simulado na última leitura'}; decai em 1–3 dias</small></article>`);
    }
    $('hec-metrics').innerHTML=cards.join('');
  }

  function renderCotas(){
    const card=$('hec-cotas-card');
    if(!S.d||S.fresh.estado==='none'){ card.hidden=true; return; }
    const p=(S.d.pontos||{}).MUCUM||{};
    const cp=p.cotas_previstas||{};
    const cens=cenarios().filter(c=>cp[c.id]);
    const cotas=S.d.pontos.MUCUM?cotasDoPonto('MUCUM'):[];
    if(!cens.length||!cotas.length){ card.hidden=true; return; }
    card.hidden=false;
    const conj=p.conjunto||{};
    const gs=Object.keys(conj).filter(g=>conj[g]&&conj[g].probabilidade_cota);
    let html='<thead><tr><th>Cota</th>'+cens.map((c,i)=>`<th>${esc(estiloCen(c.id,i).label)}</th>`).join('')+gs.map(g=>`<th>${esc(g)} · prob.</th>`).join('')+'</tr></thead><tbody>';
    cotas.forEach(ct=>{
      html+=`<tr><td><b>${esc(ct.rotulo)}</b>${ct.indicativo?'<span class="ind">indicativa</span>':''}</td>`;
      cens.forEach(c=>{
        const x=cp[c.id].cotas&&cp[c.id].cotas[ct.chave];
        if(x&&x.cruza) html+=`<td class="yes"><b>${fmtWhen(parseWhen(x.primeiro_cruzamento))}</b><br>+${nf0.format(num(x.antecedencia_h)||0)} h${x.indicativo?'<span class="ind">indicativo</span>':''}</td>`;
        else html+='<td class="no">não cruza</td>';
      });
      gs.forEach(g=>{ const pr=num(conj[g].probabilidade_cota[ct.chave]); html+=`<td>${pr!=null?nf0.format(pr*100)+' %':'—'}</td>`; });
      html+='</tr>';
    });
    html+='<tr><td><b>Pico previsto</b></td>'+cens.map(c=>{
      const x=cp[c.id];
      return `<td><b>${fmtM(num(x.pico_nivel_cm))}</b><br>${fmtWhen(parseWhen(x.t_pico))} · ${fmtQ(num(x.pico_vazao_m3s))}${x.pico_acima_validade?'<span class="ind">acima da validade</span>':''}</td>`;
    }).join('')+gs.map(()=>'<td>—</td>').join('')+'</tr></tbody>';
    $('hec-cotas').innerHTML=html;
  }

  function avisos(){
    const out=[], d=S.d, f=S.fresh;
    if(!d){ out.push({n:'alto',t:'Sem previsão recente: o arquivo da rodada HEC não foi encontrado ou está inválido. Não interprete a ausência como “rio estável”.'}); return out; }
    if(f.estado==='none') out.push({n:'alto',t:`Sem previsão recente: última emissão há ${fmtIdade(f.idadeH)}.`});
    else if(f.estado==='stale') out.push({n:'alto',t:`Previsão desatualizada (emitida há ${fmtIdade(f.idadeH)}). A chuva e o rio podem ter mudado desde então.`});
    const v=num(d.versao_esquema);
    if(v!=null&&v>S.cfg.esquema_suportado) out.push({n:'info',t:`Arquivo em formato mais novo (esquema v${v}); campos novos podem não aparecer neste painel.`});
    (Array.isArray(d.avisos)?d.avisos:[]).forEach(a=>out.push({n:'medio',t:typeof a==='string'?a:(a&&(a.texto||a.mensagem||a.msg))||JSON.stringify(a)}));
    const mu=(d.pontos||{}).MUCUM;
    if(mu){
      const lim=num(mu.limite_curva_cm)||1500;
      out.push({n:'info',t:`Acima de ${fmtM(lim)} em Muçum o nível previsto é só indicativo (fim da validade da curva-chave). A cota de 18 m não é um limiar validado pelo modelo.`});
      Object.entries(mu.cotas_previstas||{}).forEach(([id,x])=>{ if(x&&x.pico_acima_validade) out.push({n:'alto',t:`Cenário ${estiloCen(id,0).label}: o pico passa do limite da curva-chave (${fmtM(num(x.pico_nivel_cm))}); valor só indicativo.`}); });
    }
    cenarios().forEach((c,i)=>{
      const lab=estiloCen(c.id,i).label;
      if(c.status&&c.status!=='ok') out.push({n:'alto',t:`Cenário ${lab} indisponível nesta rodada (${c.status}).`});
      const id=num(c.idade_rodada_h_na_emissao);
      if(id!=null&&id>18) out.push({n:'medio',t:`Rodada do ${lab} já tinha ${fmtIdade(id)} na emissão.`});
      const cob=parseWhen(c.cobre_ate), fim=S.horas[S.horas.length-1];
      if(cob!=null&&fim!=null&&cob<fim) out.push({n:'medio',t:`Chuva do ${lab} só cobre até ${fmtWhen(cob)}; depois disso o cenário considera chuva zero.`});
    });
    const j=d.janela&&d.janela.inicio_escolhido;
    if(j&&num(j.q_muc_inicio)!=null&&j.q_muc_inicio>1500) out.push({n:'medio',t:`A janela do modelo começou com Muçum a ${nf0.format(j.q_muc_inicio)} m³/s (acima de 1.500): o estado inicial pode estar alto.`});
    const pontos=d.pontos||{};
    ['MUCUM','ENCANTADO','LJJ'].forEach(k=>{
      const p=pontos[k]; if(!p) return;
      const u=p.ultimo_observado_valido, nome=PONTOS[k].label;
      if(!u) out.push({n:'medio',t:`${nome}: sem observado válido recente; a previsão segue sem correção neste posto.`});
      else if(num(u.idade_h)!=null&&u.idade_h>6) out.push({n:'medio',t:`${nome}: correção feita com leitura de ${fmtIdade(u.idade_h)} antes de t0.`});
    });
    if(mu&&mu.ultimo_observado_valido&&mu.simulado){
      const u=mu.ultimo_observado_valido, k=S.horas.findIndex(t=>t===parseWhen(u.t));
      const prin=cenarios()[0];
      const sim=k>=0&&prin?num((mu.simulado[prin.id]||[])[k]):null, obs=num(u.vazao_m3s);
      if(sim!=null&&obs){
        const r=sim/obs;
        if(r>=1.5||r<=1/1.5) out.push({n:'medio',t:`Em t0 o modelo sem correção estava em ${nf1.format(r)}× o observado em Muçum (${nf0.format(sim)} × ${nf0.format(obs)} m³/s). A correção compensa isso nas primeiras horas e decai com τ de 24–72 h, então o pico dos próximos dias ainda pode carregar parte do ${r>1?'excesso':'déficit'} do modelo.`});
      }
    }
    const co=d.chuva_observada;
    if(co){
      const us=Array.isArray(co.postos_usados)?co.postos_usados.length:num(co.postos_usados), cons=num(co.postos_consultados);
      if(us!=null&&cons&&us/cons<.4) out.push({n:'medio',t:`Chuva observada com poucos postos: ${us} de ${cons}.`});
      const fr=co.falhas_rede&&Object.keys(co.falhas_rede).length;
      if(fr) out.push({n:'medio',t:`${fr} posto(s) de chuva com falha de rede nesta rodada.`});
      const sem=Array.isArray(co.horas_sem_estacao)?co.horas_sem_estacao.length:0;
      if(sem) out.push({n:'medio',t:`${sem} hora(s) sem nenhuma estação de chuva; essas horas entraram como zero.`});
    }
    return out;
  }

  function renderQualidade(){
    const lista=avisos();
    $('hec-avisos').innerHTML=lista.length?lista.map(a=>`<li class="${a.n}">${esc(a.t)}</li>`).join(''):'<li class="info">Nenhum aviso nesta rodada.</li>';
    const d=S.d;
    if(!d){ $('hec-chuva-obs').innerHTML='<div class="read"><span>Sem dados</span><b>—</b></div>'; $('hec-chuva').replaceChildren(); $('hec-chuva-prev').style.display='none'; $('hec-rodadas').innerHTML=''; $('hec-tech').innerHTML=S.erro?esc(S.erro.message):''; return; }
    const co=d.chuva_observada||{};
    const us=Array.isArray(co.postos_usados)?co.postos_usados.length:num(co.postos_usados);
    const qc=co.excluidos_qc?Object.keys(co.excluidos_qc):[];
    const eph=Array.isArray(co.estacoes_por_hora)?co.estacoes_por_hora.filter(x=>num(x)!=null):[];
    const med=eph.length?eph.slice().sort((a,b)=>a-b)[Math.floor(eph.length/2)]:null;
    const kObs=S.horas.findIndex(t=>t===parseWhen(co.ultima_hora_observada||co.ate));
    const serieQualquer=d.chuva_media_bacia_mm&&Object.values(d.chuva_media_bacia_mm)[0];
    let somaJanela=null;
    if(Array.isArray(serieQualquer)&&kObs>=0){ somaJanela=0; for(let i=0;i<=kObs;i++) somaJanela+=num(serieQualquer[i])||0; }
    $('hec-chuva-obs').innerHTML=[
      ['Fonte',esc(co.fonte||'—')],
      ['Até',fmtWhen(parseWhen(co.ultima_hora_observada||co.ate))],
      ['Postos usados',us!=null?`${us} de ${co.postos_consultados??'—'} (${co.postos_com_registro??'—'} com registro)`:'—'],
      ['Excluídos no controle de qualidade',qc.length?`${qc.length} (${esc(qc.join(', '))})`:'0'],
      ['Falhas de rede',co.falhas_rede?String(Object.keys(co.falhas_rede).length):'—'],
      ['Estações na última hora',eph.length?`${eph[eph.length-1]} (mediana ${med})`:'—'],
      ['Chuva média na bacia na janela',somaJanela!=null?nf1.format(somaJanela)+' mm':'—']
    ].map(([k,v])=>`<div class="read"><span>${k}</span><b>${v}</b></div>`).join('');
    renderChuva(kObs);
    $('hec-rodadas').innerHTML='<h3 style="margin-top:12px">Rodadas de chuva prevista</h3>'+cenarios().map((c,i)=>{
      const e=estiloCen(c.id,i);
      const rod=c.rodada_utc?`rodada ${esc(c.rodada_utc)} · ${fmtIdade(num(c.idade_rodada_h_na_emissao))} na emissão`:'sem rodada (referência)';
      return `<div class="read"><span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${e.cor};margin-right:6px"></i>${esc(e.label)} · ${esc(c.status||'—')}</span><b>${rod} · ${c.chuva_bacia_prevista_mm!=null?nf1.format(c.chuva_bacia_prevista_mm)+' mm':'—'}</b></div>`;
    }).join('');
    const tecnicos=cenarios().flatMap(c=>(c.avisos||[]).map(a=>`<li><b>${esc(c.id)}</b>: ${esc(a)}</li>`)).join('');
    const pr=d.parametros||{}, ja=d.janela||{};
    $('hec-tech').innerHTML=`<p>${esc(d.aviso||'')}</p>
      <p>Produto <code>${esc(d.produto||'—')}</code> · esquema v${esc(d.versao_esquema??'?')} · modo <code>${esc(d.modo||'—')}</code> · emitido ${esc(d.emitido_em||'—')} · t0 ${esc(d.t0||'—')}</p>
      <p>Parâmetros <code>${esc(pr.id||'—')}</code> (${esc(pr.familia||'')}, sha256 ${esc(pr.sha256_p||'—')}) · janela ${esc(ja.inicio||'—')} → ${esc(ja.fim||'—')}, passo ${esc(ja.passo_modelo_min??'—')} min, horizonte ${esc(ja.horizonte_h??'—')} h${ja.inicio_escolhido?`<br>Início: ${esc(ja.inicio_escolhido.regra||'')}`:''}</p>
      ${tecnicos?`<p>Registro das fontes de chuva prevista:</p><ul>${tecnicos}</ul>`:''}
      <p>Tempo do ciclo: ${d.tempos_s&&d.tempos_s.total_s!=null?nf0.format(d.tempos_s.total_s)+' s':'—'} · arquivo lido de <code>${esc(S.fonte||'—')}</code></p>`;
  }

  function renderChuva(kObs){
    const svg=$('hec-chuva');
    const d=S.d, cm=d.chuva_media_bacia_mm||{};
    $('hec-chuva-prev').style.display='';
    if(S.fresh.estado==='none'||kObs<0){ svg.replaceChildren(); $('hec-chuva-prev').style.display='none'; return; }
    const series=cenarios().filter(c=>Array.isArray(cm[c.id])).map((c,i)=>{
      const e=estiloCen(c.id,i); let acc=0;
      const vals=S.horas.map((_,k)=>{ if(k<kObs) return null; if(k>kObs) acc+=num(cm[c.id][k])||0; return acc; });
      return {id:c.id,label:e.label,cor:e.cor,w:e.w-0.6,dash:e.dash,vals,tipo:'chuva'};
    });
    if(!series.length){ svg.replaceChildren(); return; }
    desenharGrafico(svg,{series,xMin:S.horas[kObs],xMax:S.horas[S.horas.length-1],H:170,Wpadrao:480,yZero:true,spanMin:10,compactTop:true,
      fmtEixo:v=>nf0.format(v)+' mm',desc:'Chuva prevista acumulada na bacia depois da última hora observada, por cenário.'});
  }

  // ---------- Santa Tereza ----------
  function stAtiva(){
    if(LOCAL&&PARAMS.get('st')==='1') return true;
    return S.cfg.mancha_santa_tereza===true;
  }
  function stSerie(cenId){
    const pts=S.d.pontos||{};
    const proprio=pts.SANTA_TEREZA&&pts.SANTA_TEREZA.nivel_previsto_cm&&pts.SANTA_TEREZA.nivel_previsto_cm[cenId];
    if(serieValida(proprio)) return {fonte:'ponto Santa Tereza do HEC',vals:proprio.map(num),erro:null};
    const cv=S.st.curva, mu=pts.MUCUM&&pts.MUCUM.nivel_previsto_cm&&pts.MUCUM.nivel_previsto_cm[cenId];
    if(!cv||!serieValida(mu)) return null;
    const xs=cv.curva.muc_cm, ys=cv.curva.st_cm, lag=num(cv.defasagem_h)||0;
    const interp=x=>{
      if(x<=xs[0]) return ys[0];
      for(let i=1;i<xs.length;i++) if(x<=xs[i]) return ys[i-1]+(ys[i]-ys[i-1])*(x-xs[i-1])/((xs[i]-xs[i-1])||1);
      return ys[ys.length-1];
    };
    const faixa=cv.faixa_muc_cm||[xs[0],xs[xs.length-1]];
    const vals=S.horas.map((_,i)=>{ const x=num(mu[i-lag]); return x==null?null:interp(x); });
    const fora=S.horas.map((_,i)=>{ const x=num(mu[i-lag]); return x!=null&&(x<faixa[0]||x>faixa[1]); });
    const v=cv.validacao_deixando_um_evento_fora||{};
    return {fonte:`curva Muçum → Santa Tereza (defasagem ${lag} h)`,vals,fora,erro:num(v.p95_abs_cm),muc:mu};
  }
  function linkPrevia(){
    const q=new URLSearchParams(location.search); q.set('st','1');
    return '?'+q.toString()+'#hec-st';
  }
  function stExplicacaoOff(){
    const cv=S.st.curva, v=cv&&cv.validacao_deixando_um_evento_fora, ev=v&&v.por_evento_deixado_fora||{};
    const linhas=Object.entries(ev).map(([k,x])=>`<li>${esc(k)}: erro médio ${nf0.format(x.mae_cm)} cm, viés ${x.vies_cm>0?'+':''}${nf0.format(x.vies_cm)} cm, p95 ${nf0.format(x.p95_abs_cm)} cm (régua de Santa Tereza até ${fmtM(x.st_max_cm)})</li>`).join('');
    return `<div class="st-off">
      <h3>Ligação desligada nesta versão</h3>
      <p>O HEC ao vivo prevê o nível em Muçum (régua 86510000), mas a mancha de Santa Tereza é escolhida pela régua
      <b>86472600</b> (contorno HAND = régua − ${nf1.format(S.cfg.bankfull_santa_tereza_cm/100)} m). A ponte entre as duas ainda não é confiável para um mapa:</p>
      <ul>
        <li><b>Conversão Muçum → Santa Tereza:</b> ${v?`erro médio de ${nf0.format(v.mae_cm)} cm e p95 de ${nf0.format(v.p95_abs_cm)} cm deixando uma cheia de fora`:'curva indisponível'}.
          ${linhas?`<ul>${linhas}</ul>`:''}</li>
        <li><b>Viés troca de sinal</b> entre 2023–2024 e 2026: sugere mudança de régua/datum ou do leito que precisa ser conferida com o SGB.</li>
        <li><b>Datum:</b> o zero da régua 86472600 e o MDT do mosaico 2 m (drone + ANADEM) ainda não foram compatibilizados; o “nível normal” de ${nf1.format(S.cfg.bankfull_santa_tereza_cm/100)} m é provisório.</li>
        <li>O erro da conversão soma-se ao da própria previsão HEC em Muçum (acima de 15 m só indicativa).</li>
      </ul>
      <p><b>O que destrava:</b> um ponto <code>SANTA_TEREZA</code> no executor HEC com curva própria (vazão do nó de LJJ/confluência × régua 86472600),
      a compatibilização do datum régua × MDT e a validação da mancha com uma cheia observada. Quando isso existir, basta ligar
      <code>mancha_santa_tereza</code> em <code>assets/data/hec_aovivo/config.json</code>; o painel já prefere o ponto próprio do HEC à curva.</p>
      ${LOCAL?`<p><a href="${esc(linkPrevia())}">Prévia para revisão (só em localhost) →</a></p>`:''}
    </div>`;
  }
  async function renderSantaTereza(){
    const body=$('hec-st-body');
    if(!S.st.curva){ try{ S.st.curva=await fetchJson(S.cfg.curva_santa_tereza); }catch(e){ S.st.curva=null; } }
    if(!stAtiva()){ body.innerHTML=stExplicacaoOff(); S.st.map=null; return; }
    if(!S.d||S.fresh.estado==='none'){ body.innerHTML='<div class="st-off"><h3>Sem previsão recente</h3><p>A mancha só é calculada a partir de uma rodada recente do HEC.</p></div>'; S.st.map=null; return; }
    const cens=cenarios().filter(c=>stSerie(c.id));
    if(!cens.length){ body.innerHTML='<div class="st-off">Sem nível previsto em Muçum nesta rodada.</div>'; return; }
    if(!cens.some(c=>c.id===S.st.cen)) S.st.cen=cens[0].id;
    if(!S.st.map||!document.getElementById('st-map')){
      body.innerHTML=`<div class="datum"><b>PRÉVIA DE REVISÃO — ressalva de datum.</b> A régua 86472600 e o terreno (MDT/HAND) ainda não estão no mesmo datum;
        o nível normal de ${nf1.format(S.cfg.bankfull_santa_tereza_cm/100)} m é provisório. O nível de Santa Tereza aqui é <b>estimado</b> a partir de Muçum por uma curva empírica com erro
        típico de ~0,3 m e de até 2,6 m numa cheia (mai/2024). A borda é zona de atenção, não linha exata. <b>Não use para decisão.</b></div>
        <div class="hec-controls"><div class="seg" id="st-cens">${cens.map((c,i)=>`<button data-cen="${esc(c.id)}">${esc(estiloCen(c.id,i).label)}</button>`).join('')}</div></div>
        <div class="st-ctrl"><span class="tlab" id="st-tlab">—</span><input type="range" id="st-time" min="0" max="1" value="0" aria-label="Hora da previsão"></div>
        <div class="st-read" id="st-read"></div>
        <div class="st-map" id="st-map"></div>
        <p class="foot" id="st-foot"></p>`;
      body.querySelectorAll('#st-cens button').forEach(b=>b.onclick=()=>{ S.st.cen=b.dataset.cen; S.st.idx=null; atualizarST(); });
      $('st-time').oninput=e=>{ S.st.idx=+e.target.value; atualizarST(true); };
      if(typeof L==='undefined'){ $('st-map').innerHTML='<div class="st-off">O mapa (Leaflet) não carregou.</div>'; }
      else{
        const map=L.map('st-map',{scrollWheelZoom:false}).setView([-29.17,-51.73],13);
        const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'© Esri, Maxar'}).addTo(map);
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(map);
        const osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'});
        sat.on('tileerror',()=>{ if(!map.hasLayer(osm)) osm.addTo(map); });
        S.st.layers={
          unc:L.geoJSON(null,{style:{color:'transparent',weight:0,fillColor:'#ff8a00',fillOpacity:.2}}).addTo(map),
          fore:L.geoJSON(null,{style:{color:'#f07b00',weight:1,fillColor:'#ff8a00',fillOpacity:.45}}).addTo(map)
        };
        L.circleMarker([-29.1781,-51.7322],{radius:7,color:'#fff',weight:2,fillColor:'#1e5fbf',fillOpacity:.95}).addTo(map).bindTooltip('Estação Santa Tereza 86472600');
        S.st.map=map;
      }
    }
    if(!S.st.contornos&&!S.st.carregando&&S.st.map){
      S.st.carregando=true; $('st-foot').textContent='Carregando contornos da mancha (~13 MB)…';
      try{ S.st.contornos=await fetchJson(S.cfg.contornos_santa_tereza); }catch(e){ $('st-foot').textContent='Falha ao carregar os contornos: '+e.message; }
      S.st.carregando=false;
    }
    atualizarST();
  }
  function stFeature(hm){
    const fc=S.st.contornos; if(!fc||hm==null||hm<=0) return null;
    const alvo=Math.round(clamp(hm,0,15)*10)/10;
    return fc.features.find(f=>Math.abs(f.properties.nivel_m-alvo)<0.01)||null;
  }
  function atualizarST(soSlider){
    const serie=stSerie(S.st.cen); if(!serie) return;
    const k0=idxT0(), n=S.horas.length;
    const inicio=Math.max(0,k0+1);
    if(S.st.idx==null){ const pk=pico(serie.vals,k0); S.st.idx=pk?pk.i:inicio; }
    const sl=$('st-time'); sl.min=inicio; sl.max=n-1; if(!soSlider) sl.value=S.st.idx;
    document.querySelectorAll('#st-cens button').forEach(b=>b.classList.toggle('on',b.dataset.cen===S.st.cen));
    const i=S.st.idx, st=serie.vals[i];
    const bf=S.cfg.bankfull_santa_tereza_cm, hm=st!=null?(st-bf)/100:null;
    const err=serie.erro||0, hmU=st!=null?(st+err-bf)/100:null;
    $('st-tlab').textContent=`${fmtWhen(S.horas[i])} (+${Math.round((S.horas[i]-S.t0)/H_MS)} h)`;
    let areaC=null, areaU=null;
    if(S.st.layers){
      const fU=stFeature(hmU), fC=stFeature(hm);
      S.st.layers.unc.clearLayers(); if(fU) S.st.layers.unc.addData(fU);
      S.st.layers.fore.clearLayers(); if(fC) S.st.layers.fore.addData(fC);
      areaC=fC?fC.properties.area_ha:(S.st.contornos?0:null); areaU=fU?fU.properties.area_ha:(S.st.contornos?0:null);
      if(fU&&!S.st.enquadrado){ try{ S.st.map.fitBounds(L.geoJSON(fU).getBounds(),{padding:[16,16]}); S.st.enquadrado=true; }catch(e){} }
    }
    const lag=num(S.st.curva&&S.st.curva.defasagem_h)||0;
    const mu=serie.muc?num(serie.muc[i-lag]):null;
    const fora=serie.fora&&serie.fora[i];
    $('st-read').innerHTML=[
      serie.muc?`<article class="metric"><span class="k">Muçum previsto (${fmtWhen(S.horas[i-lag])})</span><strong>${fmtM(mu)}</strong><small>entrada da conversão</small></article>`:'',
      `<article class="metric ecmwf"><span class="k">Santa Tereza estimado</span><strong>${fmtM(st)}</strong><small>± ${err?nf1.format(err/100)+' m (p95)':'—'} · ${esc(serie.fonte)}${fora?' · <b>fora da faixa da curva</b>':''}</small></article>`,
      `<article class="metric"><span class="k">Nível acima do normal (HAND)</span><strong>${hm!=null?nf1.format(Math.max(0,hm))+' m':'—'}</strong><small>régua − ${nf1.format(bf/100)} m (provisório)${hm!=null&&hm>15?' · acima de 15 m: contorno máximo':''}</small></article>`,
      `<article class="metric"><span class="k">Área fora do leito</span><strong>${areaC!=null?nf0.format(areaC)+' ha':'—'}</strong><small>com a margem de erro: ${areaU!=null?nf0.format(areaU)+' ha':'—'}</small></article>`
    ].join('');
    const foot=$('st-foot');
    if(foot&&!S.st.carregando) foot.textContent='Laranja: contorno do nível estimado. Halo claro: mesmo nível + erro p95 da conversão. Contornos HAND do mosaico 2 m (assets/data/santa_tereza_inundacao/contornos_extravasamento.json), proxy de extravasamento relativo ao HAND 0.';
  }

  // ---------- ciclo ----------
  function renderTudo(){
    S.fresh=frescor();
    renderStatus();
    renderAbas();
    renderGrafico();
    renderCotas();
    renderQualidade();
  }
  async function atualizar(){
    await carregarPrevisao();
    renderTudo();
    renderSantaTereza();
  }
  async function init(){
    document.querySelectorAll('#hec-var button').forEach(b=>b.onclick=()=>{ S.grandeza=b.dataset.var; renderTudo(); });
    await carregarConfig();
    await atualizar();
    setInterval(atualizar,10*60*1000);
    const shell=$('hec-chart').parentElement;
    if(window.ResizeObserver){
      let w=shell.clientWidth;
      new ResizeObserver(()=>{ if(Math.abs(shell.clientWidth-w)<4) return; w=shell.clientWidth; clearTimeout(S.resizeTimer); S.resizeTimer=setTimeout(()=>{ if(S.d) renderTudo(); },120); }).observe(shell);
    }
  }
  window.PREVINE_HEC={estado:S,atualizar};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
