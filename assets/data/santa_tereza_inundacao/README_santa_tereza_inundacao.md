# Santa Tereza - camadas preliminares de inundacao

Gerado em: 2026-07-11.

Esta pasta contem duas camadas para o prototipo espacial do PREVINE:

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
