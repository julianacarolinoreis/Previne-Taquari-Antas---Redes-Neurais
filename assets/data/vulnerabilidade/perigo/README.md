# Setores de risco do SGB — Santa Tereza/RS

Este diretório contém o recorte oficial dos setores de risco geológico e
hidrológico mapeados pelo Serviço Geológico do Brasil (SGB) em Santa Tereza/RS.

## Arquivo

- `setores_risco_sgb_santa_tereza.geojson`: resposta original da API, sem
  remoção, renomeação ou criação de atributos e sem reclassificação dos valores.

## Fonte e data

- Órgão produtor: Serviço Geológico do Brasil (SGB/CPRM).
- Registro canônico: <https://rigeo.sgb.gov.br/items/646ab86b-280b-44f3-b279-87c6f995c0a8>
- Serviço de acesso mantido pela Defesa Civil do Rio Grande do Sul:
  <https://grd.defesacivil.rs.gov.br/server/rest/services/PRD/sgb_setor_risc/MapServer/1>
- Consulta reproduzível: `where=cd_geocmu='4317251'`, `outFields=*`,
  `returnGeometry=true`, `outSR=4326`, `f=geojson`.
- Data de captura deste snapshot: **2026-08-09**.
- Acesso: público. O registro consultado informa acesso aberto, mas não apresenta
  uma licença padronizada explícita para o conjunto; manter atribuição ao SGB e
  esta documentação de proveniência ao redistribuir.

## Escopo e referência espacial

- Município: Santa Tereza/RS, código IBGE `4317251`.
- Unidade: um setor de risco delimitado pelo SGB; o arquivo não representa
  imóveis individuais nem uma mancha contínua de inundação.
- CRS: WGS 84, `EPSG:4326`, solicitado explicitamente por `outSR=4326`. Em
  GeoJSON RFC 7946 as coordenadas aparecem na ordem longitude, latitude.
- Levantamento descrito no registro do SGB: trabalho de campo realizado entre
  30 de janeiro e 4 de fevereiro de 2025; publicação do produto em julho de 2025.

## Validação do snapshot

- 37 feições.
- Todas as feições com `cd_geocmu = 4317251`, `munic = SANTA TEREZA` e `uf = RS`.
- 37 `objectid` únicos e 37 `num_setor` únicos.
- 37 geometrias `Polygon`, sem geometria vazia e com anéis fechados.
- Bounds em EPSG:4326:
  `[-51.754681, -29.210506, -51.676685, -29.078140]`.
- Esquema uniforme, com todos os atributos recebidos da fonte preservados.
- SHA-256:
  `2e34ad1ed4b6a072439e3cbcb073c93edb007dacd69da18178dadb29fd7d0949`.

## Reprodução

Na raiz do repositório:

```console
python codigo_python/06_vulnerabilidade/baixar_setores_risco_sgb_santa_tereza.py
python codigo_python/06_vulnerabilidade/baixar_setores_risco_sgb_santa_tereza.py --check-only
```

O script usa somente a biblioteca padrão do Python. O download é gravado apenas
depois de passar pelas validações de contagem, município, identificadores,
esquema, geometria, CRS e bounds. Se a fonte oficial mudar, a execução falha para
que a atualização seja revisada conscientemente.

## Limitações de uso

- Ausência de um polígono fora dos setores mapeados não significa ausência de
  perigo ou risco.
- Os atributos `grau_risco`, `grau_vulne`, tipologias e estimativas são
  preservados exatamente como publicados; este repositório não recalcula nem
  amplia essas classificações.
- Números de pessoas, domicílios e edificações são estimativas do produto de
  setorização, não uma atualização do Censo e não devem ser inferidos em nível
  individual.
- Para auditoria e arquivamento de longo prazo, o pacote vetorial do RIGeo/SGB é
  a referência canônica; o serviço ArcGIS é usado como meio reproduzível de
  obtenção do recorte municipal.
