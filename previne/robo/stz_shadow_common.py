"""Dados e avaliacao prospectiva de Santa Tereza, separados do feed principal."""
from __future__ import annotations
import datetime as dt
import copy
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from . import gerar_previsao_ao_vivo as R

ROOT = Path(__file__).resolve().parents[2]
STZ = "86472600"
STATIONS = (STZ, "86472000")
DOWNLOAD_EVIDENCE = {}
AVISO = "SOMBRA EXPERIMENTAL - acompanhamento comparativo; nao e alerta oficial."

def stamp(t):
    return t.isoformat(timespec="seconds")

def read(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default

def write(path, data, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    layout = {"separators": (",", ":")} if compact else {"indent": 2}
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, **layout) + "\n", encoding="utf-8")
    tmp.replace(path)

def chart_point(p):
    """Somente o que o grafico usa; entradas completas ficam no historico e no arquivo de ciclo."""
    obs = p.get("observado_cm")
    return {"modelo_id": p["modelo_id"], "hora_alvo": p["hora_alvo"],
            "nivel_previsto_cm": round(float(p["nivel_previsto_cm"]), 1),
            "observado_cm": None if obs is None else round(float(obs), 1)}

def history_paths(paths):
    return [str(Path(f).resolve().relative_to(ROOT)).replace("\\", "/") for f in paths
            if Path(f).resolve().is_relative_to(ROOT)]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

def parse_xml(xml):
    root = ET.fromstring(xml)
    if (root.text or "").strip().startswith("<"):
        root = ET.fromstring(root.text)
    levels, rain, seen, conflicts, invalid_hours = {}, {}, {}, set(), set()
    for row in root.iter():
        fields = {R._local(c.tag): (c.text or "").strip() for c in row}
        t = R._parse_hora(fields.get("DataHora") or fields.get("Data_Hora") or "")
        if t is None:
            continue
        for field, dest in (("Nivel", levels), ("Chuva", rain)):
            value = fields.get(field)
            if value in (None, ""):
                continue
            h = t if R._eh_hora_cheia(t) else t.replace(minute=0,second=0,microsecond=0)+dt.timedelta(hours=1)
            try:
                v = float(value.replace(",", "."))
            except ValueError:
                if field == 'Chuva':invalid_hours.add(h)
                else:conflicts.add((t,field))
                continue
            if not math.isfinite(v):
                if field == 'Chuva':invalid_hours.add(h)
                else:conflicts.add((t,field))
                continue
            key = (t, field)
            if key in seen:
                if seen[key] != v:
                    conflicts.add(key)
                continue
            seen[key] = v
            if field == "Nivel" and R._eh_hora_cheia(t):
                dest[t] = v
            elif field == "Chuva":
                # Contrato N5: hora H contem leituras em (H-1h, H].
                h = t if R._eh_hora_cheia(t) else t.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
                if not 0 <= v <= 100:
                    invalid_hours.add(h)
                else:
                    dest[h] = dest.get(h, 0.0) + v
    for t, field in conflicts:
        if field == "Nivel":
            levels.pop(t, None)
        else:
            invalid_hours.add(t if R._eh_hora_cheia(t) else t.replace(minute=0,second=0,microsecond=0)+dt.timedelta(hours=1))
    rain = {t:v for t,v in rain.items() if t not in invalid_hours and v <= 100}
    return levels, rain

def download_station(cod):
    xml = R._obter_xml_ana(cod, 8, R.ANA_TIMEOUT_NIVEL_S, 2, R._serie_de_xml, "ANA sombra STZ")
    raw = xml.encode('utf-8') if isinstance(xml,str) else xml
    DOWNLOAD_EVIDENCE[cod] = {'disponivel':bool(raw),'xml_sha256':hashlib.sha256(raw).hexdigest().upper() if raw else None,
                              'xml':raw.decode('utf-8-sig') if raw else None}
    return parse_xml(xml) if xml else ({}, {})

def download():
    DOWNLOAD_EVIDENCE.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        data = dict(zip(STATIONS, pool.map(download_station, STATIONS)))
    return ({c: v[0] for c, v in data.items()}, {c: v[1] for c, v in data.items()})

def qc_levels(levels, limits):
    clean = {}
    for cod, serie in levels.items():
        lim = limits.get(cod, {})
        result, anchor, anchor_t, suspect = {}, None, None, False
        repeated_value, repeated_since, previous_t = None, None, None
        for t, v in sorted(serie.items()):
            if v != repeated_value or previous_t is None or t-previous_t != dt.timedelta(hours=1):
                repeated_value, repeated_since = v, t
            previous_t = t
            if (t-repeated_since).total_seconds() > 72*3600:
                continue
            if not (float(lim.get("min", -500)) <= v <= float(lim.get("max", 5000))) or v <= 0:
                continue
            jump = lim.get("salto_max_1h")
            if (anchor is not None and jump and (suspect or t - anchor_t == dt.timedelta(hours=1))
                    and abs(v - anchor) > jump):
                suspect = True
                continue
            suspect = False
            result[t] = v
            anchor, anchor_t = v, t
        clean[cod] = result
    return clean

