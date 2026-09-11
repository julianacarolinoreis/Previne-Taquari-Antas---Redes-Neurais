# Previsão de nível em Santa Tereza com redes neurais: síntese do recorte consolidado de 282 modelos MLP (2–12 h)

**Rascunho de artigo · pesquisa FAPERGS · não é alerta oficial**

Juliana Carolina Reis; Guilherme Garcia de Oliveira; Fernanda Vier  
Universidade Federal do Rio Grande do Sul (UFRGS) · PREVINE Taquari-Antas · processo FAPERGS 24/2551-0002124-8  

A lista de autoria para submissão a periódico permanece a confirmar com a equipe do projeto. Versão web com tabelas reconstruídas do recorte: `pesquisas/artigo-rna-santa-tereza.html`.

## Resumo

As inundações de 2023–2024 na bacia Taquari–Antas tornaram urgente antecipar o nível do rio com a rede telemétrica já instalada. Este rascunho sintetiza o recorte consolidado de **282 perceptrons multicamadas** treinados em MATLAB para a estação de Santa Tereza (ANA/SGB 86472600), com horizontes de 2, 4, 8 e 12 horas. A qualificação exige persistência (PERS) positiva em treino, validação, teste e série completa. A métrica de escolha é o *score de equilíbrio* — o menor PERS entre esses recortes — e não o Nash–Sutcliffe isolado de uma partição.

O erro mediano no teste cresce com a antecedência: **5,0 cm em 2 h**, 13,8 cm em 4 h, 31,2 cm em 8 h e 47,9 cm em 12 h. Os dez modelos de 2 h (todos ALT, sem chuva) equilibram acima de 0,90; o campeão `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21` (equilíbrio 0,969; MAE 3,5 cm) é também o modelo principal do feed ao vivo. Em 8 h, a família ALT generaliza melhor (mediana de equilíbrio 0,461 contra 0,286 da CONV), mas, entre candidatos com equilíbrio > 0,50, a CONV reduz o erro extremo (E95 mínimo 46 cm contra 101 cm). Em 12 h só quatro redes cruzam equilíbrio 0,50; a melhor é CONV (0,690). Os relatórios de processo de junho de 2026 ranqueavam baterias únicas por NASH ou PERS geral: o recorte consolidado muda a leitura porque a rotação de eventos e o equilíbrio separam recorde de generalização.

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

Cada modelo é um MLP de três camadas, treinado em MATLAB por retropropagação com gradiente adaptativo, até 100 mil ciclos, com várias inicializações (nit típico = 10) e retenção do ciclo de menor erro na validação. O catálogo de entrada tem 71 variáveis; cada rede usa um subconjunto (mediana de 15 inputs e 30 neurônios no 2 h; 20 e 40 no 4 h; 10 e 20 no 8 h ALT). A mediana da varredura é de **dois neurônios por input**.

As siglas **ALT** e **CONV** identificam famílias/rodadas do planilhão; não devem ser lidas, sozinhas, como duas equações de saída. Na ficha do modelo ao vivo de 2 h, ALT significa que a rede prevê a *variação* do nível e o nível previsto é o nível atual mais essa variação. O forward-pass desse `.mat` foi reproduzido em Python com RMSE nulo: normalização por média/desvio, `logsig` na oculta e na saída, desnormalização linear da variação.

### 3.2 Métricas

A persistência (PERS) mede o ganho sobre a previsão ingênua “daqui a *N* horas o nível será o de agora”, na linhagem de Kitanidis e Bras (1980). PERS = 1 é perfeito; 0 empata com a ingênua; negativo é pior do que não ter modelo. Complementam a leitura o coeficiente de Nash–Sutcliffe (Nash e Sutcliffe, 1970), o MAE e o percentil 95 do erro absoluto (E95), todos em centímetros na régua.

O **score de equilíbrio** é o mínimo entre PERS geral, de validação e de teste. Um recorde só no conjunto completo, se a validação ou o teste caem, não entra no topo. O recorte publicado já aplica o filtro: os 282 modelos têm os quatro PERS positivos. Achados de rodadas anteriores que citam persistência negativa descrevem redes *excluídas*, não este recorte.

## 4. Resultados

A Tabela 1 resume o recorte. Não há 2 h CONV nem 4 h CONV qualificados: nesses horizontes só a família ALT passou no filtro. O 8 h e o 12 h comparam as duas famílias. Fonte: `index.html#data`, tabelas em `assets/data/artigo_rna_santa_tereza.json`.

**Tabela 1. Recorte consolidado de Santa Tereza (medianas no teste).**

| Horizonte | Família | N | Equil. med. | Equil. máx. | PERS teste | MAE teste (cm) | E95 teste (cm) | N > 0,50 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2h | ALT | 10 | 0,945 | 0,969 | 0,945 | 5,0 | 18,6 | 10 |
| 4h | ALT | 117 | 0,801 | 0,846 | 0,872 | 13,8 | 52,7 | 117 |
| 8h | ALT | 66 | 0,461 | 0,694 | 0,627 | 31,2 | 114,6 | 22 |
| 8h | CONV | 45 | 0,286 | 0,651 | 0,363 | 30,5 | 92,9 | 5 |
| 12h | ALT | 22 | 0,380 | 0,574 | 0,575 | 42,5 | 126,9 | 1 |
| 12h | CONV | 22 | 0,195 | 0,690 | 0,315 | 53,2 | 132,3 | 3 |

