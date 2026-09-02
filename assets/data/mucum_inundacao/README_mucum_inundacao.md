# Muçum — mancha e cheias anteriores

## Produção atual (site)

- `mucum_inundacao.html` — **Cheias anteriores** (mesmo molde de Santa Tereza):
  chips de eventos (testes / cheias que transbordaram / referência),
  linha do tempo e mancha HAND no mosaico 2 m (drone + ANADEM).
- `mucum_previsao_inundacao.html` — previsão ao vivo, com o mesmo `event-data` tipado.

Contornos (`contornos_mancha.json`): HAND **0–25 m** a cada 0,1 m (251 níveis),
alinhado ao teto do PNG HAND. Regenerar com
`python codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py mucum`
(após `gerar_mosaico_mdt.py mucum`).

## Validação com cheia de julho/2020

Cruzamento com o banco Zenodo [10.5281/zenodo.4730371](https://doi.org/10.5281/zenodo.4730371)
(Giordani, Fan & Alves — UFRGS/HGE): ver
`assets/data/validacao_zenodo_2020/resumo.md`.
