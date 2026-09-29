# Protocolo científico — previsão adaptativa condicionada por eventos históricos em Muçum

## 1. Pergunta de pesquisa

Avaliar se uma estratégia de previsão hidrológica que seleciona, em tempo real, uma família histórica de parâmetros compatível com o estado corrente da bacia e depois a recalibra apenas com dados observados anteriores ao instante de previsão melhora a previsão de cheia em Muçum quando comparada com uma parametrização fixa.

A hipótese principal é:

> Uma biblioteca de parametrizações calibradas em eventos históricos, selecionada dinamicamente pela compatibilidade com o hidrograma observado durante o período de lookback e atualizada com o evento corrente, reduz erros de pico e de tempo de pico sem utilizar observações futuras.

## 2. Fundamento científico

A estratégia combina quatro ideias já consolidadas na hidrologia:

1. **Lookback operacional**: a simulação deve atravessar um período observado anterior ao tempo de previsão, permitindo comparar o estado simulado com o estado real antes de entrar no horizonte futuro.
2. **Calibração por evento**: diferentes cheias podem produzir respostas diferentes da mesma bacia, e conjuntos eventwise devem ser tratados como hipóteses comportamentais, não como "parâmetros verdadeiros".
3. **Calibração multiobjetivo**: não se deve selecionar um modelo apenas pelo NSE. O ajuste deve considerar nível/vazão atual, forma do hidrograma, tendência, pico e tempo de pico.
4. **Equifinalidade e atualização adaptativa**: múltiplos conjuntos de parâmetros podem ser comportamentais; observações novas servem para atualizar a plausibilidade de cada família sem assumir unicidade paramétrica.

O HEC-HMS define o método Clark com Tc associado à translação temporal e o coeficiente de armazenamento R associado à atenuação do hidrograma. Isso justifica avaliar separadamente erro de tempo e erro de magnitude, evitando usar Tc/R para compensar indevidamente routing de canal.

## 3. Estrutura experimental

O estudo terá quatro braços, sempre avaliados com o mesmo evento-alvo e a mesma chuva observada/futura:

| Braço | Descrição | Pode usar dados do evento-alvo antes de t0? | Pode usar dados após t0? |
|---|---|---:|---:|
| A | Parametrização fixa/comum | Não, além do estado inicial necessário | Não |
| B | Melhor família histórica escolhida apenas por similaridade de chuva | Sim, apenas chuva passada disponível | Não |
| C | Seleção pela compatibilidade no lookback | Sim, chuva + hidrograma observados até t0 | Não |
| D | Seleção pelo lookback + recalibração local online | Sim, apenas até t0 | Não |

O braço D corresponde à lógica usada no evento de setembro de 2026 em Muçum.

## 4. Regra contra vazamento de informação

Para cada replay retrospectivo:

- o evento-alvo é removido da biblioteca de candidatos;
- somente eventos cronologicamente anteriores ao evento-alvo podem ser usados como candidatos no teste estrito;
- o instante de previsão t0 é congelado antes da avaliação;
- nenhuma observação posterior a t0 pode participar da seleção ou recalibração;
- chuva futura observada só pode ser usada em um experimento de "forçante perfeita", separado da previsão meteorológica real;
- métricas do futuro nunca entram no score de seleção;
- parâmetros escolhidos depois de conhecer o pico do evento são proibidos no benchmark prospectivo.

## 5. Instantes de previsão

Cada evento histórico deve ser reexecutado em pelo menos três cortes:

- t0 aproximadamente 12 h antes do pico observado;
- t0 aproximadamente 6 h antes do pico observado;
- t0 na fase de subida em que a vazão/nível já apresenta tendência positiva robusta.

O caso de 28/09/2026 fica congelado como estudo prospectivo real: previsão lançada em 28/09 às 19:00 BRT, antes do pico observado.

## 6. Score de seleção no lookback

O score operacional será registrado explicitamente e nunca alterado depois de ver o futuro. A versão inicial segue a lógica usada em 28/09/2026:

```
score =
    |erro_nivel_atual| / s_nivel
  + |erro_vazao_atual_pct| / s_q
  + |erro_tendencia| / s_tend
  + RMSE_lookback / s_rmse
```

Os denominadores são escalas de normalização e serão avaliados por sensibilidade. A análise científica deve mostrar resultados com o score original e com alternativas pré-definidas.

## 7. Métricas primárias

As métricas primárias são:

