# Especificação reutilizável — ficha, triagem e cenários

Versão da especificação: **1.0.0**. Esta especificação define artefatos que
podem ser gerados a partir do GeoPackage/GeoJSON sem alterar a fonte. O arquivo
`ESPECIFICACAO_FICHA_TRIAGEM_CENARIOS.json` contém a mesma estrutura em forma
machine-readable.

## 1. Ficha municipal ou da área selecionada

### Objetivo

Entregar uma página HTML/PDF e um JSON que permitam à Defesa Civil responder:
“qual é o local, qual população está no recorte, quais grupos e condições
foram medidos, que capacidade municipal existe, quais pontos foram localizados
e quais limites impedem uma conclusão de risco?”.

### Campos obrigatórios

| Bloco | Campos |
|---|---|
| Identidade | nome, código IBGE, UF, data de geração, versão do pacote, hash de entrada |
| Geografia | camada/grão, área selecionada, CRS de entrada, `na_bacia`, `pct_na_bacia`, limites da seleção e número de feições |
| População | população do recorte, população municipal inteira quando aplicável, população estimada dentro da bacia e regra de soma |
| Indicadores | indicador, valor bruto, unidade, denominador, percentual, nulos e flags `sigilo_<campo>` |
| Capacidade | ICM faixa, pontuação e prioridade, sempre rotulado como municipal |
| Serviços | tipo, número de pontos publicados, data de captura e cobertura; “sem ponto publicado” não é “zero serviço” |
| Perigo | camada, fonte, data, feições intersectadas, cobertura espacial e declaração de que ausência de polígono não implica ausência de perigo |
| Proveniência | URL/arquivo de origem, consulta, data de captura, transformação, licença/atribuição e revisão |
| Limitações | texto curto visível na primeira página e lista detalhada no anexo |

### Saídas

- `ficha_<escopo>_<codigo>.html`: leitura humana, com tabela e fontes clicáveis;
- `ficha_<escopo>_<codigo>.pdf`: cópia para reunião, sem controles de tela;
- `ficha_<escopo>_<codigo>.json`: mesmos números e metadados para auditoria;
- `ficha_<escopo>_<codigo>_geojson.zip`: somente se a geometria da seleção puder
  ser redistribuída, com CRS e licença no README.

O título deve dizer “vulnerabilidade social” e o ano de referência. Se perigo,
ICM ou serviço aparecerem, eles devem ser blocos separados, com fonte e data.
Não criar uma nota única de “risco” sem método e camada de perigo validados.

## 2. Triagem para planejamento

Triagem é uma lista de trabalho, não um diagnóstico de risco. Ela pode ordenar
locais para vistoria ou atualização de cadastro, desde que a regra seja exibida
junto com cada resultado.

### Entrada mínima

1. camada e grão (`municipio`, `setor` ou `grade`);
2. indicadores escolhidos e unidade (`abs` ou `pct`);
3. filtros de cobertura (`na_bacia=1`, município, seleção espacial);
4. regra de ordenação ou pesos, com versão e autor;
5. tratamento explícito para nulos, supressões e ausência de ponto de serviço.

### Regra segura de exemplo

Produzir colunas separadas para:

- percentil ou classe do indicador social;
- classe ICM (A–D) e pontuação municipal;
- interseção com perigo oficial disponível, quando houver;
- cobertura de serviço e data do cadastro;
- `status_dado` (`publicado`, `suprimido`, `sem_ponto_publicado`,
  `fora_cobertura`, `não_aplicável`).

Uma ordenação composta só deve ser ativada quando todos os pesos, direções e
denominadores estiverem presentes. Se uma camada de perigo não cobre a unidade,
usar `fora_cobertura`, nunca pontuação zero. O rótulo público deve ser
“triagem para revisão”, “prioridade de vistoria” ou equivalente, e não “maior
risco”.

### Saída mínima

