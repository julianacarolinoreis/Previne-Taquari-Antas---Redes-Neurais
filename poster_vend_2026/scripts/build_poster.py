"""Monta o pôster V END / II EBHE sobre o template oficial (594 x 1026 mm)."""
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Pt
from PIL import Image

SP = Path(__file__).parent
FIG = SP.parent / "fig"
OUT = SP.parent / "poster_VEND_Santa_Tereza_ALT.pptx"
M = json.load(open(FIG / "metricas.json"))

NAVY = RGBColor(0x2A, 0x37, 0x8D)
DEEP = RGBColor(0x00, 0x3C, 0x64)
BLUE = RGBColor(0x03, 0x6C, 0xB5)
PALE = RGBColor(0xE6, 0xEE, 0xF5)
ORANGE = RGBColor(0xD9, 0x66, 0x1F)
INK = RGBColor(0x1F, 0x26, 0x33)
MUTED = RGBColor(0x5B, 0x65, 0x73)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Arial"

BODY, SMALL, CAP = 24, 20, 18


def mm(v):
    return Emu(int(round(v * 36000)))


def br(x, nd=3):
    return f"{x:.{nd}f}".replace(".", ",")


prs = Presentation(SP / "template_VEND_594x1026mm.pptx")
slide = prs.slides[0]
shapes = slide.shapes


def _style_run(run, size, bold=False, color=INK, italic=False):
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color


def text(x, y, w, h, paras, size=BODY, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         space_after=6, line=1.08, name=None):
    """paras: lista de parágrafos; cada um é str, ou lista de (texto, {bold, color, italic, size}),
    ou dict {"runs": ..., "bullet": True}."""
    tb = shapes.add_textbox(mm(x), mm(y), mm(w), mm(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, p in enumerate(paras):
        bullet = False
        if isinstance(p, dict):
            bullet = p.get("bullet", False)
            p = p["runs"]
        if isinstance(p, str):
            p = [(p, {})]
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.line_spacing = line
        para.space_after = Pt(space_after)
        if bullet:
            pPr = para._p.get_or_add_pPr()
            pPr.set("marL", str(mm(7)))
            pPr.set("indent", str(-mm(7)))
            bu_clr = pPr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buClr", {})
            srgb = bu_clr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr", {"val": "D9661F"})
            bu_clr.append(srgb)
            bu_font = pPr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buFont", {"typeface": "Arial"})
            bu_char = pPr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buChar", {"char": "■"})
            pPr.append(bu_clr)
            pPr.append(bu_font)
            pPr.append(bu_char)
        for t, opt in p:
            r = para.add_run()
            r.text = t
            _style_run(r, opt.get("size", size), opt.get("bold", False), opt.get("color", color), opt.get("italic", False))
    return tb


def header(x, y, label, w=None):
    """Rótulo de seção: pílula azul-marinho com texto branco (motivo visual do pôster)."""
    w = w or (len(label) * 7.4 + 22)
    shp = shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, mm(x), mm(y), mm(w), mm(14))
    shp.name = f"Secao {label}"
    shp.adjustments[0] = 0.5
    shp.fill.solid()
    shp.fill.fore_color.rgb = NAVY
    shp.line.fill.background()
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = mm(7)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = label
    _style_run(r, 30, True, WHITE)
    return shp


def picture(path, x, y, w=None, h=None, name=None):
    iw, ih = Image.open(path).size
    if w and not h:
        h = w * ih / iw
    elif h and not w:
        w = h * iw / ih
    pic = shapes.add_picture(str(path), mm(x), mm(y), mm(w), mm(h))
    if name:
        pic.name = name
    return w, h


def box(x, y, w, h, fill, name, radius=0.12):
    shp = shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, mm(x), mm(y), mm(w), mm(h))
    shp.name = name
    shp.adjustments[0] = radius
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def table(x, y, w, col_w, rows, size=SMALL, row_h=11.5, name=None, first_col_bold=True):
    nr, nc = len(rows), len(rows[0])
    gt = shapes.add_table(nr, nc, mm(x), mm(y), mm(w), mm(row_h * nr))
    if name:
        gt.name = name
    tbl = gt.table
    tblPr = tbl._tbl.tblPr
    # remove o estilo padrão (faixas azuis do Office)
    for k in ("bandRow", "firstRow"):
        tblPr.set(k, "0")
    total = sum(col_w)
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = mm(w * cw / total)
    for i in range(nr):
        tbl.rows[i].height = mm(row_h)
        for j in range(nc):
            c = tbl.cell(i, j)
            c.margin_left = c.margin_right = mm(2.5)
            c.margin_top = c.margin_bottom = mm(1)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            c.fill.fore_color.rgb = NAVY if i == 0 else (PALE if i % 2 == 0 else WHITE)
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 or (i > 0 and isinstance(rows[i][j], str) and len(rows[i][j]) > 8) else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(rows[i][j])
            _style_run(r, size, bold=(i == 0) or (j == 0 and first_col_bold), color=WHITE if i == 0 else INK)
    return gt