- erro absoluto do pico de nível (cm);
- erro absoluto do pico de vazão (%);
- erro de tempo do pico (h);
- RMSE e MAE no horizonte de previsão;
- NSE/KGE no horizonte futuro quando houver série suficiente;
- erro de nível em +2 h, +4 h, +8 h, +12 h e +24 h;
- erro na taxa de subida durante a aproximação do pico.

Para alerta, tempo de pico e erro de nível no trecho ascendente são tratados como desfechos de primeira ordem, não como métricas secundárias.

## 8. Experimentos complementares

Serão executados dois cenários de forçante:

**P1 — previsão real:** chuva observada até t0 + previsão meteorológica disponível em t0.

**P2 — forçante perfeita:** chuva observada até t0 + chuva que de fato ocorreu depois de t0.

A diferença P1–P2 mede quanto do erro veio da meteorologia. O erro residual em P2 mede principalmente estrutura/parametrização hidrológica, routing, estado inicial e relação vazão–nível.

## 9. Separação Clark × routing

O benchmark deve preservar uma segunda comparação:

- Clark livre, routing fixo/ausente;
- Clark fixado em faixa física, routing calibrável;
- Clark + routing com restrições físicas.

Parâmetros de routing não serão promovidos se exigirem valores incompatíveis com geometria, seções, declividade hidráulica ou tempos de onda observáveis. O objetivo é impedir que Clark absorva artificialmente tempo de viagem do canal.

## 10. Eventos e situação atual

A biblioteca core de Muçum contém E20, E21, E22, E23, E24, E25, E27, E28 e E31. Eventos E26, E29 e E30 permanecem marginais/diagnósticos.

O modelo comum existente não é tratado como padrão de verdade: o próprio pacote atual registra desempenho fraco fora da calibração, com hold-out E27 NSE negativo e média leave-one-out substancialmente inferior à calibração eventwise. Isso é uma motivação para testar a estratégia adaptativa, não uma prova de superioridade.

## 11. Caso prospectivo congelado — 28/09/2026

O caso de setembro de 2026 será preservado sem recalcular seus números originais:

- t0: 28/09/2026 19:00 BRT;
- família selecionada no lookback: E28;
- pico previsto: 11,9058 m às 05:00 BRT de 29/09;
- pico observado: 11,42 m às 04:45 BRT;
- erro de magnitude: aproximadamente +48,6 cm;
- erro de horário: +15 min.

Esse caso é evidência prospectiva real, mas isoladamente não valida a metodologia.

## 12. Critério de sucesso científico

A estratégia adaptativa só será considerada superior se:

1. melhorar o erro mediano de pico e/ou tempo de pico em replays sem vazamento;
2. não piorar sistematicamente RMSE/MAE no horizonte futuro;
3. o ganho persistir em eventos não usados para calibrar o seletor;
4. os parâmetros permanecerem hidrologicamente interpretáveis;
5. o resultado não depender de um único evento extremo.

A análise final deve reportar mediana, intervalo interquartil e resultados por evento, e não apenas uma média agregada.

## 13. Hipóteses secundárias

H2. A seleção pela compatibilidade no lookback supera a seleção apenas pelo total de chuva.

H3. A recalibração local melhora magnitude mais do que tempo quando a família histórica já representa bem a escala temporal.

H4. A inclusão de routing físico reduz a necessidade de variação excessiva de Tc/Storage entre eventos.

H5. A diferença entre P1 e P2 quantifica de forma útil a parcela do erro atribuível à previsão meteorológica.

## 14. Referências centrais

- Beven, K.; Binley, A. (1992). *The future of distributed models: Model calibration and uncertainty prediction*. Hydrological Processes, 6(3), 279–298. DOI: 10.1002/hyp.3360060305.
- Gupta, H. V.; Sorooshian, S.; Yapo, P. O. (1998). *Toward improved calibration of hydrologic models: Multiple and noncommensurable measures of information*. Water Resources Research, 34(4), 751–763. DOI: 10.1029/97WR03495.
- Yapo, P. O.; Gupta, H. V.; Sorooshian, S. (1998). *Multi-objective global optimization for hydrologic models*. Journal of Hydrology, 204, 83–97. DOI: 10.1016/S0022-1694(97)00107-8.
- USACE HEC. *Clark Unit Hydrograph Model*, HEC-HMS Technical Reference Manual.
- USACE HEC. *Selecting a Transform Method*, HEC-HMS 4.13 User's Manual.

## 15. Disciplina de publicação

Até completar os replays sem vazamento, usar os termos **método proposto**, **estratégia adaptativa** ou **framework event-conditioned**. Não declarar método superior, novo ou validado antes da comparação retrospectiva e prospectiva completa.
