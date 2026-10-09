"""Bloqueia publicacao que remova ou altere emissoes ja versionadas."""
import json
import gzip
import hashlib
from pathlib import Path
import subprocess
from previne.robo import stz_shadow_storage as S
from previne.robo import stz_shadow_common as C
from previne.robo import gerar_sombra_stz_n5 as N
from previne.robo import gerar_sombra_stz_usuario as U
from previne.robo import gerar_sombra_stz_v11 as V

def git_json(path,root=C.ROOT):
    path=str(Path(path).relative_to(root)).replace('\\','/')
    done=subprocess.run(['git','show','HEAD:'+path],cwd=root,capture_output=True)
    return json.loads(done.stdout) if done.returncode==0 else None

def git_history(directory,legacy,root=C.ROOT):
    rel=str(Path(directory).relative_to(root)).replace('\\','/')
    names=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD','--',rel+'/'],cwd=root,text=True).split()
    parts=[(Path(n).stem,git_json(root/n,root)) for n in names if n.endswith('.json')]
    return S.combine(git_json(legacy,root),parts)

def main():
    for directory,legacy in ((N.HISTORY,N.LEGACY),(U.HISTORY,U.LEGACY),(V.HISTORY,V.LEGACY)):
        before=git_history(directory,legacy)
        after=S.load(directory,legacy);S.preserve(before,after)
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
