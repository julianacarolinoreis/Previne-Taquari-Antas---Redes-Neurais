#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robô AO VIVO — PREVINE / Muçum (estação-alvo 86510000)
Espelha o robô do Santa Tereza. Roda no GitHub Actions (a cada 5 min):
  1) busca a telemetria da ANA (Muçum + montante Santa Tereza + auxiliares)
  2) para os horizontes 2h, 4h e 8h, monta os inputs na ordem
     exata (dirigida por mucum_modelo_inputs.json) e roda a RNA
  3) escreve previsao_ao_vivo_mucum.json no schema do ST (horizontes{...},
     passos) — a página monta os botões de horizonte a partir daí.

MULTI-HORIZONTE E AUTOSSUFICIENTE: lê os modelos operacionais do JSON e publica
2h mais dois candidatos 4h e dois candidatos 8h, sem fallback silencioso.

vel_nivel D-Xh = n(t) - n(t-Xh). Cada .mat é validável com `--validar <mat>`
(reproduz pred_target_tot com RMSE ~0) antes de confiar no ao vivo.
EXPERIMENTAL — não é alerta oficial.
"""
import sys, os, json, hashlib, datetime as dt, time, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.io import loadmat

BRT = dt.timezone(dt.timedelta(hours=-3))
def agora_brt(): return dt.datetime.now(BRT).replace(tzinfo=None)
def iso_utc(value):
    """Serializa um horário interno BRT-naive como RFC3339 UTC com Z."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BRT)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUTS_JSON = os.path.join(RAIZ, "assets", "data", "mucum_modelo_inputs.json")
MODELOS_AO_VIVO_JSON = os.path.join(RAIZ, "assets", "data", "mucum_modelos_ao_vivo.json")
MAT_DIR = os.path.join(RAIZ, "assets", "mat")
SAIDA = os.path.join(RAIZ, "previsao_ao_vivo_mucum.json")
HISTORICO_SAIDA = os.path.join(RAIZ, "historico_previsoes_ao_vivo_mucum.json")
AUDITORIA_MAX_GAP = dt.timedelta(minutes=30)
BANKFULL_CM = 500            # nível normal / zero da mancha (régua 86510000)
ALVO = "86510000"
LOCAL = "Muçum"
AVISO = "EXPERIMENTAL — não é alerta oficial. Camada espacial da previsão de RNA para Muçum."
ANA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
ULTIMA_RAW = {}
ANA_TIMEOUT_NIVEL_S = 15
ANA_TIMEOUT_CHUVA_S = 12
ANA_RETRIES_NIVEL = 2
ANA_RETRIES_CHUVA = 2


# ---------- configuração dos modelos (a partir do JSON) ----------
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest().upper()


def _cfg(m, hh):
    ins = sorted(m["inputs"], key=lambda x: x["ordem"])
    mid = m["modelo_id"]
    mat = m.get("arquivo_mat") or f"assets/mat/{mid}.mat"
    excel = m.get("arquivo_excel") or m.get("referencia_auditavel")
    excel_sha = m.get("arquivo_excel_sha256") or m.get("referencia_auditavel_sha256")
    cfg = {
        "horizonte_h": hh, "horizonte": m.get("chave_feed") or f"{hh}h",
        "rotulo": m.get("rotulo") or f"{hh}h",
        "tipo": m.get("tipo_modelo", "ALT"), "modelo": mid,
        "combo": m.get("combo_id", mid),
        "papel": m.get("papel", "principal"),
        "versao": m.get("versao"),
        "modelo_sha256": m.get("modelo_sha256"),
        "arquivo_excel": excel,
        "arquivo_excel_sha256": excel_sha,
        "referencia_auditavel": m.get("referencia_auditavel"),
        "referencia_auditavel_sha256": m.get("referencia_auditavel_sha256"),
        "pontos_detalhados": m.get("pontos_detalhados"),
        "fonte_rodada": m.get("fonte_rodada"),
        "criterio_selecao": m.get("criterio_selecao"),
        "selection_rank": m.get("selection_rank"),
        "metricas_auditoria": m.get("metricas_auditoria") or {},
        "contrato_chuva": m.get("contrato_chuva"),
        "input_contract_version": m.get("input_contract_version", "hourly_exact_v1"),
        "input_grade": m.get("input_grade", "hourly_exact"),
        "mat": os.path.join(RAIZ, mat) if mat.startswith("assets") else os.path.join(MAT_DIR, os.path.basename(mat)),
        "inputs": ins,
        "estacoes": sorted({str(i["estacao"]) for i in ins if not str(i.get("tipo", "")).startswith("chuva")}),
        "estacoes_chuva": sorted({str(e) for i in ins if str(i.get("tipo", "")).startswith("chuva") for e in (i.get("estacoes") or [i.get("estacao")])}),
        "n_inputs": len(ins),
    }
    esperado = m.get("modelo_sha256")
    if esperado and os.path.exists(cfg["mat"]):
        atual = _sha256(cfg["mat"])
        if atual != str(esperado).upper():
            raise ValueError(f"SHA-256 do MAT diverge para {mid}: esperado {esperado}, obtido {atual}")
        cfg["modelo_sha256"] = atual
    if excel_sha and excel and excel.startswith("assets"):
        excel_path = os.path.join(RAIZ, excel)
        if os.path.exists(excel_path):
            atual = _sha256(excel_path)
            if atual != str(excel_sha).upper():
                raise ValueError(f"SHA-256 do Excel diverge para {mid}: esperado {excel_sha}, obtido {atual}")
            cfg["arquivo_excel_sha256"] = atual
    return cfg

