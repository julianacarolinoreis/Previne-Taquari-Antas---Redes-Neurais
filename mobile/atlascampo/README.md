# AtlasCampo

Aplicativo multiplataforma para mapas georreferenciados, navegação offline e coleta de dados em campo para Android e iOS.

## Escopo do produto

O produto foi estruturado para suportar:

- biblioteca de mapas e camadas;
- mapas raster e vetoriais armazenados no dispositivo;
- localização GPS, bússola e trilhas;
- pontos, linhas, polígonos, fotos, notas e atributos;
- importação e exportação GIS;
- sincronização com PostGIS e armazenamento em nuvem;
- autenticação, compartilhamento, assinatura e painel administrativo como módulos de produção.

## Estado atual

Esta entrega contém um núcleo executável do aplicativo móvel: biblioteca de mapas, banco local, mapa interativo, GPS, trilhas, pontos/linhas/polígonos, fotos, atributos, importação/exportação KML/GPX/GeoJSON/KMZ, suporte a MBTiles e GeoTIFF, fila de sincronização e API de sincronização com PostGIS.

O núcleo foi auditado com `flutter analyze`, `flutter test` e compilação sintática do backend. Ainda não é correto chamar o produto de publicado ou pronto para loja: autenticação/contas, cobrança, painel administrativo, ingestão de mapas no servidor, assinatura de release e testes em aparelhos reais precisam ser concluídos.

Não há Flutter, Android SDK ou Xcode instalados neste ambiente. Por isso, os arquivos nativos de plataforma devem ser gerados com `flutter create` em uma máquina com o toolchain móvel instalado.

## Inicialização

```powershell
flutter pub get
flutter analyze
flutter test
flutter run
```

### Sem MacBook

O desenvolvimento compartilhado pode continuar no Windows. O workflow em `.github/workflows/mobile.yml` valida o código Android e iOS em runners apropriados; a etapa iOS usa macOS na nuvem e não depende de um MacBook local.

Para uma versão instalável no iPhone, configure uma conta Apple Developer, o App ID `br.com.atlascampo.app`, certificados/perfis e TestFlight. Para publicação Android, configure a chave de assinatura e o Google Play Console. Esses dados pertencem ao proprietário do aplicativo e não podem ser preenchidos automaticamente.

Para uma compilação de loja, configure os identificadores de pacote, assinatura Android, equipe Apple, permissões de localização e políticas de privacidade antes do envio.
