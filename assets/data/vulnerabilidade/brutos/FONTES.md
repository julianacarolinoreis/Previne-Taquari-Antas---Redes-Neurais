# Fontes (dados completos oficiais)

- Agregados por Setores Censitários — Censo 2022: https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/
  Temas usados: Básico (população, domicílios), Demografia (faixas etárias por sexo),
  Cor ou raça (indígenas; pretos + pardos), Domicílio (água por rede geral, esgoto por rede geral).
  Denominador de água/esgoto: V00001 = Domicílios Particulares Permanentes Ocupados (`dom_ocupados`).
  Valores X omitidos por sigilo estatístico permanecem nulos e têm flag booleana `sigilo_<campo>`.
- Rendimento do Responsável por setor — Censo 2022 (pasta à parte, publicada em 2026):
  https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/
  Variável V06004 = rendimento nominal médio mensal das pessoas responsáveis.
- Malha de setores censitários 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/
- Malha municipal 2022: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/
- Grade estatística 2022 (células de 200 m, população e domicílios): https://geoftp.ibge.gov.br/recortes_para_fins_estatisticos/grade_estatistica/censo_2022/grade_estatistica/
  Ladrilhos ID_14 e ID_15 cobrem a bacia Taquari-Antas, conforme os `total_bounds` dos dois shapefiles.
- Limite da bacia Taquari-Antas: https://iede.rs.gov.br/server/rest/services/DRH/Bacias_Hidrograficas/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&f=geojson

Os CSVs aqui são o recorte dos municípios que intersectam a bacia; o estadual completo está nas URLs acima.
Energia elétrica não consta no agregado de características do domicílio por setor (Censo 2022).
