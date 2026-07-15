import numpy as np, heapq, json
dem = np.load('aoi_dem.npy').astype(np.float64)
meta = json.load(open('aoi_meta.json'))
ny, nx = dem.shape
NB = [(-1,0,1),(1,0,1),(0,-1,1),(0,1,1),(-1,-1,1.4142),(-1,1,1.4142),(1,-1,1.4142),(1,1,1.4142)]

# 1) Priority-flood: preenche depressoes para a agua conectar (Barnes 2014)
def priority_flood(dem):
    filled = dem.copy()
    seen = np.zeros(dem.shape, bool)
    h = []
    for i in range(ny):
        for j in (0, nx-1):
            heapq.heappush(h, (dem[i,j], i, j)); seen[i,j]=True
    for j in range(nx):
        for i in (0, ny-1):
            if not seen[i,j]:
                heapq.heappush(h, (dem[i,j], i, j)); seen[i,j]=True
    while h:
        e,i,j = heapq.heappop(h)
        for di,dj,_ in NB:
            ni,nj = i+di, j+dj
            if 0<=ni<ny and 0<=nj<nx and not seen[ni,nj]:
                ne = dem[ni,nj] if dem[ni,nj] > e else e
                filled[ni,nj] = ne; seen[ni,nj]=True
                heapq.heappush(h, (ne, ni, nj))
    return filled

filled = priority_flood(dem)
print('filled ok')

# 2) D8: vizinho de maior declive (na superficie preenchida)
down_idx = -np.ones(ny*nx, dtype=np.int64)
best = np.full((ny,nx), -1e18)
for di,dj,dist in NB:
    ne = np.full((ny,nx), np.inf)
    si0,si1 = max(0,-di), ny-max(0,di); sj0,sj1 = max(0,-dj), nx-max(0,dj)
    ne[si0:si1, sj0:sj1] = filled[si0+di:si1+di, sj0+dj:sj1+dj]
    slope = (filled - ne)/dist
    m = slope > best
    best[m] = slope[m]
    ii,jj = np.where(m)
    down_idx[ii*nx+jj] = (ii+di)*nx + (jj+dj)

# 3) Acumulacao de fluxo: processa de cima p/ baixo
order = np.argsort(filled, axis=None)[::-1]
acc = np.ones(ny*nx)
for idx in order:
    d = down_idx[idx]
    if d >= 0 and best.flat[idx] > 0:  # so escoa se ha declive
        acc[d] += acc[idx]
acc2 = acc.reshape(ny,nx)

# 4) Canal = acumulacao acima de limiar
thr = 800  # celulas drenando (~area). ajustavel
channel = acc2 >= thr
print('canal: celulas =', int(channel.sum()), '| elev canal min/med/max',
      round(float(dem[channel].min()),1), round(float(np.median(dem[channel])),1), round(float(dem[channel].max()),1))

# 5) HAND = elev - elev do canal alcancado pelo caminho de fluxo
nce = np.full(ny*nx, np.nan)
demf = dem.ravel()
for idx in order[::-1]:  # baixo -> alto (jusante antes)
    i,j = divmod(idx, nx)
    if channel[i,j]:
        nce[idx] = demf[idx]
    else:
        d = down_idx[idx]
        if d >= 0:
            nce[idx] = nce[d]
hand = (demf - nce).reshape(ny,nx)
hand[np.isnan(hand)] = 9999
hand[hand < 0] = 0
print('HAND pronto. celulas validas:', int((hand<9999).sum()))
np.save('aoi_hand.npy', hand)

# area inundavel por cota (h metros acima do rio)
from math import cos, radians
lat0 = (meta['S']+meta['N'])/2
cell_ha = (abs(meta['a'])*111320) * (abs(meta['e'])*111320*cos(radians(lat0))) / 10000.0
print('area por celula (ha):', round(cell_ha,3))
print('h(m) | celulas | area_ha')
for h in [1,2,3,5,8,10,15,20,25]:
    n = int((hand<=h).sum())
    print(f'  {h:2d}  | {n:6d} | {n*cell_ha:8.1f}')
