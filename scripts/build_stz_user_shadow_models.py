#!/usr/bin/env python3
"""Nova rodada congelada das arquiteturas comparadas; nunca treina com dados ao vivo."""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
import xgboost
from xgboost import XGBRegressor
import torch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from previne.robo.stz_model_architectures import Temporal, NAMES, predict_numpy

SEED = 20261008
SOURCE = ROOT / "assets/data/stz_user_models"
MODELS = ROOT / "assets/models/stz_user_shadow"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def dataset(horizon):
    matrix = np.loadtxt(SOURCE / "training_n5.csv", delimiter=";", skiprows=1)
    with (SOURCE / "training_n5_meta.csv").open(encoding="utf-8-sig") as stream:
        meta = list(csv.DictReader(stream, delimiter=";"))
    if len(meta) != len(matrix):
        raise ValueError("linhas fonte/meta divergem")
    times = [dt.datetime.strptime(r["COD_SEQUENCIAL"], "%Y%m%d%H%M") for r in meta]
    events = [int(float(r["EVENTO"])) for r in meta]
    splits = matrix[:, -1].astype(int)
    rows = {(e, t): i for i, (e, t) in enumerate(zip(events, times))}
    if len(rows) != len(meta):
        raise ValueError("evento/hora duplicado")
    obs = {}
    for i, (e, t) in enumerate(zip(events, times)):
        for key, v in (((e,t), matrix[i,0]), ((e,t+dt.timedelta(hours=4)), matrix[i,0]+matrix[i,11])):
            if key in obs and abs(obs[key]-v)>1e-5:
                raise ValueError(f"observacoes conflitantes {key}")
            obs[key] = v
    seq, target, part, base, ev, stamp = [], [], [], [], [], []
    for i, (e, t) in enumerate(zip(events, times)):
        indices = [rows.get((e,t-dt.timedelta(hours=k))) for k in (3,2,1,0)]
        target_key = (e,t+dt.timedelta(hours=horizon))
        if None in indices or target_key not in obs:
            continue
        if any(splits[j] != splits[i] for j in indices):
            continue
        if target_key in rows and splits[rows[target_key]] != splits[i]:
            continue
        seq.append(matrix[indices,:11]);target.append(obs[target_key]-matrix[i,0])
        part.append(splits[i]);base.append(matrix[i,0]);ev.append(e);stamp.append(t.isoformat())
    x,y,part,base,ev = map(np.asarray,(seq,target,part,base,ev))
    event_sets = {k: set(ev[part==k]) for k in (1,2,3)}
    assert not (event_sets[1]&event_sets[2] or event_sets[1]&event_sets[3] or event_sets[2]&event_sets[3])
    return x,y,part,base,ev,stamp

def metrics(y, pred):
    e = pred-y
    return {"n":len(y),"mae_cm":float(abs(e).mean()),"rmse_cm":float(np.sqrt((e**2).mean())),"max_abs_cm":float(abs(e).max())}

def static_models():
    return {
        "Ridge": make_pipeline(StandardScaler(),Ridge(alpha=1.0)),
        "Elastic Net": make_pipeline(StandardScaler(),ElasticNet(alpha=0.1,l1_ratio=0.2,max_iter=5000)),
        "SVR": make_pipeline(StandardScaler(),SVR(C=10,epsilon=0.05)),
        "Random Forest": RandomForestRegressor(n_estimators=260,max_depth=14,min_samples_leaf=2,max_features=0.8,n_jobs=2,random_state=SEED),
        "Extra Trees": ExtraTreesRegressor(n_estimators=260,max_depth=14,min_samples_leaf=2,max_features=0.9,n_jobs=2,random_state=SEED),
        "HistGradientBoosting": HistGradientBoostingRegressor(max_iter=260,learning_rate=0.04,max_leaf_nodes=31,l2_regularization=1,random_state=SEED),
        "XGBoost": XGBRegressor(n_estimators=360,max_depth=4,learning_rate=0.03,subsample=0.85,colsample_bytree=0.85,min_child_weight=3,reg_lambda=2,objective="reg:squarederror",tree_method="hist",n_jobs=2,random_state=SEED),
    }