# ------------------------------------------------------------------ cabeçalho
for shp in shapes:
    if shp.name == "TextBox 7":
        shp.left, shp.top, shp.width = mm(30), mm(212), mm(534)
        p = shp.text_frame.paragraphs[0]
        p.line_spacing = None
        pPr = p._p.get_or_add_pPr()
        for ln in pPr.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}lnSpc"):
            pPr.remove(ln)
        run = p.runs[0]
        run.text = "Juliana Carolino Reis, Guilherme Garcia de Oliveira, Fernanda Vier Jung e Josiane Leci Vanin Barbieri"
        _style_run(run, 28, False, DEEP)
        for el in ("ea", "cs", "sym"):
            for node in run._r.rPr.findall(f"{{http://schemas.openxmlformats.org/drawingml/2006/main}}{el}"):
                run._r.rPr.remove(node)
        p2 = shp.text_frame.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        p2.space_before = Pt(4)
        r2 = p2.add_run()
        r2.text = ("Universidade Federal do Rio Grande do Sul (UFRGS) – Centro Estadual de Pesquisas em "
                   "Sensoriamento Remoto e Meteorologia (CEPSRM)  ·  julianacarolinoreis@gmail.com")
        _style_run(r2, 19, False, MUTED)

L, W = 30.0, 534.0
CW, GAP = 260.0, 14.0
XB = L + CW + GAP
t2, t4, t8 = (M[h]["teste"] for h in ("2h", "4h", "8h"))
av = M["ao_vivo"]["2h"]

# ------------------------------------------------------------------ linha A
y = 252
header(L, y, "INTRODUÇÃO")
text(L, y + 19, CW, 68, [
    [("As cheias de 2023 e 2024 na bacia do Taquari-Antas mostraram a necessidade de previsões de nível "
      "com antecedência útil para o alerta. Este trabalho aplica ", {}),
     ("Redes Neurais Artificiais", {"bold": True}),
     (" do tipo Perceptron Multicamadas (MLP) para prever o nível do rio Taquari em ", {}),
     ("Santa Tereza", {"bold": True}),
     (" com ", {}), ("2, 4 e 8 horas", {"bold": True}), (" de antecedência, pela ", {}),
     ("abordagem alternativa (ALT)", {"bold": True, "color": ORANGE}),
     (": a RNA prevê só a variação do nível.", {})],
], name="Texto introducao")

y2 = y + 91
header(L, y2, "ÁREA DE ESTUDO E DADOS")
text(L, y2 + 19, CW, 52, [
    {"bullet": True, "runs": [("Bacia do rio Taquari até a estação 86472600 (≈15.800 km²)", {})]},
    {"bullet": True, "runs": [("Dados horários de nível e chuva (2022–2025) do portal HidroTelemetria (ANA/SGB)", {})]},
    {"bullet": True, "runs": [("Amostras agrupadas por ", {}), ("eventos de cheia", {"bold": True}),
                              (", separados em treino, validação e teste", {})]},
], name="Texto area de estudo")

