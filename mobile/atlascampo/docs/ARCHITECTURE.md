# Arquitetura

## Aplicativo

Flutter fornece a camada de interface. O motor cartográfico deve receber uma fonte offline por arquivo (MBTiles/PMTiles ou árvore de tiles) e uma fonte online configurável. A camada de domínio não conhece widgets nem APIs de mapa.

O banco local usa SQLite/GeoPackage como fonte de verdade no dispositivo. Feições são armazenadas como geometria, atributos, fotos e metadados de sincronização. A fila de alterações deve ser append-only até receber confirmação do servidor.

## Processamento cartográfico

GeoPDF e GeoTIFF não devem ser tratados como uma imagem comum: a ingestão precisa ler a referência espacial, projeção, extensão e resolução, validar o CRS e gerar uma representação de tiles adequada para o dispositivo. A conversão pode ocorrer no servidor ou em uma ferramenta de pré-processamento confiável; o aplicativo só promove o arquivo após verificar o manifesto.

## Sincronização

Cada objeto terá `id`, `revision`, `updated_at`, `deleted_at` e `device_id`. O cliente envia operações idempotentes. O servidor confirma a revisão aplicada e devolve conflitos para decisão explícita quando duas alterações não puderem ser mescladas com segurança.

## Backend recomendado

- API HTTPS versionada;
- PostgreSQL/PostGIS para projetos, camadas e feições;
- armazenamento de objetos para mapas e fotos;
- fila para conversão de mapas, thumbnails e exportações;
- provedor de autenticação com tokens curtos e refresh rotacionado;
- validação de assinatura feita no servidor;
- painel web separado com trilha de auditoria.

## Licenças e operação

O provedor de tiles deve permitir o uso móvel e o armazenamento offline contratado. A licença deve ser confirmada antes de habilitar download em massa. A marca, os ícones e a interface do AtlasCampo serão próprios.
