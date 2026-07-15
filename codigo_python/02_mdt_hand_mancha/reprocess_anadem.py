import numpy as np, json, base64, rasterio
from scipy import ndimage
from PIL import Image

with rasterio.open('mdt_anadem.tif') as ds:
    dem=ds.read(1).astype('float64'); t=ds.transform; b=ds.bounds
ny,nx=dem.shape
meta={'W':b.left,'S':b.bottom,'E':b.right,'N':b.top,'a':t.a,'c':t.c,'e':t.e,'f':t.f,'rows':ny,'cols':nx}
def cell(lon,lat): return int((lat-t.f)/t.e), int((lon-t.c)/t.a)
sr,sc=cell(-51.7322,-29.1781)
r0,c0=max(0,sr-3),max(0,sc-3); w=dem[r0:sr+4,c0:sc+4]; dr,dc=np.unravel_index(np.argmin(w),w.shape); sr,sc=r0+dr,c0+dc

# talvegue: minimos locais no vale, conectados pela estacao
mn=ndimage.minimum_filter(dem,size=31); thal=(dem<=mn+0.5)&(dem<95)
lbl,_=ndimage.label(thal); thal=lbl==lbl[sr,sc]
_,(ri,rj)=ndimage.distance_transform_edt(~thal,return_indices=True)
hand=dem-dem[ri,rj]; hand[hand<0]=0
print('talvegue', int(thal.sum()),'cells | cota', round(float(dem[thal].min()),1),'->',round(float(dem[thal].max()),1))

# area por cota (conectada ao rio)
from math import cos,radians
lat0=(meta['S']+meta['N'])/2
cell_ha=(abs(t.a)*111320)*(abs(t.e)*111320*cos(radians(lat0)))/10000.0
def flood(h):
    l,_=ndimage.label(hand<=h); keep=set(np.unique(l[thal]))-{0}; return np.isin(l,list(keep))
print('h(m) | area_ha')
for h in [1,3,6,9.5,12,15]:
    print('  %4s | %.0f'%(h,int(flood(h).sum())*cell_ha))

# encode HAND -> PNG (decimetros; 255 = fora do alcance)
enc=np.full(hand.shape,255,np.uint8); valid=hand<=25.0
enc[valid]=np.clip(hand[valid]*10,0,250).astype(np.uint8)
Image.fromarray(enc,mode='L').save('hand_enc_anadem.png')
b64=base64.b64encode(open('hand_enc_anadem.png','rb').read()).decode()
out={'W':meta['W'],'S':meta['S'],'E':meta['E'],'N':meta['N'],'rows':ny,'cols':nx,
     'station':{'lat':-29.1781,'lon':-51.7322,'code':'86472600'},
     'ponte':{'lat':-29.0908727,'lon':-51.713269,'label':'Ponte Santa Barbara'},
     'hand_png_b64':b64,'fonte':'ANADEM v1.0 bare-earth 30 m'}
json.dump(out,open('hand_payload.json','w'))
np.save('aoi_hand2.npy',hand); np.save('aoi_rivermask.npy',thal); np.save('aoi_dem.npy',dem)
json.dump(meta,open('aoi_meta.json','w'))
print('payload salvo | station HAND', round(float(hand[sr,sc]),1),'| png',len(open('hand_enc_anadem.png','rb').read()),'bytes')
