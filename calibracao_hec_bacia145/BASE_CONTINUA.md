# Base-contínua (bacia 145, HEC-HMS 4.13): termo de vazão de base em janelas longas

Pesquisa; nada aqui é alerta operacional nem muda o padrão do sistema.

## Por quê

Toda janela de evento começa no q0 observado, então o J de eventos não vê a base que o modelo sustenta sozinho.
Numa rodada contínua, o vo-val-c008 e o md-val2-c002 chegam ao fim das recessões com cerca de 0,3 do observado
(LJJ, Muçum, Encantado). A causa é que a recarga do GW-2 (o reservatório lento) é só ~4–7% da percolação.

## Janelas longas (catálogo, `"longa": papel`)

Os papéis estão congelados por bloco de tempo. 2023–2024 fica fora porque a calibração (E4, E5, E12) e a validação
se intercalam no mesmo mês. O teste começa em 18/09/2026 06h, e LV2026 termina em 15/09.

| janela | período | papel | eventos dentro |
|---|---|---|---|
| LC2018 | 21/06–15/11/2018 | calibração | X03–X09 |
| LC2019 | 13/06–20/11/2019 | calibração | X16–X18 |
| LC2020 | 05/06–30/09/2020 | calibração | X19–X22 |
| LC2021 | 05/01–10/07/2021 | calibração | X23–X25 |
| LV2022 | 20/04–15/07/2022 | validação | X27–X31 |
| LV2025 | 14/06–25/11/2025 | validação | E27, E28, X61, X65 |
| LV2026 | 20/05–15/09/2026 | validação | X67, E36, E37, X71, X73 |

Os primeiros 20 dias de cada janela são aquecimento e ficam fora das métricas. A janela começa no q0 observado,
como as de evento, mas sempre num dia de vazão baixa em Muçum (perto do percentil 20 da janela). O estoque inicial do
GW-2 sai do q0; começar na descida de uma cheia (LC2019 com 518 m³/s, LV2022 com 802 m³/s) deixaria a busca
sustentar a base com a condição inicial (k2 alto) em vez da recarga.

## Forçamento (`dados/forcamento_v3b/L*.json.gz`)

O caminho é o mesmo do forcamento_v3b: o `forcamento_v3.main` original (todos os postos, cobertura ≥ 50%, QC
iterativo pelos 3 vizinhos, teste de defasagem, IDW p=2 por hora), com o CEMADEN do zip bruto e o INMET com a hora
corrigida. A telemetria ANA vem do mesmo serviço (DadosHidrometeorologicos), para os 130 códigos ANA que o v3
considera, baixada em pedaços de 31 dias.

A janela longa é processada em blocos de 15 dias e os blocos são concatenados. Cada bloco é uma janela do
`forcamento_v3.main`, com a sua cobertura e o seu QC, como as janelas de evento de 6–24 dias; o IDW é hora a hora e
sem estado. Com a janela inteira de uma vez, a regra de cobertura de 50% em 5 meses tirava postos com falhas longas
que entram nas janelas de evento: a chuva ficava até 12% menor em X20181028. Com os blocos, a chuva média da bacia
fica entre 0,94 e 1,05 do v3b em 10 das 11 janelas de evento de calibração sobrepostas (correlação horária ≥ 0,994)
e entre 0,98 e 1,06 nas 10 de validação (correlação ≥ 0,998). A exceção é X20200626 (0,90; correlação 0,94): no bloco de 05–19/07/2020, o QC tirou por excesso os
pluviômetros das três UHEs e o INMET A813, que entram na janela do evento. É o mesmo QC numa janela diferente; o J de
eventos continua no v3b das janelas de evento, e as longas só entram no termo de base. O código de geração
fica fora do repositório (`_analise_base/`: `baixar_longas.py`, `forcamento_longas.py`, `empacotar.py`), como o do v3b.

Os observados (`dados/observados/<cod>_L*.csv.gz`) são a telemetria dos 10 controles, no formato de sempre. Em
2018–2021 as UHEs (Castro Alves, Monte Claro, 14 de Julho) só têm nível, e Tainhas, Estrela, Passo Carreiro e Linha
Colombo não têm telemetria, como nas janelas de evento desses anos.

