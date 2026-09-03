# Muçum · HEC-HMS espacializado por MDT

Artefato de pesquisa para comparar um modelo HEC-HMS agregado com um piloto semidistribuído. O piloto usa uma bacia delineada por SRTM/WhiteboxTools a partir do posto de resposta ANA 86510000 e duas zonas de Thiessen de chuva horária: ANA 86472000 e 02851072.

## O que está pronto

- `index.html`: mapa raster de fundo, bacia, zonas Thiessen, postos e comparação interativa observada × HEC-HMS.
- `watershed_86510000_srtm.geojson`: bacia delineada sem aumentar artificialmente a área.
- `thiessen_zones_86510000.geojson`: bacia, zonas e pontos de chuva em EPSG:4326.
- `watershed_preparation_report.json`: origem dos seis tiles SRTM, hashes, método e área.
- `semidistributed_best/E19`, `E22`, `E27` e `E28`: projetos HEC-HMS 4.13 e séries dos melhores candidatos executados.

## Método e gate

- Área delineada pelo MDT regional: **15.690,722 km²**; área declarada no inventário ANA: **16.000 km²**; razão: **98,07%**.
- Zona 86472000: **8.550,194 km² (54,49%)**.
- Zona 02851072: **7.140,529 km² (45,51%)**.
- Perdas: Initial + Constant; transformação: Clark; baseflow: Recession.
- Os parâmetros são comuns às duas zonas para evitar identificar dois conjuntos independentes com apenas um hidrograma de saída.
- Sem interpolação de vizinhos, sem preencher lacunas e sem deslocar timestamps.

## Interpretação

O piloto semidistribuído é executável e espacializado, mas não substitui automaticamente o replay agregado já publicado. A seleção deve considerar simultaneamente NSE, erro do pico, atraso e cobertura da série. E24 e E26 permanecem bloqueados neste experimento porque a chuva local de 02851072 não cobre continuamente o período de pontuação; o caminho correto é obter/reconciliar a série, não fabricar valores.

Este pacote é **pesquisa/replay**. Não é alerta, previsão operacional, ordem de evacuação, despacho, rota ou garantia de capacidade de abrigo.

## Reprodução

Na raiz do repositório:

```powershell
python scripts/build_mucum_dem_watershed.py
python scripts/build_mucum_thiessen_zones.py
python scripts/calibrate_hec_hms_semidistributed_mucum.py --event 28 --count 60 --timeout 240 --output-dir <diretorio-de-saida>
```

O HEC-HMS 4.13 precisa ser executado a partir da pasta instalada para que o `jre` relativo do `HEC-HMS.cmd` seja encontrado.
