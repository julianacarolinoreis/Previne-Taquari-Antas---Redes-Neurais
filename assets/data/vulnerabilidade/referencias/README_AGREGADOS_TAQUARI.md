# Agregados oficiais do Taquari-Antas

Arquivos filtrados para os 118 municípios intersectantes da bacia Taquari-Antas a partir do **Censo Demográfico 2022 / IBGE**. A chave de junção é `CD_MUN` (sete dígitos), que corresponde a `cod_mun` no mapa.

## Arquivos

- `downloads/Agregados_taquari_pessoa.csv` — básico, demografia e cor/raça.
- `downloads/Agregados_taquari_domicilio.csv` — características dos domicílios, incluindo os blocos 1–3.
- `downloads/Agregados_taquari_entorno.csv` — entorno de domicílios, faces e moradores.
- `downloads/Agregados_taquari_PCD_TEA_municipio.csv` — PcD e TEA consultados nas tabelas municipais do SIDRA.
- `agregados_taquari_indicadores.json` — versão normalizada consumida pela dashboard.
- `DICIONARIO_AGREGADOS_TAQUARI.csv` — campos normalizados, unidade e universo.

Os três primeiros CSVs preservam os nomes e os valores publicados pelo IBGE e usam `;` e UTF-8 para facilitar o uso no Excel/QGIS. Valores `X`, `.`, `..` e `...` permanecem vazios; vazio não é zero.

## Escopo e leitura

Os indicadores são **municipais**. Eles não são uma estimativa da população somente dentro da bacia e não são valores setoriais. Na plataforma, ficam identificados como “município inteiro” e não substituem os agregados censitários usados no recorte setorial.

Nos pacotes GIS, os campos normalizados novos usados pela dashboard aparecem com seus nomes próprios. Quando um nome já existe no mapa (por exemplo `mulheres`, `indigenas` ou `pretos_pardos`), o valor municipal oficial também é publicado com o alias `mun_<campo>`; assim o campo original do mapa não é sobrescrito e a junção permanece auditável.

O entorno é uma pesquisa de características observadas em domicílios, faces e moradores selecionados pelo IBGE. Não é inventário completo de pavimentação, drenagem, acessibilidade, transporte ou arborização de toda a malha viária.

Os totais de faces e moradores usam os universos próprios do arquivo de entorno (`V05400` e `V05200`); eles não devem ser comparados diretamente ao total de domicílios `V05000`.

As categorias de arborização do entorno podem não fechar 100% do universo em todos os municípios: o próprio Censo preserva categorias desconhecidas ou não aplicáveis. A diferença não foi convertida em zero nem redistribuída entre as categorias.

PcD e TEA são resultados preliminares da amostra do Censo 2022 disponíveis no nível municipal. O município `4312351` não possui valor publicado para TEA nessa consulta; ele permanece como “não publicado”. Não se deve transformar ausência em zero nem comparar diretamente com uma contagem setorial.

## Fontes oficiais

- [Agregados municipais do Censo 2022 (FTP IBGE)](https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Municipio_csv/)
- [Agregados municipais do entorno (FTP IBGE)](https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Caracteristicas_urbanisticas_do_entorno_dos_domicilios/Agregados_por_Municipio_csv/)
- [SIDRA, tabela 10125 — PcD](https://sidra.ibge.gov.br/tabela/10125)
- [SIDRA, tabela 10145 — TEA](https://sidra.ibge.gov.br/tabela/10145)

Gerador reproduzível: `codigo_python/06_vulnerabilidade/baixar_agregados_taquari_oficiais.py`.
