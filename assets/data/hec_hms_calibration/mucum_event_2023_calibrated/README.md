# HEC-HMS — Muçum / evento de setembro de 2023

## Estado

Calibração executada no HEC-HMS 4.13 para um evento histórico único, com busca determinística coarse + focal e refinamento amostrado. Foram 360 combinações válidas, além da execução independente de validação do conjunto selecionado.

O resultado é uma calibração de pesquisa/replay. Não é uma previsão operacional, não emite alerta e não autoriza evacuação, despacho de equipes ou definição de capacidade de abrigo.

## Conjunto selecionado

| Parâmetro | Valor | Unidade |
| --- | ---: | --- |
| Initial Loss | 2,5 | mm |
| Constant Loss Rate | 1,0 | mm/h |
| Time of Concentration (Clark) | 45 | min |
| Storage Coefficient (Clark) | 5 | min |
| Recession Factor | 0,70 | adimensional |
| Initial Flow/Area Ratio | 0,005 | adimensional |
| Área da bacia | 13.000 | km² |

## Resultado na série pareada

| Indicador | Valor |
| --- | ---: |
| Observações pareadas | 239 horas |
| MAE | 1.173,27 m³/s |
| RMSE | 1.776,48 m³/s |
| NSE | 0,7717 |
| Pico observado | 15.447,88 m³/s |
| Pico simulado | 10.486,00 m³/s |
| Índice do pico observado | 93 |
| Índice do pico simulado | 96 |

Os indicadores foram recalculados na execução independente em `calibrated_metrics.csv`, comparando a vazão observada e a vazão simulada gravadas pelo próprio HEC-HMS no DSS de resultados.

## Fontes e limites conhecidos

- Chuva: série horária candidata de `86472000`, campo `Chuva`, no intervalo de 01–10/09/2023.
- Resposta: série horária derivada de `Vazao` da telemetria de `86472000`.
- A interpretação de `Vazao` como m³/s é a hipótese usada no replay e ainda deve ser confirmada pela documentação/semântica definitiva da série ANA.
- A identificação da estação 86472000 e a área declarada de 13.000 km² vêm do inventário ANA; o campo pluviométrico dessa estação não está marcado no inventário, portanto a chuva permanece uma série candidata, não uma verdade observacional fechada para toda a bacia.
- O MDT/FAPERGS foi auditado como referência de terreno local em resolução de 1 m e EPSG:31982. Os derivados recortados não cobrem sozinhos a bacia de 13.000 km²; por isso não foram usados para inventar uma delimitação de bacia completa.
- O ajuste é de um único evento e não substitui validação em outros eventos, análise de sensibilidade, confirmação de unidades/fuso e avaliação independente.

## Arquivos

- `bacia_86472000.basin`: parâmetros selecionados.
- `mucum_event_2023.hms`, `chuva_86472000.met`, `mucum_event_2023.gage`, `evento_2023-09.control`: projeto HEC-HMS.
- `mucum_event_2023.dss`: entrada observada/candidata usada no replay.
- `Calibracao.dss`: saída HEC-HMS da execução selecionada.
- `calibrated_series.csv`: pares observado/simulado.
- `calibrated_metrics.csv`: métricas recalculadas.
- `../mucum_event_2023/calibration_search/`: trilha das 360 combinações pesquisadas e seus resultados coarse/focal/refine.

## Reexecução

Com o HEC-HMS 4.13 portátil instalado, executar na pasta do HEC-HMS:

```text
HEC-HMS.cmd -s D:/PREVINE/worktrees/previne-catalogo-pesquisas-20260828/assets/data/hec_hms_calibration/mucum_event_2023_calibrated/validate_calibrated.script
```

O script recompõe `Calibracao.dss`, `calibrated_series.csv` e `calibrated_metrics.csv`.
