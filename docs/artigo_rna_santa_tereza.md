# Previsão de nível em Santa Tereza com redes neurais: síntese do recorte consolidado de 282 modelos MLP (2–12 h)

**Rascunho de artigo · pesquisa FAPERGS · não é alerta oficial**

Juliana Carolina Reis; Guilherme Garcia de Oliveira; Fernanda Vier  
Universidade Federal do Rio Grande do Sul (UFRGS) · PREVINE Taquari-Antas · processo FAPERGS 24/2551-0002124-8  

A lista de autoria para submissão a periódico permanece a confirmar com a equipe do projeto. Versão web com tabelas reconstruídas do recorte: `pesquisas/artigo-rna-santa-tereza.html`.

## Resumo

As inundações de 2023–2024 na bacia Taquari–Antas tornaram urgente antecipar o nível do rio com a rede telemétrica já instalada. Este rascunho sintetiza o recorte consolidado de **282 perceptrons multicamadas** treinados em MATLAB para a estação de Santa Tereza (ANA/SGB 86472600), com horizontes de 2, 4, 8 e 12 horas. A qualificação exige persistência (PERS) positiva em treino, validação, teste e série completa. A métrica de escolha é o *score de equilíbrio* — o menor PERS entre geral, validação e teste. A metodologia descreve as principais combinações de variáveis testadas. Os resultados reportam só o melhor modelo de cada horizonte.

O melhor modelo de 2 h (`009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21`) equilibra 0,969, com MAE de teste de **3,5 cm** e E95 de 10,4 cm; é também o modelo principal do feed ao vivo. Em 4 h o melhor equilibra 0,846 (MAE 13,9 cm). Em 8 h, ALT C0289 equilibra 0,694 (MAE 32,0 cm). Em 12 h o melhor é CONV C0149 (equilíbrio 0,690; MAE 40,9 cm). O erro do campeão cresce com a antecedência. Relatórios de processo de junho de 2026 ranqueavam baterias únicas por NASH ou PERS geral: o recorte consolidado muda a leitura porque a rotação de eventos e o equilíbrio separam recorde de generalização.

**Palavras-chave:** previsão de nível; redes neurais artificiais; índice de persistência; Santa Tereza; Taquari–Antas; alerta de inundação (pesquisa).

## 1. Introdução

Sistemas de alerta de inundação na bacia Taquari–Antas combinam telemetria ANA/SGB, o SACE e, na pesquisa, modelos de nível de curto prazo. Finck (2020) demonstrou a aplicabilidade de RNAs em estações de jusante da mesma bacia (Encantado, Estrela, Porto Mariante e Taquari), com NSE médio da ordem de 0,93 / 0,89 / 0,71 em 8, 12 e 24 h. Santa Tereza, a montante, passou a ser o primeiro município com recorte publicado no PREVINE: o objetivo é antecipar o nível na régua 86472600 com 2 a 12 horas, usando níveis da própria estação, estações a montante e, quando a ficha do modelo inclui, chuva acumulada.

Entre junho e julho de 2026 a equipe treinou dezenas de rodadas MATLAB (21 pastas de Santa Tereza em 11 dias). Em paralelo, relatórios de processo — gerados a partir de CSVs de uma bateria — descreveram combinações de inputs de 4 h e uma rodada 8 h ALT/CONV. Esses textos cumprem papel de caderno de laboratório. Eles não unificam horizontes, não usam o score de equilíbrio como régua e, em vários trechos, ranqueiam NASH de teste de uma partição só.

Este rascunho faz o passo seguinte: toma o recorte já consolidado em `index.html` (282 modelos com PERS positiva nos quatro recortes; 215 ALT e 67 CONV) e o organiza em formato de artigo. Muçum permanece fora do escopo, salvo menção de fronteira. Natureza do resultado: pesquisa e replay histórico. Não é boletim SACE/SGB, ordem de evacuação, rota ou despacho.

## 2. Área de estudo e dados

