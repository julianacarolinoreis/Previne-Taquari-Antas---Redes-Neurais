"""INMET (apitempo) — exige token. Lido da variável de ambiente INMET_TOKEN (secret no GitHub); sem token, a fonte é
pulada e isso fica registrado na cobertura. Hora: HR_MEDICAO em UTC (acumulado da hora que termina nela) → BRT − 3 h,
o mesmo rótulo do forcamento_v3 (hora H = (H − 1 h, H])."""
import os
import time
from datetime import datetime, timedelta

import requests

URL = "https://apitempo.inmet.gov.br/token/estacao/{a:%Y-%m-%d}/{b:%Y-%m-%d}/{cod}/{token}"


def token():
    return os.environ.get("INMET_TOKEN") or None


def baixar(cod, ini, fim, tk, timeout=60, tentativas=3):
    """{hora BRT: mm} da estação (código sem o prefixo INMET_), (erro ou None)."""
    erro = None
    for k in range(tentativas):
        try:
            r = requests.get(URL.format(a=ini - timedelta(days=1), b=fim + timedelta(days=1), cod=cod, token=tk),
                             timeout=timeout)
            if r.status_code == 204 or not r.content:
                return {}, "sem conteúdo (204)"
            r.raise_for_status()
            out = {}
            for x in r.json():
                if x.get("CHUVA") in (None, ""):
                    continue
                t = datetime.strptime(f"{x['DT_MEDICAO']} {int(x['HR_MEDICAO']):04d}", "%Y-%m-%d %H%M") - timedelta(hours=3)
                v = float(x["CHUVA"])
                if ini <= t <= fim and 0 <= v < 200:
                    out[t] = v
            return out, None
        except Exception as exc:  # noqa: BLE001
            erro = repr(exc)[:160]
            time.sleep(3 * (k + 1))
    return {}, erro
