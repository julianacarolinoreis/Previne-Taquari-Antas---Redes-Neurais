# Rotas de fuga / evacuação — Etapa 2 (roteamento por ruas)

Roteamento **real por ruas** (OpenStreetMap + caminho mínimo Dijkstra) de cada
casa até o ponto de encontro/abrigo mais próximo, **evitando a área que alaga**.
Cobre **Santa Tereza** e **Muçum** com um gerador único.

## Ordem de execução

```bash
# 1. Cota de alagamento por pixel (uma vez por MDT; ~1 min por cidade)
python codigo_python/09_rota_fuga/gerar_cota_alaga.py

# 2. Rotas (por cidade e fonte de nível)
python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade mucum --fonte cenario
python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade mucum --fonte live
python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade santa_tereza --fonte cenario
python codigo_python/09_rota_fuga/gerar_rota_fuga_ruas.py --cidade santa_tereza --fonte live

# 3. Camadas derivadas (leem o JSON do cenário)
python codigo_python/09_rota_fuga/gerar_painel.py --cidade mucum
python codigo_python/09_rota_fuga/gerar_mapa_margem.py --cidade mucum
python codigo_python/09_rota_fuga/gerar_mapa_impacto.py --cidade mucum
python codigo_python/09_rota_fuga/gerar_estudo_caso_mucum.py
python codigo_python/09_rota_fuga/gerar_estudo_caso_slides.py
python codigo_python/09_rota_fuga/gerar_fila_cidade.py          # depois dos slides (lê fila_evacuacao_mucum.json)
python codigo_python/09_rota_fuga/gerar_comparacao_osm_ibge.py
```

`--fonte`: `live` (pico entre atual/2h/4h da RNA; telemetria com mais de 3 h
é marcada como desatualizada no JSON e no mapa), `cenario` (cota oficial de
inundação: régua 18 m em Muçum, 15 m em Santa Tereza), `fixo` (`--nivel` em
HAND). `--tempo-max` (padrão 30 min): limite de caminhada do idoso.

Saídas: `assets/data/rota_fuga/rota_fuga_ruas_<cidade>*.json` +
`<cidade>_rota_fuga_ruas*.html` (toque numa casa → a rota dela).

## Método

### Área que alaga
`gerar_cota_alaga.py` grava `cota_alaga_<cidade>.tif`: para cada pixel do
mosaico 2 m, o menor nível HAND (0 a 25 m, passo 0,1 m) em que ele alaga
**ligado ao rio** — o mesmo critério de `contornos_mancha.json`, que para em
15 m (abaixo do recorde de 2024 em Santa Tereza, HAND ~21,8 m). Nas casas,
o raster concorda com os contornos (a 13 m, 77 casas em comum; os contornos
suavizados pegam algumas a mais).

Cada trecho de rua guarda o perfil desse raster a cada 4 m. No nível L, a
**fração** do trecho abaixo de L entra no custo: `tempo × (1 + 60 × fração)`.
Ponte e túnel não usam o perfil (o rio embaixo não alaga o tabuleiro): alagam
quando uma cabeceira alaga. Abrigo que alaga no nível sai do roteamento.

O mapa mostra os contornos do site até 15 m; acima disso, o próprio raster.

### Origem casa a casa
A origem é cada edificação do OpenStreetMap (`osm_casas_<cidade>.json`),
ligada pela perpendicular à via mais próxima (até 80 m). A rede inclui
calçadões, caminhos e escadarias, baixada num recorte 0,015° maior que o das
casas (`osm_vias_pe_ampla_<cidade>.json`). A cota de alagamento da casa é a
menor entre os vértices e o ponto interno da edificação.

Não entram como casa: tags não residenciais (indústria, galpão, comércio,
escola, igreja, estação…) e polígonos com menos de 20 m² ou mais de 1000 m²
(Curtume CBR, hospital e pavilhões em Muçum; aviários em Santa Tereza). Ponte
e túnel não recebem ligação de casa.

Situação de cada casa no nível de projeto:

| Situação | Critério |
|---|---|
| `ok` | rota até o abrigo dentro do tempo, ou casa seca com rota seca |
| `excede` | casa na água e rota acima de `--tempo-max` |
| `ilhada` | casa seca, mas a rota cruza área que alaga (qualquer trecho: 40 cm de água já derrubam um idoso) |
| `sem_rota` | sem via a 80 m, ou ligada a um trecho de rede sem caminho até abrigo oficial |

Trechos de rede desconectados da rede principal (50+ nós) ficam no grafo se
alguma casa depende deles — é o caso da outra margem em Santa Tereza (614
nós, 48 casas). Abrigos sempre se ligam à rede principal.

### Tempo de caminhada com declive
r.walk do GRASS (Naismith + Langmuir) com a cota do MDT 2 m em cada nó,
escalado para um **idoso a 0,9 m/s no plano**. Descida limitada a 1,1 m/s,
rampa a ±35 %, escadaria ×1,5; pontes interpolam a cota entre as cabeceiras.
Grafo direcionado: subir e descer a mesma rua têm tempos diferentes.

