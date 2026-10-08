"""Configuração comum da calibração HEC-HMS Taquari-Antas (rodada de 05/10/2026).

Numeração dos eventos = catálogo Muçum 2h v1 da usuária
(redes_neurais/mucum/muçum 2h/modelo_mucum_2h_novo_v1.xlsx, aba V001).
Equivalência com a numeração antiga usada pelo Codex (catálogo mucum_q62):
E1=E19(q62), E5=E22(q62), E12=E24(q62), E18=E27(q62), E22=E28(q62).
"""
import os
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# Caminhos configuráveis por variável de ambiente (nuvem/Linux); o padrão continua sendo o PC da usuária.
CODEX = Path(r"C:\Users\Usuario\Documents\Codex\2026-09-19\quero-que-voc-veja-o-nosso")
HEC_CMD = Path(os.environ.get("HEC_HMS_CMD", r"D:\PREVINE\tools\hec-hms-4.13\portable\HEC-HMS-4.13\HEC-HMS.cmd"))
# Bacia de referência do Codex (Tc/R/K originais, passos Muskingum admissíveis a 10 min).
BASIN_BASE = Path(os.environ.get("HEC_BASIN_BASE", str(CODEX / "calibracao_chuva_ampliada_20260930" / "a00_E27.basin")))
MDT_TRECHOS = Path(os.environ.get("HEC_MDT_CSV", str(
    CODEX / "modelo_bacia_taquari_antas_reconstruido_20260920" / "atributos_mdt_bacia_full_20260920" / "mdt_trechos_atributos.csv")))
MDT_SUBBACIAS = Path(os.environ.get("HEC_MDT_SUB", str(
    CODEX / "modelo_bacia_taquari_antas_reconstruido_20260920" / "atributos_mdt_bacia_full_20260920" / "mdt_subbacias_atributos.csv")))
DADOS = AQUI / "dados_ana"
FORC = AQUI / os.environ.get("HEC_FORC", "forcamento")          # forcamento_v3 = todos os pluviômetros
RESULT = AQUI / os.environ.get("HEC_RESULT", "resultados")    # pasta de saída das avaliações
RUNS = Path(os.environ.get("HEC_RUNS", r"C:\Users\Usuario\hec_calibracao_rodadas_20261005"))  # SSD: DSS no HD (D:) é ~25x mais lento

T = datetime.fromisoformat

MUCUM, LJJ = "86510000", "86472000"
CONTROLES = {"MUCUM": ("J_201", MUCUM), "LJJ": ("J_208", LJJ)}
AREA_MUCUM_KM2 = 15989.276

# Postos de chuva da rede ANA usada pelo Codex (22 postos). Código da telemetria sem zero à esquerda.
POSTOS = {
    "2851044": ("Guaporé", -28.8444, -51.8792), "2851072": ("Ibiraiaras", -28.3811, -51.6331),
    "2851085": ("CGH Taipinha", -28.9364, -51.5058), "2851092": ("CSG Ipê", -28.6678, -51.1731),
    "2852004": ("Auler", -28.8039, -52.3817), "2852077": ("CGH Soledade", -28.9378, -52.4856),
    "2950109": ("Aparados da Serra", -29.1586, -50.0789), "2951146": ("CGH Boa Vista", -29.4728, -51.8681),
    "86060010": ("CGH Cambará", -28.9489, -50.0556), "86099000": ("PCH Pezzi", -28.8047, -50.4936),
    "86163000": ("PCH Serra dos Cavalinhos II", -28.7869, -50.7447), "86195000": ("PCH Cazuza Ferreira", -29.0206, -50.7314),
    "86280500": ("PCH Rio São Marcos", -29.0367, -51.0956), "86321000": ("UHE Castro Alves", -29.0633, -51.3236),
    "86350000": ("PCH Chimarrão", -28.4725, -51.36), "86406000": ("PCH Santa Carolina", -28.6189, -51.4011),
    "86410800": ("PCH da Ilha", -28.7983, -51.4744), "86472000": ("Linha José Júlio", -29.0978, -51.6997),
    "86472600": ("Santa Tereza", -29.1781, -51.7322), "86488000": ("PCH Caçador", -28.6847, -51.8506),
    "86507000": ("PCH Cotiporã", -28.9722, -51.7558), "86510000": ("Muçum", -29.1672, -51.8686),
}