CSV/GeoJSON com os campos originais, os componentes da regra, a posição no
ranking, a versão da regra, a cobertura, o motivo da inclusão e um link para a
ficha. O relatório deve listar quantos registros ficaram de fora e por quê.

## 3. Proveniência e auditoria

Cada camada e cada execução precisam registrar:

```json
{
  "source_name": "IBGE Censo 2022",
  "source_url": "https://…",
  "source_query": "where=…&outSR=4326",
  "captured_at": "2026-08-18T00:20:38Z",
  "reference_period": "2022",
  "input_sha256": "…",
  "output_sha256": "…",
  "crs": "EPSG:4326",
  "transformations": ["recorte por ponto representativo", "join por cod_mun"],
  "license_or_attribution": "IBGE / SEMA-DRH / IEDE-RS / SGB",
  "coverage": "…",
  "limitations": ["…"],
  "review_status": "revisado|pendente|bloqueado"
}
```

O `catalogo.json` é a fonte dos hashes e contagens do pacote atual. A ficha
deve copiar esses valores, não recalculá-los silenciosamente. Mudanças de
malha, denominador, consulta ou classificação exigem nova versão e uma nota de
quebra metodológica.

## 4. Atualização temporal

- Censo 2022 permanece como retrato até que um novo agregado oficial seja
  publicado. Não interpolar população ou grupos entre anos.
- IEDE, ICM e perigo devem ter data de captura/atualização visível; se a origem
  não fornecer data, registrar `captura_sem_data_na_fonte` e não chamá-la de
  “atual”.
- A cada atualização, comparar contagens, bounds, CRS, chaves, nulos/supressões,
  cobertura de serviços e soma dos agregados municipais.
- A tabela temporal deve manter uma coluna `comparabilidade` com valores
  `comparável`, `comparável_com_ressalva` ou `não_comparável`.
- Um indicador só entra em série quando conceito, universo, unidade, malha e
  regra de supressão são compatíveis. Caso contrário, mostrar as versões lado a
  lado com explicação.

## 5. Cenários de perigo e exposição

Um cenário só pode ser publicado após uma camada de perigo regional validada.
O produto atual do SGB em Santa Tereza é setorizado e não atende esse requisito.

### Entradas obrigatórias

- fonte e versão da superfície ou polígonos de perigo;
- tipo de perigo, nível/cota/profundidade e data ou janela do cenário;
- CRS e método de interseção;
- unidade de exposição (setor, grade, domicílio ou outro) e regra de soma;
- população, domicílios e serviços com data e cobertura;
- distinção entre observado, modelado e proxy.

### Saídas obrigatórias

- pessoas, domicílios e pontos intersectados por classe de perigo;
- área e proporção da unidade atingida;
- incerteza ou intervalo quando o perigo for modelado;
- lista de unidades fora da cobertura;
- mapa, tabela e ficha com o cenário, fonte, data, CRS e limitações.

Não somar pessoas de municípios inteiros a setores dentro da bacia. Não tratar
uma interseção geométrica como população atingida sem um método de ponderação
documentado. A validação mínima inclui teste de CRS, bounds, geometrias vazias,
duplicidade de chaves, reconciliação de totais e inspeção visual de pelo menos
uma unidade por classe de perigo.

## 6. Critérios de aceite

- [ ] fonte, data, CRS, grão e denominador aparecem no artefato;
- [ ] nulos e supressões não foram convertidos em zero;
- [ ] ausência de serviço e fora de cobertura estão separados;
- [ ] ICM está marcado como municipal;
- [ ] perigo está separado de vulnerabilidade e risco;
- [ ] regra de triagem e pesos são reproduzíveis;
- [ ] versão/hash do pacote está na ficha e no JSON;
- [ ] PDF/HTML e GeoJSON/CSV reconciliam com o `catalogo.json`;
- [ ] o relatório registra o que não pode ser concluído com os dados atuais.