Santa Tereza (RS) situa-se no médio Taquari. A estação-alvo é a fluviométrica **86472600** (ANA/SGB). As fichas dos modelos combinam, conforme a rodada, o nível local e suas diferenças (D–*x* h) e acelerações (A–*x* h), níveis de montante (trecho a montante de Santa Tereza, Veranópolis, Ituim, Carreiro e outras estações do catálogo de 71 variáveis) e a chuva média acumulada em 36 h. A série é horária. A cota de pesquisa usada nas leituras públicas da cheia em Santa Tereza é 1.500 cm; ela não entra no treino como rótulo de classificação.

Os dados são partidos por **eventos de cheia**, não por janela aleatória. Treino, validação e teste trocam de papel entre rotações (R01–R10 no 2 h; onze rótulos no 4 h, inclusive um baseline; ondas altR_* / rot8h_* / conv8hR_* no 8 h). O evento 13 foi retirado de várias ondas curtas por ser pouco informativo — registro que os relatórios de 8 h de junho já faziam, e que o recorte consolidado preserva como decisão de processo, não como resultado de teste.

## 3. Método

### 3.1 Arquitetura

Cada modelo é um MLP de três camadas, treinado em MATLAB por retropropagação com gradiente adaptativo, até 100 mil ciclos, com várias inicializações (nit típico = 10) e retenção do ciclo de menor erro na validação. O catálogo de entrada tem 71 variáveis; cada rede usa um subconjunto. A mediana da varredura é de **dois neurônios por input**.

As siglas **ALT** e **CONV** identificam famílias/rodadas do planilhão; não devem ser lidas, sozinhas, como duas equações de saída. Na ficha do modelo ao vivo de 2 h, ALT significa que a rede prevê a *variação* do nível e o nível previsto é o nível atual mais essa variação. O forward-pass desse `.mat` foi reproduzido em Python com RMSE nulo: normalização por média/desvio, `logsig` na oculta e na saída, desnormalização linear da variação.

### 3.2 Métricas e regra de escolha

A persistência (PERS) mede o ganho sobre a previsão ingênua “daqui a *N* horas o nível será o de agora”, na linhagem de Kitanidis e Bras (1980). PERS = 1 é perfeito; 0 empata com a ingênua; negativo é pior do que não ter modelo. Complementam a leitura o coeficiente de Nash–Sutcliffe (Nash e Sutcliffe, 1970), o MAE e o percentil 95 do erro absoluto (E95), todos em centímetros na régua.

O **score de equilíbrio** é o mínimo entre PERS geral, de validação e de teste. Um recorde só no conjunto completo, se a validação ou o teste caem, não entra no topo. O recorte publicado já aplica o filtro: os 282 modelos têm os quatro PERS positivos. Achados de rodadas anteriores que citam persistência negativa descrevem redes *excluídas*, não este recorte. Em cada horizonte reporta-se um único modelo: o de maior equilíbrio. Métricas idênticas (inicializações equivalentes) contam como o mesmo modelo.

### 3.3 Combinações de variáveis

A varredura testou muitas montagens a partir do catálogo de 71 variáveis. O recorte qualificado reúne 1 conjunto de inputs em 2 h, 6 em 4 h, 14 em 8 h e 5 em 12 h. O Quadro 1 não lista todas as combinações: traz as principais usadas em 2 h, 4 h e 8 h e, de forma compacta, a montagem do horizonte 12 h. **O quadro descreve só as variáveis, sem métricas de desempenho.**

Em 4 h as seis montagens são aninhadas (13 ⊂ 14 ⊂ 15 ⊂ 16 ⊂ 20 ⊂ 24 entradas). O quadro mostra o núcleo (13), o núcleo com acelerações locais e a estação 86298000 (16) e o núcleo ampliado (24). Os intermediários de 14, 15 e 20 variáveis ficam de fora. Em 8 h, depois de unificar aliases do catálogo, restam 14 conjuntos; o quadro traz C0289, C0078 e C0265 — a mais recorrente, uma montagem com Ituim e a mais enxuta entre as frequentes.

