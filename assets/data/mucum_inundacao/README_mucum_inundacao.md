# Muçum — mancha e cheias anteriores

## Produção atual (site)

- `mucum_inundacao.html` — **Cheias anteriores** (mesmo molde de Santa Tereza):
  chips de eventos (testes / cheias que transbordaram / referência),
  linha do tempo e mancha HAND no mosaico 2 m (drone + ANADEM).
- `mucum_previsao_inundacao.html` — previsão ao vivo, com o mesmo `event-data` tipado.

Contornos (`contornos_mancha.json`): HAND **0–25 m** a cada 0,1 m (251 níveis),
alinhado ao teto do PNG HAND. O teto antigo de 15 m pinava maio/2024 e jul/2020
na mesma mancha (~1.326 ha). Regenerar com
`python codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py mucum`
(após `gerar_mosaico_mdt.py mucum`).

Geradores:
- `codigo_python/01_previsao_ao_vivo/gerar_pagina_inundacao_mucum.py`
- `codigo_python/01_previsao_ao_vivo/gerar_pagina_previsao_mucum.py`
- `codigo_python/01_previsao_ao_vivo/mucum_eventos_payload.py`

## Validação julho/2020

Cruzamento com Zenodo [10.5281/zenodo.4730371](https://doi.org/10.5281/zenodo.4730371):
ver `assets/data/validacao_zenodo_2020/resumo.md`.
