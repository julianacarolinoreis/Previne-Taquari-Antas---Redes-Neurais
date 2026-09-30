# Protocolo operacional de validação — Muçum (86510000)

## Objetivo
Nenhuma curva REC/HEC é tratada como resultado final apenas porque o HEC-HMS concluiu a execução. A rodada deve ser iterativamente calibrada contra o estado observado mais recente e contra a dinâmica hidrológica da bacia.

## Princípio
1. Até o tempo de corte (t0), chuva, nível e vazão são observados.
2. Depois de t0, entra a previsão meteorológica/hidrológica.
3. Postos aninhados não são somados como contribuições independentes.
4. Redes neurais são controle independente; não são usadas para forçar o HEC.
5. Parâmetros observados não são alterados para melhorar ajuste.
6. Somente estado interno, warm-up e routing dentro de faixas fisicamente plausíveis podem ser recalibrados automaticamente.

## Dados obrigatórios
- Muçum 86510000: nível observado mais recente.
- Linha José Júlio 86472000: vazão observada a montante.
- Passo Carreiro 86500000: vazão observada do ramo Carreiro.
- Demais postos frescos de nível/vazão: QC e tendência dos ramos.
- Chuva observada espacializada na bacia: todos os postos válidos.
- ECMWF/IFS: apenas para o período futuro.
- Incrementos Carreiro→Santa Tereza e Santa Tereza→Muçum explicitamente representados no modelo.

## Critérios para considerar uma candidata VALIDATED
- erro absoluto do nível em t0 <= 10 cm;
- erro absoluto da inclinação atual <= 12 cm/h;
- RMSE das últimas 6 h <= 35 cm;
- viés absoluto das últimas 6 h <= 15 cm;
- correlação do tempo de viagem observado >= 0,98;
- RMSE da relação a montante→Muçum <= 150 m³/s;
- pelo menos 40 postos válidos de chuva;
- pelo menos 30 postos com vazão;
- fronteiras principais (Linha José Júlio e Carreiro) com idade <= 2 h.

## Ciclo automático
1. Atualizar observados.
2. Atualizar ECMWF/IFS.
3. Construir o forçamento observado→previsto sem sobreposição.
4. Rodar conjunto inicial de parâmetros internos.
5. Avaliar os critérios.
6. Se não passar, refinar routing/warm-up ao redor da melhor candidata.
7. Repetir a busca de forma adaptativa.
8. Quando uma candidata passar, rodá-la novamente e confirmar os critérios.
9. Marcar como VALIDATED e só então usar como curva final/gráfico.
10. Se nenhuma combinação fisicamente permitida passar, manter CALIBRATION_PENDING e investigar erro estrutural/topológico/forçamento; nunca forçar artificialmente o ajuste.

## Interpretação de "acertar"
VALIDATED significa que o modelo reproduz satisfatoriamente o estado e a dinâmica observados no momento da rodada. Não significa certeza sobre o pico futuro. O pico e o horário continuam sendo previsão e devem ser atualizados com cada nova telemetria/rodada meteorológica.

## Segurança
Produto de pesquisa/apoio à decisão. Não substitui alertas oficiais do SGB/Defesa Civil.
