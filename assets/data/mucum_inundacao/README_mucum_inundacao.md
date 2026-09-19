# Muçum — mancha e cheias anteriores

## Produção atual (site)

- `mucum_inundacao.html` — **Cheias anteriores** (mesmo molde de Santa Tereza):
  chips de eventos (testes / cheias que transbordaram / referência),
  linha do tempo e mancha HAND no mosaico 2 m (drone + ANADEM).
- `mucum_previsao_inundacao.html` — previsão ao vivo, com o mesmo `event-data` tipado.

Contornos vetoriais (`contornos_mancha.json`): a geração passa a cobrir HAND **0–30 m** a cada 0,1 m (301 níveis), calculada diretamente do HAND em memória. O PNG raster continua limitado a 25 m pela codificação antiga de 8 bits; ele não deve limitar os cenários vetoriais. O teto antigo de 15 m fazia eventos grandes parecerem artificialmente iguais. Regenerar com
`python codigo_python/02_mdt_hand_mancha/gerar_contornos_vetoriais.py mucum`
(após `gerar_mosaico_mdt.py mucum`).

## O que existe acima de 18 m

O plano municipal consultado pela sala de situação tem seu último marco em
18 m. Isso **não significa que o rio tenha máximo físico de 18 m**. Para o
estudo de expansão topográfica, `contornos_extravasamento.json` já contém
contornos HAND atualmente publicados até 25,0 m; a nova geração vetorial foi ampliada para 30,0 m. Os contornos são derivados do MDT mosaico e subtraídos do
contorno HAND 0 (proxy do leito). No recorte atualmente publicado, os valores
de referência são:

| HAND em foco | área adicional relativa ao HAND 0 | área total do contorno HAND |
|---:|---:|---:|
| 18,0 m | 1.427,1 ha | 1.593,2 ha |
| 20,0 m | 1.586,1 ha | 1.752,3 ha |
| 22,0 m | 1.728,8 ha | 1.895,6 ha |
| 25,0 m | 1.878,3 ha | 2.046,0 ha |

Assim, a diferença calculada entre o recorte HAND de 18 m e o de 25 m é de
451,2 ha de área adicional. Essa leitura é uma **expansão relativa à drenagem
mais próxima**, não uma afirmação de que o nível da régua tenha chegado a
25 m. A conversão para cota de estação exige reconciliar o zero da régua, o
datum vertical e a validação hidrodinâmica/campo. O teto de 25 m é apenas o limite da camada vetorial publicada anteriormente, não o máximo físico do rio; a próxima regeneração cobre até 30 m.

O painel de evacuação expõe essa camada ao selecionar `Plano municipal` e
arrastar `Cenário em foco` para além de 18 m. A área exibida continua sendo
pesquisa: não libera rota, abrigo, ponte, capacidade ou ordem de evacuação.

Geradores:
- `codigo_python/01_previsao_ao_vivo/gerar_pagina_inundacao_mucum.py`
- `codigo_python/01_previsao_ao_vivo/gerar_pagina_previsao_mucum.py`
- `codigo_python/01_previsao_ao_vivo/mucum_eventos_payload.py`

## Validação julho/2020

Cruzamento com Zenodo [10.5281/zenodo.4730371](https://doi.org/10.5281/zenodo.4730371):
ver `assets/data/validacao_zenodo_2020/resumo.md`.