# Janelas de simulação (com ~3 dias de aquecimento) e eventos do catálogo avaliados em cada uma.
# papel: "calibracao" entra na função objetivo; "validacao" nunca entra.
SIMULACOES = {
    "S2023_07": dict(ini=T("2023-07-04 18:00"), fim=T("2023-07-20 18:00")),
    "S2023_09": dict(ini=T("2023-08-31 09:00"), fim=T("2023-09-10 00:00")),
    "S2023_10": dict(ini=T("2023-10-02 16:00"), fim=T("2023-10-23 21:00")),
    "S2023_11": dict(ini=T("2023-11-10 00:00"), fim=T("2023-11-28 11:00")),
    "S2024_05": dict(ini=T("2024-04-26 13:00"), fim=T("2024-05-19 11:00")),
    "S2024_06": dict(ini=T("2024-06-12 22:00"), fim=T("2024-07-03 02:00")),
    "S2025_06": dict(ini=T("2025-06-15 14:00"), fim=T("2025-07-03 18:00")),
    "S2026_07": dict(ini=T("2026-07-18 15:00"), fim=T("2026-08-02 21:00")),
}

# Eventos (catálogo Muçum 2h v1): janela de avaliação, controles válidos e papel.
EVENTOS = {
    "E3":  dict(sim="S2023_07", ini=T("2023-07-07 18:00"), fim=T("2023-07-11 16:00"), papel="validacao"),
    "E4":  dict(sim="S2023_07", ini=T("2023-07-12 07:00"), fim=T("2023-07-17 18:00"), papel="calibracao"),
    # E5: Muçum parou em 04/09 19:30 (sem pico); LJJ completo. Janela estendida além do recorte truncado.
    "E5":  dict(sim="S2023_09", ini=T("2023-09-03 09:00"), fim=T("2023-09-08 00:00"), papel="calibracao", sem_pico={"MUCUM"}),
    "E9":  dict(sim="S2023_10", ini=T("2023-10-04 02:00"), fim=T("2023-10-07 01:00"), papel="validacao"),
    "E10": dict(sim="S2023_10", ini=T("2023-10-07 01:00"), fim=T("2023-10-16 12:00"), papel="validacao"),
    "E11": dict(sim="S2023_10", ini=T("2023-10-16 13:00"), fim=T("2023-10-20 21:00"), papel="validacao"),
    "E12": dict(sim="S2023_11", ini=T("2023-11-13 00:00"), fim=T("2023-11-25 11:00"), papel="calibracao"),
    "E18": dict(sim="S2024_05", ini=T("2024-04-29 13:00"), fim=T("2024-05-09 18:00"), papel="calibracao"),
    "E19": dict(sim="S2024_05", ini=T("2024-05-10 13:00"), fim=T("2024-05-16 11:00"), papel="validacao"),
    "E22": dict(sim="S2024_06", ini=T("2024-06-15 22:00"), fim=T("2024-06-22 09:00"), papel="calibracao"),
    "E23": dict(sim="S2024_06", ini=T("2024-06-24 05:00"), fim=T("2024-06-30 02:00"), papel="validacao"),
    "E27": dict(sim="S2025_06", ini=T("2025-06-18 14:00"), fim=T("2025-06-23 18:00"), papel="validacao"),
    "E28": dict(sim="S2025_06", ini=T("2025-06-28 22:00"), fim=T("2025-06-30 18:00"), papel="validacao"),
    "E36": dict(sim="S2026_07", ini=T("2026-07-21 15:00"), fim=T("2026-07-25 11:00"), papel="validacao"),
    "E37": dict(sim="S2026_07", ini=T("2026-07-28 07:00"), fim=T("2026-07-30 21:00"), papel="validacao"),
}

