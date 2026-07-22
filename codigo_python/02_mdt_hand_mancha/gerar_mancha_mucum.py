#!/usr/bin/env python3
# ROBÔ — mancha de inundação de Muçum a partir do MDT commitado.
# Lê o TIF (mesmo padrão do Santa Tereza), calcula o talvegue e o HAND
# (Height Above Nearest Drainage), codifica o HAND como PNG em decímetros e
# injeta o payload dentro de mucum_inundacao.html (<script id="hand-data">).
# Não baixa nada: a única fonte é o TIF já versionado no repositório.
import os, re, json, base64, io
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
    print(f"elev {dem.min():.1f}-{dem.max():.1f} m")

    # semente = mínimo global (rio Taquari no fundo do vale)
    sr, sc = np.unravel_index(int(np.argmin(dem)), dem.shape)
    print(f"semente r{sr} c{sc} cota {dem[sr,sc]:.1f} @ lon {W+sc*a:.4f} lat {N+sr*e:.4f}")

    # talvegue: células perto do mínimo local, no fundo do vale, conectadas à semente
    mn = ndimage.minimum_filter(dem, size=9)
    corte_vale = np.percentile(dem, 15)
    thal = (dem <= mn + 1.0) & (dem <= corte_vale)
    lbl, _ = ndimage.label(thal)
    thal = lbl == lbl[sr, sc]
    print(f"talvegue {int(thal.sum())} cel | cota {dem[thal].min():.1f}->{dem[thal].max():.1f} | corte vale {corte_vale:.1f}")

    # HAND = cota - cota do talvegue mais próximo
    _, (ri, rj) = ndimage.distance_transform_edt(~thal, return_indices=True)
    hand = dem - dem[ri, rj]
    hand[hand < 0] = 0

    # sanidade: área alagada conectada ao rio por nível
    def flood(h):
        l, _ = ndimage.label(hand <= h)
        keep = set(np.unique(l[thal])) - {0}
        return np.isin(l, list(keep))
    print("nível(m) | área_ha")
    for h in (2, 4, 6, 8, 10, 13):
        print(f"   {h:2d}    | {int(flood(h).sum())*cell_ha:8.1f}")

    # codifica HAND -> PNG decímetros (0..250; acima disso satura, não alaga)
    dm = np.clip(np.round(hand * 10), 0, int(NIVEL_MAX_M * 10)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(dm, mode="L").save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    payload = {
        "cols": nx, "rows": ny, "S": round(S, 6), "W": round(W, 6),
        "N": round(N, 6), "E": round(E, 6),
        "estacao_alvo": ESTACAO_ALVO, "estacao_montante": ESTACAO_MONTANTE,
        "bankfull_cm": BANKFULL_CM,
        "fonte": "MDT 30 m (base Copernicus GLO-30) — recorte do vale do Taquari em Muçum",
        "hand_png_b64": b64,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    # injeta no <script id="hand-data"> da página
    html = open(PAGINA, encoding="utf-8").read()
    novo = f'<script id="hand-data" type="application/json">{payload_json}</script>'
    html2, n = re.subn(
        r'<script id="hand-data" type="application/json">.*?</script>',
        lambda m: novo, html, count=1, flags=re.DOTALL,
    )
    if n != 1:
        raise SystemExit("ERRO: <script id=hand-data> não encontrado em mucum_inundacao.html")
    open(PAGINA, "w", encoding="utf-8").write(html2)
    print(f"payload injetado ({len(payload_json)} chars, png {len(buf.getvalue())} bytes) em mucum_inundacao.html")


if __name__ == "__main__":
    main()
