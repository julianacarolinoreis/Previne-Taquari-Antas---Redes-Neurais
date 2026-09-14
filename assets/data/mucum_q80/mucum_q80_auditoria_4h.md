# Auditoria dos cinco candidatos Muçum H4 — fila 80

Escopo: área de pesquisa. Esta publicação não altera o robô ao vivo.

## Regras verificadas

- 1.500 linhas por modelo e partição única por evento: treino 681, validação 316, teste 503.
- Eventos de treino: 4, 5, 6, 7, 11, 12, 13, 22, 30. Validação: 18, 21, 23. Teste: 24, 31, 34, 35, 37.
- `OUT04H_DIF = NIVEL_FUTURO - nivel_86510000` em todas as linhas.
- `RNA_FINAL` do XLSX = `Tctot1` do MAT em até 1e-6 cm.
- `NIVEL_FUTURO` foi confrontado com o nível de `86510000` em t+4h dentro do mesmo evento quando essa linha existe; não houve substituição por outro evento.
- COD_SEQUENCIAL sem duplicidades; séries dos gráficos ordenadas por data/hora.

## Limite que permanece explícito

Em cada modelo há 84 linhas sem uma linha futura correspondente no mesmo evento dentro do workbook auditável filtrado. Isso ocorre nas caudas e em lacunas internas dos eventos 12, 24 e 35. Esse número descreve a representação do recorte, não uma ausência do alvo na fonte. A planilha de origem declarada no manifesto, `4H_ALT__015_alt_MUC_H04_V15_LJJ_AUDITADO_SEM32_R07_T8-21_V11-18-31.xlsx`, tem 2.350 linhas; para cada um dos 1.500 registros de cada modelo, o confronto da fonte em t+4h no mesmo evento encontrou 1.500 alvos, zero ausências, zero candidatos de outro evento e zero divergências de valor. Os COD_SEQUENCIAL e os campos controlados também coincidiram com a fonte. Portanto, as 84 linhas não indicam troca de evento ou alvo inventado; elas impedem apenas revalidar a ligação t+4h usando exclusivamente a linha seguinte do XLSX filtrado. O alvo armazenado no MAT e no workbook continua sendo o valor usado pelo treinamento.

Os PERS por evento, os diagnósticos linha a linha e a reconciliação auditável-versus-fonte estão nos CSVs deste diretório. A reconciliação está em `mucum_q80_target_reconciliation.csv`.
