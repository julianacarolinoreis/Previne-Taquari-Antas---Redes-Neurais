"""Uma coleta ANA compartilhada, com isolamento de falha entre os dois destinos."""
from . import stz_shadow_common as C
from . import gerar_sombra_stz_n5 as N
from . import gerar_sombra_stz_usuario as U

def main():
    # Nao consultar a ANA se os historicos versionados estiverem ausentes.
    N.S.load(N.HISTORY);U.S.load(U.HISTORY)
    data=C.download();now=C.R.agora_brt()
    failures=[]
    for name,run in (('n5',N.main),('usuario',U.main)):
        try:run(data,now)
        except Exception as exc:
            print(f'FALHA {name}: {type(exc).__name__}: {exc}',flush=True)
            failures.append(name)
    return int(bool(failures))

if __name__=='__main__':raise SystemExit(main())
