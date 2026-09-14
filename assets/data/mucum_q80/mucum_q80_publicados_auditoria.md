# Correção do catálogo de pesquisa Muçum — q80

Esta correção atua somente na área de pesquisa. O robô ao vivo não foi alterado.

## Resultado

Foram reconciliados oito modelos q80: cinco H4 já publicados e um candidato selecionado para cada horizonte adicional H2, H8 e H12. O MAT, a planilha auditável, o CSV de métricas e os alvos por evento foram conferidos.

O defeito de visualização encontrado era estrutural: os cinco H4 tinham séries numéricas e métricas por evento, mas faltavam os campos `key`, `start`, `end`, `obsPeak`, `rnaPeak`, `riseObs` e `riseRna` que o modal usa para habilitar os gráficos por evento. Esses campos foram reconstruídos a partir da própria série auditável.

A verificação de integridade q80 registrou `source_missing_rows=0`, `source_mismatch_count_capped_100=0`, `target_event_mismatch=0`, `target_value_mismatch=0`, `formula_mismatch=0`, `event32_rows=0` e divergência MAT–XLSX de zero para os modelos publicados.

Os CSVs agregados desta pasta contêm as métricas completas, o manifesto, PERS por evento, diagnóstico linha a linha e reconciliação dos alvos com a fonte.
