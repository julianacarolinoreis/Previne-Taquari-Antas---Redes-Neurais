"""Historicos estritos e arquivo imutavel de cada ciclo, inclusive indisponibilidade."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import sys
from importlib.metadata import version
from pathlib import Path
from . import stz_shadow_common as C

ARCHIVE = C.ROOT / 'assets/data/stz_shadow_archive'
SCHEMA = 'stz_shadow_history_v1'
FROZEN = ('modelo_id','modelo_sha256','hora_modelo','hora_alvo','horizonte_h',
          'emitida_em','nivel_previsto_cm','nivel_base_cm','origem','inputs','inputs_horas')
SCORED = ('observado_cm','conferido_em','erro_cm','erro_persistencia_cm')

def key(p):
    return (p['modelo_id'],p['modelo_sha256'],p['hora_modelo'],p['horizonte_h'])

def validate(history):
    if not isinstance(history,dict) or history.get('schema_version')!=SCHEMA or history.get('shadow_only') is not True or not isinstance(history.get('registros'),list):
        raise ValueError('Historico de sombra ausente ou com schema invalido; nao reinicializar')
    keys=set()
    for p in history['registros']:
        k=key(p)
        if k in keys:raise ValueError('Chave duplicada no historico de sombra')
        keys.add(k)
        base,target,issued=(dt.datetime.fromisoformat(p[n]) for n in ('hora_modelo','hora_alvo','emitida_em'))
        if target-base!=dt.timedelta(hours=p['horizonte_h']) or not issued<target or p.get('origem')!='emissao_prospectiva':
            raise ValueError('Horario/origem invalida no historico prospectivo')
        for n in ('nivel_previsto_cm','nivel_base_cm'):
            if not isinstance(p.get(n),(int,float)) or not math.isfinite(p[n]):raise ValueError('Nivel invalido no historico')
        if p.get('observado_cm') is not None:
            obs=p['observado_cm']
            if not math.isfinite(obs) or dt.datetime.fromisoformat(p['conferido_em'])<target:
                raise ValueError('Conferencia invalida')
            if abs(p['erro_cm']-(p['nivel_previsto_cm']-obs))>1e-8 or abs(p['erro_persistencia_cm']-(p['nivel_base_cm']-obs))>1e-8:
                raise ValueError('Erro nao reconcilia com observacao')
    return history

def load(path):
    # Estes arquivos ja foram inicializados e versionados na ativacao.
    # Um checkout incompleto nunca autoriza apagar sua historia.
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))

def preserve(before,after):
    validate(before);validate(after)
    rows={key(p):p for p in after['registros']}
    for old in before['registros']:
        new=rows.get(key(old))
        if new is None:raise ValueError('Uma previsao anterior desapareceu')
        if any(old.get(n)!=new.get(n) for n in FROZEN):raise ValueError('Emissao anterior foi alterada')
        if old.get('observado_cm') is not None and any(old.get(n)!=new.get(n) for n in SCORED):
            raise ValueError('Primeira conferencia foi alterada')

def save(path,before,after):
    preserve(before,after)
    C.write(path,after)

def archive(source,now,predictions,levels,rain,before,after,root=None):
    preserve(before,after)
    root=Path(root or ARCHIVE)
    run='-'.join(os.environ.get(n,'local') for n in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT'))
    if any(c not in '0123456789-local' for c in run):raise ValueError('Identificador de execucao invalido')
    filename=f'{source}_{now.strftime("%Y%m%dT%H%M%S")}_{run}.json.gz'
    path=root/now.date().isoformat()/filename
    index_path=root/'index.json'
    if not index_path.exists() and any(root.rglob('*.json.gz')):
        raise ValueError('Indice de arquivo ausente; nao recriar sobre ciclos existentes')
    index=C.read(index_path,{'schema_version':'stz_shadow_archive_index_v1','arquivos':[]})
    if not isinstance(index,dict) or index.get('schema_version')!='stz_shadow_archive_index_v1' or not isinstance(index.get('arquivos'),list):
        raise ValueError('Indice de arquivo invalido')
    old={key(p):p for p in before['registros']}
    changes=[p for p in after['registros'] if key(p) not in old or p!=old[key(p)]]
    payload={'schema_version':'stz_shadow_cycle_v1','fonte':source,'emitida_em':C.stamp(now),
             'run_id':run,'timezone':'America/Sao_Paulo','unidades':{'nivel':'cm','chuva':'mm'},
             'previsoes':predictions,'alteracoes_historico':changes,
             'historico_n':len(after['registros']),
             'historico_sha256_canonico':hashlib.sha256(json.dumps(after,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest().upper(),
             'historico_inicial':before if not any(a['fonte']==source for a in index['arquivos']) else None,
             'contrato_sha256':C.sha(C.ROOT/'assets/data/stz_n5_sombra_contrato.json'),
             'manifesto_sha256':C.sha(C.ROOT/'assets/data/stz_user_models/manifest.json'),
             'runtime':{'python':sys.version,'pacotes':{n:version(n) for n in ('numpy','scipy','scikit-learn','torch','xgboost','joblib')}},
             'coleta_ana':copy.deepcopy(C.DOWNLOAD_EVIDENCE),
             'nivel_apos_qc':{cod:{C.stamp(t):v for t,v in sorted(series.items())} for cod,series in C.qc_levels(levels,C.read(C.ROOT/'assets/data/stz_n5_sombra_contrato.json')['limites_estacao_cm']).items()},
             'telemetria':{kind:{cod:{C.stamp(t):v for t,v in sorted(series.items())} for cod,series in data.items()} for kind,data in (('nivel',levels),('chuva_horaria',rain))}}
    if path.exists():
        payload['historico_inicial']=json.loads(gzip.decompress(path.read_bytes())).get('historico_inicial')
    body=gzip.compress((json.dumps(payload,ensure_ascii=False,allow_nan=False,sort_keys=True)+'\n').encode('utf-8'),mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=body:raise ValueError('Tentativa de sobrescrever arquivo imutavel de ciclo')
    if not path.exists():
        tmp=path.with_suffix('.tmp');tmp.write_bytes(body);tmp.replace(path)
    digest=hashlib.sha256(body).hexdigest().upper()
    info={'arquivo':str(path.relative_to(root)).replace('\\','/'),'sha256':digest,'bytes':len(body),
          'fonte':source,'emitida_em':C.stamp(now),'previsoes_n':len(predictions),
          'disponiveis_n':sum(p['disponivel'] for p in predictions),'alteracoes_n':len(changes),'historico_n':len(after['registros'])}
    existing=next((a for a in index['arquivos'] if a['arquivo']==info['arquivo']),None)
    if existing and existing!=info:raise ValueError('Indice de arquivo imutavel divergente')
    if not existing:index['arquivos'].append(info)
    index['atualizado_em']=C.stamp(now);C.write(index_path,index)
    return dict(info,arquivo='assets/data/stz_shadow_archive/'+info['arquivo'])
