(function(){
  'use strict';
  const raw='https://raw.githubusercontent.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/main/';
  const repo='https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/tree/main/';
  const nf=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
  const cm=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:1});
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?Number(v):null;
  const date=v=>v?new Date(/[zZ]|[+-]\d\d:\d\d$/.test(v)?v:v+'-03:00'):null;
  const when=v=>{const d=date(v);return d&&Number.isFinite(+d)?d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';};
  const meters=v=>num(v)===null?'—':nf.format(Number(v)/100)+' m';
  const error=v=>num(v)===null?'—':cm.format(Number(v))+' cm';
  const current=(feed,p)=>p&&p.disponivel&&date(p.hora_alvo)>new Date()&&Date.now()-date(feed.gerado_em)<90*60000;
  async function fetchFeed(file){
    const urls=location.hostname==='127.0.0.1'||location.hostname==='localhost'?[file]:[raw+file,file];
    const candidates=await Promise.all(urls.map(async url=>{try{const r=await fetch(url+'?v='+Math.floor(Date.now()/60000),{cache:'no-store'});if(r.ok)return await r.json();}catch(e){}return null;}));
    const valid=candidates.filter(v=>v&&v.gerado_em&&Number.isFinite(+date(v.gerado_em)));
    valid.sort((a,b)=>date(b.gerado_em)-date(a.gerado_em));
    if(valid.length)return valid[0];
    throw new Error('Feed comparativo indisponível');
  }
  function chart(rows,latest){
    const points=[];
    rows.forEach(r=>{const t=+date(r.hora_alvo);if(num(r.nivel_previsto_cm)!==null)points.push({t,y:r.nivel_previsto_cm,kind:'p'});if(num(r.observado_cm)!==null)points.push({t,y:r.observado_cm,kind:'o'});});
    if(latest){points.push({t:+date(latest.hora_modelo),y:latest.nivel_base_cm,kind:'o'});points.push({t:+date(latest.hora_alvo),y:latest.nivel_previsto_cm,kind:'p'});}
    const good=points.filter(p=>Number.isFinite(p.t)&&num(p.y)!==null);
    if(!good.length)return '<svg class="shadow-chart" viewBox="0 0 760 265" role="img" aria-label="Gráfico aguardando previsões registradas"><rect x="55" y="40" width="670" height="180" fill="#faf9fc" stroke="#e8e5ee"/><text x="390" y="135" text-anchor="middle" font-size="16" fill="#586a64">Aguardando previsões registradas</text></svg>';
    const minT=Math.min(...good.map(p=>p.t)),maxT=Math.max(...good.map(p=>p.t));
    const minY=Math.min(...good.map(p=>p.y)),maxY=Math.max(...good.map(p=>p.y));
    const lo=minY-Math.max(15,(maxY-minY)*.1),hi=maxY+Math.max(15,(maxY-minY)*.1);
    const x=t=>55+(t-minT)/Math.max(3600000,maxT-minT)*670,y=v=>220-(v-lo)/(hi-lo)*180;
    let svg='<svg class="shadow-chart" viewBox="0 0 760 265" role="img" aria-label="Nível observado em azul e previsão comparativa em roxo, em metros">';
    for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;svg+=`<line x1="55" x2="725" y1="${y(v)}" y2="${y(v)}" stroke="#e8e5ee"/><text x="48" y="${y(v)+4}" text-anchor="end" font-size="11" fill="#586a64">${nf.format(v/100)}</text>`;}
    for(const kind of ['o','p']){
      const ps=good.filter(p=>p.kind===kind).sort((a,b)=>a.t-b.t);const color=kind==='o'?'#1e5fbf':'#74439b';
      for(let i=1;i<ps.length;i++){if(ps[i].t-ps[i-1].t<=65*60000&&ps[i].t!==ps[i-1].t)svg+=`<line x1="${x(ps[i-1].t)}" y1="${y(ps[i-1].y)}" x2="${x(ps[i].t)}" y2="${y(ps[i].y)}" stroke="${color}" stroke-width="2" ${kind==='p'?'stroke-dasharray="5 4"':''}/>`;}
      ps.forEach(p=>svg+=`<circle cx="${x(p.t)}" cy="${y(p.y)}" r="3.2" fill="${color}"><title>${kind==='o'?'Observado':'Previsto'}: ${meters(p.y)} · ${when(new Date(p.t).toISOString())}</title></circle>`);
    }
    svg+=`<text x="55" y="245" font-size="11" fill="#586a64">${when(new Date(minT).toISOString())}</text><text x="725" y="245" text-anchor="end" font-size="11" fill="#586a64">${when(new Date(maxT).toISOString())}</text></svg>`;
    return svg;
  }
  function saved(feed,file){
    const count=Number.isInteger(feed.historico_registros_n)?feed.historico_registros_n:null;
    const parts=Array.isArray(feed.historico_arquivos)?feed.historico_arquivos:[];
    const latest=parts.length?parts[parts.length-1]:file;
    const folder=parts.length?' · <a href="'+repo+latest.replace(/\/[^/]+$/,'')+'" target="_blank" rel="noopener">Todos os meses</a>':'';
    return `<p class="shadow-note">Histórico permanente${count===null?'':': '+count+' previsões registradas'}. <a href="${raw+latest}" target="_blank" rel="noopener">Baixar histórico JSON${parts.length?' do mês':''}</a>${folder}${feed.arquivo_emissao?' · <a href="'+raw+feed.arquivo_emissao.arquivo+'" target="_blank" rel="noopener">Entradas e telemetria desta rodada (.gz)</a>':''}</p>`;
  }
  function publicPanel(el,feed){
    const p=feed.previsao||{},ok=current(feed,p),m=feed.avaliacao?.total||{},rows=feed.serie_recente||[];
    el.innerHTML=`<span class="shadow-tag">Comparativa em sombra · 4 h</span><h3>N5 · sem Castro Alves</h3><p>Previsão independente para acompanhar o desempenho da nova RNA.</p><strong class="shadow-number">${ok?meters(p.nivel_previsto_cm):'Aguardando dados'}</strong><p class="shadow-status">${ok?'Para '+when(p.hora_alvo)+' · base '+when(p.hora_modelo):'Sem previsão futura com base recente neste ciclo.'}</p>${ok?'<p class="shadow-note">Antecedência restante: '+cm.format((date(p.hora_alvo)-new Date())/3600000)+' h. O horizonte de 4 h é contado a partir da base.</p>':''}<div class="shadow-metrics"><span>Conferidas<b>${m.n||0}</b></span><span>MAE<b>${error(m.mae_cm)}</b></span><span>RMSE<b>${error(m.rmse_cm)}</b></span></div><p class="shadow-note">${m.n?'Erros calculados após a leitura ANA no horário-alvo.':'A avaliação ao vivo começa nesta ativação. Aguardando os horários-alvo e as leituras ANA.'}</p>${chart(rows,ok?p:null)}${saved(feed,'historico_sombra_stz_n5.json')}<p class="shadow-note">Azul: observado. Roxo: previsão emitida. Atualização: ${when(feed.gerado_em)}. Pesquisa experimental; não é alerta oficial.</p>`;
  }
  function n5Row(feed,n5,win){
    const p=n5&&n5.previsao;if(!p)return '';
    const m=n5.avaliacao?.[win]||{},t=feed.referencia_n5_teste||{},ok=current(n5,p);
    return `<tr class="is-reference"><th scope="row">N5 · MATLAB (comparativa pública)</th><td title="${esc((p.inputs_faltantes||[]).join('; ')||p.status)}">${ok?'Em acompanhamento':'Sem previsão futura'}</td><td>${ok?meters(p.nivel_previsto_cm):'—'}</td><td>${ok?when(p.hora_alvo):'—'}</td><td>${m.n||0}</td><td>${error(m.mae_cm)}</td><td>${error(m.rmse_cm)}</td><td>${error(m.vies_cm)}</td><td>${error(m.mae_persistencia_cm)}</td><td>${error(t.mae_cm)}</td></tr>`;
  }
  function v11Panel(el,feed){
    const p=feed.previsao||{},ok=current(feed,p),m=feed.avaliacao?.total||{},two=p.cascata_2h||{};
    const coverage=(p.cobertura_chuva||[]).map(c=>`${c.janela_h} h: ${Object.entries(c.horas_por_posto||{}).map(([cod,n])=>`${cod}: ${n}/${c.janela_h} horas`).join(' · ')}`).join('; ');
    const partial=ok&&(p.cobertura_chuva||[]).some(c=>c.parcial);
    el.innerHTML=`<span class="shadow-tag">Comparativa em sombra · 4 h</span><h3>V11 · cascata 2 h → 4 h</h3><p>A RNA principal de 2 h fornece a variação e o nível futuro usados nas duas últimas entradas da V11.</p><strong class="shadow-number">${ok?meters(p.nivel_previsto_cm):'Aguardando dados'}</strong><p class="shadow-status">${ok?'Para '+when(p.hora_alvo)+' · base '+when(p.hora_modelo):'Sem previsão futura com todas as entradas necessárias neste ciclo.'}</p>${ok?'<p class="shadow-note">Passo de 2 h: '+meters(two.nivel_previsto_cm)+' para '+when(two.hora_alvo)+'. Antecedência restante da V11: '+cm.format((date(p.hora_alvo)-new Date())/3600000)+' h.</p>':''}${partial?'<p class="shadow-warning">Cobertura de chuva parcial: a média usa os postos com leitura em cada hora. Ausências não são substituídas por zero.</p>':''}<div class="shadow-metrics"><span>Conferidas<b>${m.n||0}</b></span><span>MAE<b>${error(m.mae_cm)}</b></span><span>RMSE<b>${error(m.rmse_cm)}</b></span></div><p class="shadow-note">${m.n?'Erros calculados com leituras observadas após os horários-alvo.':'Avaliação prospectiva iniciada nesta ativação. Aguardando horários-alvo e leituras ANA.'}</p>${chart(feed.serie_recente||[],ok?p:null)}${saved(feed,'historico_sombra_stz_v11.json')}<details><summary>Entradas e limites da V11</summary><p>Níveis e diferenças de Santa Tereza e Linha José Júlio; chuva média acumulada de 12 h no grupo local e 15 h no posto ANA 2851044 (Carreiro).</p><p>${esc(coverage||'Cobertura ainda indisponível.')}</p>${!ok?'<p>'+esc((p.inputs_faltantes||[]).join('; ')||p.status||'Aguardando coleta')+'</p>':''}<p>${esc(feed.limite_cientifico)}</p><p>As duas redes usam a mesma hora-base. O passo de 2 h é calculado antes de seu horário-alvo, sem utilizar observação futura.</p></details><p class="shadow-note">Azul: observado. Roxo: previsão emitida. Atualização: ${when(feed.gerado_em)}. Pesquisa experimental; não é alerta oficial.</p>`;
  }
  function userPanel(el,feed,n5){
    let h=Number(el.dataset.horizon||4),win=el.dataset.window||'168',selected=el.dataset.model||'';
    const models=(feed.modelos||[]).filter(p=>p.horizonte_h===h);
    if(!models.some(p=>p.modelo_id===selected))selected=models[0]?.modelo_id||'';
    el.dataset.model=selected;
    const picked=models.find(p=>p.modelo_id===selected),start=win==='total'?0:Date.now()-Number(win)*3600000;
    const rows=(feed.serie_recente||[]).filter(r=>r.modelo_id===selected&&date(r.hora_alvo)>=start);
    const graphNote=!rows.length&&!current(feed,picked)?'<p class="shadow-note">Ainda não há emissões válidas deste modelo nesta janela. Se o horário-alvo já passou, aguardamos uma base nova para registrar a próxima previsão.</p>':'';
    const status=p=>current(feed,p)?'Em acompanhamento':p.status==='ALVO_JA_PASSOU'?'Aguardando base nova':p.status==='SAIDA_FORA_FAIXA_PLAUSIVEL'?'Fora da faixa plausível':'Dados/modelo indisponíveis';
    el.innerHTML=`<span class="shadow-tag">Seu acompanhamento · modelos em sombra</span><h3>Como cada arquitetura se sai ao vivo?</h3><p>Compare previsões emitidas antes do horário-alvo com o nível observado pela ANA. Os indicadores abaixo usam somente esse acompanhamento prospectivo.</p><div class="shadow-controls"><label>Horizonte<select id="shadow-horizon">${[2,4,8,12].map(n=>`<option value="${n}" ${n===h?'selected':''}>${n} h</option>`).join('')}</select></label><label>Janela de avaliação<select id="shadow-window">${[['24','24 horas'],['72','3 dias'],['168','7 dias'],['total','Desde a ativação']].map(([v,l])=>`<option value="${v}" ${v===win?'selected':''}>${l}</option>`).join('')}</select></label><label>Modelo no gráfico<select id="shadow-model">${models.map(p=>`<option value="${esc(p.modelo_id)}" ${p.modelo_id===selected?'selected':''}>${esc(p.nome)}</option>`).join('')}</select></label></div><p class="shadow-status">Atualização: ${when(feed.gerado_em)} · ${models.filter(p=>current(feed,p)).length}/${models.length} modelos com previsão futura disponível neste horizonte.</p><h4>Nível previsto e observado · ${h} h</h4>${chart(rows,current(feed,picked)?picked:null)}${graphNote}${saved(feed,'historico_sombra_stz_usuario.json')}<p class="shadow-note">Azul: nível observado. Roxo: previsão registrada. Gráfico: até oito dias de emissões; métricas: janela selecionada. Lacunas não são preenchidas. A base pode anteceder a atualização; confira o horário-alvo.</p><div class="shadow-table-wrap"><table><caption class="sr-only">Resultados prospectivos por arquitetura no horizonte selecionado</caption><thead><tr><th>Modelo</th><th>Estado</th><th>Previsão</th><th>Horário-alvo</th><th>Conferidas</th><th>MAE</th><th>RMSE</th><th>Viés</th><th>MAE persistência</th><th>MAE teste histórico</th></tr></thead><tbody>${models.map(p=>{const m=p.avaliacao?.[win]||{};const ok=current(feed,p);return `<tr class="${p.modelo_id===selected?'is-selected':''}"><th scope="row">${esc(p.nome)}</th><td title="${esc((p.inputs_faltantes||[]).join('; ')||p.motivo||p.status)}">${status(p)}</td><td>${ok?meters(p.nivel_previsto_cm):'—'}</td><td>${ok?when(p.hora_alvo):'—'}</td><td>${m.n||0}</td><td>${error(m.mae_cm)}</td><td>${error(m.rmse_cm)}</td><td>${error(m.vies_cm)}</td><td>${error(m.mae_persistencia_cm)}</td><td title="${esc(p.teste_historico?'persistência no mesmo teste: '+error(p.teste_historico.persistencia_mae_cm):'')}">${error(p.teste_historico?.mae_cm)}</td></tr>`;}).join('')}${h===4?n5Row(feed,n5,win):''}</tbody></table></div><p class="shadow-note">Zero previsões conferidas significa que os alvos ainda não chegaram ou que a observação exata não está disponível. Os indicadores são individuais; a cobertura pode diferir entre modelos. MAE teste histórico: erro nos eventos reservados do treino (partição 3), não é desempenho ao vivo.</p><details><summary>Origem e limites deste acompanhamento</summary><p>${esc(feed.proveniencia)}</p><p>As mesmas arquiteturas foram reexecutadas em uma rodada congelada com os 11 sinais do contrato N5, sem Castro Alves. Os eventos de treino, validação e teste ficam separados. Os erros históricos de teste não são misturados aos erros ao vivo. A extensão de 12 h é nova.</p><p>DCRNN/GraphGRU e Transformer + GNN: pendentes de um grafo hidrológico validado; não têm previsões executadas neste painel.</p><p>${feed.historico_legado_sem_inputs_n||0} emissões iniciais foram preservadas com previsão e horários, mas sem entradas arquivadas. A gravação completa de entradas e telemetria começa nesta revisão; não é reconstruída retroativamente.</p><p>Produto experimental; não é alerta oficial e não altera a RNA principal de 2 h.</p></details>`;
    for(const [id,key] of [['shadow-horizon','horizon'],['shadow-window','window'],['shadow-model','model']])el.querySelector('#'+id).addEventListener('change',e=>{el.dataset[key]=e.target.value;userPanel(el,feed,n5);});
  }
  const cache={};
  const unavailable='<span class="shadow-tag">Comparativa em sombra</span><p class="shadow-warning">Os dados de acompanhamento estão indisponíveis. A avaliação será exibida quando o feed voltar.</p>';
  function render(){
    if(!cache.loaded)return;
    const pub=document.getElementById('stz-shadow-n5'),v11=document.getElementById('stz-shadow-v11'),user=document.getElementById('stz-shadow-user');
    if(pub){if(cache.n5)publicPanel(pub,cache.n5);else pub.innerHTML=unavailable;}
    if(v11){if(cache.v11)v11Panel(v11,cache.v11);else v11.innerHTML=unavailable;}
    if(user){if(cache.user)userPanel(user,cache.user,cache.n5);else user.innerHTML=unavailable;}
  }
  async function refresh(){
    const pub=document.getElementById('stz-shadow-n5'),v11=document.getElementById('stz-shadow-v11'),user=document.getElementById('stz-shadow-user');
    const [n5,feed,third]=await Promise.all([pub||user?fetchFeed('previsao_sombra_stz_n5.json').catch(()=>null):null,user?fetchFeed('previsao_sombra_stz_usuario.json').catch(()=>null):null,v11?fetchFeed('previsao_sombra_stz_v11.json').catch(()=>null):null]);
    cache.n5=n5;cache.user=feed;cache.v11=third;cache.loaded=true;render();
  }
  function openUser(){document.getElementById('mode-p')?.click();document.getElementById('stz-shadow-user')?.scrollIntoView({behavior:'smooth',block:'start'});}
  document.getElementById('stz-shadow-open')?.addEventListener('click',openUser);
  // Robo publica a cada 30 min; busca a cada 5 min e redesenha a cada minuto para expirar alvos vencidos.
  refresh();setInterval(refresh,300000);setInterval(render,60000);
  if(location.hash==='#stz-shadow-user')setTimeout(openUser,500);
})();