**Quadro 1. Principais combinações de variáveis testadas em Santa Tereza (sem métricas).** Fonte: `index.html#data`.

| Horizonte | Combinação | N var. | Variáveis |
|---|---|---:|---|
| 2 h | 2H · Nível local e montante, sem chuva | 15 | ST; ST D–1 h; ST D–2 h; ST D–4 h; ST A–1 h; ST A–2 h; ST A–4 h; ST D–8 h; ST A–12 h; montante; montante D–1 h; montante D–2 h; montante D–5 h; montante A–12 h; montante A–20 h |
| 4 h | núcleo · Núcleo 4 h | 13 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Veranópolis; montante A–14 h; Veranópolis D–14 h; Ituim; Ituim D–11 h; ST D–4 h; ST D–2 h; ST A–2 h |
| 4 h | núcleo+86298000 · Núcleo + ST A–1 h + ST A–4 h + 86298000 | 16 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Veranópolis; montante A–14 h; Veranópolis D–14 h; Ituim; Ituim D–11 h; ST D–4 h; ST D–2 h; ST A–2 h; ST A–1 h; ST A–4 h; 86298000 |
| 4 h | ampliado · Núcleo ampliado (Carreiro e mais defasagens) | 24 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Veranópolis; montante A–14 h; Veranópolis D–14 h; Ituim; Ituim D–11 h; ST D–4 h; ST D–2 h; ST A–2 h; ST A–1 h; ST A–4 h; 86298000; montante D–4 h; montante D–1 h; montante A–12 h; Veranópolis D–12 h; Carreiro; Carreiro D–16 h; montante D–5 h; Ituim D–12 h |
| 8 h | C0289 | 10 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Veranópolis; montante A–14 h; Veranópolis D–14 h; 86430900; 86430900 D–14 h |
| 8 h | C0078 | 11 | ST; ST D–1 h; chuva 36 h; Veranópolis; Veranópolis D–14 h; Ituim; Ituim D–11 h; ST D–4 h; ST D–2 h; ST A–2 h; ST A–1 h |
| 8 h | C0265 | 8 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Veranópolis; montante A–14 h; Veranópolis D–14 h |
| 12 h | C0149 | 14 | ST; ST D–1 h; chuva 36 h; montante; montante D–2 h; Ituim; Ituim D–11 h; ST D–4 h; ST D–2 h; montante D–4 h; montante D–1 h; montante A–12 h; Ituim D–12 h; Ituim D–10 h |

ST = Santa Tereza (86472600); D–*x* h = diferença em *x* horas; A–*x* h = aceleração; montante = trecho a montante de Santa Tereza; chuva 36 h = chuva média acumulada em 36 h. Códigos numéricos são estações ANA/SGB.

## 4. Resultados

A Tabela 1 traz o melhor modelo de cada horizonte. Não se listam as dez rotações 2 h, nem um ranking intermediário, nem medianas de família. O erro do campeão no teste aumenta com a antecedência — o comportamento esperado de um modelo autorregressivo de nível, e o argumento mais simples contra tratar 2 h e 12 h com a mesma tolerância. Fonte: `index.html#data`, tabelas em `assets/data/artigo_rna_santa_tereza.json`.

**Tabela 1. Melhor modelo de cada horizonte, pelo score de equilíbrio.** Equilíbrio = min(PERS geral, validação, teste).

| H | Fam. | Modelo | Rotação | Equil. | PERS teste | MAE (cm) | E95 (cm) | Chuva | Inputs | Nh |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|
| 2h | ALT | `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21` | R09 | 0,969 | 0,969 | 3,5 | 10,4 | não | 15 | 30 |
| 4h | ALT | `V01_R10_T19-21_V1-3-5-15-17_nh48_nit10_cic100000` | R10 | 0,846 | 0,876 | 13,9 | 52,7 | sim | 24 | 48 |
| 8h | ALT | `altR_004_08_8h_alt_8H_ALT_C0289` | altR_004 | 0,694 | 0,694 | 32,0 | 135,0 | sim | 10 | 20 |
| 12h | CONV | `004_conv_C0149_R01_T2_V1_3` | R01_T2_V1_3 | 0,690 | 0,696 | 40,9 | 125,3 | sim | 14 | 28 |