def inputs(specs, levels, rain, t):
    x, missing = [], []
    for s in specs:
        c, kind, h = s.get("estacao"), s["tipo"], int(s.get("defasagem_h", 0))
        n = lambda lag: levels.get(c, {}).get(t - dt.timedelta(hours=lag))
        v = None
        if kind == "nivel":
            v = n(h)
        elif kind == "vel_nivel":
            a, b = n(0), n(h)
            v = a - b if None not in (a, b) else None
        elif kind == "acel_nivel":
            a, b, cc, d = n(0), n(1), n(h), n(h + 1)
            v = (a - b) - (cc - d) if None not in (a, b, cc, d) else None
        elif kind == "chuva_acum":
            acc = []
            for cod in s["estacoes"]:
                values = [rain.get(cod, {}).get(t - dt.timedelta(hours=i)) for i in range(s["janela_h"])]
                if all(z is not None and math.isfinite(z) for z in values):
                    acc.append(sum(values))
            v = sum(acc) / len(acc) if acc else None
        else:
            raise ValueError(f"entrada nao implementada: {kind}")
        x.append(v)
        if v is None or not math.isfinite(v):
            missing.append(s["nome"])
    return x, missing

def recent_base(specs, levels, rain, now, lookback=1):
    latest_missing = []
    for t in sorted(levels.get(STZ, {}), reverse=True):
        if t > now or (now - t).total_seconds() > 180 * 60:
            continue
        sequence, missing = [], []
        for i in range(lookback - 1, -1, -1):
            x, absent = inputs(specs, levels, rain, t - dt.timedelta(hours=i))
            sequence.append(x)
            missing.extend(f"{name} @ {stamp(t - dt.timedelta(hours=i))}" for name in absent)
        if not missing:
            return t, sequence, []
        if not latest_missing:
            latest_missing = missing
    return None, None, latest_missing or ["sem base completa nas ultimas 3 horas"]

def update_history(history, new, observed, now, limits=None):
    history = copy.deepcopy(history) if history is not None else {"schema_version": "stz_shadow_history_v1", "shadow_only": True, "registros": []}
    if limits is None:
        limits = read(ROOT / 'assets/data/stz_n5_sombra_contrato.json')['limites_estacao_cm']
    observed = qc_levels({STZ:observed},limits)[STZ]
    records = history["registros"]
    keys = {(p["modelo_id"], p["modelo_sha256"], p["hora_modelo"], p["horizonte_h"]) for p in records}
    for p in new:
        if not p.get("disponivel"):
            continue
        key = (p["modelo_id"], p["modelo_sha256"], p["hora_modelo"], p["horizonte_h"])
        issued, target = dt.datetime.fromisoformat(p["emitida_em"]), dt.datetime.fromisoformat(p["hora_alvo"])
        if p.get("disponivel") and issued < target and key not in keys:
            records.append(dict(p, origem="emissao_prospectiva", observado_cm=None))
            keys.add(key)
    for p in records:
        target = dt.datetime.fromisoformat(p["hora_alvo"])
        if (p.get("observado_cm") is not None or p.get("origem") != "emissao_prospectiva"
                or dt.datetime.fromisoformat(p["emitida_em"]) >= target or target > now):
            continue
        obs = observed.get(target)
        if obs is not None and R._nivel_plausivel(obs, STZ):
            p.update(observado_cm=float(obs), conferido_em=stamp(now),
                     erro_cm=p["nivel_previsto_cm"] - obs,
                     erro_persistencia_cm=p["nivel_base_cm"] - obs)
    history["atualizado_em"] = stamp(now)
    return history

def metrics(records, now, hours=None):
    rows = [p for p in records if p.get("observado_cm") is not None
            and (hours is None or 0 <= (now - dt.datetime.fromisoformat(p["hora_alvo"])).total_seconds() <= hours * 3600)]
    out = {"n": len(rows), "mae_cm": None, "rmse_cm": None, "vies_cm": None, "max_abs_cm": None,
           "mae_persistencia_cm": None, "status": "CONFERIDO" if rows else "AGUARDANDO_OBSERVACOES"}
    if rows:
        e = np.array([p["erro_cm"] for p in rows], dtype=float)
        out.update(mae_cm=float(np.abs(e).mean()), rmse_cm=float(np.sqrt((e ** 2).mean())),
                   vies_cm=float(e.mean()), max_abs_cm=float(np.abs(e).max()),
                   mae_persistencia_cm=float(np.mean([abs(p["erro_persistencia_cm"]) for p in rows])))
    return out

def evaluate(records, now):
    return {str(h or "total"): metrics(records, now, h) for h in (24, 72, 168, None)}
