"""Reconstrucao verificavel a partir dos ciclos; nunca sobrescreve um destino existente."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
from previne.robo import stz_shadow_storage as S
from previne.robo import stz_shadow_common as C

def recover(root,source):
    root=Path(root)
    index=C.read(root/'index.json')
    if not index:raise ValueError('Indice de ciclos ausente')
    rows=sorted((a for a in index['arquivos'] if a['fonte']==source),key=lambda a:(a['emitida_em'],a['arquivo']))
    history=None
    for item in rows:
        path=(root/item['arquivo']).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('Caminho fora do arquivo')
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest().upper()!=item['sha256']:raise ValueError('SHA do ciclo divergente')
        payload=json.loads(gzip.decompress(body))
        if history is None:
            history=payload.get('historico_inicial')
            if history is None:raise ValueError('Semente do historico ausente')
            S.validate(history)
        before=copy.deepcopy(history)
        positions={S.key(p):i for i,p in enumerate(history['registros'])}
        for p in payload['alteracoes_historico']:
            k=S.key(p)
            if k in positions:history['registros'][positions[k]]=p
            else:
                positions[k]=len(history['registros']);history['registros'].append(p)
        history['atualizado_em']=payload['emitida_em']
        S.preserve(before,history)
        digest=hashlib.sha256(json.dumps(history,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest().upper()
        if digest!=payload['historico_sha256_canonico']:raise ValueError('Historico reconstruido nao confere com o ciclo')
    if history is None:raise ValueError('Nenhum ciclo para a fonte')
    return history

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-root',type=Path,default=S.ARCHIVE)
    parser.add_argument('--source',choices=('n5','usuario','v11'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    history=recover(args.archive_root,args.source)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(history,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print('Recuperado:',len(history['registros']),'registros em',args.output)

if __name__=='__main__':main()
