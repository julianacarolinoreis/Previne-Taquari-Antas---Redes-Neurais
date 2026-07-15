import numpy as np, json, heapq
from scipy import ndimage
dem=np.load('aoi_dem.npy').astype(np.float64); ny,nx=dem.shape
down=np.load('aoi_down.npy'); meta=json.load(open('aoi_meta.json'))
tr={'a':meta['a'],'c':meta['c'],'e':meta['e'],'f':meta['f']}
def cell(lon,lat): return int((lat-tr['f'])/tr['e']), int((lon-tr['c'])/tr['a'])
def lowcell(r,c,rad=3):
    r0,c0=max(0,r-rad),max(0,c-rad); w=dem[r0:r+rad+1,c0:c+rad+1]
    dr,dc=np.unravel_index(np.argmin(w),w.shape); return r0+dr,c0+dc

A=lowcell(*cell(-51.7322,-29.1781))      # estacao Santa Tereza
B=lowcell(*cell(-51.713269,-29.0908727)) # ponte / confluencia (montante)
print('A(estacao) elev',round(dem[A],1),'| B(ponte) elev',round(dem[B],1))

# Dijkstra custo = cota da celula entrada (segue o thalweg)
def dijkstra_path(src,dst):
    N=ny*nx; dist=np.full(N,np.inf); prev=np.full(N,-1,np.int64)
    s=src[0]*nx+src[1]; d=dst[0]*nx+dst[1]
    cost=(dem/10.0)**4   # penaliza fortemente cotas altas -> gruda no fundo do vale
    dist[s]=cost.flat[s]; pq=[(dist[s],s)]
    nb=[(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]
    while pq:
        du,u=heapq.heappop(pq)
        if u==d: break
        if du>dist[u]: continue
        ur,uc=divmod(u,nx)
        for di,dj in nb:
            vr,vc=ur+di,uc+dj
            if 0<=vr<ny and 0<=vc<nx:
                v=vr*nx+vc; nd=du+cost[vr,vc]
                if nd<dist[v]: dist[v]=nd; prev[v]=u; heapq.heappush(pq,(nd,v))
    path=[]; c=d
    while c!=-1: path.append(c); c=prev[c]
    return path[::-1]

path=dijkstra_path(B,A)  # montante -> estacao (segue o rio pela cidade)
river=set(path)
# estende jusante da estacao ate a borda (segue o fluxo, so descendo)
i=A[0]*nx+A[1]; last=dem.flat[i]
while i>=0 and i not in river:
    river.add(i); ni=int(down[i])
    if ni==i or ni<0 or dem.flat[ni]>last+0.5: break
    last=dem.flat[ni]; i=ni
print('celulas do rio (thalweg):', len(river), '| cota', round(min(dem.flat[c] for c in river),1),'->',round(max(dem.flat[c] for c in river),1))

rm=np.zeros((ny,nx),bool)
for c in river: rm[divmod(c,nx)]=True
_,(ri,rj)=ndimage.distance_transform_edt(~rm, return_indices=True)
hand=dem-dem[ri,rj]; hand[hand<0]=0
np.save('aoi_hand2.npy',hand); np.save('aoi_rivermask.npy',rm)

from math import cos,radians
lat0=(meta['S']+meta['N'])/2
cell_ha=(abs(meta['a'])*111320)*(abs(meta['e'])*111320*cos(radians(lat0)))/10000.0
def conn_area(h):
    lbl,_=ndimage.label(hand<=h); keep=set(np.unique(lbl[rm]))-{0}
    return int(np.isin(lbl,list(keep)).sum())*cell_ha
print('h(m) | area_ha conectada')
for h in [1,2,3,5,8,10,12,15]:
    print(f'  {h:2d}  | {conn_area(h):8.1f}')
