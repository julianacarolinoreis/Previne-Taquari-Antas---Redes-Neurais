# Santa Tereza - camadas de inundacao

Atualizado em: 2026-09-01.

## Produção atual (site)

A página ao vivo `santa_tereza_previsao_inundacao.html` usa o **HAND 5 m**
gerado a partir dos rasters de campo em `D:\\PREVINE\\hand\\santa tereza`.
O rio principal é definido por `FLOWACC >= 50.000.000` células finas e o
gerador atual segue o `FLOWDIR` D8 até o rio principal. A calibração vertical
permanece separada: **1,60 m na régua = HAND 0**.

O gerador `codigo_python/02_mdt_hand_mancha/gerar_hand_lidar_santa_tereza.py`
também produz uma grade de altitude absoluta a ~10 m a partir do **mesmo**
`FILL_CLIP_MOSAICO_LIDAR_RS.tif`. A página só aceita essa grade quando o
metadado declara `same_source_as_hand: true`, e posiciona a imagem usando os
bounds do próprio MDT.

### MDT refinado antigo — legado, não usar na página ao vivo

Os arquivos abaixo pertencem ao mosaico anterior drone + ANADEM e foram
retirados da página ao vivo em 21/09/2026 porque não são espacialmente
compatíveis com o HAND 5 m atual:

- `mdt_refinamento_santa_tereza.json`;
- `mdt/altitude_terreno_10m_refinado.json`;
- `mdt/mdt_santa_tereza_10m_refinado_visual.png`;
- `codigo_python/02_mdt_hand_mancha/refinar_mdt_santa_tereza.py`.

Eles permanecem apenas para rastreabilidade histórica. Não devem ser usados
para consulta de altitude, sobreposição visual ou cálculo junto com o HAND
atual.

## Camadas preliminares legadas

Esta pasta tambem contem duas camadas antigas do prototipo espacial:

1. `mancha_preliminar_santa_tereza.png` e `.geojson`
   - Recorte de `D:/PREVINE/inundacoes/profundidade_inund_v02.tif`.
   - Uso: mancha local preliminar para visualizacao no site.
   - Area positiva aproximada: 1369.67 ha.

2. `cenario_dem_na9765_santa_tereza.png` e `.geojson`
   - Cenario derivado do Copernicus DEM GLO-30 recortado.
   - Limiar: `NA 97,65 m`, extraido do anteprojeto publico da Ponte Santa Barbara.
   - Mascara filtrada por conectividade a partir dos pontos do rio/ponte/estacao.
   - Area aproximada: 1374.87 ha.

Arquivo de controle:

- `mancha_preliminar_santa_tereza.json`: metadados consumidos pela pagina do site.
- `protocolo_leave_one_event_out_estrangulamento.json`: proposta de teste RNA deixando fora um evento critico.

Pagina:

- `/santa_tereza_inundacao.html`

Fontes publicas principais:

- Compras RS Edital 0028/2024: https://www.compras.rs.gov.br/editais/0028_2024/318164
- SELT/DAER Ponte Santa Barbara: https://transportes.rs.gov.br/obras-da-ponte-santa-barbara-avancam-na-ers-431
- SGB/SACE: https://www.sgb.gov.br/sace/
- Zenodo cheias RH Guaiba 2024: https://zenodo.org/records/13227745
- Copernicus DEM: https://registry.opendata.aws/copernicus-dem/

Limitacao tecnica:

Estas camadas sao prova de conceito. A camada `NA 97,65` ainda depende da
compatibilizacao entre datum da ponte, datum do DEM e zero da regua da estacao
86472600 para uso operacional.