### Rotas por nível
Além do nível de projeto, o JSON traz em `niveis` as rotas recalculadas de
HAND 0 a 25 m (passo 1 m): próximo nó, abrigo e tempo por nó; nó, tempo e
água por casa. O painel usa o nível do slider (arredondado para cima).

### Pontos de encontro candidatos
Três tipos de casa pedem outro ponto de encontro: na água e acima de
`--tempo-max` (`tempo`), ligada a um trecho de rede sem caminho até abrigo
oficial (`sem_rota`) e ilhada. O local candidato é um nó que só alaga **2 m
acima** do nível de projeto, em rampa de até **15 %**.

A escolha é por **cobertura gulosa**: um local atende a casa se ela chega lá
em até `--tempo-max` (idoso) e se ele ganha do abrigo oficial no custo com
penalidade de água (senão o roteamento continuaria mandando a casa ao
oficial); para a ilhada, sem cruzar água. A cada passo entra
o local que atende mais casas na água ou sem rota (mínimo 3); depois, os que
atendem mais ilhadas (mínimo 5); até 8 locais.

O JSON traz por candidato os motivos, o pior tempo antes/depois, a cota em
que ele alaga, a rampa e a **demanda**, além da rota até ele (`rota_cand`) e,
por casa, `cand`, `tempo_cand_s` e `no_cand`. **Capacidade não é avaliada** —
são sugestões para a Defesa Civil, não abrigos oficiais.

### Demanda por destino
Cada casa recebe `pessoas`: a população da grade IBGE 2022 (domicílios
ocupados) dividida entre as casas OSM da célula. Casa fora das células com
moradores fica `null` (não residencial ou posterior ao Censo — 214 em Muçum,
65 em Santa Tereza) e conta 0. Por abrigo e candidato, `demanda` soma as
casas na água que vão até ele e, nos candidatos, as ilhadas e sem rota.

### Cenários oficiais (outubro/2026)

| | Muçum 18 m | Santa Tereza 15 m |
|---|---|---|
| Casas (OSM) | 1937 | 565 |
| HAND do cenário | 13,0 m | 13,4 m |
| Na área que alaga | 115 | 18 |
| Na água acima de 30 min | 47 → **0** | 14 → **0** |
| Sem caminho até abrigo oficial (outra margem) | 0 | 46 → **0** |
| Casas secas ilhadas | 194 → **62** | 425 → **27** |
| Locais candidatos | 4 | 5 |

(antes → com candidatos; ilhada = a rota até o abrigo oficial cruza qualquer
trecho que alaga. As que restam não têm caminho seco até nenhum local alto
fora da água: abrigar-se no próprio local ou sair antes.)

Santa Tereza usa o HAND LiDAR do `main` (`contornos_mancha.json`, 0–25 m) com
a calibração de campo régua 1,60 m = HAND 0; a cota de alagamento é
rasterizada desses contornos (`gerar_cota_alaga.py`, `cota_de_contornos`). O
Ginásio (único abrigo) só alaga em HAND 21,3 m (régua 22,9 m), mas a via até
ele alaga a partir de HAND 13,0 m perto de (−29,1726, −51,7237): ~35 m de
rua com ~40 cm de água no cenário deixam 361 casas ilhadas, todas atendidas
por um candidato do lado seco. A outra margem é ligada ao centro só por uma
lacuna de ~190 m perto de (−29,1794, −51,7344) que cruza o canal do rio
(ponte ou balsa), não rua faltando; o candidato de lá atende as 46 casas.

Muçum: o Salão José Marcolin alaga a partir de HAND 18 m (régua 23 m) e o
CTG Sentinela a partir de 20,6 m.

## Camadas derivadas
- `gerar_painel.py` — **painel casa a casa** (`<cidade>_painel_casas.html`) com abas
  Rotas · Margem · Quem sai; em Quem sai cada casa é um ponto colorido pela situação.
  Não substitui o `<cidade>_painel_evacuacao.html` (grade IBGE, robô de 30 m).
- `gerar_mapa_margem.py`, `gerar_mapa_impacto.py` — o mesmo painel com uma aba só.
- `gerar_estudo_caso_<cidade>.py` — "a água chega nesta casa em 4h → rota → margem".
- `gerar_estudo_caso_slides.py` — vídeo/slides de Muçum, recalculando as rotas por nível.
- `gerar_fila_cidade.py` — fila por célula IBGE (`fila_cidade_<cidade>.json`):
  cota da casa mais baixa da célula e p90 do tempo a pé.

Todas leem o JSON do **cenário oficial** de cada cidade.

**Margem de fuga** (painel): quanto tempo a pessoa ainda pode esperar para
sair. É o mínimo, ao longo da rota até o abrigo no nível do slider, de
`tempo até a água chegar no ponto − tempo do idoso para chegar nele`. Se a
rota já cruza água no nível, a casa é "ilhada".

**Quem sai**: a população de cada célula IBGE é dividida entre as casas OSM
dentro dela, cada casa com sua situação; célula sem casa mapeada usa o nó de
via mais próximo do centroide.

