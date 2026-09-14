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

Em cada modelo há 84 linhas sem uma linha futura correspondente no mesmo evento dentro do workbook filtrado. Isso ocorre nas caudas e em lacunas internas dos eventos 12, 24 e 35; não é evidência de troca de evento, mas impede revalidar a ligação t+4h apenas pela linha seguinte do mesmo XLSX. O alvo armazenado no MAT e no workbook continua sendo o valor usado pelo treinamento.

Os PERS por evento e os diagnósticos linha a linha estão nos CSVs deste diretório.
