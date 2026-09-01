# Configuração nativa

## Android

Adicionar ao `AndroidManifest.xml` as permissões necessárias para localização em primeiro plano e, somente se o usuário ativar gravação contínua, localização em segundo plano. Configurar o serviço foreground para a trilha e declarar a justificativa de uso na tela de consentimento.

## iOS

Adicionar ao `Info.plist` as mensagens de localização em uso e em segundo plano. Habilitar Background Modes apenas para o recurso de trilha contínua, com indicação visível ao usuário e opção clara de parar a gravação.

## Lojas

Configurar identificadores exclusivos, assinatura Android, equipe Apple, ícones, screenshots, política de privacidade, termos de uso, contato de suporte e declaração de uso de localização. As assinaturas devem ser validadas no servidor antes de liberar recursos pagos.
