"""Bloqueia publicacao que remova ou altere emissoes ja versionadas."""
import json
import gzip
import hashlib
from pathlib import Path
import subprocess
from previne.robo import stz_shadow_storage as S
from previne.robo import stz_shadow_common as C

def main():
    for filename in ('historico_sombra_stz_n5.json','historico_sombra_stz_usuario.json'):
        before=json.loads(subprocess.check_output(['git','show','HEAD:'+filename],cwd=C.ROOT))
        after=S.load(C.ROOT/filename);S.preserve(before,after)
    path=S.ARCHIVE/'index.json'
    index=C.read(path,{'arquivos':[]})
    old_path='assets/data/stz_shadow_archive/index.json'
    old_exists=subprocess.run(['git','cat-file','-e','HEAD:'+old_path],cwd=C.ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if old_exists:
        old_index=json.loads(subprocess.check_output(['git','show','HEAD:'+old_path],cwd=C.ROOT))
        current={a['arquivo']:a for a in index['arquivos']}
        for old in old_index['arquivos']:
            if current.get(old['arquivo'])!=old:raise ValueError('Arquivo anterior removido ou alterado no indice')
    files={str(p.relative_to(S.ARCHIVE)).replace('\\','/') for p in S.ARCHIVE.rglob('*.json.gz')}
    indexed={a['arquivo'] for a in index['arquivos']}
    if files!=indexed or len(indexed)!=len(index['arquivos']):raise ValueError('Indice nao corresponde aos arquivos de ciclo presentes')
    for item in index['arquivos']:
        archive=(S.ARCHIVE/item['arquivo']).resolve()
        if not archive.is_relative_to(S.ARCHIVE.resolve()):raise ValueError('Caminho de arquivo fora do catalogo')
        body=archive.read_bytes()
        if hashlib.sha256(body).hexdigest().upper()!=item['sha256']:raise ValueError('SHA do arquivo de ciclo diverge')
        payload=json.loads(gzip.decompress(body))
        if len(payload['previsoes'])!=item['previsoes_n']:raise ValueError('Contagem do arquivo diverge')
    print('Persistencia validada: historicos preservados;',len(index['arquivos']),'arquivos de ciclo integros')
    return 0

if __name__=='__main__':raise SystemExit(main())
