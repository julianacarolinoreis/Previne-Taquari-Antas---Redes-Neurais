"""Uma coleta ANA compartilhada, com isolamento de falha entre os tres destinos."""
from . import stz_shadow_common as C
from . import gerar_sombra_stz_n5 as N
from . import gerar_sombra_stz_usuario as U
from . import gerar_sombra_stz_v11 as V

def main():
    # Nao consultar a ANA se os historicos versionados estiverem ausentes.
    N.S.load(N.HISTORY,N.LEGACY);U.S.load(U.HISTORY,U.LEGACY);V.S.load(V.HISTORY,V.LEGACY)
    data=C.download();now=C.R.agora_brt()
    failures=[]
    for name,run in (('n5',N.main),('v11',V.main),('usuario',U.main)):
        try:run(data,now)
        except Exception as exc:
            print(f'FALHA {name}: {type(exc).__name__}: {exc}',flush=True)
            failures.append(name)
    return int(bool(failures))

if __name__=='__main__':raise SystemExit(main())
