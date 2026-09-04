# Rede HEC-HMS Taquari–Antas — estado verificável

Este diretório contém a primeira representação conectada da bacia usada no estudo: **Rio das Antas → Santa Tereza → Muçum**. A topologia foi montada a partir da BHO6/ANA, respeitando o sentido `noorigem → nodestino` e usando áreas incrementais em vez de lançar duas bacias diretamente no exutório.

## O que já foi executado

- modelo HEC-HMS 4.13 com três sub-bacias incrementais, dois reaches e Santa Tereza como ponto intermediário;
- execução reproduzível para E19, E22, E24, E27 e E28;
- extração de séries simuladas e observadas no ponto 86510000/Muçum;
- auditoria de terreno com o MDT/SRTM disponível, sem transformar altitude do terreno em seção de calha;
- busca diagnóstica de routing/perdas e busca específica para os eventos que ainda apresentam viés.

## Resultado atual do melhor pacote candidato por evento

Os números abaixo são **replays de pesquisa**, com parâmetros e política de chuva que ainda variam por evento. Eles não são uma calibração comum nem uma autorização operacional.

| Evento | NSE | atraso do pico | erro relativo do pico | leitura |
|---|---:|---:|---:|---|
| E19 | -1,280 | +28 h | 8,88% | forma e tempo ainda não explicados |
| E22 | 0,584 | 0 h | 54,81% | pico subestimado |
| E24 | 0,817 | +2 h | 0,30% | bom ajuste específico; não promovido |
| E27 | 0,823 | +2 h | 13,02% | ajuste intermediário |
| E28 | 0,906 | 0 h | 0,18% | bom ajuste específico; não promovido |

E26 permanece bloqueado porque o pacote de entrada HEC-HMS não está reconciliado nesta rodada.

## Teste de generalização

Foi executada uma busca diagnóstica com **12 candidatos comuns**, sempre usando o mesmo vetor de parâmetros nos cinco eventos e a mesma chuva-proxy de 86472000 nos três incrementos. Todos os 12 candidatos executaram, mas o melhor escore composto alcançou somente NSE médio **−1,023**, NSE mediano **0,484**, atraso médio absoluto **9 h** e erro médio de pico **32,4%**. Portanto, não existe ainda um conjunto comum de parâmetros que possa ser chamado de calibração fechada. O resultado completo está em [`common_search_report.json`](network_common_calibration_search/common_search_report.json).

## Teste de chuva local em Santa Tereza — E28

Foi feita uma segunda rodada mantendo a topologia da bacia e trocando apenas a entrada dos incrementos a jusante: a chuva horária bruta da estação ANA **86472600/Santa Tereza** alimenta `SB_INC_STZ_E28` e `SB_INC_MUCUM_E28`; `SB_ANTAS_E28` continua usando 86472000. A série foi agregada diretamente dos registros ANA, sem interpolar ou preencher horas.

No E28, a busca fina testou **39 candidatos**. A melhor candidata específica foi: perda inicial **2,5 mm**, perda constante **2,0 mm/h**, `Tc` **25 h**, armazenamento **25 h**, fator de recessão **0,80**, razão de vazão inicial **0,003** e `K` **1 h**. O resultado foi **NSE 0,863**, **atraso de 1 h**, **erro de pico 3,57%**, **MAE 503 m³/s** e pico simulado **7.605 m³/s** contra **7.887 m³/s** observado.

Essa candidata é melhor que a primeira espacialização testada, mas ainda é específica do E28. Ela não prova que a mesma parametrização funcione em E19, E22, E24 e E27; também não fecha a validação no ponto intermediário porque a vazão reconciliada de Santa Tereza continua ausente. E24 e E27 têm lacuna interna na chuva bruta local, por isso permanecem no fallback explícito 86472000. O relatório está em [`station_e28_search_report.json`](network_station_e28_calibration_search/station_e28_search_report.json), com a tabela em [`station_e28_search.csv`](network_station_e28_calibration_search/station_e28_search.csv).

## O que ainda falta para chamar de calibração

1. Fechar a série observada de Santa Tereza e sua curva cota–vazão, para que Santa Tereza seja um ponto de validação real e não apenas um nó geométrico.
2. Repetir a busca espacializada em E24 e E27 depois de obter a hora faltante ou uma fonte independente auditada; não preencher a lacuna.
3. Fechar a espacialização da chuva: quais estações representam cada área incremental, pesos, falhas e unidade; E24 tem cinco valores ausentes/negativos na série Thiessen e não recebeu preenchimento silencioso.
4. Obter evidência de calha para os reaches: comprimento validado, seções, nível/cota, declividade hidráulica e escolha justificável entre Muskingum e Muskingum-Cunge.
5. Rodar uma calibração comum em eventos de treino e validar em evento separado. Um ajuste bom em E24/E28 não pode ser promovido enquanto E19/E22/E27 não forem explicados pelo mesmo conjunto de regras.
6. Só depois discutir integração com previsão RNA e, mais adiante, com o HEC-HMS de previsão. Até lá, a saída deve continuar rotulada como pesquisa/replay.

## Visualização

Abra [`network_dashboard/index.html`](network_dashboard/index.html) por um servidor local ou pela página publicada do catálogo. Ela apresenta a rede em diagrama legível, alterna os eventos, mostra as métricas e aponta diretamente para os artefatos auditáveis. O GeoJSON da rede está em [`bho6_taquari_antas_network.geojson`](bho6_taquari_antas_network.geojson).

## Limites importantes

O MDT/SRTM é adequado aqui para uma triagem geométrica do terreno, mas não informa sozinho o fundo da calha, a seção hidráulica, Manning ou o tempo de viagem. Portanto, “zero atraso” pode ser uma métrica de ajuste de um replay e não deve ser apresentado como verdade física. Este estudo não emite alerta, não ordena evacuação e não calcula uma rota operacional.
