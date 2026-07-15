import numpy as np, json
from collections import defaultdict
from scipy import ndimage

dem=np.load('aoi_dem.npy').astype(np.float64); ny,nx=dem.shape
acc=np.load('aoi_acc.npy'); down=np.load('aoi_down.npy'); meta=json.load(open('aoi_meta.json'))

def rc(idx): return divmod(idx,nx)
# estacao (na do rio) e ponte/confluencia
tr={'a':meta['a'],'c':meta['c'],'e':meta['e'],'f':meta['f']}
def cell(lon,lat): return int((lat-tr['f'])/tr['e']), int((lon-tr['c'])/tr['a'])
st_r,st_c=cell(-51.7322,-29.1781)
# ancora o inicio do tracado na celula de menor cota numa janelinha ao redor da estacao (thalweg)
win=dem[max(0,st_r-2):st_r+3, max(0,st_c-2):st_c+3]
dr,dc=np.unravel_index(np.argmin(win),win.shape)
seed_r,seed_c=max(0,st_r-2)+dr, max(0,st_c-2)+dc
seed=seed_r*nx+seed_c
print('seed elev', round(float(dem.flat[seed]),1))

# inflows: quem escoa para cada celula
inflow=defaultdict(list)
for c in range(ny*nx):
    d=down[c]
    if d>=0: inflow[d].append(c)

river=set()
# jusante: segue o fluxo
i=seed
while i>=0 and i not in river:
    river.add(i); i=int(down[i])
# montante: sobe sempre pelo afluente de maior acumulacao (o tronco)
i=seed
for _ in range(4000):
    ins=inflow.get(i,[])
    if not ins: break
    nxt=max(ins,key=lambda c:acc.flat[c])
    if nxt in river: break
    river.add(nxt); i=nxt
print('celulas do rio tracado:', len(river))

rivermask=np.zeros(ny*nx,bool);
for c in river: rivermask[c]=True
rivermask=rivermask.reshape(ny,nx)
# HAND relativo ao rio mais proximo (2D)
_,(ri,rj)=ndimage.distance_transform_edt(~rivermask, return_indices=True)
ref=dem[ri,rj]
hand=dem-ref
hand[hand<0]=0
np.save('aoi_hand2.npy',hand)
np.save('aoi_rivermask.npy',rivermask)

# area por cota, mantendo so o componente conectado ao rio
from math import cos,radians
lat0=(meta['S']+meta['N'])/2
cell_ha=(abs(meta['a'])*111320)*(abs(meta['e'])*111320*cos(radians(lat0)))/10000.0
print('h(m) | area_ha (conectada ao rio)')
for h in [1,2,3,5,8,10,12,15]:
    mask=hand<=h
    lbl,n=ndimage.label(mask)
    keep=set(np.unique(lbl[rivermask]))-{0}
    conn=np.isin(lbl,list(keep))
    print(f'  {h:2d}  | {int(conn.sum())*cell_ha:8.1f}   (bruto {int(mask.sum())*cell_ha:.0f})')