O MAE mediano no teste aumenta de forma monótona com o horizonte — o comportamento esperado de um modelo autorregressivo de nível, e o argumento mais simples contra tratar 2 h e 12 h com a mesma tolerância.

### 4.1 Horizonte de 2 h

Os dez modelos 2 h compartilham a mesma montagem de 15 inputs (nível local, diferenças e acelerações, mais montante) e 30 neurônios. Nenhum usa chuva. A mediana de equilíbrio é 0,945; o pior ainda equilibra 0,903. O campeão, `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21`, testa os eventos 10, 15 e 16, equilibra 0,969, tem MAE de teste 3,5 cm e E95 10,4 cm. É o modelo `principal` do feed ao vivo. A diferença entre o primeiro e o décimo é pequena no MAE (3,5 a 6,3 cm) e maior no E95 (10,4 a 23,5 cm) — a cauda do erro, não a média, separa rotações.

### 4.2 Horizonte de 4 h

São 117 redes ALT, todas com chuva média de 36 h, equilíbrio mediano 0,801 e MAE mediano 13,8 cm. Todas equilibram acima de 0,50. O topo da rotação R10 (24 inputs, 48 neurônios) chega a equilíbrio 0,846. Vários identificadores (V01, V05, V06, V07) repetem a mesma métrica: são inicializações equivalentes, não campeões independentes. A bateria de 5 de junho (20 rodadas, recomendação da combinação de inputs [1, 2, 4, 7, 8] por NASH de teste ≈ 0,984) é anterior a este recorte e não deve ser citada como resultado final de 4 h.

### 4.3 Horizonte de 8 h

Aqui o recorte corrige o relatório técnico de 28 de junho. Naquela rodada única, a CONV C0289 liderava o PERS geral (0,718). No recorte consolidado, com rotações:

- ALT tem mediana de equilíbrio **0,461** (66 redes; 22 acima de 0,50). A melhor é `altR_004_08_8h_alt_8H_ALT_C0289` (equilíbrio 0,694; MAE 32,0 cm; E95 135 cm).
- CONV tem mediana de equilíbrio **0,286** (45 redes; só 5 acima de 0,50), mas PERS geral mediano alto (0,743). Sinal clássico de sobreajuste da métrica agregada.
- Entre candidatos com equilíbrio > 0,50, o menor E95 da CONV é **46 cm** (`rot8h_002_24_8h_conv_8H_CONV_C0289`, MAE 19,4 cm); o menor E95 da ALT no mesmo corte é **101 cm**. Nos extremos, a CONV desta família ainda é mais robusta.

A combinação C0289 permanece central — o que o relatório de junho acertou — mas a escolha entre ALT e CONV deixa de ser um único ranking de PERS geral. Equilíbrio favorece ALT C0289 na rotação 004; erro de cauda favorece CONV C0289 na rotação 002.

A chuva discrimina no 8 h mesmo dentro do recorte já filtrado: 105 redes com chuva têm equilíbrio mediano 0,438 e MAE 31,2 cm; as 6 sem chuva caem para equilíbrio 0,161 e MAE 45,1 cm. A amostra sem chuva é pequena: leia como indício, não como experimento controlado.

### 4.4 Horizonte de 12 h

Quarenta e quatro redes, metade ALT e metade CONV, todas com chuva. Só quatro cruzam equilíbrio 0,50. A melhor é `004_conv_C0149_R01_T2_V1_3` (equilíbrio 0,690; MAE 40,9 cm; E95 125 cm). A ALT da mesma combinação equilibra 0,574. Prever 12 h à frente é viável em alguns recortes de evento; não é estável no conjunto. O teto de equilíbrio (0,690) empata o melhor 8 h ALT, com MAE bem maior.

### 4.5 Campeões por horizonte

| H | Fam. | Modelo | Rotação | Equil. | PERS teste | MAE (cm) | E95 (cm) | Chuva | Inputs | Nh |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|
| 2h | ALT | `009_alt_STZ_2H_R09_T10-15-16_V1-5-12-17-21` | R09 | 0,969 | 0,969 | 3,5 | 10,4 | não | 15 | 30 |
| 4h | ALT | `V01_R10_T19-21_V1-3-5-15-17_nh48_nit10_cic100000` | R10 | 0,846 | 0,876 | 13,9 | 52,7 | sim | 24 | 48 |
| 8h | ALT | `altR_004_08_8h_alt_8H_ALT_C0289` | altR_004 | 0,694 | 0,694 | 32,0 | 135,0 | sim | 10 | 20 |
| 12h | CONV | `004_conv_C0149_R01_T2_V1_3` | R01_T2_V1_3 | 0,690 | 0,696 | 40,9 | 125,3 | sim | 14 | 28 |

## 5. Discussão: o que os relatórios de processo acertaram e o que este rascunho muda

