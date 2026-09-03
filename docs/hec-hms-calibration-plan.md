# Plano de calibração HEC-HMS — Muçum e Santa Teresa

## Escopo e limite de uso

Este documento registra uma pesquisa de transformação chuva–vazão para
reproduzir eventos históricos. O resultado é um replay científico versionado:
não é alerta, ordem de evacuação, despacho de bombeiros, rota segura ou
capacidade operacional de abrigo. Qualquer uso pela Defesa Civil exige
validação independente, procedimentos locais e confirmação em campo.

## Correção da identificação hidrológica

O primeiro ajuste usava a estação `86472000` como se fosse a resposta de
Muçum. Essa identificação estava errada para o objetivo do modelo. A série de
resposta adotada agora é a estação fluviométrica ANA `86510000` (Muçum, Rio
Taquari), com área de drenagem de 16.000 km² no inventário oficial do SNIRH/ANA
([ficha da estação](https://portal1.snirh.gov.br/server/rest/services/dados_abertos/Estacao_Fluviometrica_com_Medicao_de_Descarga/MapServer/0)).

As demais estações permanecem explicitamente separadas:

- `86472000`: estação auxiliar/candidato de precipitação usado em alguns
  replays; não é o alvo fluviométrico de Muçum.
- `86472600`: estação de Santa Teresa no Rio Taquari, usada como alternativa
  de chuva local quando havia observação disponível.
- `02851072`: pluviômetro regional de Ibiraiaras; não é Santa Teresa.

Não houve preenchimento silencioso de lacunas, interpolação de vizinhos ou
deslocamento artificial de timestamps. Quando a chuva não explicava a
resposta observada, o evento foi mantido como pendente.

## Eventos históricos e resultado atual

Cada evento foi ajustado em projeto HEC-HMS isolado, usando a estação de
resposta `86510000` e área de 16.000 km². A busca inicial avaliou 360
combinações por evento; uma busca fina adicional de 240 combinações foi
executada para E27 e E28. O critério interno de seleção combina NSE, erro
relativo do pico e atraso absoluto do pico de no máximo duas horas, preferindo
zero ou uma hora. Esse critério é de pesquisa e não um padrão operacional.

| Evento | Período | Status | NSE | Pico simulado / observado | Atraso | Erro relativo do pico |
|---|---|---:|---:|---:|---:|---:|
| E19 | maio/2023 | pendente | 0,2091 | 1.267 / 1.408 m³/s | −3 h | 10,02% |
| E22 | setembro/2023 | pendente | 0,5785 | 6.893 / 10.438 m³/s | 0 h | 33,96% |
| E24 | novembro/2023 | replay calibrado | 0,8669 | 13.569 / 11.435 m³/s | −2 h | 18,66% |
| E26 | abril/2024 | pendente | 0,3784 | 1.375 / 1.576 m³/s | +2 h | 12,74% |
| E27 | maio/2024 | replay calibrado | 0,7853 | 13.499 / 14.525 m³/s | 0 h | 7,07% |
| E28 | junho/2024 | replay calibrado | 0,9125 | 7.930 / 7.887 m³/s | −1 h | 0,54% |

### O que “replay calibrado” significa aqui

E24, E27 e E28 têm uma combinação reproduzível de parâmetros que atende ao
gate interno desta pesquisa. O pacote guarda os projetos, séries observadas e
simuladas, parâmetros e métricas por evento em
`assets/data/mucum_eventwise_replay_calibrated/`.

E19, E22 e E26 não foram promovidos. Em E19, a vazão observada sobe enquanto
as chuvas disponíveis permanecem nulas no início do recorte; o conjunto atual
não identifica essa resposta. E22 tem uma interrupção prolongada na série de
resposta durante o evento, além de subestimar o pico. E26 é curto e apresenta
desalinhamento entre chuva disponível e resposta. Esses eventos continuam no
pacote como diagnóstico para a próxima rodada, não como calibração encerrada.

## Limite do MDT e do modelo atual

O modelo atual é agregado, de uma bacia, e não uma delimitação hidrológica
completa derivada do MDT. Portanto, a calibração não valida por si só manchas
de inundação, profundidades, casas atingidas, rotas, abrigos ou ordem de
evacuação. O MDT deve entrar na próxima etapa com cobertura comprovada, sistema
de referência, resolução, preenchimento hidrológico, área de contribuição,
rede de drenagem e validação espacial documentados.

## Reprodução

O script principal é
`scripts/calibrate_hec_hms_mucum_multi_event.py`. Os projetos e o DSS-alvo
foram gerados com HEC-HMS 4.13; os caminhos, hashes e status estão em
`assets/data/mucum_eventwise_replay_calibrated/eventwise_manifest.json`.

Antes de qualquer promoção futura, ainda é necessário:

- confirmar a semântica, unidade, curva-chave e vigência da vazão observada;
- revisar cobertura, fuso, lacunas e intervalo de acumulação de cada chuva;
- delimitar e parametrizar sub-bacias com o MDT real;
- reservar eventos independentes para validação;
- comparar volume, pico, horário do pico, NSE/KGE e PBIAS com incerteza;
- testar em campo e somente então discutir integração com previsão ou resposta.

O estado correto neste commit é `pesquisa/replay calibrado por evento`, não
`previsão operacional`.
