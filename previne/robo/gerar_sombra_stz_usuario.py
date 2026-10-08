"""Todas as arquiteturas comparativas da versao de usuario, por horizonte."""
import datetime as dt
import joblib
import numpy as np
import torch
from . import stz_shadow_common as C
from . import gerar_previsao_ao_vivo as R
from .stz_model_architectures import predict_numpy
from . import stz_shadow_storage as S

MANIFEST = C.ROOT / "assets/data/stz_user_models/manifest.json"
OUT = C.ROOT / "previsao_sombra_stz_usuario.json"
HISTORY = C.ROOT / "historico_sombra_stz_usuario.json"

def main(data=None,issued_at=None):
    torch.set_num_threads(2)
    contract = C.read(C.ROOT / "assets/data/stz_n5_sombra_contrato.json")
    specs = contract["horizontes"]["4h"]["modelos"][0]["inputs"]
    manifest = C.read(MANIFEST)
    before=S.load(HISTORY)
    levels, rain = data if data is not None else C.download()
    now = issued_at or R.agora_brt()
    clean = C.qc_levels(levels, contract["limites_estacao_cm"])
    bases = {k: C.recent_base(specs, clean, rain, now, k) for k in (1,4)}
    predictions = []
    for m in manifest["models"]:
        p = {"modelo_id": m["id"], "nome": m["name"], "horizonte_h": m["horizon_h"],
             "modelo_sha256": m["sha256"], "emitida_em": C.stamp(now), "shadow_only": True,
             "disponivel": False, "status": "ENTRADAS_INCOMPLETAS", "nivel_previsto_cm": None,
             "hora_modelo": None, "hora_alvo": None}
        t, seq, missing = bases[m["lookback_h"]]
        p["inputs_faltantes"] = missing
        path = C.ROOT / m["path"]
        try:
            if C.sha(path) != m["sha256"]:
                raise ValueError("SHA256 do modelo diverge")
            if t is not None:
                target = t + dt.timedelta(hours=m["horizon_h"])
                x = np.asarray(seq,dtype=np.float32)
                p.update(hora_modelo=C.stamp(t),hora_alvo=C.stamp(target),nivel_base_cm=float(x[-1,0]),
                         antecedencia_efetiva_h=(target-now).total_seconds()/3600,
                         inputs=x.tolist(),inputs_nomes=[s['nome'] for s in specs],
                         inputs_horas=[C.stamp(t-dt.timedelta(hours=i)) for i in range(m['lookback_h']-1,-1,-1)])
                if target <= now:
                    p["status"] = "ALVO_JA_PASSOU"
                else:
                    delta = float(predict_numpy(path,m["name"],x[None])[0]) if m["family"]=="temporal" else float(joblib.load(path).predict(x[-1:])[0])
                    base = float(x[-1,0]); pred = base + delta
                    p.update(hora_modelo=C.stamp(t),hora_alvo=C.stamp(target),nivel_base_cm=base,
                             antecedencia_efetiva_h=(target-now).total_seconds()/3600)
                    if R._nivel_plausivel(pred,C.STZ):
                        p.update(disponivel=True,status="OK_SOMBRA",nivel_previsto_cm=pred)
                    else:
                        p["status"] = "SAIDA_FORA_FAIXA_PLAUSIVEL"
        except (ValueError,OSError) as exc:
            p.update(status="BLOQUEADO_MODELO",motivo=str(exc))
        predictions.append(p)
    hist = C.update_history(before,predictions,levels.get(C.STZ,{}),now,contract['limites_estacao_cm'])
    archive=S.archive('usuario',now,predictions,levels,rain,before,hist)
    for p in predictions:
        rows=[r for r in hist["registros"] if r["modelo_id"]==p["modelo_id"] and r["modelo_sha256"]==p["modelo_sha256"]]
        p["avaliacao"] = C.evaluate(rows,now)
    feed={"schema_version":"stz_user_shadow_v1","gerado_em":C.stamp(now),"timezone":"America/Sao_Paulo",
          "shadow_only":True,"official_alert":False,"promotion_allowed":False,"aviso":C.AVISO,
          "proveniencia":manifest["provenance"],"versao":manifest["version"],
          "modelos":predictions,"arquiteturas_pendentes":manifest["unavailable_architectures"],
          "arquivo_emissao":archive,"historico_registros_n":len(hist['registros']),
          "historico_legado_sem_inputs_n":sum('inputs' not in p for p in hist['registros']),
          "serie_recente":[p for p in hist["registros"] if (now-dt.datetime.fromisoformat(p["hora_modelo"])).total_seconds()<=8*86400]}
    S.save(HISTORY,before,hist);C.write(OUT,feed)
    print('Usuario sombra:',len(predictions),'modelos;',sum(p['disponivel'] for p in predictions),'disponiveis')
    return 0

if __name__=="__main__":raise SystemExit(main())
