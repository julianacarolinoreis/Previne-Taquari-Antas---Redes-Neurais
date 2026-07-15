import openpyxl, json
from collections import OrderedDict

def load_events(path):
    wb=openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws=wb['DADOS']; data=list(ws.iter_rows(values_only=True))[1:]
    iEv,iNiv,iConj=0,23,2
    evs=OrderedDict()
    for r in data: evs.setdefault(r[iEv],[]).append(r[iNiv])
    conj={ev:None for ev in evs}
    for r in data:
        if conj[r[0]] is None: conj[r[0]]=r[iConj]
    return evs, conj

def segment(niv, PEAK_MIN=500, MIN_KEEP=10, TOL=30):
    """Mantém UM bloco contíguo por evento: a subida (desde o começo, mesmo abaixo de 5 m)
    até o pico e a recessão logo após, cortando quando o nível cai abaixo de 5 m pela
    primeira vez depois do pico. Descarta o que vem antes da subida e todo o 'sobe-e-desce
    dos 5 m' depois. Eventos que nunca passam de 5 m (ou espetinhos) saem inteiros."""
    n=len(niv)
    if max(niv) < PEAK_MIN:
        return [False]*n, None
    P=niv.index(max(niv))                      # pico principal (máximo do evento)
    # borda direita: primeira queda abaixo de 5 m depois do pico
    R=P
    while R+1<n and niv[R+1]>=PEAK_MIN: R+=1
    # borda esquerda: início da subida — desce pela rampa até o vale, tolerando ruído
    L=P; run_min=niv[P]
    while L-1>=0 and niv[L-1]<=run_min+TOL:
        L-=1; run_min=min(run_min,niv[L])
    keep=[False]*n
    for i in range(L,R+1): keep[i]=True
    if sum(keep) < MIN_KEEP:
        return [False]*n, None
    return keep, (L,P,R)

if __name__=='__main__':
    evs,conj=load_events('wb_top12h.xlsx')
    tot=0; kepttot=0
    print('EV | conj | linhas | mantidas | descartadas | subida->pico->corte | niv_inicio')
    for ev,niv in evs.items():
        keep,win=segment(niv)
        k=sum(keep); tot+=len(niv); kepttot+=k
        if win: L,P,Rr=win; info=f'{L}->{P}->{Rr}  (inicia em {niv[L]} cm)'
        else: info='evento inteiro descartado'
        print(f' {ev:3}| {conj[ev][:5]:5}| {len(niv):4} | {k:4} | {len(niv)-k:4} | {info}')
    print(f'TOTAL: {tot} linhas -> mantidas {kepttot} ({100*kepttot/tot:.0f}%), descartadas {tot-kepttot} ({100*(tot-kepttot)/tot:.0f}%)')
