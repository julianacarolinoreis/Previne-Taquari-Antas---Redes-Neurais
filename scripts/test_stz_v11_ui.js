'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function panel(feed){
  const el={innerHTML:''};
  vm.runInNewContext(fs.readFileSync('assets/js/stz_shadow.js','utf8'),{
    document:{getElementById:id=>id==='stz-shadow-v11'?el:null},location:{hostname:'localhost',hash:''},
    fetch:async()=>({ok:true,json:async()=>feed}),Intl,Date,setInterval:()=>{},setTimeout:()=>{}
  });await new Promise(r=>setImmediate(r));return el.innerHTML;
}
(async()=>{
  const feed={gerado_em:new Date().toISOString(),historico_registros_n:1,serie_recente:[],avaliacao:{total:{n:0}},limite_cientifico:'Treino usa observacao futura em +2h; cascata em avaliacao prospectiva.',previsao:{disponivel:true,hora_modelo:new Date().toISOString(),hora_alvo:new Date(Date.now()+4*3600000).toISOString(),nivel_previsto_cm:469.29,nivel_base_cm:456,cascata_2h:{nivel_previsto_cm:486,hora_alvo:new Date(Date.now()+2*3600000).toISOString()},cobertura_chuva:[{janela_h:15,parcial:true,horas_por_posto:{A894:0,'2851044':15}}]}};
  const live=await panel(feed);assert.match(live,/4,69 m/);assert.match(live,/V11 · cascata/);assert.match(live,/Cobertura de chuva parcial/);assert.match(live,/A894: 0\/15 horas/);assert.match(live,/historico_sombra_stz_v11.json/);assert.match(live,/Treino usa observacao futura/);
  feed.previsao.disponivel=false;feed.previsao.inputs_faltantes=['chuva @ 2026-10-08T20:00:00'];
  const absent=await panel(feed);assert.match(absent,/Aguardando dados/);assert.match(absent,/2026-10-08T20:00:00/);assert.doesNotMatch(absent,/4,69 m/);
  feed.previsao.disponivel=true;feed.gerado_em='2020-01-01T00:00:00';assert.doesNotMatch(await panel(feed),/4,69 m/);
  feed.gerado_em=new Date().toISOString();feed.previsao.hora_alvo='2020-01-01T00:00:00';assert.doesNotMatch(await panel(feed),/4,69 m/);
  console.log('V11: previsao futura, cobertura parcial, falta de dados, feed vencido e alvo passado verificados.');
})().catch(e=>{console.error(e);process.exitCode=1;});
