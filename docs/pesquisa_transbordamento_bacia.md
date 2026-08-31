# Pesquisa de transbordamento da bacia Taquari–Antas

Este documento descreve a camada integrada publicada em
`assets/data/research_basin_screening_latest.json` e no
`dashboard_bacia.html`. Ela organiza evidências para responder, em modo de
pesquisa, **onde está chovendo, como o rio está respondendo e o que cada modelo
estima por horizonte**.

## O que entra na rodada

1. **Nível observado:** leitura do robô ao vivo de ANA/SGB, com horário, idade e
   fonte. A previsão curta de +2 h/+4 h continua sendo a saída do modelo de
   nível, sem ser misturada à chuva de longo prazo.
2. **Chuva prevista:** ECMWF IFS no ponto e uma rede auditada de células
   associadas aos pontos monitorados a montante. Os acumulados são em mm e não
   são probabilidade.
3. **Montante/cabeceiras:** a média simples e o máximo das células únicas são
   mostrados como *proxy da rede monitorada a montante*. Não são uma máscara
   hidrológica, não têm ponderação por área e não representam a média oficial da
   bacia. Para Muçum, a referência atual é compartilhada e fica marcada como não
   independente.
4. **Eventos:** picos acima da cota de pesquisa (1.500 cm em Santa Tereza e
   1.800 cm em Muçum), com candidatos e situação de revisão preservados.
5. **Risco experimental:** score/probabilidade dos artefatos publicados,
   sempre com fonte, idade, estado e regra binária de pesquisa (`>= 50%`).

Na dashboard integrada, um score cuja fonte esteja `STALE` ou sem a marca
`usable_as_current_probability: true` aparece como `—` na leitura principal.
O valor arquivado continua visível apenas como valor de auditoria, com a data
da rodada. Assim, atualizar a página ou usar **Atualizar dados** não transforma
uma rodada antiga em uma estimativa atual.

## Separação temporal e de fontes

O feed não usa o nível futuro (`NIVEL_FUTURO`) como entrada e não preenche
horas ausentes por interpolação. A leitura atual, a previsão meteorológica, o
proxy espacial, o score da RNA e a probabilidade são campos distintos. Se um
feed fica velho ou tem cobertura parcial, a interface mostra `atrasado` ou
`parcial`; isso nunca é convertido em “não vai inundar”.

## O que está implementado automaticamente

`.github/workflows/santa-weather-feed.yml` atualiza Santa Tereza de hora em
hora. `.github/workflows/research-basin.yml` integra as duas estações por agenda,
manualmente e após os workflows de previsão. A sequência é:

```text
feeds publicados → contexto integrado → QA de schema/proveniência → commit
somente se mudou → GitHub Pages
```

O robô é idempotente para os mesmos artefatos. Os relatórios e hashes ficam no
JSON para auditoria; o dashboard só consome o artefato publicado.

## Gates científicos ainda explícitos

- `hydrologic_mask`: a rede de pontos a montante já é atualizada, mas ainda não
  há outlet, rede hidrográfica, acumulação de fluxo regional e ponderação por
  área validados.
- `mucum_independent_headwater`: Muçum precisa de um recorte espacial próprio;
  a referência Santa Tereza não deve ser lida como chuva local de Muçum.
- `soil_observation`: a umidade atual é variável modelada; não há sensor local
  de saturação publicado para as estações.
- `radar_qpe`: o radar/QPE CEMADEN permanece opcional até que o download e a
  autenticação sejam reproduzíveis.
- `travel_time`: há âncoras nos modelos ao vivo, mas a relação precisa ser
  validada por evento antes de virar regra da bacia.
- `probability_calibration`: cinco eventos em Santa Tereza e quatro candidatos
  em Muçum, sem negativos independentes e com fontes diferentes, não sustentam
  uma probabilidade operacional calibrada.

Esses gates não impedem a pesquisa: eles impedem apenas que uma aproximação
seja apresentada como alerta ou como certeza. Quando uma fonte nova for
adicionada, o robô a incorpora e mantém a mesma trilha de auditoria.

## Pesquisa de fontes oficiais para os próximos recortes

Foi incluído no feed e na dashboard o arquivo
`assets/data/research_source_registry.json`. Ele é um registro de fontes
identificadas, não um catálogo de dados já aprovados. As prioridades são:

- **ANA BHO 2017 / BHO6:** serviço consultável da [rede de trechos de
  drenagem](https://www.snirh.gov.br/arcgis/rest/services/SPR/BHO2017_50K_TRECHODRENAGEM/FeatureServer/0)
  e [metadados da BHO6](https://metadados.snirh.gov.br/geonetwork/srv/api/records/b228d007-6d68-46e5-b30d-a1e191b2b21f),
  para conferir rede, áreas contribuintes, outlet e códigos Otto.
- **INPE TOPODATA:** [modelo digital de elevação nacional](https://www.dsr.inpe.br/topodata/),
  candidato a derivar direção e acumulação de fluxo no recorte regional.
- **CEMADEN:** [opção pública de download de radares](https://mapainterativo.cemaden.gov.br/download/downradares.php),
  incluindo Santa Teresa; o download ainda precisa ser reproduzido e ter a
  qualidade conferida antes de virar entrada automática.
- **ANA HidroWebService:** [documentação/Swagger da API](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html#),
  para reconciliar séries de estações e testar propagação por evento.

A dashboard mostra, para cada fonte, o gate associado, o estado “fonte
identificada” e o próximo teste necessário. Nenhuma dessas URLs altera o
estado dos gates por si só.

## QA executado nesta revisão

- contratos Python da dashboard integrada e do feed da bacia: aprovados;
- validação estrutural da publicação: aprovada;
- navegador em 360 px: controles e atualização manual visíveis, sem overflow
  horizontal e sem erros de console;
- estado desta rodada: `DEGRADED`, por score/probabilidade não calibrado e
  fonte espacial GEFS/NODD em proxy. Esse estado é intencional até que os gates
  científicos acima tenham fonte e validação independentes.

