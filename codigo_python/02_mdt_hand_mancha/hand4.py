import numpy as np, json
from scipy import ndimage
from PIL import Image
dem=np.load('aoi_dem.npy').astype(np.float64); ny,nx=dem.shape; meta=json.load(open('aoi_meta.json'))
def cell(lon,lat): return int((lat-meta['f'])/meta['e']), int((lon-meta['c'])/meta['a'])
sr,sc=cell(-51.7322,-29.1781)
r0,c0=max(0,sr-3),max(0,sc-3); w=dem[r0:sr+4,c0:sc+4]; dr,dc=np.unravel_index(np.argmin(w),w.shape); sr,sc=r0+dr,c0+dc

# talvegue: celulas quase no minimo local (janela ~9 cells), dentro do vale, conectadas pela estacao
mn=ndimage.minimum_filter(dem, size=9)
thal=(dem<=mn+1.0) & (dem<95)
lbl,_=ndimage.label(thal)
thal=lbl==lbl[sr,sc]
print('talvegue cells:', int(thal.sum()), '| cota', round(float(dem[thal].min()),1),'->',round(float(dem[thal].max()),1))

# HAND = cota - cota do talvegue mais proximo (2D)
_,(ri,rj)=ndimage.distance_transform_edt(~thal, return_indices=True)
hand=dem-dem[ri,rj]; hand[hand<0]=0
np.save('aoi_hand2.npy',hand); np.save('aoi_rivermask.npy',thal)

from math import cos,radians
lat0=(meta['S']+meta['N'])/2
cell_ha=(abs(meta['a'])*111320)*(abs(meta['e'])*111320*cos(radians(lat0)))/10000.0
def flood(h):
    lbl,_=ndimage.label(hand<=h); keep=set(np.unique(lbl[thal]))-{0}
    return np.isin(lbl,list(keep))
print('h(m) | area_ha')
for h in [1,2,3,4,6,8,10]:
    print(f'  {h:2d}  | {int(flood(h).sum())*cell_ha:7.1f}')

# render debug: DEM cinza + talvegue + mancha h=6
base=np.clip((dem-dem.min())/(np.percentile(dem,97)-dem.min()),0,1)
img=np.stack([(60+base*150).astype(np.uint8)]*3,axis=-1)
f6=flood(6)
img[f6]=[40,110,230]
img[thal]=[255,255,255]
r,c=cell(-51.7322,-29.1781); img[max(0,r-2):r+3,max(0,c-2):c+3]=[255,0,0]
Image.fromarray(img).resize((nx*2,ny*2),Image.NEAREST).save('flood_debug.png')
print('saved flood_debug.png (mancha em h=6m)')