# Candidatas a controle de vazão/nível na bacia inteira (SGB/CPRM, UHEs CERAN, Defesa Civil RS)
CONTROLES_CAND = {
    "86160000": "Passo Tainhas", "86110000": "PCH Passo do Meio jusante", "86118000": "PCH S. Cavalinhos I barramento",
    "86220600": "PCH Palanquinho jusante", "86298000": "UHE Castro Alves RS-122", "86305000": "UHE Castro Alves barramento",
    "86329001": "Nova Roma/Farroupilha", "86410001": "Protásio Alves/Ipê (Turvo)", "86447000": "UHE Monte Claro Balsa do Prata",
    "86448000": "UHE Monte Claro barramento", "86470800": "UHE 14 de Julho barramento", "86471000": "UHE 14 de Julho jusante",
    "86472000": "Linha José Júlio", "86472600": "Santa Tereza", "86500000": "Passo Carreiro", "86507220": "Cotiporã/Dois Lajeados",
    "86510000": "Muçum", "86542000": "União da Serra (Guaporé)", "86560000": "Linha Colombo (Guaporé)",
    "86581000": "Muçum/Encantado (Guaporé)", "86720000": "Encantado", "86780000": "Barra do Fão (Forqueta)",
    "86879300": "Estrela", "86881000": "Bom Retiro do Sul", "86895000": "Porto Mariante", "86950000": "Taquari",
}

# Relógio da telemetria (achado da revisão de 06/10/2026, confirmado em relogio_mucum.py):
# Muçum registrou com +105 min em [2023-10-02 15:00, 2024-11-03 01:00) — intervalo fixado na rodada RNA
# Muçum 4h/8h (02_SERIES_HORARIAS/corrigir_relogio_mucum.py), coerente com relogio_mucum.py.
from datetime import timedelta as _td
RELOGIO = {"86510000": (T("2023-10-02 15:00"), T("2024-11-03 00:59"), _td(minutes=-105))}


def corrige_relogio(cod, t):
    r = RELOGIO.get(cod)
    if r and r[0] <= t <= r[1]:
        return t + r[2]
    return t


# Catálogo ampliado (catalogo_ampliado.py): com HEC_CATALOGO=catalogo_ampliado.json entram as janelas e eventos novos
# (papel "novo" até definirmos a divisão calibração/validação/teste).
if os.environ.get("HEC_CATALOGO"):
    import json as _json
    _c = _json.loads((AQUI / os.environ["HEC_CATALOGO"]).read_text(encoding="utf-8"))
    for _s in _c["simulacoes"]:
        SIMULACOES[_s["sim"]] = dict(ini=T(_s["ini"]), fim=T(_s["fim"]))
    for _e in _c["eventos"]:
        EVENTOS[_e["id"]] = dict(sim=_e["sim"], ini=T(_e["ini"]), fim=T(_e["fim"]), papel=_e.get("papel", "novo"))
    for _k, _p in _c.get("papeis_antigos", {}).items():
        if _k in EVENTOS:
            EVENTOS[_k]["papel"] = _p

# Troca de papéis por experimento (validação cruzada, "deixar de fora"): HEC_PAPEIS aponta para um JSON {evento: papel}.
# Só vale para eventos que existem; o teste (papel "teste") não pode ser alterado por aqui.
if os.environ.get("HEC_PAPEIS"):
    import json as _json2
    _pp = Path(os.environ["HEC_PAPEIS"])
    _pp = _pp if _pp.is_absolute() else AQUI / _pp
    for _k, _p in _json2.loads(_pp.read_text(encoding="utf-8")).items():
        if _k in EVENTOS and EVENTOS[_k]["papel"] != "teste" and _p != "teste":
            EVENTOS[_k]["papel"] = _p
