# Validação de campo do HAND LiDAR — Santa Tereza

Campanha de 05/09/2026: marcas de cheia e limites de inundação dos eventos de
set/2023, nov/2023 e mai/2024, posicionados com GNSS de celular e com GNSS RTK.
A análise sustenta o trabalho para o SBSR 2027 e o artigo em preparação.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `analise_erros_campo.py` | Lê a planilha de campo e recalcula todos os erros com fórmulas únicas. |
| `erros_campo_santa_tereza.csv` | Uma linha por ponto × evento, sem coordenadas. |
| `metricas_validacao_campo.json` | Viés, MAE, RMSE e demais métricas por conjunto. |
| `figuras/` | Figuras 1–3 (300 dpi) e figuras do manuscrito (`fig_manuscrito_*`; a Figura 1 do SBSR 2027 é `fig_manuscrito_1_mapa_erros.png`, mapa e erros juntos). |
| `estatisticas_manuscrito.py` / `.json` | IC 95% (bootstrap e t), z0 por evento, sensibilidade à fonte do pico (telemetria × SGB), Δz celular × RTK, plano horizontal como modelo nulo. |
| `figuras_manuscrito.py` | Gera as figuras do manuscrito (precisa da planilha e de um GeoJSON de UFs). |
| `analises_adicionais.py` / `.json` | Concordância (NSE, KGE), classes de perigo com kappa, teste da premissa de linha d'água paralela (cota observada × cota do trecho de drenagem), validação cruzada HAND × plano horizontal, erro horizontal da borda, MDTs nos vértices RTK, orçamento de erros e sensibilidade aos pontos excluídos. Gera `figuras/fig_adicional_cheia_vs_drenagem.png`. |

A planilha original (`sumario_erros_hand.xlsx`) não é versionada porque traz as
coordenadas exatas dos pontos de campo. Para reproduzir:

```
pip install openpyxl numpy scipy rasterio pyproj shapely pillow matplotlib
python pesquisas/validacao-campo-hand-santa-tereza/analise_erros_campo.py caminho/sumario_erros_hand.xlsx
```

## Definições

- Lâmina HAND do evento: `d = (pico_régua − 1,60) − HAND`, com limiares de
  22,05 m (set/2023), 20,01 m (nov/2023) e 20,73 m (mai/2024).
- Erro de lâmina (celular): `d_HAND − d_obs`, com o LiDAR na posição do celular;
  nos limites, `d_obs = 0`.
- Erro na cota da cheia (RTK): `(z_LiDAR + d_HAND) − (z_RTK + d_obs)`.
- Altitude RTK: `h − 6,46 m`. O hgeoHNOR2020 dá de 6,44 a 6,47 m nos pontos.

## Resultados principais

| Conjunto | n | Viés (m) | MAE (m) | RMSE (m) |
|---|---|---|---|---|
| Lâmina, set/2023, zero 1,60 m (calibração) | 17 | 0,00 | 0,64 | 0,99 |
| Lâmina, set/2023, validação cruzada LOO | 17 | 0,00 | 0,68 | 1,05 |
| Lâmina, nov/2023 + mai/2024 (independente) | 5 | +0,61 | 0,62 | 0,85 |
| Lâmina, todas | 22 | +0,14 | 0,64 | 0,96 |
| Cota da cheia com RTK | 19 | +0,17 | 0,77 | 1,05 |

O zero que anula o viés de set/2023 é 1,601 m, ou seja, o 1,60 m operacional
equivale a uma calibração com esses pontos.

Análises adicionais (`analises_adicionais.json`):

- Concordância das 22 profundidades: NSE 0,65 e KGE 0,80. O HAND acerta a
  classe de perigo (< 0,5; 0,5–1; 1–2; > 2 m) em 15 de 22 observações e erra por
  no máximo uma classe em 20 (kappa ponderado 0,72).
- Em set/2023, o HAND refere os pontos com RTK a trechos do rio com cotas de
  52,8 e 53,8 m no LiDAR, mas a cota observada da cheia não acompanha essa
  diferença: inclinação −0,14 (IC 95% −0,88 a 0,60); a premissa de paralelismo
  (inclinação 1) é rejeitada com p = 0,005.
- Validação cruzada leave-one-out (n = 15): plano horizontal com MAE de 0,56 m,
  HAND com 0,76 m; a diferença tem IC de −0,42 a +0,03 m.
- Nos 22 vértices RTK, o NMAD do terreno é de 0,30 m no MDT de drone (1 m),
  0,72 m no LiDAR reamostrado a 10 m e 5,0 m no ANADEM (30 m). O drone difere
  do RTK em cerca de +6,1 m, o que indica altitudes elipsoidais.
- Incertezas de medição plausíveis explicariam MAE de cerca de 0,19 m, contra
  0,64 m observados.

## Diferenças em relação à planilha original

- `VALIDACAO_RTK_SET23 ERRO VERTICAL` é `z_LiDAR − z_RTK`, uma diferença de
  terreno, e não erro do modelo. Ela foi substituída pelo erro na cota da cheia.
- Em V005, V009 e V011, o "erro RTK" da planilha soma a lâmina só do lado do
  LiDAR, o que infla os valores em 2,8–3,8 m. Por isso, o MAE "RTK" de 1,31 m
  da `TABELA_ARTIGOS` não deve ser usado.
- O vértice RTK de V001 está a 5 mm do de H001 e foi excluído da análise RTK.
- H002 usa o vértice RTK rotulado `V009`, e V009 usa o `V009A`, como na planilha.
- H010, H011, H012 (Linha José Júlio) e V012 (altura mínima) ficam fora, como na
  tabela original.

## Conferências com dados do repositório

O LiDAR de 10 m e o HAND web de 5 m foram amostrados nas coordenadas RTK
(colunas `z_lidar10_no_rtk_m`, `hand_web_no_rtk_m`). Eles servem só como
diagnóstico: em margens íngremes, células de 5–10 m geram erros de vários
metros. Para publicar, extraiam o HAND e o LiDAR de 1 m nas coordenadas RTK.