def carregar_modelos():
    """Carrega 2h e os dois melhores 4h/8h com chave própria no feed.

    O arquivo separado é deliberadamente uma lista operacional auditável: os
    candidatos possuem MAT, Excel e séries ponto a ponto reconciliados. Os
    fallbacks antigos não entram silenciosamente no novo feed.
    """
    d = json.load(open(INPUTS_JSON, encoding="utf-8"))
    modelos = [_cfg(d["modelo_campeao_2h"], 2)]
    if os.path.exists(MODELOS_AO_VIVO_JSON):
        op = json.load(open(MODELOS_AO_VIVO_JSON, encoding="utf-8"))
        for raw in op.get("modelos", []):
            m = dict(raw)
            m.setdefault("criterio_selecao", op.get("criterio_selecao"))
            modelos.append(_cfg(m, int(m["horizonte_h"])))
        return modelos
    # Compatibilidade explícita para cópias antigas do repositório.
    for m in d.get("modelos_recomendados_outros_horizontes", []):
        if int(m["horizonte_h"]) == 4:
            modelos.append(_cfg(m, 4))
            break
    return modelos


# ---------- telemetria ANA (idêntica ao robô do Santa Tereza) ----------
def _local(tag): return tag.rsplit("}", 1)[-1]
def _parse_hora(dh):
    if dh in (None, ""):
        return None
    dh = dh.strip()
    try: return dt.datetime.fromisoformat(dh.replace("T", " ")[:19])
    except Exception:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try: return dt.datetime.strptime(dh[:19], fmt)
            except Exception: pass
    return None

def _extrair_serie(root):
    serie = {}; ultima_raw = None
    for row in root.iter():
        campos = {_local(ch.tag): (ch.text or "") for ch in row}
        dh = campos.get("DataHora") or campos.get("Data_Hora") or campos.get("DataHoraMedicao")
        niv = campos.get("Nivel")
        if niv in (None, ""): niv = campos.get("nivel") or campos.get("NivelSensor") or campos.get("Cota")
        if not dh or niv in (None, ""): continue
        t = _parse_hora(dh)
        if t is None: continue
        try: valor = float(str(niv).replace(",", "."))
        except Exception: continue
        if ultima_raw is None or t > ultima_raw[0]: ultima_raw = (t, valor)
        # Mantem leituras intermediarias (15/30/45 min) para a auditoria e
        # para identificar a leitura mais recente. Os inputs da RNA, porém,
        # só usam timestamps exatos na hora cheia.
        serie[t.replace(second=0, microsecond=0)] = valor
    return serie, ultima_raw


def _extrair_serie_chuva(root):
    """Extrai chuva por hora sem preencher lacunas.

    A ANA pode responder em 15/30/45 minutos. As planilhas históricas
    acumulam essas leituras dentro da hora; a grade do modelo continua sendo
    somente a hora cheia. Uma hora sem leitura permanece ausente.
    """
    acumulado_hora = {}; ultima_raw = None
    for row in root.iter():
        campos = {_local(ch.tag): (ch.text or "") for ch in row}
        dh = campos.get("DataHora") or campos.get("Data_Hora") or campos.get("DataHoraMedicao")
        chuva = campos.get("Chuva") or campos.get("chuva") or campos.get("Precipitacao") or campos.get("Precipitação")
        if not dh or chuva in (None, ""):
            continue
        t = _parse_hora(dh)
        if t is None:
            continue
        try:
            valor = float(str(chuva).replace(",", "."))
        except Exception:
            continue
        if ultima_raw is None or t > ultima_raw[0]:
            ultima_raw = (t, valor)
        hora = t.replace(minute=0, second=0, microsecond=0)
        acumulado_hora[hora] = acumulado_hora.get(hora, 0.0) + valor
    return acumulado_hora, ultima_raw

def _serie_de_xml(xml):
    root = ET.fromstring(xml); serie, ultima_raw = _extrair_serie(root)
    if not serie and (root.text or "").strip().startswith("<"):
        try: serie, ultima_raw = _extrair_serie(ET.fromstring(root.text))
        except Exception: pass
    return serie, len(xml), ultima_raw