Em **2 h** a única montagem do recorte (15 inputs de nível, sem chuva, 30 neurônios) gerou dez rotações; todas equilibram acima de 0,90. O campeão, `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21`, testa os eventos 10, 15 e 16, equilibra 0,969, tem MAE de teste 3,5 cm e E95 10,4 cm. É o modelo `principal` do feed ao vivo.

Em **4 h** o recorte tem 117 redes ALT, todas com chuva de 36 h. O melhor é `V01_R10_T19-21_V1-3-5-15-17_nh48_nit10_cic100000` (24 inputs, 48 neurônios, equilíbrio 0,846, MAE 13,9 cm, E95 52,7 cm). Identificadores V01, V05, V06 e V07 repetem a mesma métrica: são inicializações equivalentes, não campeões independentes. A bateria de 5 de junho (20 rodadas, combinação [1, 2, 4, 7, 8] por NASH de teste ≈ 0,984) é anterior a este recorte e não é o resultado de 4 h.

Em **8 h** o melhor pelo equilíbrio é `altR_004_08_8h_alt_8H_ALT_C0289` (10 inputs, 20 neurônios, equilíbrio 0,694, MAE 32,0 cm, E95 135 cm). A combinação C0289, já central no relatório de 28 de junho, permanece a montagem escolhida; a métrica de escolha, porém, deixa de ser o PERS geral de uma rodada única.

Em **12 h** o melhor é `004_conv_C0149_R01_T2_V1_3` (14 inputs, 28 neurônios, equilíbrio 0,690, MAE 40,9 cm, E95 125 cm). O teto de equilíbrio empata o 8 h escolhido, com MAE maior. Só quatro redes do horizonte cruzam equilíbrio 0,50: prever 12 h é viável em alguns recortes de evento, não estável no conjunto.

## 5. Discussão: o que os relatórios de processo acertaram e o que este rascunho muda

Os HTML em `pesquisas/rna-relatorio-*.html`, `relatorio-tecnico-8h.html`, `relatorio-8h-*.html` e `plano-exploracao-8h.html` são cadernos de uma bateria. Este rascunho (1) unifica os quatro horizontes no recorte já filtrado; (2) troca NASH de uma partição e PERS geral por equilíbrio + MAE/E95; (3) trata rotação de eventos como método, não como nota de rodapé; (4) separa família ALT/CONV de equação de saída; (5) mostra na metodologia só o quadro das variáveis principais e, nos resultados, só o melhor modelo de cada horizonte; (6) não reapresenta como resultado as redes com PERS negativa que aqueles relatórios ainda listavam.

O relatório visual de 4 h (5 de junho) acertou a intuição de que inputs de montante e a aceleração local importam, e avisou que NASH de validação alto com E95 ruim não escolhe modelo. O recorte de 117 redes 4 h confirma os dois pontos e descarta a combinação [1, 2, 4, 7, 8] como “modelo final”: aquela bateria era estreita demais.

O relatório técnico de 8 h (28 de junho) acertou a centralidade de C0289. Naquela rodada única, a CONV C0289 liderava o PERS geral (0,718). No recorte consolidado o equilíbrio escolhe a ALT C0289 da rotação 004. Entre candidatos com equilíbrio > 0,50, a CONV da mesma combinação ainda reduz o erro extremo: E95 mínimo 46 cm (`rot8h_002_24_8h_conv_8H_CONV_C0289`, MAE 19,4 cm), contra 101 cm no menor E95 da ALT nesse corte. Isso é ressalva para uma futura sombra operacional — não um segundo campeão na Tabela 1.