Os HTML em `pesquisas/rna-relatorio-*.html`, `relatorio-tecnico-8h.html`, `relatorio-8h-*.html` e `plano-exploracao-8h.html` são cadernos de uma bateria. Este rascunho (1) unifica os quatro horizontes no recorte já filtrado; (2) troca NASH de uma partição e PERS geral por equilíbrio + MAE/E95; (3) trata rotação de eventos como método, não como nota de rodapé; (4) separa família ALT/CONV de equação de saída; (5) corrige a leitura de 8 h (CONV “ganha” no geral, ALT generaliza, CONV segura a cauda); (6) não reapresenta como resultado as redes com PERS negativa que aqueles relatórios ainda listavam.

O relatório visual de 4 h (5 de junho) acertou a intuição de que inputs de montante e a aceleração local importam, e avisou que NASH de validação alto com E95 ruim não escolhe modelo. O recorte de 117 redes 4 h confirma os dois pontos e descarta a combinação [1, 2, 4, 7, 8] como “modelo final”: aquela bateria era estreita demais.

O relatório técnico de 8 h (28 de junho) acertou a centralidade de C0289 e a irregularidade da ALT na rodada original. Errou ao encerrar a comparação CONV vs ALT naquela amostra de 32 redes. As rotações posteriores — exatamente o plano de exploração de 29 de junho — eram o experimento que faltava; agora elas estão no recorte.

A comparação com Finck (2020) é apenas contextual: estações, período, filtros de chuva e horizonte de 24 h não coincidem. O que se pode afirmar é que NSE de teste da ordem de 0,99 em 2–4 h e ≈ 0,88–0,94 nos melhores 8–12 h é compatível com RNAs de nível em telemetria densa, e que o ganho que importa para alerta é o PERS, porque a persistência de 2 h já é uma previsão difícil de bater.

## 6. Limitações

- Os horizontes têm N muito diferentes (10, 117, 111, 44). Comparar medianas entre horizontes é descritivo, não um teste controlado.
- Há poucos eventos de cheia; PERS e E95 no teste herdam a sorte da rotação. O spread entre recortes permanece o risco principal de superinterpretação.
- O campo `evento_teste` do 4 h aparece preenchido com o mesmo rótulo em 117 linhas; a leitura segura da partição 4 h é o campo `rotacao`.
- Não há 2 h CONV nem 4 h CONV no recorte qualificado: a comparação ALT/CONV só é justa em 8 h e 12 h.
- A conversão régua → HAND/mancha, a calibração de probabilidade e o uso operacional continuam bloqueados. Replay de 2 h por evento existe; reconciliação auditável de 8 h/12 h por evento ainda está pendente.
- Cópias no Google Drive pessoal dos relatórios de processo não puderam ser reabertas neste ambiente. A melhoria usa as versões já no repositório e o recorte consolidado do site.

## 7. Conclusões

O recorte consolidado de Santa Tereza sustenta quatro afirmações, e só elas, neste rascunho:

1. Antecipar 2 h com MLP ALT de 15 inputs de nível (sem chuva) é estável nas dez rotações publicadas; o campeão já é o feed principal ao vivo, com MAE de teste de 3,5 cm.
2. Antecipar 4 h é igualmente denso no recorte (117 ALT com chuva, todas com equilíbrio > 0,50), com MAE mediano de 14 cm.
3. Em 8 h não existe vencedor único: ALT generaliza melhor; CONV, quando equilibra, erra menos nos extremos. C0289 permanece a combinação a discutir, agora com duas leituras.
4. Em 12 h a viabilidade é pontual (quatro redes acima de 0,50). Mais eventos e novas montagens ainda são pesquisa aberta, não produto.

O próximo manuscrito deve acrescentar hidrogramas dos eventos de teste do campeão de cada horizonte, a tabela de rotação 4 h conferida contra as planilhas `.xlsx`, e a decisão explícita de qual 8 h (ALT equilíbrio vs CONV E95) entra em sombra — sem promover alerta.

## Referências

FINCK, J. S. *Previsão em tempo atual de níveis fluviais com redes neurais artificiais: aplicação à bacia do Rio Taquari-Antas/RS*. Dissertação (Mestrado) — Universidade Federal do Rio Grande do Sul, Porto Alegre, 2020. https://lume.ufrgs.br/handle/10183/213406

KITANIDIS, P. K.; BRAS, R. L. Real-time forecasting with a conceptual hydrologic model. 2. Applications and results. *Water Resources Research*, v. 16, n. 6, p. 1034–1044, 1980.

NASH, J. E.; SUTCLIFFE, J. V. River flow forecasting through conceptual models part I — A discussion of principles. *Journal of Hydrology*, v. 10, n. 3, p. 282–290, 1970.

PREVINE Taquari-Antas. Recorte auditável de modelos RNA de Santa Tereza. In: `index.html` (script `data`). Repositório GitHub, 2026.

PREVINE Taquari-Antas. Relatórios de processo RNA 4 h e 8 h. In: `pesquisas/rna-relatorio-geral.html`; `pesquisas/relatorio-tecnico-8h.html`; `pesquisas/plano-exploracao-8h.html`. 2026.
