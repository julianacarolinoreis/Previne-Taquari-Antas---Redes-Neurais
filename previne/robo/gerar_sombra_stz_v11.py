"""V11 de 4 h em cascata com a RNA principal de 2 h, sem observacoes futuras."""
import copy
import datetime as dt
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from . import stz_shadow_common as C
from . import stz_shadow_storage as S
from . import gerar_previsao_ao_vivo as R
from . import fontes_chuva_8h as F

CONTRACT = C.ROOT / 'assets/data/stz_v11_sombra_contrato.json'
OUT = C.ROOT / 'previsao_sombra_stz_v11.json'
HISTORY = S.HISTORY_ROOT / 'v11'
LEGACY = C.ROOT / 'historico_sombra_stz_v11.json'
HOUR = dt.timedelta(hours=1)

def complete_ana_rain(xml):
    """Soma (H-1h,H]; descarta quartos ausentes, conflitos e valores invalidos."""
    if not xml:
        return {}
    _, rain = C.parse_xml(xml)
    root = ET.fromstring(xml)
    if (root.text or '').strip().startswith('<'):
        root = ET.fromstring(root.text)
    times = set()
    for row in root.iter():
        fields = {R._local(c.tag): (c.text or '').strip() for c in row}
        if fields.get('Chuva') not in (None, ''):
            t = R._parse_hora(fields.get('DataHora') or fields.get('Data_Hora') or '')
            if t is not None:
                times.add(t)
    quarter_hour = any(t.minute != 0 for t in times)
    offsets = (0,15,30,45) if quarter_hour else (0,)
    return {h:v for h,v in rain.items()
            if all(h-dt.timedelta(minutes=i) in times for i in offsets)}

def download_rain(rain, now):
    """Coleta os tres postos exatos e registra payloads; sem substituicao espacial."""
    result = copy.deepcopy(rain)
    evidence = {}
    for cod in C.STATIONS:
        raw = C.DOWNLOAD_EVIDENCE.get(cod, {}).get('xml')
        result[cod] = complete_ana_rain(raw) if raw else {}
    def ana():
        xml = R._obter_xml_ana('2851044',8,R.ANA_TIMEOUT_CHUVA_S,2,R._serie_chuva_de_xml,'ANA chuva V11')
        raw = xml.encode('utf-8') if isinstance(xml,str) else xml
        return complete_ana_rain(xml), {'fonte':'ANA','xml_sha256':hashlib.sha256(raw).hexdigest().upper() if raw else None,'xml':raw.decode('utf-8-sig') if raw else None}
    def official(cod):
        if cod == 'A894':
            url=F.INMET_URL.format(ini=(now-dt.timedelta(days=8)).date().isoformat(),fim=now.date().isoformat(),cod=cod)
            parser=F.parse_inmet_chuva
        else:
            url=F.CEMADEN_URL.format(id_estacao=F.CEMADEN_ID,horas_menos_um=167)
            parser=F.parse_cemaden_chuva
        payload=F._http_json(url,timeout=12,tentativas=1)
        series=parser(payload)
        # Os parsers existentes rotulam o inicio; V11 usa o final do intervalo.
        series={t+HOUR:v for t,v in series.items() if math.isfinite(v) and 0<=v<=100}
        body=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')
        return series,{'fonte':'INMET' if cod=='A894' else 'CEMADEN','endpoint':url,'payload_sha256':hashlib.sha256(body).hexdigest().upper(),'payload':payload}
    jobs={'2851044':ana,'A894':lambda:official('A894'),'432040401A':lambda:official('432040401A')}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={cod:pool.submit(fn) for cod,fn in jobs.items()}
        for cod,future in pending.items():
            try:result[cod],evidence[cod]=future.result()
            except Exception as exc:
                result[cod]={};evidence[cod]={'estado':'INDISPONIVEL','erro':f'{type(exc).__name__}: {exc}'}
    csv=R._carregar_chuvas_8h_csv()
    for cod in ('A894','432040401A'):
        fallback={t+HOUR:v for t,v in csv.get(cod,{}).items() if math.isfinite(v) and 0<=v<=100}
        missing={t:v for t,v in fallback.items() if t not in result[cod]}
        result[cod].update(missing)
        evidence[cod]['contingencia_csv_horas']=len(missing)
    csvpath=C.ROOT/'assets/data/chuvas_horarias.csv'
    if csvpath.exists():evidence['csv_sha256']=C.sha(csvpath)
    return result,evidence

def rain_inputs(specs, rain, base):
    x,missing,coverage=[],[],[]
    for spec in specs:
        total=0.0;hours=[];counts={cod:0 for cod in spec['estacoes']}
        for i in range(spec['janela_h']):
            t=base-i*HOUR
            observed={cod:rain.get(cod,{}).get(t) for cod in spec['estacoes']}
            observed={cod:v for cod,v in observed.items() if isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=100}
            absent=[cod for cod in spec['estacoes'] if cod not in observed]
            hours.append({'hora_final':C.stamp(t),'postos_observados':list(observed),'postos_ausentes':absent})
            for cod in observed:counts[cod]+=1
            if observed:total+=sum(observed.values())/len(observed)
            else:missing.append(f"{spec['nome']} @ {C.stamp(t)}: nenhum posto observado")
        complete=all(h['postos_observados'] for h in hours)
        partial=any(h['postos_ausentes'] for h in hours)
        x.append(total if complete else None)
        coverage.append({'nome':spec['nome'],'janela_h':spec['janela_h'],'estacoes_previstas':spec['estacoes'],
                         'horas_por_posto':counts,'completa':complete and not partial,'parcial':partial,'horas':hours})
    return x,missing,coverage

