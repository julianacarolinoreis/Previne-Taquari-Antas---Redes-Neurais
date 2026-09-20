# Diagnóstico técnico: Transformer–GNN experimental no PREVINE

**Estado:** diagnóstico de pesquisa; não é modelo em produção, alerta ou autorização operacional.

**Data do diagnóstico:** 20 de setembro de 2026.

## 1. O que o artigo de referência realmente faz

O artigo *Urban Pluvial Flood Prediction in Huai’an City Based on a Transformer–GNN Fusion Model* (Zheng, Tang, Yu e Xue, *Water*, 2026, 18(17), 2206, DOI [10.3390/w18172206](https://doi.org/10.3390/w18172206)) propõe uma previsão espaço-temporal de profundidade de inundação urbana.

O problema do artigo é pluvial e urbano: a chuva horária, o acúmulo temporal e a estrutura de drenagem influenciam a profundidade em unidades espaciais. O estudo usa um evento de chuva intensa associado ao tufão In-Fa em julho de 2021, gera dados de treinamento com simulações SWMM + LISFLOOD-FP e compara LSTM, CNN, U-Net e Transformer–GNN. O protocolo informado usa validação cruzada de cinco folds e as métricas R², RMSE, MAE e MAPE. O valor reportado para o modelo proposto é R² médio 0,9561, RMSE 6,0201 cm, MAE 3,1048 cm e MAPE 11,12%.

Esses valores não são transferíveis diretamente para o Taquari–Antas: são de outra bacia, outra escala, outro problema de inundação e um conjunto de exemplos que depende de simulações hidrodinâmicas. O resultado metodologicamente útil é a decomposição:

1. o Transformer representa dependências temporais da chuva e da evolução da profundidade;
2. o GNN/GAT representa relações espaciais/topológicas entre unidades conectadas;
3. uma fusão por atenção combina os dois ramos;
4. todos os concorrentes precisam ser treinados e avaliados sob o mesmo protocolo;
5. a incerteza do simulador usado para gerar dados limita a confiança do surrogate.

Fonte primária consultada: [página oficial do artigo na MDPI](https://www.mdpi.com/2073-4443/18/17/2206).

## 2. O que já existe no PREVINE

O PREVINE já possui uma arquitetura coerente, porém diferente:

```text
dados hidrometeorológicos → RNA de nível → nível previsto
→ HAND/MDT e cenários de cota → mapa/WebGIS → auditoria previsão × observado
```

Na auditoria local existem, entre outros, os seguintes elementos:

- modelos RNA auditáveis por horizonte e por cidade;
- planilhas com partições temporais e eventos identificados;
- replay Q62 de Muçum com cinco eventos independentes (E31, E33, E34, E35 e E37) para +8 h e +12 h;
- comparação no mesmo recorte entre RNA fonte, persistência, Ridge, MLP, Random Forest e XGBoost;
- pacote Santa Tereza 2 h com estação 86472600, evento independente E12 e seis rotações com chaves comuns;
- MDT/HAND, contornos e visualizações espaciais experimentais;
- páginas de sala integrada, catálogo e auditoria de dados;
- bloqueios explícitos para promoção operacional, conversão cota–vazão sem curva-chave e capacidade/rota sem confirmação local.

O que ainda não existe de forma validada para uma linha Transformer–GNN é uma sequência temporal padronizada multiestação, um grafo hidrográfico versionado e uma verdade espacial observada ou hidrodinâmica suficientemente auditada para treinar profundidade por célula.

## 3. O que não deve ser confundido

O artigo é uma referência para desenho experimental, não uma prova de que Transformer–GNN será melhor no PREVINE. A RNA atual prevê nível em pontos de resposta. O Transformer–GNN proposto pelo artigo prevê profundidade espacial em um problema pluvial urbano. A linha experimental do PREVINE deve comparar primeiro tarefas equivalentes:

1. previsão de nível em uma estação e horizonte fixo;
2. previsão multie estação, se houver observações reconciliadas;
3. espacialização de nível para mapa por HAND/MDT;
4. somente depois, surrogate espacial de profundidade ou mancha.

Não se deve comparar MAE de nível em centímetros com IoU de mancha como se fossem a mesma tarefa.

## 4. Arquitetura experimental recomendada

### Fase A — benchmark temporal honesto

Para +2 h, +4 h, +8 h e +12 h, manter uma tabela de dados com:

- instante-base;
- instante-alvo;
- estação e município;
- nível observado no instante-base;
- níveis defasados e diferenças/acentuações;
- chuva observada e acumulada por janelas;
- chuva prevista, com rodada e horário de emissão;
- evento e partição temporal;
- nível observado no alvo.

Comparar, no mesmo conjunto independente:

- persistência;
- Ridge;
- RNA fonte;
- MLP feed-forward;
- LSTM/GRU, se houver runtime reproduzível;
- Transformer temporal;
- Random Forest;
- XGBoost.

Selecionar hiperparâmetros em validação por evento. O conjunto de teste não pode participar da seleção. A divisão deve ser por evento ou por bloco temporal, nunca por linhas embaralhadas do mesmo evento.

### Fase B — grafo hidro-hidrológico da bacia

O primeiro grafo deve ser pequeno e verificável, com estações, não milhões de pixels.

**Nós candidatos:**

- Santa Tereza — 86472600;
- Muçum — 86510000;
- Encantado, Estrela, Lajeado e outros pontos apenas quando a identidade, série e direção hidrológica estiverem reconciliadas;
- pluviômetros associados, se o papel de cada estação estiver documentado.

**Arestas candidatas:**

- montante → jusante por rede hidrográfica;
- conexão hidrológica confirmada por sub-bacia e curso d'água;
- tempo de propagação como atributo da aresta;
- distância, área contribuinte e diferença de cota como atributos;
- nenhuma aresta deve ser criada apenas porque dois pontos aparecem próximos no mapa.

**Atributos de nó:**

- nível atual e defasagens;
- chuva observada/acumulada;
- chuva prevista e rodada meteorológica;
- área de drenagem;
- declividade média e estatísticas do terreno;
- HAND, altitude e distância ao canal, quando auditados;
- indicador de qualidade/falta do dado.

**Saída inicial:** vetor de níveis nos mesmos nós para +2, +4, +8 e +12 h. Essa saída permite uma comparação justa com as RNAs atuais e não exige, ainda, inventar profundidade em cada pixel.

### Fase C — fusão temporal-espacial

O protótipo deve ser pequeno:

```text
janela temporal por estação
        ├─ Transformer temporal por nó
        └─ GAT/Message Passing no grafo hidrográfico
                    ↓
          atenção/fusão temporal + espacial
                    ↓
          nível previsto em cada estação/horizonte
```

O modelo não deve ser chamado de melhor por ser mais complexo. Ele precisa superar ou empatar, sob o mesmo recorte, com persistência, Ridge e RNA fonte. Se não superar, o resultado científico é manter a solução simples.

### Fase D — espacialização paralela

Manter o caminho oficial da pesquisa:

```text
nível previsto → HAND/MDT → cenário de cota e mancha preliminar
```

Como experimento separado, estudar:

```text
estado multie estação + chuva + grafo do terreno
→ surrogate de profundidade por unidade espacial
```

O grafo espacial deve usar unidades agregadas hidrologicamente relevantes, como sub-bacias, trechos, células de drenagem ou unidades de HAND conectadas por direção de fluxo. Conectar apenas pixels vizinhos produziria uma geometria sem significado hidráulico. A linha espacial só pode ser comparada com mapas observados, drone, sensoriamento remoto ou saída hidrodinâmica com data, resolução e incerteza documentadas.

## 5. Estratégia de validação sem leakage

O protocolo mínimo é:

1. fixar a definição do alvo e do horizonte antes do treino;
2. separar eventos inteiros em treino, validação e teste;
3. impedir que uma mesma cheia apareça parcialmente nos três conjuntos;
4. usar validação por evento ou por blocos temporais, não K-fold aleatório em linhas correlacionadas;
5. congelar o conjunto de teste até o final;
6. versionar a lista de eventos, hashes das planilhas, nomes de estações e features;
7. registrar valores ausentes e não substituí-los silenciosamente por zero;
8. publicar as métricas por evento, além da média agregada.

Para o benchmark já executado, Q62 usa a interseção das mesmas chaves evento + hora-base entre os cinco modelos de cada horizonte. Em Santa Tereza 2 h, E12 é preservado como `Verificacao` porque esse é o rótulo original; apenas as seis rotações que realmente contêm E12 foram incluídas.

## 6. Métricas obrigatórias

Para nível:

- MAE e RMSE em cm;
- viés;
- NSE e R² quando definidos;
- erro absoluto e assinado do pico;
- atraso do pico em horas;
- MAE médio, mediano e pior por evento;
- desempenho separado em eventos extremos.

Para mapa, somente quando houver referência compatível:

- IoU;
- CSI;
- precision, recall e false alarm ratio;
- erro de profundidade por classe;
- erro de área inundada;
- diferença de borda/contorno com resolução declarada.

Nenhuma métrica isolada decide promoção. Persistência, por exemplo, pode ter pico próximo por repetir o nível inicial e ainda ter péssimo erro ponto a ponto; por isso pico, MAE e RMSE precisam aparecer juntos.

## 7. Incerteza e explicabilidade

Cada resultado deve carregar quatro camadas de incerteza separadas:

1. observação e telemetria;
2. chuva prevista;
3. MDT/HAND e transformação nível → cenário;
4. erro do modelo.

O primeiro protótipo pode usar ensembles por evento, quantis de resíduos e intervalos conformais calculados exclusivamente na validação. A página deve mostrar intervalo e estado de cobertura, não uma profundidade única como verdade.

Para explicabilidade, registrar:

- importância de atributos;
- ablação de estações a montante;
- sensibilidade a chuva acumulada e nível antecedente;
- atenção temporal/espacial apenas como diagnóstico, não como causalidade automática;
- SHAP em um conjunto de validação, se o custo computacional e a estabilidade permitirem.

Uma explicação útil no PREVINE seria: “o aumento veio principalmente do nível antecedente, da chuva acumulada na estação X e da subida observada a montante”. Isso precisa ser uma síntese de experimentos de ablação, não uma frase inventada a partir de um peso de atenção.

## 8. Dados já disponíveis e dados que faltam

**Disponíveis para o primeiro protótipo:** planilhas auditáveis, eventos, níveis, entradas derivadas, estação 86472600 em Santa Tereza, estação 86510000 no pacote Q62 de Muçum, partições e metadados de RNA; camadas de MDT/HAND e alguns artefatos HEC-HMS espaciais para estudos separados.

**Ainda necessários:** inventário reconciliado multie estação, direção de fluxo e tempos de propagação documentados, chuva com rodada de previsão, vazão/curva-chave onde a tarefa for vazão, dataset hidrodinâmico espacial validado, observação espacial independente e protocolo de missingness.

Sem esses elementos, instalar PyTorch Geometric ou declarar um `Transformer-GNN` não constitui experimento válido.

## 9. Viabilidade computacional

Medir por rodada:

- tempo de treino;
- tempo de inferência por horizonte;
- tempo para gerar o artefato espacial;
- memória e tamanho do modelo;
- reprodutibilidade por seed;
- diferença entre executar localmente e no pipeline do site.

A primeira linha multie estação deve ser pequena o suficiente para ser auditada em CPU. Uma rede espacial por milhares de células só deve existir depois que o grafo, a referência espacial e a incerteza forem resolvidos.

## 10. Roadmap de execução

### Protótipo

- consolidar contratos por horizonte;
- rodar baselines e XGBoost no mesmo recorte;
- construir o grafo com poucas estações e arestas documentadas;
- implementar Transformer temporal pequeno e GNN simples em ambiente experimental;
- registrar hashes, seeds e artefatos.

### Validação

- selecionar hiperparâmetros apenas nos eventos de validação;
- testar pelo menos dois eventos independentes adicionais;
- comparar métricas por evento e extremos;
- auditar atraso, missingness e identidade de estação.

### Comparação

- publicar tabela comum entre persistência, Ridge, RNA, MLP, RF, XGBoost, LSTM/GRU e Transformer quando executados;
- executar Transformer–GNN somente após o contrato multie estação;
- não preencher modelos ausentes com zero ou rótulo de “não aplicável” sem explicação.

### Integração experimental

- gerar saída multie estação em JSON versionado;
- acoplar apenas em modo sombra/experimental;
- manter RNA → HAND/MDT como linha de referência;
- mostrar intervalos, fontes, horário da rodada e bloqueios.

### Eventual incorporação

Só considerar incorporação depois de uma revisão independente, vários eventos de teste, reconciliação de estação, validação espacial e decisão explícita sobre limiar de desempenho. Até lá, nenhuma saída deve ser apresentada como alerta oficial, ordem de evacuação, rota liberada ou capacidade atual de abrigo.

## Conclusão

O caminho cientificamente mais forte para o PREVINE é incremental: usar o artigo para organizar uma linha temporal-espacial experimental, mas começar pelo grafo de estações e pela previsão de nível multie estação. O ganho de complexidade só se justifica se melhorar resultados em eventos independentes e permanecer explicável. A espacialização por HAND/MDT continua sendo a referência operacional de pesquisa; o surrogate espacial Transformer–GNN deve permanecer paralelo até existir uma verdade espacial e um protocolo de incerteza compatíveis.
