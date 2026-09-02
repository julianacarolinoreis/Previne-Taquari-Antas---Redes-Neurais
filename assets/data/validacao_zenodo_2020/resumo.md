# Cruzamento Zenodo 2020 × manchas HAND (PREVINE)

Fonte: [Giordani, Fan & Alves (2021)](https://doi.org/10.5281/zenodo.4730371) — cheia de julho/2020 no Taquari-Antas (pontos de vídeos/fotos + manchas MGB).

## Leitura rápida

- Em **Muçum**, o HAND do site no pico de 08/07/2020 (**2202 cm** → HAND **17.02 m**) cobre **88.1%** dos pontos Zenodo no bbox (e **92.7%** só com rótulo municipal Muçum).
- Os contornos publicados só vão até **15 m** de HAND → cobririam **65.5%** desses pontos; o pico de 2020 pede ~17 m.
- Sobreposição espacial HAND × MGB (n=0,030) em Muçum: IoU **0.55** (n=0,045: **0.58**). Concordância moderada — métodos diferentes (HAND estático vs hidrodinâmica MGB).
- **Santa Tereza** não tem pontos demarcados nesse Zenodo; só dá para comparar com o raster MGB (IoU@15 m ≈ **0.52**).

## Muçum (detalhe)

- Pontos no bbox HAND: **84** ({'Roca Sales': 13, 'Muçum': 55, 'Encantado': 16})
- HAND nos pontos: min=5.199999809265137, p50=14.199999809265137, p90=17.380000114440918, max=25.0
- Confusão HAND@pico × MGB n=0,030 nos pontos: TP=27 FP=47 FN=5 TN=5
  - Muitos FP: HAND no pico é mais generoso que o MGB nos pontos (ou MGB subestima / pontos fora do canal principal modelado).
- Melhor limiar HAND vs MGB (grade): **22.0 m** (IoU=0.5821145026265491)

## Santa Tereza

- Pontos Zenodo no bbox: **0** (dataset focado no Vale do Taquari a jusante).
- IoU HAND@15 m × MGB n=0,030: **0.52**

## Arquivos

- `relatorio_cruzamento.json` — métricas completas
- `pontos_mucum_08jul2020.geojson` — pontos do dia 08 com HAND amostrado

Script: `codigo_python/02_mdt_hand_mancha/validar_zenodo_2020_mancha.py`
