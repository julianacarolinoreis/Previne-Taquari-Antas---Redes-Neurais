# Arquitetura G040: HEC-HMS contínuo/SMA + MGB + HEC-RAS + assimilação + ensemble

## Objetivo

Evoluir o PREVINE para uma cadeia de pesquisa integrada para **toda a bacia Taquari–Antas (G040)**, preservando os modelos existentes e separando claramente:

1. forçantes meteorológicas e estado antecedente;
2. transformação chuva–vazão;
3. propagação hidrológica/hidráulica;
4. assimilação de observações;
5. ensemble e avaliação;
6. previsão de impacto.

Este pacote é de **pesquisa**. Não é sistema oficial de alerta nem autorização de evacuação.

## Correção estrutural importante: 32 != 145

Existem duas camadas diferentes no repositório e elas não devem ser confundidas.

### 32 polígonos IEDE / 7 UGs

Os 32 polígonos são usados como:

- enquadramento/gestão;
- auditoria espacial;
- apoio para inventário de postos;
- apoio para QC e agregações de chuva.

Eles **não são automaticamente sub-bacias computacionais do HEC-HMS**. A conectividade inferida entre esses polígonos é apenas diagnóstica.

### 145 sub-bacias + 72 reaches do HEC

O relatório de julho de 2026 registra um modelo HEC-HMS para a G040 com:

- **145 sub-bacias**;
- **72 reaches**;
- Muçum e Estrela como pontos de controle citados;
- SCS Curve Number + SCS Unit Hydrograph no modelo histórico;
- Muskingum-Cunge no roteamento.

O inventário foi recuperado do relatório, mas os arquivos nativos de geometria/topologia do projeto HEC ainda precisam ser recuperados ou reconstruídos e verificados. Portanto:

> os 145 registros são o **alvo HEC**, mas ainda não constituem uma rede executável reproduzida neste scaffold.

Nenhum algoritmo deve inventar a ligação entre eles.

## Arquitetura alvo

```text
pluviômetros + radar/satélite + ECMWF/IFS
                  │
                  ▼
        chuva horária espacializada
                  │
                  ├─────────────────────┐
                  │                     │
          estado antecedente            │
        (SMA/MGB + observações)         │
                  │                     │
                  ▼                     ▼
            HEC-HMS SMA                MGB
                  │                     │
                  └──────────┬──────────┘
                             ▼
                      vazões por ramo
                             │
                             ▼
                      HEC-RAS 1D/2D
                   Diffusion Wave ↔ SWE
                             │
                             ▼
          nível + velocidade + profundidade + mancha
                             │
                             ▼
                          PREVINE
                             ▲
                             │
              assimilação de observações
                             │
                 RNAs como membro independente
```

## 1. Chuva e condição antecedente

A chuva não deve ser reduzida a um único acumulado da bacia. O acumulado integral é um **diagnóstico**, enquanto o modelo precisa preservar a distribuição espacial e temporal.

### Chuva observada

Política:

- precipitação horária como acumulado do intervalo;
- ausência de dado nunca vira zero;
- fonte, unidade, timestamp e intervalo de acumulação auditáveis;
- série bruta preservada;
- acumulados de 1, 3, 6, 12, 24, 48 e 72 h como diagnósticos;
- espacialização final sobre as unidades hidrológicas verificadas, não imposta pelos 32 polígonos de gestão.

### Chuva prevista

Para ECMWF/IFS:

- preservar ciclo;
- preservar lead time;
- preservar membro/controle;
- arquivar rodadas;
- marcar explicitamente a transição observado → previsto;
- integrar espacialmente sobre as unidades efetivamente usadas por cada modelo.

### Umidade do solo

No HEC-HMS, o caminho proposto é o **Soil Moisture Accounting (SMA)** em simulação contínua.

No MGB, o estado antecedente é parte do balanço hídrico contínuo do modelo.

Produto externo de umidade do solo pode entrar como:

- diagnóstico;
- comparação;
- eventualmente assimilação.

Não deve substituir parâmetros/estados internos sem método e validação.

## 2. HEC-HMS contínuo/SMA

O objetivo é evoluir o modelo de eventos para uma representação contínua em que a resposta a uma nova chuva depende do estado anterior da bacia.

O scaffold gera **145 linhas**, uma para cada sub-bacia registrada no inventário do relatório.

Ele preserva como referência:

- área;
- CN histórico;
- comprimento e declividade de canal reportados;
- Tc/Kirpich;
- lag SCS;
- parâmetros calibrados do evento 2 quando presentes.

Esses parâmetros antigos **não são convertidos automaticamente em SMA**.

Campos SMA permanecem vazios até existir fonte e justificativa para:

- canopy storage;
- surface storage;
- soil storage;
- tension storage;
- soil percolation;
- groundwater 1/2;
- condições iniciais;
- ET potencial.

### Gate HEC/SMA

Bloquear promoção enquanto faltar:

- geometria/topologia verificadas das 145 unidades;
- parâmetros SMA com proveniência;
- warm-up adequado;
- chuva auditada;
- vazões/níveis de validação;
- validação independente;
- avaliação simultânea de volume, pico e timing.

## 3. MGB

O MGB entra como **modelo independente**, não como substituto automático do HEC-HMS.

Preparação mínima:

- MDT hidrologicamente consistente;
- rede;
- mini-bacias;
- unidades de resposta hidrológica;
- solos;
- uso/cobertura;
- meteorologia;
- precipitação;
- vazões observadas para calibração/validação.

A discretização do MGB deve ser derivada para o próprio MGB. Nem os 32 polígonos de gestão nem as 145 unidades do inventário HEC são impostos automaticamente.

