"""Cliente opcional da API oficial ANA HidroWebService.

Usa ANA_HIDRO_ID / ANA_HIDRO_SENHA quando disponíveis. A rota adotada retorna
chuva e cota telemétricas com carimbo de medição. Se as credenciais não
existirem ou a API falhar, os chamadores mantêm o WebService legado como
contingência.

Pesquisa PREVINE; este módulo não emite alerta.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import urllib.parse
import urllib.request

BASE = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas"
UA = {"User-Agent": "previne-robo/2.0", "Accept": "application/json"}
_TOKEN = {"value": None, "at": 0.0}
_TOKEN_LOCK = threading.Lock()
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def _when(v):
    if not v:
        return None
    s = str(v).strip().replace("T", " ")
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def _credentials():
    ident = (os.environ.get("ANA_HIDRO_ID") or "").strip()
    senha = (os.environ.get("ANA_HIDRO_SENHA") or "").strip()
    return ident, senha


def _token():
    ident, senha = _credentials()
    if not ident or not senha:
        return None
    with _TOKEN_LOCK:
        if _TOKEN["value"] and time.time() - _TOKEN["at"] < 45 * 60:
            return _TOKEN["value"]
        req = urllib.request.Request(
            BASE + "/OAUth/v1",
            headers={**UA, "Identificador": ident, "Senha": senha},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        items = doc.get("items") or {}
        value = items.get("tokenautenticacao") or items.get("token")
        if not value:
            raise RuntimeError("HidroWebService não retornou tokenautenticacao")
        _TOKEN.update(value=str(value), at=time.time())
        return _TOKEN["value"]


def buscar_telemetria_adotada(codigo, dias=7):
    """Retorna {'nivel', 'chuva', 'ultima_nivel', 'ultima_chuva', 'qc'} ou None.

    A API telemétrica limita a consulta a 30 dias. O resultado é filtrado para a
    janela solicitada. Chuva sub-horária é agregada por hora, como no parser
    legado já usado pelo PREVINE.
    """
    ident, senha = _credentials()
    if not ident or not senha:
        return None
    dias = max(1, min(int(dias or 7), 30))
    key = (str(codigo), dias)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and time.time() - cached[0] < 120:
            return cached[1]
    try:
        token = _token()
        if not token:
            return None
        query = urllib.parse.urlencode({
            "CodigoDaEstacao": str(codigo),
            "TipoFiltroData": "DATA_LEITURA",
            "RangeIntervaloDeBusca": "DIAS_30",
        })
        req = urllib.request.Request(
            BASE + "/HidroinfoanaSerieTelemetricaAdotada/v1?" + query,
            headers={**UA, "Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        rows = doc.get("items") or []
        cutoff = dt.datetime.now() - dt.timedelta(days=dias)
        nivel = {}
        chuva = {}
        ultima_nivel = None
        ultima_chuva = None
        qc = {"nivel_suspeito": 0, "chuva_suspeita": 0, "linhas": 0}
        for row in rows:
            t = _when(row.get("Data_Hora_Medicao"))
            if t is None or t < cutoff:
                continue
            qc["linhas"] += 1
            cota = _num(row.get("Cota_Adotada"))
            if cota is not None:
                nivel[t] = cota
                if str(row.get("Cota_Adotada_Status") or "0") not in ("", "0"):
                    qc["nivel_suspeito"] += 1
                if ultima_nivel is None or t > ultima_nivel[0]:
                    ultima_nivel = (t, cota)
            ch = _num(row.get("Chuva_Adotada"))
            if ch is not None:
                h = t.replace(minute=0, second=0, microsecond=0)
                chuva[h] = chuva.get(h, 0.0) + ch
                if str(row.get("Chuva_Adotada_Status") or "0") not in ("", "0"):
                    qc["chuva_suspeita"] += 1
                if ultima_chuva is None or t > ultima_chuva[0]:
                    ultima_chuva = (t, ch)
        out = {
            "nivel": nivel,
            "chuva": chuva,
            "ultima_nivel": ultima_nivel,
            "ultima_chuva": ultima_chuva,
            "qc": qc,
            "fonte": "ANA HidroWebService / SerieTelemetricaAdotada",
        }
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), out)
        return out
    except Exception as exc:
        print(f"[ANA HidroWebService {codigo}] fallback legado: {exc}")
        return None
