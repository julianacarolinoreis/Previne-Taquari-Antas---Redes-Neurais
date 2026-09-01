# Backend AtlasCampo

Contrato inicial para contas, projetos, mapas, feições, arquivos e sincronização incremental.

## Serviços de produção

- API HTTPS para autenticação, projetos e sincronização;
- PostgreSQL com PostGIS para geometrias e revisões;
- armazenamento de objetos para mapas, fotos e exportações;
- worker de ingestão para validar CRS e converter GeoPDF/GeoTIFF/GPKG em tiles;
- worker de exportação para KML, GPX, GeoJSON e GeoPackage;
- painel administrativo separado.

O aplicativo não deve confiar em um arquivo importado como mapa utilizável até receber um manifesto de ingestão com CRS, extensão, níveis de zoom, checksum e estado `ready`.

## Desenvolvimento local

```powershell
docker compose up -d db object-storage
```

Os serviços de API e worker ainda dependem da configuração de identidade, armazenamento e filas do ambiente escolhido. O esquema e o contrato HTTP estão versionados para que essa decisão não altere o aplicativo móvel.
