# Muçum — replay HEC-HMS por evento

Pacote de pesquisa para reproduzir eventos históricos no HEC-HMS 4.13. O
objetivo é comparar chuva observada e vazão observada no posto-alvo de Muçum;
não é alerta, previsão operacional, ordem de evacuação, despacho ou validação
de rota.

## Resultado fechado

Foram preservados os três eventos que atenderam ao gate interno desta rodada:

| Evento | Período | Chuva usada | NSE | Pico simulado / observado | Atraso do pico | Erro relativo do pico |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| E24 | nov/2023 | ANA 86472000 | 0,8625 | 11.434,6 / 11.435,0 m³/s | 0 h | 0,0027% |
| E27 | mai/2024 | ANA 86472000 | 0,7853 | 13.499 / 14.525 m³/s | 0 h | 7,07% |
| E28 | jun/2024 | ANA 86472000 | 0,9125 | 7.930 / 7.887 m³/s | -1 h | 0,54% |

O critério interno usado para priorizar resposta foi NSE alto, erro de pico
baixo e atraso absoluto de no máximo duas horas; para a seleção final, foi dada
preferência a atraso de zero ou uma hora. Os números acima são calculados
somente nas horas pareadas e existentes na série observada.

E24 foi refinado em 03/09/2026 com buscas HEC-HMS locais nos parâmetros de
perda, concentração e armazenamento. A seleção atual mantém o pico na mesma
hora da observação e reduz o erro de pico para 0,0027% (11.434,6 contra
11.435,0 m³/s), com NSE 0,8625 e RMSE 1.082,8 m³/s. O NSE ficou um pouco
abaixo da versão anterior, portanto a escolha é explicitamente um compromisso
de pico + horário, não uma afirmação de generalização para outros eventos.
As alternativas e a referência anterior estão em
`E24_timing_peak_tradeoffs.csv`; a versão anterior permanece em
`event_E24_published_20260902/`. O refinamento local que gerou a seleção está
em `E24_loss_timing_refinement_20260903.csv`.

O E27 também recebeu uma nova rodada de auditoria: 60 combinações no entorno
da configuração publicada e testes com a chuva da estação 86510000 e uma
composição entre estações. Nenhuma alternativa superou o replay vigente; a
lacuna oficial de chuva em 02/05/2024 está documentada em
`E27_calibration_audit_20260903.md`.
Também há uma versão navegável para o Pages em
`E27_calibration_audit_20260903.html`.

O teste de generalização com um único conjunto de parâmetros para E24, E27 e
E28 está documentado em
`multi_event_common_calibration_audit_20260903.md` e em sua versão HTML
`multi_event_common_calibration_audit_20260903.html`.

A matriz consolidada dos seis eventos HEC-HMS de Muçum está disponível em
`matriz_calibracao_hec_hms_mucum_20260903.html`.

A auditoria específica da tentativa de eliminar todos os atrasos está em
`zero_lag_calibration_audit_20260903.md` e em sua versão navegável
`zero_lag_calibration_audit_20260903.html`. Ela mostra por que E19 e E26 não
aceitam atraso zero sem destruir a curva e por que o E28 tem um compromisso de
0,5 h no passo de 15 minutos, mas ainda não uma solução sem atraso e com erro
de pico baixo.

## Eventos não fechados

- E19 (mai/2023): melhor busca com NSE 0,2091 e atraso de 3 h. A vazão-alvo já
  subia quando as chuvas pontuais disponíveis ainda estavam zeradas; não foi
  promovido.
- E22 (set/2023): busca focada de 288 combinações chegou a NSE 0,6516,
  RMSE 952,6 m³/s, atraso de 0 h e pico subestimado em 33,73%. Ainda há
  somente 110 horas pareadas e uma interrupção longa no posto-alvo; continua
  como diagnóstico em `diagnostics/E22_partial/`, não foi promovido.
- E26 (abr/2024): NSE 0,3784, apesar de erro de pico de 12,74% e atraso de 2 h.
  A subida observada começa antes de uma chuva coerente nas fontes pontuais;
  não foi promovido.

Os diagnósticos e as séries pareadas desses casos estão em `diagnostics/`.
Eles existem para orientar a próxima aquisição/modelagem, não para serem
apresentados como validação.

## Dados e decisões

- O posto de resposta é `86510000` (Muçum, Rio Taquari).
- `86472000` permanece apenas como fonte pluviométrica candidata/auxiliar;
  não foi usado como posto de resposta de Muçum.
- A área usada foi 16.000 km², conforme o cadastro aberto do SNIRH/ANA para o
  posto-alvo. O MDT local não foi alterado artificialmente para forçar ajuste;
  este pacote ainda representa uma bacia agregada de uma sub-bacia HEC-HMS e
  não uma delimitação hidrologicamente completa derivada do MDT.
- Lacunas de vazão não foram interpoladas. A chuva alternativa do posto
  86472600 e a composição experimental entre fontes foram testadas, mas não
  superaram a fonte selecionada para os eventos fechados.
- Não foi aplicado deslocamento artificial de timestamp para eliminar atraso.

## Reprodução

O script de busca é
`scripts/calibrate_hec_hms_mucum_multi_event.py` e o refinamento fino é
reproduzível com `scripts/run_focused_mucum_search.py --event 24
--profile timing_peak`. Os arquivos HEC-HMS
selecionados estão em `event_E24/`, `event_E27/` e `event_E28/`; cada pasta
também contém `metrics.csv` e `series.csv` com a conferência pareada. A série
DSS compartilhada está em `mucum_target_multi_event.dss`.

Fonte oficial de cadastro da área e identidade: [SNIRH/ANA — Estação
Fluviométrica com Medição de Descarga](https://portal1.snirh.gov.br/server/rest/services/dados_abertos/Estacao_Fluviometrica_com_Medicao_de_Descarga/MapServer/0).

## Limite de uso

Este é um replay histórico de pesquisa. Antes de qualquer uso municipal,
seriam necessários eventos independentes, curva-chave/unidades confirmadas,
chuva espacializada, bacias derivadas do MDT, análise de incerteza, validação
de campo, integração com o plano de contingência e aprovação formal do órgão
responsável.