## Termo de base (`codigo/base_continua.py`)

Por controle do objetivo e janela longa, nas médias diárias (elas também apagam a oscilação diária das UHEs):

- **recessões**: trechos de ≥ 6 dias em que a média diária observada não sobe (tolerância de 2%), sem os 2 primeiros
  dias de cada trecho;
- **vol**: |ln(soma sim / soma obs)| nos dias de recessão, dividido por ln 1,2;
- **dia**: média de |ln(sim/obs)| diário nos dias de recessão, dividida por ln 1,3;
- **fim**: média, por recessão, de |ln(sim/obs)| nos 2 últimos dias, dividida por ln 1,2;
- **pen**: média dos três termos (vale 1 no limite), limitada a 20.

`J_base` é a média de pen nas janelas longas de calibração; `J_base_val`, a média nas de validação.
`nuvem_agregar.py` grava `J_base`, `J_base_val`, `J_bc = J + J_base` e `metricas_base`. O J de eventos não muda.
`nuvem_lote.py` grava a vazão das janelas longas em médias horárias, para o artefato não passar de centenas de MB.

## Família `lrdcb` (`estrutura_v3.PARAMS_LRDCB`)

É a lrdcr mais o k2 regional (`xk2_T`, `xk2_B`, de 1/3 a 3), com o k2 efetivo limitado a 150–6000 h (6 a 250 dias).
Os demais parâmetros que governam a base continuam livres nas faixas físicas de antes: k2 (150–4000 h), fb (0,3–1;
a perda profunda é 1 − fb), p1 (0,02–0,98), s1 e perc, mais os multiplicadores regionais de fb e perc.
Multiplicadores = 1 reproduzem a lrdcr.

## Resultado (out/2026)

Busca evolutiva a partir de vo-rp5-c041/vo-val-c008, com duas linhas de mesmo orçamento e mesma semente-base: uma
com o termo de base no objetivo e um controle só de eventos. O candidato de cada linha é o primeiro pelo objetivo de
calibração; a validação não escolhe nada, e o teste (X20260918, X75, X76) não entrou.

Primeira rodada, com objetivo J (linhas B = J + J_base, C = J): as duas linhas melhoram eventos pequenos e pioram
médios e grandes. O controle também piora na validação (J val 6,04 contra 5,84 do c008), então o defeito é o
objetivo J, não o termo de base. Mexer só nos parâmetros de base em volta do c008 (bc-bs0) não serve: o melhor por
J + J_base tem J val 8,94, porque os parâmetros de evento precisam se reajustar junto.

Segunda rodada, com objetivo J_pico (o critério da linhagem do c008: linha D = J_pico + J_base, controle E = J_pico):

| candidato | J cal | J val | J_pico val | J_base val | fim de recessão LV (Muçum / Encantado) | grandes val: pico Muçum / Encantado |
|---|---|---|---|---|---|---|
| vo-val-c008 | 6,112 | 5,838 | 6,039 | 3,11 | 0,54 / 0,38 | −26% / −31% |
| D: bc-B5-c004 | 6,134 | 5,715 | 6,222 | 0,99 | 1,05 / 1,21 | −30% / −33% |
| E: bc-E3-c014 | 5,830 | 5,729 | 6,067 | 1,74 | 0,70 / 0,66 | −26% / −31% |

Com o termo de base, o fim das recessões nas janelas longas passa de 0,3–0,5 para 0,9–1,2 do observado, e o volume
nas recessões de validação vai de 0,58–0,80 para 0,88–1,16. O J val não piora; o J_pico val sobe 0,16–0,18, e o
pico das cheias grandes fica 2–4 pontos mais baixo. Na calibração, bc-D1-c002 empata com bc-B5-c004 no objetivo
(6,785 contra 6,784). Os parâmetros dos três estão em `rodadas/bc_candidatos.json`. Nenhum vira padrão sem decisão
explícita; para operar, o `-sistema` precisaria do xk2 regional da família lrdcb e de um τ(h) próprio.