def forecast(levels, rain, now, contract):
    two=contract['cascata_2h']
    p={'modelo_id':contract['modelo_id'],'modelo_sha256':contract['modelo_sha256'],'horizonte_h':4,
       'emitida_em':C.stamp(now),'shadow_only':True,'principal':False,'disponivel':False,
       'status':'ENTRADAS_INCOMPLETAS','nivel_previsto_cm':None,'hora_modelo':None,'hora_alvo':None,
       'inputs_faltantes':[],'cobertura_chuva':[],'contrato_sha256':C.sha(CONTRACT)}
    for m in (contract,two):
        if C.sha(C.ROOT/m['mat'])!=m['modelo_sha256']:
            p['status']='BLOQUEADO_SHA256';return p
    clean=C.qc_levels(levels,contract['limites_estacao_cm'])
    candidates=[t for t in sorted(clean.get(C.STZ,{}),reverse=True)
                if R._eh_hora_cheia(t) and t<=now<t+2*HOUR]
    for base in candidates:
        x,missing=C.inputs(contract['inputs_nivel'],clean,{},base)
        x2,missing2=C.inputs(two['inputs'],clean,{},base)
        xr,mr,coverage=rain_inputs(contract['chuvas'],rain,base)
        absent=missing+[f'RNA2h: {name}' for name in missing2]+mr
        if absent:
            if not p['inputs_faltantes']:
                p.update(inputs_faltantes=absent,cobertura_chuva=coverage)
            continue
        delta2=float(R.prever(str(C.ROOT/two['mat']),x2));level2=x[0]+delta2
        if not R._nivel_plausivel(level2,C.STZ):
            p['status']='CASCATA_2H_FORA_FAIXA_PLAUSIVEL';return p
        full=x+xr+[delta2,level2]
        delta4=float(R.prever(str(C.ROOT/contract['mat']),full));pred=x[0]+delta4
        if not R._nivel_plausivel(pred,C.STZ):
            p['status']='SAIDA_FORA_FAIXA_PLAUSIVEL';return p
        p.update(disponivel=True,status='OK_SOMBRA_CHUVA_PARCIAL' if any(c['parcial'] for c in coverage) else 'OK_SOMBRA',
                 hora_modelo=C.stamp(base),hora_alvo=C.stamp(base+4*HOUR),nivel_base_cm=x[0],nivel_previsto_cm=pred,
                 delta_previsto_cm=delta4,inputs=full,inputs_faltantes=[],cobertura_chuva=coverage,
                 contrato_temporal='hourly_exact_cascade_v1',idade_base_min=(now-base).total_seconds()/60,
                 antecedencia_efetiva_h=(base+4*HOUR-now).total_seconds()/3600,
                 cascata_2h={'modelo_id':two['modelo_id'],'modelo_sha256':two['modelo_sha256'],
                             'hora_modelo':C.stamp(base),'hora_alvo':C.stamp(base+2*HOUR),
                             'emitida_em':C.stamp(now),'delta_previsto_cm':delta2,'nivel_previsto_cm':level2,
                             'inputs':x2,'origem':'inferencia_2h_mesma_base_sem_observacao_futura'})
        return p
    if not candidates:p['inputs_faltantes']=['sem nivel exato recente com alvo intermediario de 2 h ainda futuro']
    return p

def main(data=None, issued_at=None):
    contract=C.read(CONTRACT);before=S.load(HISTORY,LEGACY)
    levels,rain=data if data is not None else C.download()
    now=issued_at or R.agora_brt()
    rain,evidence=download_rain(rain,now)
    # A emissao e posterior a toda a coleta; a antecedencia nao usa a hora de inicio.
    now=R.agora_brt()
    p=forecast(levels,rain,now,contract)
    hist=C.update_history(before,[p],levels.get(C.STZ,{}),now,contract['limites_estacao_cm'])
    archive=S.archive('v11',now,[p],levels,rain,before,hist,provenance={
        'contrato_sha256':C.sha(CONTRACT),'coleta_chuva':evidence,'limite_cientifico':contract['limite_cientifico']})
    files=S.save(HISTORY,before,hist,LEGACY)
    feed={'schema_version':'stz_v11_shadow_v1','gerado_em':C.stamp(now),'timezone':'America/Sao_Paulo',
          'shadow_only':True,'official_alert':False,'promotion_allowed':False,'aviso':C.AVISO,
          'limite_cientifico':contract['limite_cientifico'],'previsao':p,'avaliacao':C.evaluate(hist['registros'],now),
          'serie_recente':[C.chart_point(r) for r in hist['registros'][-240:]],'arquivo_emissao':archive,
          'historico_registros_n':len(hist['registros']),'historico_arquivos':C.history_paths(files)}
    C.write(OUT,feed,compact=True)
    print('V11',p['status'],p['hora_modelo'],p['hora_alvo'],p['nivel_previsto_cm'],flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
