# iOS sem MacBook

O código Flutter pode ser desenvolvido no Windows e o projeto iOS já está versionado em `ios/`. O que não existe no Windows é o toolchain da Apple: Xcode, SDK iOS, certificados e perfis de provisionamento.

## Caminho de entrega

1. Criar ou conectar uma conta Apple Developer pertencente ao dono do aplicativo.
2. Registrar o Bundle ID `br.com.atlascampo.app`.
3. Executar o workflow iOS em um runner macOS na nuvem para gerar o arquivo do aplicativo.
4. Configurar assinatura Apple e enviar para App Store Connect/TestFlight.
5. Testar no iPhone real pelo TestFlight; só depois preparar a submissão pública.

O workflow deste projeto faz apenas a validação iOS sem assinatura. Ele prova que o código compila em macOS, mas não cria uma versão publicável sem os certificados, perfis e credenciais do proprietário.

## O que o iPhone resolve

O iPhone é suficiente para teste de campo depois que uma build assinada chega ao TestFlight. Ele não substitui o macOS/Xcode para criar a build assinada; essa parte fica na nuvem.
