# Estudo da bacia Taquari-Antas

**Estudo, nao modelo.** Nao sao so 32 sub-bacias.

## Hierarquia

1. 3 regioes hidrograficas
2. 25 bacias (G040 = Taquari-Antas)
3. ~175 UPG (zip SEMA "UBH" = este nivel)
4. 32 enquadramentos em G040 (qualidade da agua)
5. ~33 mil ottobacias BHO6 na arvore `786` (mini-unidades)
6. mini-bacias SIOUT/ArcHydro (outorga) — distintas do zip UBH

Leia `mapa_hierarquia_rs.html`, `mapa_postos_upg.html` e os JSONs.

Postos: `postos_por_upg_latest.json` (ANA ∩ G040 por UPG/familia BHO6).

```bash
python scripts/build_estudo_bacia_taquari_antas.py
python scripts/build_estudo_bacia_subbacias_fozes.py
python scripts/build_estudo_hierarquia_rs_bacias.py
python scripts/build_estudo_postos_por_upg.py
python scripts/build_estudo_pluvio_recorte.py
```

## Decisao de recorte

Leia `recorte_modelo.html` antes de qualquer HEC.