def _serie_chuva_de_xml(xml):
    root = ET.fromstring(xml); serie, ultima_raw = _extrair_serie_chuva(root)
    if not serie and (root.text or "").strip().startswith("<"):
        try: serie, ultima_raw = _extrair_serie_chuva(ET.fromstring(root.text))
        except Exception: pass
    return serie, len(xml), ultima_raw

def buscar_ana(cod, dias=6, tentativas_rede=ANA_RETRIES_NIVEL):
    """Telemetria da ANA. O endpoint às vezes devolve vazio/erro de forma
    transitória, então tenta algumas vezes com backoff curto antes de desistir."""
    import time
    fim = agora_brt(); ini = fim - dt.timedelta(days=dias)
    urls = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for attempt in range(tentativas_rede):
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
                xml = urllib.request.urlopen(req, timeout=ANA_TIMEOUT_NIVEL_S).read()
                serie, nbytes, ultima_raw = _serie_de_xml(xml)
                print(f"[ANA {cod}] tent={attempt+1} bytes={nbytes} linhas={len(serie)}")
                if ultima_raw: ULTIMA_RAW[cod] = ultima_raw
                if serie: return serie
            except Exception as e:
                print(f"[ANA {cod}] tent={attempt+1} erro: {e}")
        if attempt < tentativas_rede - 1:
            time.sleep(4 * (attempt + 1))
    return {}


def buscar_ana_chuva(cod, dias=6, tentativas_rede=ANA_RETRIES_CHUVA):
    """Busca chuva observada e devolve somente acumulados horários reais."""
    fim = agora_brt(); ini = fim - dt.timedelta(days=dias)
    urls = [
        f"{ANA}?codEstacao={cod}&dataInicio={ini:%d/%m/%Y}&dataFim={fim:%d/%m/%Y}",
        f"{ANA}?codEstacao={cod}&dataInicio=&dataFim=",
    ]
    for attempt in range(tentativas_rede):
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "previne-robo/1.0"})
                xml = urllib.request.urlopen(req, timeout=ANA_TIMEOUT_CHUVA_S).read()
                serie, nbytes, ultima_raw = _serie_chuva_de_xml(xml)
                print(f"[ANA chuva {cod}] tent={attempt + 1} bytes={nbytes} horas={len(serie)}")
                if ultima_raw: ULTIMA_RAW[f"chuva_{cod}"] = ultima_raw
                if serie: return serie
            except Exception as e:
                print(f"[ANA chuva {cod}] tent={attempt + 1} erro: {e}")
        if attempt < tentativas_rede - 1:
            time.sleep(2 * (attempt + 1))
    return {}


