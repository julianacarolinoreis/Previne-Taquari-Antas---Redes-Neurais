# Resultados preliminares — framework adaptativo de previsão em Muçum

## Status

**Promissor, mas ainda não validado como método superior.**

O framework foi formalizado antes da interpretação final e testado em três replays pseudo-operacionais históricos (E24, E27, E28) sob chuva futura perfeita (P2), seguido por um hold-out E31 executado sem alterar o algoritmo. O caso real de 28–29/09/2026 permanece como evidência prospectiva P1 com ECMWF.

## Desenho

A — parametrização fixa baseada na mediana dos eventos anteriores.

B — seleção apenas por analogia da chuva.

C — seleção da família histórica pela compatibilidade com o hidrograma no lookback.

D — C + recalibração local online usando somente observações anteriores a t0.

Em todos os replays o evento-alvo foi excluído da biblioteca e somente eventos cronologicamente anteriores puderam ser candidatos.

## E24 + E27 + E28 — P2

Agregado de 6 casos (3 eventos × cortes de 12 h e 6 h antes do pico):

| Braço | Mediana erro abs. pico Q | Mediana erro abs. tempo | Mediana RMSE Q | Mediana NSE futuro | Mediana erro abs. pico de nível* |
|---|---:|---:|---:|---:|---:|
| A fixo | 39,4% | 4,25 h | 1788 m³/s | 0,019 | 586 cm |
| B chuva | 31,6% | 4,50 h | 1902 m³/s | 0,048 | 334 cm |
| C lookback | 34,2% | 7,25 h | 1791 m³/s | -0,013 | 335 cm |
| D lookback + recalibração | **25,6%** | 5,25 h | **1393 m³/s** | **0,443** | **161 cm** |

\*Quando a vazão simulada permaneceu dentro do domínio da curva-chave publicada.

O braço D reduziu substancialmente erro de magnitude e RMSE no agregado, mas **não melhorou de forma consistente o horário do pico**. Isso é coerente com a hipótese de que parte do tempo de propagação ainda está sendo representada de forma inadequada por Clark/estrutura simplificada.

## Leitura por evento

### E24

Foi o caso mais favorável à estratégia adaptativa. Com t0 a 6 h do pico:

- braço B/C: erro de pico Q ≈ -15,2% e lag +1,25 h;
- braço D: erro de pico Q ≈ +1,0% e lag +0,25 h;
- erro de pico de nível do braço D ≈ -71 cm;
- NSE futuro do braço D ≈ 0,906.

Com t0 a 12 h, o braço D também ficou próximo do pico: +3,0% em Q e -1,75 h no horário.

### E27

É o evento que impede qualquer conclusão triunfal. Todos os braços tiveram dificuldade na propagação temporal. O braço D melhorou magnitude em um dos cortes, mas o pico permaneceu atrasado em 10,5–17,5 h. Isso sugere deficiência estrutural/routing, não apenas escolha de família histórica.

### E28

O braço D melhorou RMSE e magnitude em relação às alternativas, porém ainda antecipou o pico em aproximadamente 3,25–7,25 h. Novamente, a magnitude responde à atualização online melhor do que o tempo de propagação.

## Hold-out E31 — executado sem mudar o método

O E31 (28/06–04/07/2025) foi usado como teste externo depois de congelado o algoritmo do P2.

Agregado dos cortes de 12 h e 6 h:

| Braço | Erro abs. pico Q | Erro abs. tempo | RMSE Q | NSE futuro | Erro abs. pico nível |
|---|---:|---:|---:|---:|---:|
| A fixo | 18,5% | **0,25 h** | **874** | **0,726** | 183 cm |
| B chuva | 16,1% | 4,25 h | 908 | 0,703 | 157 cm |
| C lookback | 20,5% | 1,75 h | 1175 | 0,499 | 187 cm |
| D lookback + recalibração | **9,5%** | 1,75 h | 1029 | 0,617 | **88 cm** |

No corte de 6 h, o braço D reduziu o erro do pico para **-5,4%** e o erro de nível para aproximadamente **-51 cm**, embora o braço fixo tenha sido melhor no horário do pico (-15 min).

Isso é uma confirmação importante: o ganho do braço D em **magnitude** apareceu também num evento não usado para ajustar o algoritmo, mas o ganho em **timing** não se confirmou.

## Caso prospectivo real — 28/09/2026

A lógica adaptativa selecionou E28 no lookback e recalibrou o evento corrente sem usar observações futuras.

- pico previsto: 11,9058 m às 05:00;
- pico observado: 11,42 m às 04:45;
- erro de magnitude: +48,6 cm;
- erro de horário: +15 min.

Este caso é especialmente importante porque não é replay retrospectivo.

## Conclusão científica preliminar

Os resultados apoiam duas afirmações diferentes:

1. **Há evidência preliminar de que a seleção condicionada pelo estado da bacia + recalibração online melhora a magnitude do hidrograma e do pico em relação a alternativas simples.**
2. **Ainda não há evidência de que ela melhore sistematicamente o tempo do pico.**

O segundo resultado é tão importante quanto o primeiro. Ele reforça a necessidade de separar explicitamente **resposta de sub-bacia (Clark)** de **propagação no canal (routing)** antes de tentar ajustar novamente Tc/Storage.

## Próximo teste congelado

O próximo desenvolvimento deve alterar a estrutura física, não o score para fazê-lo caber nos eventos já vistos:

- inserir reaches físicos Antas → Carreiro → Santa Tereza → Muçum;
- restringir routing com seções/declividade/tempo de onda;
- manter o seletor e o score atuais congelados;
- repetir os replays e comparar se o erro de timing diminui;
- preservar novos eventos reais como validação prospectiva.

Não retunar o seletor com E31. Ele agora faz parte da validação.
