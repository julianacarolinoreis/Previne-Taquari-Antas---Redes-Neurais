# Auditoria de calibração conjunta · E24, E27 e E28

Atualização de 03/09/2026. Foi executada uma busca HEC-HMS 4.13 com 60
combinações de um único conjunto de parâmetros comum aos três eventos fechados
de Muçum. A chuva usada foi a ANA 86472000 e cada evento foi avaliado somente
nas horas observadas e pareadas.

## Melhor configuração comum encontrada

| Parâmetro | Valor |
| --- | ---: |
| Perda inicial | 5,0 |
| Perda constante | 4,0 |
| Tempo de concentração | 5 min |
| Armazenamento | 60 min |
| Recessão | 0,9 |
| Ajuste inicial de vazão/área | 0,0025 |

Resultado médio: NSE **0,4225**, atraso absoluto médio **10,0 h** e erro
relativo médio de pico **36,38%**.

| Evento | Horas | NSE | Pico simulado / observado (m³/s) | Atraso | Erro do pico |
| --- | ---: | ---: | ---: | ---: | ---: |
| E24 | 238 | 0,1619 | 5.126,2 / 11.435,0 | −13 h | 55,171% |
| E27 | 245 | 0,7066 | 17.293,2 / 14.525,2 | 0 h | 19,057% |
| E28 | 209 | 0,3989 | 5.132,1 / 7.886,7 | −17 h | 34,927% |

## Interpretação

O conjunto comum não é aceitável como replay. Ele perde o pico e o horário do
E24 e E28, mesmo mantendo um ajuste razoável apenas no E27. Isso mostra que a
calibração precisa preservar os parâmetros selecionados por evento enquanto
investigamos causas físicas para a diferença entre as respostas: chuva de
bacia insuficientemente espacializada, condições antecedentes, estrutura
agregada de 16.000 km² e limitações da série observada.

Por isso, os replays publicados continuam usando configurações específicas:
E24, E27 e E28 não foram substituídos pelo conjunto comum. A busca é um
diagnóstico de generalização, não uma promoção operacional.

## Próximo avanço

Obter chuva contínua e espacializada, separar calibração de validação por
evento e testar uma estrutura HEC-HMS distribuída ou semi-distribuída. A
calibração de Santa Teresa segue bloqueada até existir vazão ou curva-chave
reconciliada para a estação de resposta.