O slider mostra o nível em **régua** (HAND entre parênteses). A paleta separa
urgente (escuro) de folgado (claro) também para daltônicos; no celular o
painel começa recolhido.

## Cobertura OSM × IBGE
`gerar_comparacao_osm_ibge.py` conta, por célula da grade estatística, as
edificações OSM usadas como casa e compara com os domicílios (`dom`).
Saída em `output/relatorios/comparacao_osm_ibge/`.

| | Muçum | Santa Tereza |
|---|---|---|
| Domicílios IBGE no município | 1782 | 630 |
| Dentro do recorte das casas | 1441 | 267 |
| Edificações OSM nesse recorte / domicílios | 1,19 | 1,85 |
| Fora ou parcialmente fora do recorte | 341 | 363 |
| … em células que tocam a mancha | 112 | 73 |
| … ponderando pela área alagada da célula | ~32 | ~19 |

Dentro do recorte, nenhuma célula com 5+ domicílios tem menos da metade das
edificações esperadas. Em Muçum, o excesso de edificações bate com galpões e
anexos (menos de 30 m² ou mais de 300 m²); em Santa Tereza, não — quase tudo é
só `building=yes` e o filtro residencial não separa nada. Fora do recorte
ficam domicílios ribeirinhos e rurais que o modelo ainda não enxerga.

## Pendências conhecidas
- **Referência do HAND**: o talvegue do mosaico tem poços e degraus; trocar
  pela linha central do rio e um perfil de linha d'água suavizado muda muito a
  contagem de casas atingidas. Exige refazer `02_mdt_hand_mancha`.
- **Zero da régua**: ±1 m no zero leva as casas na água de Muçum de 62 a 330.
  Calibrar com as manchas e marcas das cheias de 2023/2024.
- Capacidade dos abrigos e dos candidatos: a demanda já sai no JSON, falta a
  capacidade para comparar.
- A fila (`fila_cidade_*.json` + `assets/previsao_fila.js`) ainda não está nas
  páginas de previsão ao vivo: primeiro validar o painel de evacuação. Ao
  ligar, `gerar_pagina_previsao_mucum.py` (que copia a página de Santa Tereza)
  precisa trocar também o bloco da fila para Muçum (JSON, replayKey, links).

## Abrigos / pontos de encontro
`assets/data/servicos/abrigos.geojson` (filtrado por `municipio`):
- **Santa Tereza**: Ginásio de Esportes (geocodificado do link da Defesa Civil).
- **Muçum**: 6 pontos de encontro oficiais do **Plano de Contingência de Muçum 2025**
  (seção 8.3): Hospital NSa Aparecida, Igreja Matriz da Purificação, Salão Cidade
  Alta, Salão José Marcolin, Posto Sander, CTG Sentinela — com coordenadas oficiais.

## Calibração régua ↔ HAND — Muçum

O `zero_regua_m` de Muçum é **5,0 m** (500 cm na régua **86510000**): o mesmo
bankfull operacional já usado na mancha (`gerar_mancha_mucum.py`), na RNA ao
vivo (`gerar_previsao_ao_vivo_mucum.py`) e em `mucum_inundacao.html`. Coincide
com a **cota de atenção** do Plano de Contingência.

Conversão: `HAND = régua_m − 5`.

| Alarme oficial (régua) | HAND |
|---|---|
| Atenção **5 m** | 0 m (sai da calha) |
| Alerta **10 m** | 5 m |
| Inundação **18 m** | 13 m |

O cenário (`--fonte cenario`) ancora na cota de **inundação 18 m**. O ao vivo
(`--fonte live`) lê `previsao_ao_vivo_mucum.json`; rio abaixo de 5 m → sem mancha.

Valor **operacional**, não o RN nivelado do SGB/ANA. Definitivo: amarrar a cota
oficial do zero da régua ao mesmo datum do mosaico 2 m
(`codigo_python/04_zero_regua/consulta_estacao_ana.py 86510000`).

Santa Tereza usa a calibração de campo **régua 1,60 m = HAND 0** no rio
principal (régua_m − 1,6 = HAND), válida só sobre o HAND LiDAR de
`gerar_hand_lidar_santa_tereza.py`. O cenário usa a inundação oficial de 15 m
(HAND 13,4 m). Antes: bankfull 4 m sobre o mosaico 2 m (HAND 11 m).

## Fontes
- Plano de Contingência do Município de Muçum 2025 (Defesa Civil / Prefeitura) —
  abrigos, pontos de encontro, cotas oficiais, rotas de fuga oficiais (seção 8.4).
- Franco, G. G. — notebook de roteamento de evacuação, Zenodo,
  [doi:10.5281/zenodo.20402230](https://doi.org/10.5281/zenodo.20402230) (CC-BY 4.0):
  origem casa a casa ligada à rua por perpendicular, tempo de caminhada pelo
  r.walk e ponto de encontro calculado a partir das casas, fora da mancha
  (aqui adaptado como candidatos por cobertura gulosa, ao lado dos abrigos oficiais).
- © OpenStreetMap contributors (ODbL) — vias e edificações; IBGE — grade estatística.