A comparação com Finck (2020) é apenas contextual: estações, período, filtros de chuva e horizonte de 24 h não coincidem. O que se pode afirmar é que NSE de teste da ordem de 0,99 em 2–4 h e ≈ 0,88–0,94 nos melhores 8–12 h é compatível com RNAs de nível em telemetria densa, e que o ganho que importa para alerta é o PERS, porque a persistência de 2 h já é uma previsão difícil de bater.

## 6. Limitações

- Os horizontes têm N muito diferentes (10, 117, 111, 44). O crescimento do MAE dos campeões com o horizonte é descritivo, não um teste controlado.
- Há poucos eventos de cheia; PERS e E95 no teste herdam a sorte da rotação. O spread entre recortes permanece o risco principal de superinterpretação.
- O campo `evento_teste` do 4 h aparece preenchido com o mesmo rótulo em 117 linhas; a leitura segura da partição 4 h é o campo `rotacao`.
- Não há 2 h CONV nem 4 h CONV no recorte qualificado: a comparação ALT/CONV só é justa em 8 h e 12 h, e mesmo aí o resultado principal não a promove a ranking.
- A conversão régua → HAND/mancha, a calibração de probabilidade e o uso operacional continuam bloqueados. Replay de 2 h por evento existe; reconciliação auditável de 8 h/12 h por evento ainda está pendente.
- Cópias no Google Drive pessoal dos relatórios de processo não puderam ser reabertas neste ambiente. A melhoria usa as versões já no repositório e o recorte consolidado do site.

## 7. Conclusões

O recorte consolidado de Santa Tereza sustenta quatro afirmações, e só elas, neste rascunho — cada uma ligada ao melhor modelo do horizonte:

1. Em 2 h, o MLP ALT de 15 inputs de nível (sem chuva) `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21` equilibra 0,969, com MAE de teste de 3,5 cm, e já é o feed principal ao vivo.
2. Em 4 h, o melhor é a montagem ampliada de 24 inputs com chuva, `V01_R10_T19-21_V1-3-5-15-17_nh48_nit10_cic100000` (equilíbrio 0,846; MAE 13,9 cm).
3. Em 8 h, o melhor pelo equilíbrio é ALT C0289, `altR_004_08_8h_alt_8H_ALT_C0289` (0,694; MAE 32,0 cm). A CONV da mesma combinação, quando equilibra, erra menos nos extremos — ressalva de discussão, não segundo resultado.
4. Em 12 h, o melhor é CONV C0149, `004_conv_C0149_R01_T2_V1_3` (0,690; MAE 40,9 cm). A viabilidade nesse horizonte continua pontual.

O próximo manuscrito deve acrescentar hidrogramas dos eventos de teste do campeão de cada horizonte, a tabela de rotação 4 h conferida contra as planilhas `.xlsx`, e a decisão explícita de qual 8 h (ALT equilíbrio vs CONV E95) entra em sombra — sem promover alerta.

## Referências

FINCK, J. S. *Previsão em tempo atual de níveis fluviais com redes neurais artificiais: aplicação à bacia do Rio Taquari-Antas/RS*. Dissertação (Mestrado) — Universidade Federal do Rio Grande do Sul, Porto Alegre, 2020. https://lume.ufrgs.br/handle/10183/213406

KITANIDIS, P. K.; BRAS, R. L. Real-time forecasting with a conceptual hydrologic model. 2. Applications and results. *Water Resources Research*, v. 16, n. 6, p. 1034–1044, 1980.

NASH, J. E.; SUTCLIFFE, J. V. River flow forecasting through conceptual models part I — A discussion of principles. *Journal of Hydrology*, v. 10, n. 3, p. 282–290, 1970.

PREVINE Taquari-Antas. Recorte auditável de modelos RNA de Santa Tereza. In: `index.html` (script `data`). Repositório GitHub, 2026.

PREVINE Taquari-Antas. Relatórios de processo RNA 4 h e 8 h. In: `pesquisas/rna-relatorio-geral.html`; `pesquisas/relatorio-tecnico-8h.html`; `pesquisas/plano-exploracao-8h.html`. 2026.
