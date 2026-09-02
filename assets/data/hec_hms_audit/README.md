# Auditoria de chuva para o HEC-HMS

Este diretório contém a primeira etapa verificável da preparação do modelo:
proveniência das estações, respostas brutas e um recorte horário de evento.

## Situação atual

- o CSV local está horário e sem duplicidades/quebras de cadência;
- o evento de 01–10/09/2023 foi reproduzido exatamente para as colunas ANA
  `chuva_86472000` e `chuva_02851072`;
- `86472000` é estação fluviométrica em Santa Tereza com variável `Chuva` na
  telemetria, portanto a aceitação como precipitação precisa ser documentada;
- `02851072` é pluviométrica em Ibiraiaras e não pode ser chamada de chuva de
  Santa Tereza;
- a calibração HEC-HMS ainda não foi executada.

## Arquivos

- `rainfall_station_audit_latest.json`: relatório, hashes, perfis, identidades e
  comparações hora a hora;
- `terrain_inventory_latest.json`: resolução, CRS, extensão, cobertura das
  estações e ressalvas semânticas dos seis rasters locais;
- `raw/`: respostas preservadas da ANA, INMET e CEMADEN;
- `derived/event_2023-09-01_2023-09-10_hourly_candidates.csv`: recorte horário
  candidato para revisão; chuva é soma intrahorária e nível/vazão são médias
  intrahorárias apenas para inspeção;
- `../../../docs/hec-hms-calibration-plan.md`: protocolo para montar,
  calibrar e validar o projeto sem confundir pesquisa com operação.

## Reexecução

Na raiz do repositório:

```text
python scripts/audit_hec_hms_rainfall_sources.py --download
python scripts/test_hec_hms_rainfall_audit.py
```

O relatório deve continuar classificando a proveniência como `PARCIAL` até que
o conjunto de chuva representativo, o fuso, a política de lacunas, a curva-chave
e o projeto HEC-HMS sejam reconciliados.