Comparações:

- volume;
- NSE;
- KGE;
- PBIAS;
- pico;
- erro de pico;
- horário do pico;
- desempenho por faixa de vazão;
- estabilidade entre eventos.

## 4. HEC-RAS 1D/2D

O HEC-RAS recebe hidrogramas do HEC-HMS/MGB.

Estratégia:

- **1D** onde a calha/seções representam adequadamente o escoamento;
- **2D** em planícies e áreas urbanas onde o fluxo lateral/multidirecional é relevante;
- pontes e outras estruturas explicitamente, quando houver dados;
- condição de jusante capaz de representar remanso no baixo Taquari quando necessário.

### Diffusion Wave × SWE

**Diffusion Wave** é o baseline de desenvolvimento.

**SWE** deve ser comparado especialmente em:

- pontes/contrações;
- confluências;
- curvas;
- expansões;
- vales encaixados;
- fluxo urbano multidirecional;
- trechos com remanso;
- situações em que momento/inércia possam alterar nível, velocidade ou tempo de chegada.

A equação é selecionada por comparação com observações, não por conveniência.

### Domínios iniciais

Prioridade:

1. Santa Tereza;
2. Muçum;
3. Encantado;
4. Arroio do Meio;
5. Lajeado;
6. Estrela;
7. Taquari.

Santa Tereza e Muçum já possuem ativos de terreno/mancha que tornam bons pilotos. Estrela aparece também no inventário do HEC histórico como ponto de controle.

## 5. Assimilação

Assimilação não é apenas deslocar visualmente a curva para encostar no observado.

Cada atualização deve registrar:

- horário da observação;
- estação/sensor;
- variável;
- valor/unidade;
- QC;
- estado temporal do modelo;
- método de atualização.

Primeira versão possível:

- atualização determinística de estado/condição de contorno documentada.

Etapas posteriores:

- métodos sequenciais/ensemble, após validação.

## 6. Ensemble

Membros mínimos:

- HEC-HMS SMA;
- MGB;
- RNA local validada.

Não usar média simples por padrão.

Cada membro precisa de skill histórico e pseudo-operacional. A saída deve informar:

- estimativa central;
- dispersão;
- divergência entre modelos;
- confiança;
- motivo de confiança baixa.

## 7. Previsão de impacto

Somente após gates hidrológicos e hidráulicos:

- nível;
- vazão;
- horário do pico;
- profundidade;
- velocidade;
- mancha;
- tempo até extravasamento;
- exposição de setores/quadras/equipamentos;
- rotas candidatas fora da mancha.

A interface deve distinguir explicitamente:

- observado;
- previsto;
- cenário.

## 8. Sequência de execução

### Fase A — base G040

- manter os 32 polígonos como camada de gestão/auditoria;
- recuperar/reconstruir e verificar a rede nativa dos 145 HEC + 72 reaches;
- fechar matriz de postos;
- fechar chuva horária observada e prevista espacialmente;
- selecionar ET;
- preservar tudo com proveniência.

### Fase B — HEC-HMS SMA

- criar o projeto contínuo;
- atribuir parâmetros iniciais apenas com fonte;
- definir warm-up;
- calibrar em múltiplos períodos/eventos;
- validar fora da amostra;
- comparar com o modelo de evento histórico.

### Fase C — MGB

- preparar mini-bacias/HRUs;
- rodar hindcast;
- calibrar/validar;
- comparar com HEC-HMS.

### Fase D — HEC-RAS

- pilotos Santa Tereza/Muçum;
- expandir gradualmente;
- comparar Diffusion Wave e SWE;
- incorporar pontes/estruturas;
- representar remanso quando necessário.

### Fase E — assimilação + ensemble

- generalizar atualização multiestação;
- rodar avaliação pseudo-operacional;
- combinar membros somente após skill documentado.

### Fase F — impacto

- mapas e indicadores;
- validação histórica;
- governança antes de qualquer uso operacional.

## 9. Métricas mínimas

### Hidrologia

- NSE;
- KGE;
- PBIAS;
- RMSE/MAE;
- erro de volume;
- erro absoluto/relativo de pico;
- erro de timing do pico;
- subida/descida;
- desempenho por horizonte.

### Hidráulica

- erro de cota;
- tempo de chegada;
- CSI/F1 de inundação;
- erro de profundidade;
- plausibilidade/erro de velocidade;
- sensibilidade a Manning;
- sensibilidade à malha/seções;
- sensibilidade às condições de contorno.

### Ensemble

- skill por membro;
- dispersão;
- frequência de divergência;
- cobertura da faixa;
- erro condicionado ao estado antecedente.

## 10. Regra de promoção

Um componente só sai de `research` para `candidate` quando:

1. entrada está auditada;
2. parâmetros são rastreáveis;
3. treino/calibração e validação são separados;
4. há múltiplos eventos/períodos;
5. magnitude e timing são avaliados juntos;
6. limitações acompanham a saída.

`candidate` só vira `operational` após validação independente, procedimentos locais e governança explícita.

## Arquivos

- `config/g040_hydro_stack_v1.json`: contrato central;
- `scripts/build_g040_hydro_stack_scaffold.py`: cria templates/manifests;
- `scripts/test_g040_hydro_stack_scaffold.py`: testes de integridade;
- `.github/workflows/g040-hydro-stack-scaffold.yml`: CI do scaffold;
- `.github/workflows/hec-g040-full-basin-architecture.yml`: auditoria/persistência da camada G040 e encadeamento do scaffold.