mw, mh = picture(FIG / "mapa.png", XB + (CW - 232) / 2, y, w=232, name="Mapa da bacia")
text(XB, y + mh + 2, CW, 8, ["Figura 1 – Bacia do rio Taquari até Santa Tereza e postos fluviométricos."],
     size=CAP, color=MUTED, name="Legenda mapa")

# ------------------------------------------------------------------ linha B: metodologia
y = 428
header(L, y, "METODOLOGIA: ABORDAGEM ALTERNATIVA (ALT)")
yb, hb = y + 20, 44
etapas = [
    ("Entradas", "níveis, diferenças e acelerações em Santa Tereza e a montante; chuva acumulada", PALE, INK),
    ("RNA MLP", "1 camada oculta · sigmoide · retropropagação com gradiente adaptativo", PALE, INK),
    ("Saída da RNA", "variação do nível ΔH = H(t+h) − H(t)", PALE, INK),
    ("Nível previsto", "Ĥ(t+h) = H(t) + ΔH", NAVY, WHITE),
]
bw, aw = 118.0, 20.0
for i, (tit, desc, fill, fc) in enumerate(etapas):
    bx = L + i * (bw + aw)
    b = box(bx, yb, bw, hb, fill, f"Etapa {i + 1}")
    tf = b.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = mm(4)
    tf.margin_top = tf.margin_bottom = mm(2)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = tit
    _style_run(r, 24, True, ORANGE if fc == INK else WHITE)
    p = tf.add_paragraph(); p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = desc
    _style_run(r, 18, False, fc)
    if i < len(etapas) - 1:
        a = shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, mm(bx + bw + 3), mm(yb + hb / 2 - 6), mm(aw - 6), mm(12))
        a.name = f"Seta {i + 1}"
        a.fill.solid(); a.fill.fore_color.rgb = ORANGE
        a.line.fill.background(); a.shadow.inherit = False

yt = yb + hb + 9
text(L, yt, CW, 62, [
    {"bullet": True, "runs": [("Neurônios ocultos ≈ 2 × nº de entradas; 10 inicializações por rede", {})]},
    {"bullet": True, "runs": [("Entradas escolhidas por algoritmo de busca em Python; redes treinadas no MATLAB", {})]},
    {"bullet": True, "runs": [("Avaliação: NSE, PME (ganho sobre a persistência), EAM e E95 (erro não superado em 95%)", {})]},
], size=SMALL, space_after=4, name="Texto metodologia")
table(XB, yt, CW, [1.0, 1.05, 1.15, 3.6], [
    ["Modelo", "Entradas", "Neurônios", "Variáveis de entrada"],
    ["ALT 2h", M["2h"]["n_inputs"], M["2h"]["neuronios"], "Santa Tereza e Linha José Júlio"],
    ["ALT 4h", M["4h"]["n_inputs"], M["4h"]["neuronios"], "+ 2 postos a montante"],
    ["ALT 8h", M["8h"]["n_inputs"], M["8h"]["neuronios"], "7 postos fluviométricos + chuva"],
], size=19, row_h=12.5, name="Tabela configuracao")

# ------------------------------------------------------------------ linha C: resultados (dispersão)
y = 562
header(L, y, "RESULTADOS")
dw, dh = picture(FIG / "dispersao.png", L + (W - 430) / 2, y + 17, w=430, name="Dispersao previsto x observado")
text(L, y + 17 + dh + 1, W, 8, ["Figura 2 – Nível previsto × observado (série completa) dos modelos ALT ao vivo em Santa Tereza."],
     size=CAP, color=MUTED, name="Legenda dispersao")