def buscar_series_paralelo(codigos, funcao, max_workers=8):
    """Consulta estações independentes em paralelo para não estourar o ciclo."""
    codigos = list(codigos)
    if not codigos: return {}
    workers = max(1, min(int(max_workers), len(codigos)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ana-live") as executor:
        resultados = list(executor.map(funcao, codigos))
    return dict(zip(codigos, resultados))

def nivel_exato(serie, t):
    """Nível observado exatamente em ``t``; não interpola nem usa vizinho."""
    return None if not serie else serie.get(t)

def observar_nivel(serie, alvo):
    """Observa apenas a leitura ANA exatamente na hora-alvo."""
    valor = nivel_exato(serie, alvo)
    return (float(valor), alvo) if valor is not None else (None, None)


# ---------- inputs / inferência ----------
def _chuva_horaria(inp, series, hora):
    postos = [str(p) for p in (inp.get("estacoes") or [inp.get("estacao")]) if p]
    fontes = series.get("__chuva_postos__", {})
    valores = [(fontes.get(p) or {}).get(hora) for p in postos]
    presentes = [float(v) for v in valores if v is not None]
    if inp.get("agregacao") == "soma":
        return sum(presentes) if len(presentes) == len(postos) else None
    minimo = int(inp.get("min_estacoes_hora") or 2)
    return sum(presentes) / len(presentes) if len(presentes) >= minimo else None


def _chuva_acumulada(inp, series, t, deslocamento_h=0):
    janela = int(inp.get("janela_h") or 0)
    if janela <= 0 or t.minute != 0:
        return None
    vals = [_chuva_horaria(inp, series, t - dt.timedelta(hours=deslocamento_h + h)) for h in range(janela)]
    if any(v is None for v in vals):
        return None
    return float(sum(vals))


def _horarios_faltantes_chuva(inp, series, t):
    janela = int(inp.get("janela_h") or 0)
    deslocamentos = [0]
    if inp.get("tipo") == "chuva_diferenca":
        deslocamentos.append(int(inp.get("janela_anterior_h") or janela))
    faltantes = []
    for deslocamento in deslocamentos:
        for h in range(janela):
            hora = t - dt.timedelta(hours=deslocamento + h)
            if _chuva_horaria(inp, series, hora) is None:
                faltantes.append(hora.isoformat(timespec="minutes"))
    return sorted(set(faltantes))


def montar_inputs(cfg, series, t):
    """Monta os inputs de um modelo na hora t, na ordem exata (campo `ordem`).
       nivel -> n(t - defasagem_h);
       vel_nivel -> n(t) - n(t - defasagem_h);
       acel_nivel -> [n(t)-n(t-1h)] - [n(t-h)-n(t-(h+1)h)]."""
    def n(cod, h=0):
        s = series.get(str(cod))
        return None if s is None else nivel_exato(s, t - dt.timedelta(hours=h))
    x = []
    for inp in cfg["inputs"]:
        cod, tipo, h = inp["estacao"], inp["tipo"], inp["defasagem_h"]
        if tipo == "nivel":
            x.append(n(cod, h))
        elif tipo == "vel_nivel":
            a, b = n(cod, 0), n(cod, h)
            x.append(None if None in (a, b) else a - b)
        elif tipo in ("acel_nivel", "aceleracao"):
            a, b = n(cod, 0), n(cod, 1)
            c, d = n(cod, h), n(cod, h + 1)
            x.append(None if None in (a, b, c, d) else (a - b) - (c - d))
        elif tipo == "chuva_acum":
            x.append(_chuva_acumulada(inp, series, t))
        elif tipo == "chuva_diferenca":
            atual = _chuva_acumulada(inp, series, t)
            anterior = _chuva_acumulada(inp, series, t, int(inp.get("janela_anterior_h") or inp.get("janela_h") or 0))
            x.append(None if None in (atual, anterior) else atual - anterior)
        else:
            raise ValueError(f"tipo de input não suportado: {tipo}")
    return x


def diagnosticar_inputs(cfg, x, series=None, t=None):
    faltantes = []
    for inp, valor in zip(cfg["inputs"], x):
        if valor is not None:
            continue
        faltantes.append({
            "ordem": inp.get("ordem"),
            "input": inp.get("nome") or inp.get("variavel") or f"inp{inp.get('ordem')}",
            "estacao": str(inp.get("estacao")),
            "tipo": inp.get("tipo"),
            "defasagem_h": inp.get("defasagem_h"),
        })
        if str(inp.get("tipo", "")).startswith("chuva") and series is not None and t is not None:
            item = faltantes[-1]
            item["estacoes"] = [str(p) for p in (inp.get("estacoes") or [inp.get("estacao")]) if p]
            item["horarios_faltantes"] = _horarios_faltantes_chuva(inp, series, t)
    return faltantes


def carregar_mat(mat_path):
    """Carrega MAT clássico e MATLAB v7.3 com o mesmo contrato de arrays."""
    try:
        return loadmat(mat_path, squeeze_me=True)
    except NotImplementedError:
        # O modelo V001 foi salvo como MATLAB v7.3 (HDF5). h5py é instalado
        # pelo workflow do robô somente para suportar esse formato.
        import h5py
        with h5py.File(mat_path, "r") as f:
            return {
                k: np.asarray(f[k])
                for k in f.keys()
                if isinstance(f[k], h5py.Dataset) and not k.startswith("#")
            }


def prever(mat_path, x):
    m = carregar_mat(mat_path)
    ae = np.asarray(m["ae"], float).ravel(); be = np.asarray(m["be"], float).ravel()
    wh = np.atleast_2d(np.asarray(m["wh"], float))
    # MATLAB v7.3/HDF5 expõe a matriz transposta em relação ao loadmat
    # clássico: (n_inputs, n_hidden), enquanto o forward usa (hidden, inputs).
    if wh.shape[1] != len(ae) and wh.shape[0] == len(ae):
        wh = wh.T
    if wh.shape[1] != len(ae):
        raise ValueError(f"arquitetura incompatível: wh={wh.shape}, n_inputs={len(ae)}")
    bh = np.asarray(m["bh"], float).ravel()
    ws = np.asarray(m["ws"], float).ravel(); bs = float(np.asarray(m["bs"], float).ravel()[0])
    au = float(np.asarray(m["au"], float).ravel()[0]); bu = float(np.asarray(m["bu"], float).ravel()[0])
    logsig = lambda z: 1.0 / (1.0 + np.exp(-z))
    pn = (np.asarray(x, float).ravel() - be) / ae
    h = logsig(wh.dot(pn) + bh)
    yn = logsig(ws.dot(h) + bs)
    return float(yn * au + bu)   # variação prevista (cm)

def melhor_hora(cfg, series, horas, limite_alvo=None):
    """Hora mais recente (até 12 h atrás) em que TODOS os inputs do modelo existem."""
    if not horas: return None
    t_ult = horas[-1]
    for t in [h for h in reversed(horas) if h.minute == 0 and (t_ult - h) <= dt.timedelta(hours=12)]:
        if limite_alvo is not None and (t + dt.timedelta(hours=cfg["horizonte_h"])) <= limite_alvo:
            continue
        x = montar_inputs(cfg, series, t)
        if all(v is not None for v in x):
            return t, x
    return None


# ---------- saída (schema do Santa Tereza) ----------
def base_saida(cfg, nivel_agora, nivel_prev, t, status, faltantes=None, nivel_base=None, input_values=None):
    consultado = agora_brt(); raw = ULTIMA_RAW.get(ALVO)
    idade = round((consultado - raw[0]).total_seconds() / 60) if raw else None
    nivel_raw_cm = (round(raw[1]) if raw else (round(nivel_agora) if nivel_agora is not None else None))
    nivel_base = nivel_agora if nivel_base is None else nivel_base
    hora_alvo = (t + dt.timedelta(hours=cfg["horizonte_h"])).isoformat() if t else None
    out = {
        "modo": "ao_vivo",
        "gerado_em": (t.isoformat() if t else consultado.isoformat()),
        "gerado_em_utc": iso_utc(t or consultado),
        "hora_modelo": (t.isoformat() if t else None),
        "hora_modelo_utc": iso_utc(t),
        "hora_alvo": hora_alvo,
        "hora_alvo_utc": iso_utc(t + dt.timedelta(hours=cfg["horizonte_h"]) if t else None),
        "consultado_em": consultado.isoformat(timespec="seconds"),
        "consultado_em_utc": iso_utc(consultado),
        "telemetria_ultima_em": (raw[0].isoformat() if raw else None),
        "telemetria_ultima_em_utc": iso_utc(raw[0] if raw else None),
        "telemetria_ultima_nivel_cm": (round(raw[1]) if raw else None),
        "idade_telemetria_min": idade,
        "status_dados": (None if idade is None else ("telemetria recente" if idade <= 30 else f"telemetria atrasada ({idade} min)")),
        "estacao": ALVO, "local": LOCAL,
        "horizonte": cfg["horizonte"], "rotulo": cfg["rotulo"], "horizonte_h": cfg["horizonte_h"],
        "tipo": cfg["tipo"], "modelo": cfg["modelo"], "combo": cfg["combo"], "bankfull_cm": BANKFULL_CM,
        "modelo_papel": cfg.get("papel", "principal"),
        "selection_rank": cfg.get("selection_rank"),
        "versao": cfg.get("versao"),
        "modelo_sha256": cfg.get("modelo_sha256"),
        "arquivo_excel": cfg.get("arquivo_excel"),
        "arquivo_excel_sha256": cfg.get("arquivo_excel_sha256"),
        "referencia_auditavel": cfg.get("referencia_auditavel"),
        "referencia_auditavel_sha256": cfg.get("referencia_auditavel_sha256"),
        "pontos_detalhados": cfg.get("pontos_detalhados"),
        "fonte_rodada": cfg.get("fonte_rodada"),
        "criterio_selecao": cfg.get("criterio_selecao"),
        "metricas_auditoria": cfg.get("metricas_auditoria") or {},
        "input_labels": [i.get("nome") for i in cfg.get("inputs", [])],
        "nivel_modelo_cm": (round(nivel_base) if nivel_base is not None else None),
        "nivel_base_cm": (round(nivel_base) if nivel_base is not None else None),
        "nivel_rio_agora_cm": nivel_raw_cm,
        "nivel_rio_agora_em": (raw[0].isoformat() if raw else (t.isoformat() if t else None)),
        "nivel_rio_agora_em_utc": iso_utc(raw[0] if raw else (t if t else None)),
        "nivel_atual_cm": (round(nivel_raw_cm) if nivel_raw_cm is not None else (round(nivel_agora) if nivel_agora is not None else None)),
        "nivel_previsto_cm": (round(nivel_prev) if nivel_prev is not None else None),
        "inputs_total": cfg["n_inputs"], "inputs_faltantes_n": len(faltantes or []),
        "inputs_faltantes": faltantes or [], "estacoes_status": [],
        "input_contract_version": cfg.get("input_contract_version", "hourly_exact_v1"),
        "input_grade": cfg.get("input_grade", "hourly_exact"),
        "disponivel": nivel_prev is not None,
        "auditoria_inputs": {
            "status": "NORMAL" if nivel_prev is not None and not faltantes else "ATENCAO",
            "formula_conferida_com_montador": True,
            "n_inputs": cfg["n_inputs"],
            "n_exatos": cfg["n_inputs"] - len(faltantes or []),
            "n_inputs_nao_exatos": 0,
            "n_interpolados": 0,
            "n_vizinhos_mais_proximos": 0,
            "n_inputs_chuva": sum(1 for i in cfg.get("inputs", []) if str(i.get("tipo", "")).startswith("chuva")),
            "chuva_fontes": cfg.get("estacoes_chuva", []),
            "contrato_chuva": cfg.get("contrato_chuva"),
            "usa_interpolacao_chuva": False,
            "usa_preenchimento_chuva": False,
            "input_grade": "hourly_exact",
            "hora_base_minuto": (t.minute if t else None),
            "usa_interpolacao_nivel": False,
            "usa_vizinho_nivel": False,
            "contrato_temporal": f"{cfg['n_inputs']} inputs em hora cheia exata; níveis e chuva sem interpolação, vizinho ou preenchimento",
        },
        "status": status, "aviso": AVISO,
    }
    if input_values is not None:
        out["input_values_cm"] = [round(float(v), 6) for v in input_values]
    if cfg.get("modelo_sha256"):
        out["modelo_integridade"] = "sha256_conferido_no_robo"
    if nivel_prev is not None and nivel_raw_cm is not None:
        delta_base = nivel_base if nivel_base is not None else nivel_raw_cm
        out["delta_previsto_cm"] = round(nivel_prev - delta_base, 1)
        out["passos"] = [[out["hora_modelo"], out["nivel_modelo_cm"], out["nivel_rio_agora_cm"], out["nivel_previsto_cm"]]]
    return out

def carregar_historico():
    if not os.path.exists(HISTORICO_SAIDA):
        return []
    try:
        with open(HISTORICO_SAIDA, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict):
            return dados.get("registros", [])
        return dados if isinstance(dados, list) else []
    except Exception as e:
        print("historico Mucum invalido, reiniciando:", e)
        return []


def salvar_historico(registros):
    pacote = {
        "atualizado_em": agora_brt().isoformat(timespec="seconds"),
        "local": LOCAL,
        "estacao": ALVO,
        "registros": registros[-1200:],
    }
    with open(HISTORICO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(pacote, f, ensure_ascii=False, indent=1)


def hora_cheia(value):
    parsed = _parse_hora(value or "")
    return parsed if parsed is not None and parsed.minute == 0 and parsed.second == 0 else None


def normalizar_historico_grade(registros):
    """Retira da série de erros os registros legados fora da hora cheia."""
    agora = agora_brt().isoformat(timespec="seconds")
    for reg in registros:
        if hora_cheia(reg.get("hora_modelo")) is not None and hora_cheia(reg.get("hora_alvo")) is not None:
            continue
        reg.update({
            "observado_cm": None,
            "observado_em": None,
            "erro_cm": None,
            "erro_abs_cm": None,
            "status_auditoria": "fora_grade_horaria",
            "auditado_em": agora,
        })
    return registros


def upsert_previsao_historico(registros, saida):
    if saida.get("status") != "ok" or saida.get("nivel_previsto_cm") is None or not saida.get("hora_modelo"):
        return registros
    chave = f"{saida['local']}|{saida['horizonte']}|{saida['modelo']}|{saida['hora_modelo']}"
    novo = {
        "id": chave,
        "local": saida["local"],
        "estacao": saida["estacao"],
        "horizonte": saida["horizonte"],
        "horizonte_h": saida["horizonte_h"],
        "tipo": saida.get("tipo"),
        "modelo": saida["modelo"],
        "hora_modelo": saida["hora_modelo"],
        "hora_modelo_utc": saida.get("hora_modelo_utc"),
        "hora_alvo": saida["hora_alvo"],
        "hora_alvo_utc": saida.get("hora_alvo_utc"),
        "nivel_modelo_cm": saida.get("nivel_modelo_cm"),
        "nivel_rio_agora_cm": saida.get("nivel_rio_agora_cm"),
        "nivel_previsto_cm": saida.get("nivel_previsto_cm"),
        "status_auditoria": "aguardando",
        "criado_em": saida.get("consultado_em"),
        "criado_em_utc": saida.get("consultado_em_utc"),
    }
    for i, reg in enumerate(registros):
        if reg.get("id") == chave:
            preservados = {
                k: reg.get(k)
                for k in ("observado_cm", "observado_em", "erro_cm", "erro_abs_cm", "status_auditoria", "auditado_em")
                if k in reg
            }
            novo.update(preservados)
            registros[i] = novo
            return registros
    registros.append(novo)
    return registros


def conferir_historico(registros, series):
    serie_alvo = series.get(ALVO, {})
    ultima_hora = max(serie_alvo) if serie_alvo else None
    for reg in registros:
        alvo = _parse_hora(reg.get("hora_alvo", ""))
        if alvo is None or hora_cheia(reg.get("hora_modelo")) is None or hora_cheia(reg.get("hora_alvo")) is None:
            continue
        observado_em = _parse_hora(reg.get("observado_em", ""))
        if reg.get("status_auditoria") == "conferido" and observado_em == alvo:
            continue
        # Registros antigos podem ter sido conferidos por vizinhança. Eles
        # precisam ser reabertos para não conservar uma comparação inventada.
        reg.update({
            "observado_cm": None,
            "observado_em": None,
            "erro_cm": None,
            "erro_abs_cm": None,
        })
        obs, obs_em = observar_nivel(serie_alvo, alvo)
        if obs is not None:
            previsto = reg.get("nivel_previsto_cm")
            erro = None if previsto is None else float(previsto) - float(obs)
            reg.update({
                "observado_cm": round(obs),
                "observado_em": obs_em.isoformat(),
                "erro_cm": (round(erro, 1) if erro is not None else None),
                "erro_abs_cm": (round(abs(erro), 1) if erro is not None else None),
                "status_auditoria": "conferido",
                "auditado_em": agora_brt().isoformat(timespec="seconds"),
            })
        elif ultima_hora and (alvo + AUDITORIA_MAX_GAP) <= ultima_hora:
            reg.update({
                "status_auditoria": "sem_dado_ana",
                "auditado_em": agora_brt().isoformat(timespec="seconds"),
            })
        else:
            reg.update({
                "status_auditoria": "aguardando",
                "auditado_em": agora_brt().isoformat(timespec="seconds"),
            })
    return registros


def media(vals):
    vals = [float(v) for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def resumo_auditoria(registros, horizonte):
    regs = [r for r in registros if r.get("horizonte") == horizonte]
    conferidos = sorted(
        [r for r in regs if r.get("status_auditoria") == "conferido"],
        key=lambda r: r.get("hora_alvo") or ""
    )
    aguardando = len([r for r in regs if r.get("status_auditoria") == "aguardando"])
    agora = agora_brt()
    ult24 = []
    for r in conferidos:
        alvo = _parse_hora(r.get("hora_alvo", ""))
        if alvo and (agora - alvo).total_seconds() <= 24 * 3600:
            ult24.append(r)
    return {
        "n_total": len(regs),
        "n_conferidas": len(conferidos),
        "n_aguardando": aguardando,
        "ultima_conferida": (conferidos[-1] if conferidos else None),
        "mae_ultimas_6_cm": media([r.get("erro_abs_cm") for r in conferidos[-6:]]),
        "mae_24h_cm": media([r.get("erro_abs_cm") for r in ult24]),
        "maior_erro_abs_24h_cm": (max([r.get("erro_abs_cm") for r in ult24 if r.get("erro_abs_cm") is not None]) if ult24 else None),
        "ultimas_conferidas": conferidos[-12:],
    }

def _tem_previsao(d):
    if not d:
        return False
    if d.get("nivel_previsto_cm") is not None:
        return True
    hs = d.get("horizontes")
    return isinstance(hs, dict) and any(v.get("nivel_previsto_cm") is not None for v in hs.values() if isinstance(v, dict))

def escrever(top, horizontes, max_stale_h=6):
    top = dict(top)
    if horizontes:
        top["horizontes"] = horizontes
    # Resiliência: se este ciclo NÃO tem previsão (telemetria da ANA falhou),
    # preserva a última previsão boa (se ainda recente) em vez de apagá-la —
    # assim a página não "cai" para o replay num hiccup transitório da ANA.
    if not _tem_previsao(top) and os.path.exists(SAIDA):
        try:
            ant = json.load(open(SAIDA, encoding="utf-8"))
            hm = ant.get("hora_modelo")
            if _tem_previsao(ant) and hm:
                idade_h = (agora_brt() - dt.datetime.fromisoformat(hm)).total_seconds() / 3600
                if idade_h <= max_stale_h:
                    print(f"telemetria falhou neste ciclo; mantendo última previsão boa ({idade_h:.1f} h) — não sobrescreve")
                    return
        except Exception as e:
            print("não consegui ler JSON anterior:", e)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(top, f, ensure_ascii=False, indent=1)
    hs = ",".join(horizontes.keys()) if horizontes else "-"
    print("escrito", SAIDA, "->", top.get("nivel_atual_cm"), "->", top.get("nivel_previsto_cm"),
          "| horizontes:", hs, "|", top.get("status"))


def escrever_pacote(horizontes, historico):
    for hz, out in horizontes.items():
        out["auditoria"] = resumo_auditoria(historico, hz)
    principal = horizontes.get("2h") or next(iter(horizontes.values()))
    pacote = dict(principal)
    pacote["horizontes"] = horizontes
    pacote["auditoria_historico"] = {
        hz: resumo_auditoria(historico, hz) for hz in horizontes.keys()
    }
    escrever(pacote, horizontes)


def filtrar_historico_modelos(registros, modelos):
    """Mantém no histórico ao vivo somente os modelos ativos por chave.

    A troca de uma receita 4h/8h não deve misturar o erro do modelo antigo ao
    erro do candidato que acabou de ser publicado.
    """
    ativos = {}
    for cfg in modelos:
        ativos.setdefault(cfg["horizonte"], set()).add(cfg["modelo"])
    return [
        r for r in registros
        if r.get("horizonte") not in ativos or r.get("modelo") in ativos[r.get("horizonte")]
    ]


def main():
    modelos = carregar_modelos()
    disponiveis = [c for c in modelos if os.path.exists(c["mat"])]
    print("modelos:", [(c["horizonte"], os.path.basename(c["mat"]), "OK" if os.path.exists(c["mat"]) else "sem .mat") for c in modelos])
    if not disponiveis:
        horizontes = {c["horizonte"]: base_saida(c, None, None, None, "nenhum .mat disponível no repo") for c in modelos}
        escrever_pacote(horizontes, []); return

    estacoes = sorted({e for c in modelos for e in c["estacoes"]})
    estacoes_chuva = sorted({e for c in modelos for e in c.get("estacoes_chuva", [])})
    series = buscar_series_paralelo(estacoes, buscar_ana, max_workers=8)
    series["__chuva_postos__"] = buscar_series_paralelo(estacoes_chuva, buscar_ana_chuva, max_workers=6)
    horas_muc = sorted(series.get(ALVO, {}).keys())
    nivel_agora = nivel_exato(series.get(ALVO, {}), horas_muc[-1]) if horas_muc else None

    horizontes = {}
    raw_mucum = ULTIMA_RAW.get(ALVO)
    limite_alvo = raw_mucum[0] if raw_mucum else None
    for cfg in modelos:
        horizonte = cfg["horizonte"]
        if not os.path.exists(cfg["mat"]):
            horizontes[horizonte] = base_saida(cfg, nivel_agora, None, None, "MAT ausente no repositório")
            continue
        if not horas_muc:
            horizontes[horizonte] = base_saida(cfg, nivel_agora, None, None, "sem dado recente em Muçum")
            continue
        mh = melhor_hora(cfg, series, horas_muc, limite_alvo)
        if mh is None:
            t_diag = horas_muc[-1]
            x = montar_inputs(cfg, series, t_diag)
            faltantes = diagnosticar_inputs(cfg, x, series, t_diag)
            falt = len([v for v in x if v is None])
            horizontes[horizonte] = base_saida(
                cfg, nivel_agora, None, None,
                f"inputs incompletos ({falt}/{cfg['n_inputs']} faltando) - sem previsao nesta hora",
                faltantes)
            print(f"[{horizonte}] {cfg['modelo']} incompleto; saída explícita sem previsão")
            continue
        t, x = mh
        try:
            variacao = prever(cfg["mat"], x)
            nivel_base = nivel_exato(series[ALVO], t)
            nivel_prev = nivel_base + variacao if cfg["tipo"].upper() == "ALT" else variacao
            out = base_saida(cfg, nivel_agora, nivel_prev, t, "ok", nivel_base=nivel_base, input_values=x)
            horizontes[horizonte] = out
            print(f"[{horizonte}] {cfg['modelo']} OK base={t.isoformat()} previsão={round(nivel_prev, 1)} cm")
        except Exception as e:
            horizontes[horizonte] = base_saida(cfg, nivel_agora, None, t, f"falha no modelo: {e}")
            print(f"[{horizonte}] {cfg['modelo']} falhou: {e}")

    historico = normalizar_historico_grade(carregar_historico())
    historico = filtrar_historico_modelos(historico, modelos)
    for out in horizontes.values():
        historico = upsert_previsao_historico(historico, out)
    historico = conferir_historico(historico, series)
    salvar_historico(historico)

    escrever_pacote(horizontes, historico)


def validar(mat_path):
    m = carregar_mat(mat_path)
    n_in = np.asarray(m["ae"], float).size
    wh = np.atleast_2d(np.asarray(m["wh"], float))
    n_hidden = wh.shape[0] if wh.shape[1] == n_in else wh.shape[1]
    print("n_inputs:", n_in, "| n_neuronios:", n_hidden)
    dados = np.asarray(m["DADOS"], float)
    if dados.ndim == 2 and dados.shape[0] == n_in + 1 and dados.shape[1] != n_in + 1:
        dados = dados.T
    X = dados[:, :n_in]
    be = np.asarray(m["be"], float).ravel(); ae = np.asarray(m["ae"], float).ravel()
    if "ptot" in m:
        pn = (X - be) / ae
        ptot = np.asarray(m["ptot"], float)
        if ptot.shape != pn.shape and ptot.T.shape == pn.shape:
            ptot = ptot.T
        err = float(np.max(np.abs(pn - ptot)))
        print(f"(X-be)/ae == ptot: max|erro| = {err:.6f}  (esperado ~0)")
    pred = np.array([prever(mat_path, X[i]) for i in range(len(X))])
    ref_key = "pred_target_tot" if "pred_target_tot" in m else ("Tctot" if "Tctot" in m else None)
    if ref_key:
        ref = np.asarray(m[ref_key], float).ravel()
        k = min(len(pred), len(ref)); rmse = float(np.sqrt(np.mean((pred[:k] - ref[:k]) ** 2)))
        print(f"RMSE(forward vs {ref_key}) = {rmse:.6f} cm (esperado ~0) n={k}")


if __name__ == "__main__":
    if "--validar" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--validar"]
        alvo = args[0] if args else os.path.join(MAT_DIR, "MUC_H2_ALT_STC002_R2M001.mat")
        validar(alvo if os.path.isabs(alvo) else os.path.join(MAT_DIR, os.path.basename(alvo)))
    else:
        main()
