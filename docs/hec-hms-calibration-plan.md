# Plano de calibração HEC-HMS — Santa Tereza e Muçum

## Escopo

Este documento organiza uma pesquisa de transformação chuva–vazão para
reproduzir eventos históricos e, depois, testar cenários. Não é alerta, ordem de
evacuação, despacho de bombeiros ou validação de rota. Qualquer uso pela Defesa
Civil precisa de validação independente, procedimentos locais e confirmação em
campo.

## Evidência que já foi fechada

- `assets/data/chuvas_horarias.csv` tem 32.904 linhas horárias, sem duplicidade
  de timestamp e sem quebra de cadência no recorte auditado.
- No evento de 01 a 10/09/2023, a coluna `chuva_86472000` reproduz a telemetria
  ANA agregada por hora em 240/240 horas: soma de 224,6 mm e erro médio
  absoluto de 0 mm.
- No mesmo evento, `chuva_02851072` reproduz a telemetria ANA em 240/240
  horas: soma de 390,8 mm e erro médio absoluto de 0 mm.
- A telemetria de `86472000` também contém nível e vazão intrahorários em todo
  o recorte horário candidato; isso oferece um alvo observado para o HMS, mas a
  unidade e a definição do campo `Vazao` ainda precisam ser confirmadas.
- A identidade oficial não é intercambiável: `86472000` é estação
  fluviométrica em Santa Tereza; `02851072` é pluviométrica em Ibiraiaras;
  `A894` e o CEMADEN `432040401A`/ID 8928 são de Serafina Corrêa.
- `86472600` é a estação de Santa Tereza no Rio Taquari, mas não apresentou
  chuva na telemetria do evento auditado.

O detalhe completo, com hashes e respostas brutas, está em
`assets/data/hec_hms_audit/rainfall_station_audit_latest.json`.

## Decisão de modelagem

O primeiro caso deve ser um replay histórico, não um cenário inventado:

1. selecionar o evento 01–10/09/2023;
2. usar os horários observados preservando BRT, unidade e intervalo de
   acumulação;
3. manter 86472000 como candidato de precipitação telemétrica qualificada,
   explicitando que o inventário ANA o classifica como fluviométrico;
4. manter 02851072 como pluviômetro regional de Ibiraiaras, sem renomeá-lo para
   Santa Tereza;
5. excluir do primeiro ajuste as colunas sem observação reconciliada no evento;
6. registrar cada entrada no meteorologic model pelo código oficial, município,
   coordenada e período de validade.

## O que ainda é necessário antes de calibrar

### Modelo físico e dados

- bacias e sub-bacias delimitadas a partir do MDT, com área, declividade,
  comprimento e declividade dos cursos;
- uso do solo, solo, impermeabilização e parâmetros iniciais documentados;
- meteorologic model com pluviômetros selecionados por área de contribuição,
  não por proximidade nominal;
- control specifications com timestep, início/fim e janela de aquecimento;
- observação de vazão no ponto de controle com unidade confirmada; caso se use
  nível convertido em vazão, curva-chave válida e sua vigência;
- inventário de lacunas, relógio e qualidade para cada evento.

### Ajuste e validação

- calibrar somente em eventos com chuva e resposta hidrológica observadas;
- reservar ao menos um evento independente para validação;
- comparar volume, pico, horário do pico, NSE/KGE e PBIAS, sempre com a unidade
  e o intervalo temporal explícitos;
- testar sensibilidade dos parâmetros e reportar faixas, não apenas um número;
- rejeitar resultados que dependam de preencher lacunas com vizinhos ou de
  misturar nível futuro com a entrada disponível no instante da previsão.

## Gate de saída

O HEC-HMS só pode ser marcado como “calibrado para pesquisa” depois de:

- projeto `.hms`/bacia/meteorologia/controle versionado;
- fonte bruta e transformação de cada chuva preservadas;
- curva-chave ou descarga observada auditada;
- calibração e validação reproduzidas por script;
- relatório de incerteza e limitações revisado.

Até esse gate, a classificação correta é “preparação de calibração” e não
“previsão operacional”.
