# Auditoria de calibração do E27 · Muçum

Atualização de 03/09/2026. Esta nota registra as buscas executadas no HEC-HMS
4.13 para tentar reduzir o erro do evento E27 (maio/2024), sem deslocar
timestamps, interpolar vizinhos ou preencher chuva ausente com zero.

## Referência atualmente publicada

O replay publicado usa a chuva horária da ANA 86472000 e compara com a vazão
observada no posto-alvo ANA 86510000. O modelo é uma bacia agregada de 16.000
km²; esta configuração não é uma delineação hidrológica completa derivada do
MDT.

| Fonte e configuração | Horas pareadas | NSE | Pico simulado / observado (m³/s) | Atraso | Erro do pico |
| --- | ---: | ---: | ---: | ---: | ---: |
| ANA 86472000 · configuração publicada | 245 | 0,7853 | 13.498,8 / 14.525,2 | 0 h | 7,066% |
| ANA 86472000 · refinamento local, 60 combinações | 245 | 0,7853 | 13.498,8 / 14.525,2 | 0 h | 7,066% |
| ANA 86510000 · melhor de 72 combinações | 73 | 0,6541 | 16.038,1 / 14.525,2 | +4 h | 10,415% |
| Composta 86510000 + fallback 86472000 · 72 combinações | 245 | 0,4464 | 16.217,4 / 14.525,2 | +1 h | 11,650% |

## O que foi verificado

1. A busca refinada no entorno do E27 variou perda constante, tempo de
   concentração e armazenamento, mantendo os demais parâmetros e o horário
   produzido pelo HEC-HMS. Nenhum dos 60 candidatos superou a configuração
   publicada.
2. A chuva direta da estação 86510000 foi testada. A fonte oficial da ANA
   respondeu normalmente, mas não possui chuva em 02/05/2024 às 17:00,
   17:15, 17:30 e 17:45. Vazão e nível existem nesse intervalo. Como não é
   permitido inventar a chuva, o fluxo de calibração encerra a entrada antes
   da lacuna; por isso a comparação tem somente 73 horas pareadas.
3. A composição que usa a 86472000 apenas para atravessar essa lacuna recupera
   245 horas, mas piora NSE, pico e erro. Ela permanece somente como teste de
   sensibilidade, não como dado observado oficial.
4. Uma rodada antiga com a estação local 86472600 exibiu NSE alto em apenas 37
   horas pareadas e atraso de 9 horas, usando outro DSS e outra área de bacia.
   Esse número não é comparável ao replay publicado e não foi promovido.

## Decisão científica

O E27 permanece como replay calibrado de pesquisa, com a chuva 86472000,
NSE 0,7853, atraso zero e erro de pico 7,066%. Não foi aceito um candidato que
melhorasse somente o pico sacrificando a curva completa, nem uma fonte com
lacuna ou um fallback espacial tratado como observação.

O próximo avanço necessário é obter uma série pluviométrica contínua e
reconciliada para a bacia — ou um modelo distribuído com várias estações — e
então repetir a validação em eventos que não tenham sido usados para escolher
os parâmetros. Esta nota não autoriza alerta, rota, evacuação, despacho ou
capacidade de abrigo.

Fonte consultada para a lacuna: serviço oficial ANA DadosHidrometeorológicos,
estação 86510000, consulta de 02–03/05/2024.
