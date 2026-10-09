"""N5 4 h sem Castro Alves: comparativa publica com feed e historico proprios."""
import datetime as dt
from . import stz_shadow_common as C
from . import gerar_previsao_ao_vivo as R
from . import stz_shadow_storage as S

CONTRACT = C.ROOT / "assets/data/stz_n5_sombra_contrato.json"
OUT = C.ROOT / "previsao_sombra_stz_n5.json"
HISTORY = S.HISTORY_ROOT / "n5"
LEGACY = C.ROOT / "historico_sombra_stz_n5.json"

def forecast(levels, rain, now, contract):
    m = contract["horizontes"]["4h"]["modelos"][0]
    p = {"modelo_id": "STZ_4H_N5", "modelo_sha256": m["modelo_sha256"], "modelo": m["modelo_id"],
         "horizonte_h": 4, "emitida_em": C.stamp(now), "shadow_only": True, "principal": False,
         "disponivel": False, "status": "ENTRADAS_INCOMPLETAS", "nivel_previsto_cm": None,
         "hora_modelo": None, "hora_alvo": None, "estacoes_nivel": m["estacoes_nivel"],
         "estacoes_chuva": m["estacoes_chuva"], "inputs_faltantes": []}
    path = C.ROOT / m["mat"]
    if C.sha(path) != m["modelo_sha256"]:
        p["status"] = "BLOQUEADO_SHA256"
        return p
    clean = C.qc_levels(levels, contract["limites_estacao_cm"])
    t, seq, missing = C.recent_base(m["inputs"], clean, rain, now)
    p["inputs_faltantes"] = missing
    if t is None:
        return p
    x = seq[-1]
    predicted = float(x[0] + R.prever(str(path), x))
    if not R._nivel_plausivel(predicted, C.STZ):
        p["status"] = "SAIDA_FORA_FAIXA_PLAUSIVEL"
        return p
    p.update(disponivel=True, status="OK_SOMBRA", hora_modelo=C.stamp(t),
             hora_alvo=C.stamp(t + dt.timedelta(hours=4)), nivel_base_cm=x[0], nivel_previsto_cm=predicted,
             inputs=x, contrato_temporal="hourly_exact_v1", idade_base_min=(now-t).total_seconds()/60,
             antecedencia_efetiva_h=(t+dt.timedelta(hours=4)-now).total_seconds()/3600)
    return p

def main(data=None, issued_at=None):
    contract = C.read(CONTRACT)
    before = S.load(HISTORY, LEGACY)
    levels, rain = data if data is not None else C.download()
    now = issued_at or R.agora_brt()
    p = forecast(levels, rain, now, contract)
    hist = C.update_history(before, [p], levels.get(C.STZ, {}), now,contract['limites_estacao_cm'])
    archive = S.archive('n5',now,[p],levels,rain,before,hist)
    rows = [r for r in hist["registros"] if r["modelo_sha256"] == p["modelo_sha256"]]
    files = S.save(HISTORY,before,hist,LEGACY)
    feed = {"schema_version": "stz_n5_shadow_v1", "gerado_em": C.stamp(now), "timezone": "America/Sao_Paulo",
            "shadow_only": True, "official_alert": False, "promotion_allowed": False, "aviso": C.AVISO,
            "previsao": p, "avaliacao": C.evaluate(rows, now),
            "serie_recente": [C.chart_point(r) for r in rows[-240:]], "arquivo_emissao":archive,
            "historico_registros_n":len(hist['registros']), "historico_arquivos":C.history_paths(files)}
    C.write(OUT, feed, compact=True)
    print(p["status"], p["hora_modelo"], p["hora_alvo"], p["nivel_previsto_cm"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