# ------------------------------------------------------------------ linha D
y = y + 17 + dh + 12
red = lambda t: f"−{100 * (1 - t['EAM'] / t['EAM_persistencia']):.0f}%"
table(L, y, CW, [1.0, 1.0, 1.0, 1.05, 0.95, 1.55], [
    ["Teste", "NSE", "PME", "EAM", "E95", "EAM × persist."],
    ["ALT 2h", br(t2["NSE"]), br(t2["PME"]), f"{br(t2['EAM'], 1)} cm", f"{t2['E95']:.0f} cm", red(t2)],
    ["ALT 4h", br(t4["NSE"]), br(t4["PME"]), f"{br(t4['EAM'], 1)} cm", f"{t4['E95']:.0f} cm", red(t4)],
    ["ALT 8h", br(t8["NSE"]), br(t8["PME"]), f"{br(t8['EAM'], 1)} cm", f"{t8['E95']:.0f} cm", red(t8)],
], size=19, row_h=12.5, name="Tabela resultados")
text(L, y + 52, CW, 8, ["Tabela 1 – Desempenho no conjunto de teste (eventos não usados no treinamento)."],
     size=CAP, color=MUTED, name="Legenda tabela")

yc = y + 64
header(L, yc, "CONCLUSÕES")
text(L, yc + 19, CW, 110, [
    {"bullet": True, "runs": [("Nos três horizontes, a abordagem ALT alcançou ", {}), ("NSE ≥ 0,979", {"bold": True}),
                              (" e ", {}), ("PME de 0,88 a 0,97", {"bold": True}), (" no teste.", {})]},
    {"bullet": True, "runs": [("O erro médio cai 65–81% frente à persistência e cresce com a antecedência (de 3,5 a 23 cm).", {})]},
    {"bullet": True, "runs": [("Em tempo real, o modelo 2h acompanhou a cheia de set/2026 com erro médio de 9 cm: potencial "
                               "de uso operacional no alerta de Santa Tereza.", {})]},
], size=SMALL, space_after=5, name="Texto conclusoes")

header(XB, y, "OPERAÇÃO EM TEMPO REAL")
vw, vh = picture(FIG / "ao_vivo_2h.png", XB, y + 18, w=236, name="Operacao ao vivo 2h")
text(XB, y + 18 + vh + 1, CW, 8,
     ["Figura 3 – Previsão ao vivo 2h × telemetria (25/09 a 05/10/2026)."],
     size=CAP, color=MUTED, name="Legenda ao vivo")
text(XB, y + 18 + vh + 11, CW, 40, [
    [("Robô horário com telemetria do SGB/ANA, em teste paralelo ao alerta oficial. Em ", {}),
     (f"{av['n']} previsões auditadas", {"bold": True}), (" (pico de ", {}),
     (f"{br(av['pico_obs'] / 100, 1)} m", {"bold": True}), ("), o modelo 2h teve ", {}),
     (f"EAM de {br(av['EAM'], 1)} cm", {"bold": True, "color": ORANGE}),
     (f" (persistência: {br(av['EAM_persistencia'], 1)} cm).", {})],
], size=SMALL, name="Texto ao vivo")

# ------------------------------------------------------------------ rodapé de referências
text(L, 913, W, 12, [
    [("Referências: ", {"bold": True}),
     ("ALVISI, S. et al. (2006). Hydrology and Earth System Sciences, 10(1), 1-17. · RUMELHART, D. E. et al. (1986). "
      "Nature, 323, 533-536. · KUMAR, V. et al. (2023). Sustainability, 15(13), 10543.   ", {}),
     ("Agradecimentos: ", {"bold": True}),
     ("FAPERGS (processos 24/2551-0002124-8 e 25/2551-0002522-2).", {})],
], size=15, color=MUTED, line=1.0, name="Referencias e agradecimentos")

prs.save(OUT)
print("salvo", OUT)
