# AtlasCampo — escopo de produção

## Objetivo

Oferecer uma alternativa própria a aplicativos de mapas de campo: o usuário importa mapas georreferenciados, trabalha sem conexão, coleta informações com GPS e sincroniza os resultados quando voltar à internet.

## Módulos obrigatórios

### Aplicativo iOS e Android

1. Biblioteca local de mapas.
2. Importação de GeoPDF, GeoTIFF, MBTiles, GeoPackage, KML, KMZ, GPX e GeoJSON.
3. Renderização de mapas raster e vetoriais.
4. GPS em primeiro e segundo plano, com autorização explícita do usuário.
5. Bússola, precisão, altitude, velocidade e estado da conexão.
6. Pontos, linhas, polígonos e trilhas.
7. Fotos, notas, formulários e atributos por feição.
8. Estilos, cores, nomes e visibilidade das camadas.
9. Medição de distância, perímetro e área.
10. Exportação e compartilhamento de dados.
11. Busca na biblioteca e nas camadas.
12. Operação offline com fila de sincronização.

### Nuvem

- cadastro, login e recuperação de conta;
- projetos, equipes e permissões;
- sincronização incremental e resolução de conflitos;
- armazenamento de mapas, fotos e exportações;
- links de compartilhamento com expiração;
- histórico e auditoria de alterações;
- exclusão e exportação dos dados da conta.

### Operação comercial

- plano gratuito e planos pagos;
- assinaturas Apple e Google validadas no servidor;
- limites de armazenamento e mapas;
- painel administrativo;
- catálogo de mapas, se o negócio incluir venda/distribuição;
- telemetria mínima, logs de falha e suporte.

## Critérios de aceite

- Um mapa importado continua abrindo em modo avião.
- Um ponto criado sem internet permanece no banco local após fechar e reabrir o aplicativo.
- Uma trilha não perde pontos quando o sinal de GPS fica temporariamente indisponível.
- A sincronização não duplica feições nem sobrescreve silenciosamente uma alteração conflitante.
- Exportações podem ser reimportadas em um GIS compatível.
- O aplicativo informa claramente quando uma camada ou mapa está desatualizado, incompleto ou aguardando sincronização.
- Permissões de localização são solicitadas somente no contexto de uso.
- Não há dados de usuário, tokens ou arquivos privados em logs.
- Builds de release passam por testes em aparelhos iOS e Android reais.

## Decisões que continuam abertas

- nome comercial e identidade visual;
- provedor de tiles e licença dos dados cartográficos;
- se haverá loja de mapas;
- política de preços;
- região inicial e idiomas;
- limites de tamanho para GeoPDF/GeoTIFF e fotos.

Essas decisões não impedem o desenvolvimento do núcleo móvel, mas são necessárias antes da publicação comercial.
