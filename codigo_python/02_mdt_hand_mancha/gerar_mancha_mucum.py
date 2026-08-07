#!/usr/bin/env python3
# LEGADO (ANADEM 30 m puro) — NÃO usar em produção.
# A mancha publicada de Muçum vem do mosaico 2 m:
#   python codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py mucum
#   python codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_mucum.py
# Este script permanece só para auditoria histórica. Para forçar o legado:
#   ALLOW_ANADEM_ONLY_MANCHA=1 python .../gerar_mancha_mucum.py
import os
import sys

if os.environ.get("ALLOW_ANADEM_ONLY_MANCHA") != "1":
    print(
        "ERRO: gerar_mancha_mucum.py é legado (ANADEM-only) e sobrescreveria o mosaico 2 m.\n"
        "Use: python codigo_python/02_mdt_hand_mancha/gerar_mancha_mosaico.py mucum\n"
        "     python codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_mucum.py\n"
        "Para forçar o legado: ALLOW_ANADEM_ONLY_MANCHA=1",
        file=sys.stderr,
    )
    raise SystemExit(2)

import re, json, base64, io
import numpy as np
import rasterio
from scipy import ndimage
from math import cos, radians
from PIL import Image

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TIF = os.path.join(RAIZ, "assets", "data", "mucum_inundacao", "mdt", "mdt_mucum_anadem_30m.tif")
PAGINA = os.path.join(RAIZ, "mucum_inundacao.html")

# Calibração vinda do Dispatch (redes neurais de Muçum)
ESTACAO_ALVO = "86510000"      # régua de Muçum
ESTACAO_MONTANTE = "86472600"  # montante (Santa Tereza)
BANKFULL_CM = 500              # nível normal / zero operacional da mancha (HAND 0)
NIVEL_MAX_M = 25.0             # alcance codificado no PNG (dm 0..250)


def main():
    with rasterio.open(TIF) as ds:
        dem = ds.read(1).astype("float64")
        b = ds.bounds
        nd = ds.nodata
    ny, nx = dem.shape
    W, S, E, N = b.left, b.bottom, b.right, b.top
    a = (E - W) / nx
    e = (S - N) / ny
    lat0 = (S + N) / 2
    cell_ha = (abs(a) * 111320) * (abs(e) * 111320 * cos(radians(lat0))) / 1e4
    print(f"TIF {ny}x{nx} | bounds W{W:.4f} S{S:.4f} E{E:.4f} N{N:.4f} | cel {cell_ha:.3f} ha")

    # nodata -> preenche com valor alto para não virar leito
    if nd is not None:
        dem = np.where(dem == nd, np.nan, dem)
    if np.isnan(dem).any():
        dem = np.where(np.isnan(dem), np.nanmax(dem), dem)

    # talvegue: mínimo local + corte de percentil, maior componente da semente
    sr, sc = np.unravel_index(int(np.argmin(dem)), dem.shape)
    mn = ndimage.minimum_filter(dem, size=9)
    corte = np.percentile(dem, 15)
    thal = (dem <= mn + 1.0) & (dem <= corte)
    lbl, _ = ndimage.label(thal)
    thal = lbl == lbl[sr, sc]
    print(f"talvegue {int(thal.sum())} px | cota {dem[thal].min():.1f}-{dem[thal].max():.1f} m")

    # HAND: distância vertical ao talvegue mais próximo
    _, inds = ndimage.distance_transform_edt(~thal, return_distances=True, return_indices=True)
    hand = dem - dem[inds[0], inds[1]]
    hand = np.clip(hand, 0, NIVEL_MAX_M)

    # PNG em decímetros (0..250)
    dm = np.clip(np.round(hand * 10), 0, 250).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(dm, mode="L").save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    payload = {
        "cols": nx, "rows": ny, "S": S, "W": W, "N": N, "E": E,
        "estacao_alvo": ESTACAO_ALVO, "estacao_montante": ESTACAO_MONTANTE,
        "bankfull_cm": BANKFULL_CM,
        "fonte": "LEGADO ANADEM 30 m puro — não usar; preferir gerar_mancha_mosaico.py",
        "hand_png_b64": b64,
    }
    html = open(PAGINA, encoding="utf-8").read()
    html2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        '<script id="hand-data" type="application/json">' + json.dumps(payload, ensure_ascii=False) + "</script>",
        html, count=1, flags=re.DOTALL,
    )
    if n != 1:
        raise SystemExit("hand-data não encontrado em " + PAGINA)
    open(PAGINA, "w", encoding="utf-8").write(html2)
    print(f"injetado em {PAGINA} ({len(b64)} chars b64)")


if __name__ == "__main__":
    main()
