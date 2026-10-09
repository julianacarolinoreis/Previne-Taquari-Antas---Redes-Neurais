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
| LC2018 | 20/06–15/11/2018 | calibração | X03–X09 |
| LC2019 | 05/05–20/11/2019 | calibração | X12, X13, X16–X18 |
| LC2020 | 05/06–30/09/2020 | calibração | X19–X22 |
| LC2021 | 05/01–10/07/2021 | calibração | X23–X25 |
| LV2022 | 05/04–15/07/2022 | validação | X27–X31 |
| LV2025 | 01/06–25/11/2025 | validação | E27, E28, X61, X65 |
| LV2026 | 20/05–15/09/2026 | validação | X67, E36, E37, X71, X73 |

Os primeiros 20 dias de cada janela são aquecimento e ficam fora das métricas. A janela começa no q0 observado,
como as de evento.

## Forçamento (`dados/forcamento_v3b/L*.json.gz`)

O caminho é o mesmo do forcamento_v3b: o `forcamento_v3.main` original (todos os postos, cobertura ≥ 50%, QC
iterativo pelos 3 vizinhos, teste de defasagem, IDW p=2 por hora), com o CEMADEN do zip bruto e o INMET com a hora
corrigida. A telemetria ANA vem do mesmo serviço (DadosHidrometeorologicos), para os 130 códigos ANA que o v3
considera, baixada em pedaços de 31 dias.

A janela longa é processada em blocos de 15 dias e os blocos são concatenados. Cada bloco é uma janela do
`forcamento_v3.main`, com a sua cobertura e o seu QC, como as janelas de evento de 6–24 dias; o IDW é hora a hora e
sem estado. Com a janela inteira de uma vez, a regra de cobertura de 50% em 5 meses tirava postos com falhas longas
que entram nas janelas de evento: a chuva ficava até 12% menor em X20181028. Com os blocos, a chuva média da bacia
fica entre 0,94 e 1,07 do v3b em 11 das 12 janelas de evento de calibração sobrepostas, com correlação horária
≥ 0,994. A exceção é X20200626 (0,90; correlação 0,94): no bloco de 05–19/07/2020, o QC tirou por excesso os
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