def main():
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    MODELS.mkdir(parents=True,exist_ok=True)
    manifest={"version":"stz_user_shadow_20261008", "created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "research_only":True,"promotion_allowed":False,"official_alert":False,
        "provenance":"Arquiteturas do comparativo 2026-09-15 e AI Lab; novos pesos com contrato N5 sem Castro Alves. 12 h e uma nova extensao.",
        "source_sha256":sha(SOURCE/"training_n5.csv"),"source_meta_sha256":sha(SOURCE/"training_n5_meta.csv"),
        "target_mode":"delta", "sequence_hours":4,"seed":SEED,
        "versions":{"sklearn":sklearn.__version__,"xgboost":xgboost.__version__,"torch":torch.__version__,"joblib":joblib.__version__,"numpy":np.__version__},
        "models":[],"datasets":{},"unavailable_architectures":[{"name":"DCRNN / GraphGRU","reason":"Sem grafo hidrologico validado no contrato original"},{"name":"Transformer + GNN","reason":"Sem grafo hidrologico validado no contrato original"}]}
    for h in (2,4,8,12):
        x,y,s,base,ev,t = dataset(h)
        train,val,test = s==1,s==2,s==3
        manifest["datasets"][str(h)]={"n_train":int(train.sum()),"n_validation":int(val.sum()),"n_test":int(test.sum()),"events":{str(k):sorted(map(int,set(ev[s==k]))) for k in (1,2,3)},"persistence_test":metrics(y[test],np.zeros(test.sum()))}
        for name,model in static_models().items():
            print('FIT',h,name,flush=True)
            model.fit(x[train,-1],y[train])
            path=MODELS/f"h{h}_{name.lower().replace(' ','_')}.joblib"
            joblib.dump(model,path,compress=3)
            pred=model.predict(x[test,-1]);rep=joblib.load(path).predict(x[test,-1]);err=float(abs(pred-rep).max())
            assert err<1e-8
            manifest["models"].append({"id":f"h{h}_{name}","name":name,"horizon_h":h,"family":"static","lookback_h":1,"path":str(path.relative_to(ROOT)).replace('\\','/'),"sha256":sha(path),"test":metrics(y[test],pred),"export_max_error_cm":err})
        xm=x[train].reshape(-1,11).mean(0).astype(np.float32)
        xs=x[train].reshape(-1,11).std(0).astype(np.float32);xs[xs<1e-8]=1
        ym,ys=float(y[train].mean()),float(y[train].std())
        xt=torch.tensor((x-xm)/xs,dtype=torch.float32);yt=torch.tensor((y-ym)/ys,dtype=torch.float32)
        for name in NAMES:
            print('FIT',h,name,flush=True)
            torch.manual_seed(SEED+h)
            model=Temporal(name);optim=torch.optim.Adam(model.parameters(),lr=0.002)
            best=float('inf');stale=0;best_state=None;best_epoch=0
            for epoch in range(1,91):
                model.train();optim.zero_grad();loss=((model(xt[train])-yt[train])**2).mean();loss.backward();optim.step()
                model.eval()
                with torch.no_grad():v=float(((model(xt[val])-yt[val])**2).mean())
                if v<best-1e-7:
                    best=v;stale=0;best_epoch=epoch;best_state={k:z.detach().numpy().copy() for k,z in model.state_dict().items()}
                else:stale+=1
                if stale>=16:break
            model.load_state_dict({k:torch.from_numpy(z) for k,z in best_state.items()})
            path=MODELS/f"h{h}_{name.lower()}.npz"
            np.savez_compressed(path,**{'w__'+k:z for k,z in best_state.items()},x_mean=xm,x_scale=xs,y_mean=np.array(ym),y_scale=np.array(ys))
            with torch.no_grad():pred=model(xt[test]).numpy()*ys+ym
            rep=predict_numpy(path,name,x[test]);err=float(abs(pred-rep).max());assert err<0.002,(name,err)
            manifest["models"].append({"id":f"h{h}_{name}","name":name,"horizon_h":h,"family":"temporal","lookback_h":4,"path":str(path.relative_to(ROOT)).replace('\\','/'),"sha256":sha(path),"test":metrics(y[test],pred),"best_epoch":best_epoch,"epochs_run":epoch,"export_max_error_cm":err})
        (SOURCE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('EXPORTED',len(manifest['models']),flush=True)

if __name__=='__main__':main()
