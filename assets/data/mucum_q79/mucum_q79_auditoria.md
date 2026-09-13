# Auditoria independente derivada — fila 79 Muçum

Escopo: leitura de 20 XLSX, 20 MAT, marcadores `.done`, CSV de métricas e fontes originais do manifesto. Nenhum arquivo oficial foi alterado.

## Resultado estrutural

- Modelos analisados: 20 (5 por horizonte).
- Cada modelo: MAT + XLSX + `.done`; CSV consolidado com 20 modelos.
- `NIVEL_FUTURO` contra a fonte no horário futuro: 0 ausências, 0 divergências de valor e 0 alvos em outro evento.
- COD_SEQUENCIAL/data-hora: 0 divergências; duplicidades: 0.
- Os eventos da fila têm pelo menos 35 linhas no recorte; não apareceu evento de quatro linhas.
- A reconciliação MAT–XLSX–CSV das métricas agregadas é registrada em `model_metrics_recalculated_q79.csv`; `RECONCILIACAO_OK` indica igualdade numérica até 1e-8.

## Melhores por PERS de teste recalculado

| Horizonte | Modelo | PERS teste | MAE teste (cm) | Média simples de PERS/evento |
|---:|---|---:|---:|---:|
| 2h | `002_MUC_H02_BASE_COMPLETA_Q58_V15_RISE_GATE_NH32_M00_S02` | 0.949209 | 9.257 | 0.900237 |
| 4h | `006_MUC_H04_DOWNLOAD_015_V15_RISE_GATE_NH24_M00_S06` | 0.891223 | 22.505 | 0.833132 |
| 8h | `015_MUC_H08_V24_RAIN18_24_48_RISE_GATE_NH72_M06_S15` | 0.861181 | 47.708 | 0.829173 |
| 12h | `018_MUC_H12_V24_RAIN18_24_48_RISE_GATE_NH56_M03_S18` | 0.809793 | 75.192 | 0.820093 |

## Achados por evento

- H02, `002_MUC_H02_BASE_COMPLETA_Q58_V15_RISE_GATE_NH32_M00_S02`: menores eventos — E30: PERS 0.587 (MAE 12.6 cm), E34: PERS 0.800 (MAE 7.9 cm), E18: PERS 0.810 (MAE 8.6 cm).
- H04, `006_MUC_H04_DOWNLOAD_015_V15_RISE_GATE_NH24_M00_S06`: menores eventos — E30: PERS 0.540 (MAE 22.3 cm), E22: PERS 0.549 (MAE 12.7 cm), E7: PERS 0.792 (MAE 16.1 cm).
- H08, `015_MUC_H08_V24_RAIN18_24_48_RISE_GATE_NH72_M06_S15`: menores eventos — E18: PERS 0.686 (MAE 32.0 cm), E30: PERS 0.689 (MAE 37.0 cm), E34: PERS 0.765 (MAE 38.4 cm).
- H12, `018_MUC_H12_V24_RAIN18_24_48_RISE_GATE_NH56_M03_S18`: menores eventos — E21: PERS 0.716 (MAE 94.5 cm), E30: PERS 0.742 (MAE 41.7 cm), E37: PERS 0.778 (MAE 141.6 cm).
- A maior fração de platô consecutivo observada na `RNA_FINAL` foi 0%; na série observada, a maior fração foi 3,95%.
- A média simples de PERS por evento é informativa, mas não substitui o PERS global: os denominadores e o número de linhas por evento diferem.

## Limitações

- A checagem de PERS por evento é uma média simples dos PERS eventuais; ela não substitui o PERS global, que é calculado pela razão entre somas dos erros quadráticos.
- Correlação alta e NASH alto não eliminam erros de pico, atraso ou viés; a decisão de publicação exige inspeção dos gráficos e dos extremos.

- A conferência local contra XML ANA cobriu 4.290 linhas dos eventos 22 e 24, com horário exato e diferença zero; XMLs dos eventos 19, 26, 27 e 28 foram localizados, mas esses eventos não aparecem nos recortes da q79.
- A telemetria local não é uma validação operacional em tempo real; ela confirma somente a correspondência histórica dos horários e níveis disponíveis.
- `telemetry_check_q79.csv` e `telemetry_samples_q79.csv` registram a cobertura e a amostra determinística.

## Arquivos

- `model_metrics_recalculated_q79.csv`
- `event_metrics_q79.csv`
- `integrity_q79.csv`
- `plots/scatter_H02_all_models.png`, `scatter_H04_all_models.png`, `scatter_H08_all_models.png`, `scatter_H12_all_models.png`
- `plots/scatter_best_by_horizon.png`
- `plots/pers_event_by_horizon.png`
