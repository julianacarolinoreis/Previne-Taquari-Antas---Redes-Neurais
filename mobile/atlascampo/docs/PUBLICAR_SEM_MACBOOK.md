# Publicar o AtlasCampo sem MacBook

Este procedimento usa o Windows para enviar o código e um serviço de build macOS na nuvem para gerar o aplicativo iOS. O iPhone será usado para testar pelo TestFlight.

## 1. Criar o repositório do código

1. Crie uma conta no GitHub e um repositório privado chamado `atlascampo`.
2. No PowerShell, dentro da pasta do projeto, execute:

```powershell
cd C:\caminho\para\atlascampo
git init
git add .
git commit -m "AtlasCampo inicial"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/atlascampo.git
git push -u origin main
```

Use a pasta entregue em `outputs/atlascampo`. O arquivo `.gitignore` evita enviar arquivos temporários do Flutter.

## 2. Criar a ficha do iOS

1. Inscreva-se no Apple Developer Program com a sua própria conta Apple.
2. Abra o App Store Connect e crie um novo aplicativo iOS.
3. Use exatamente o Bundle ID `br.com.atlascampo.app`.
4. Preencha nome, categoria, classificação etária, política de privacidade e informações da loja.
5. Em Users and Access > Integrations > App Store Connect API, crie uma chave com permissão `App Manager` e baixe o arquivo `.p8` uma única vez.

A Apple exige assinatura para instalar em aparelho real e para enviar ao TestFlight/App Store. O arquivo `.p8` é secreto: não o coloque no GitHub nem o envie por mensagem.

## 3. Conectar ao Codemagic

1. Crie uma conta no Codemagic e autorize o acesso ao repositório GitHub.
2. Selecione `Add application` e escolha o repositório `atlascampo`.
3. Escolha Flutter e abra o editor de workflow.
4. Em iOS, configure o Bundle ID `br.com.atlascampo.app`.
5. Em iOS code signing, selecione `Automatic` e conecte a chave do App Store Connect.
6. Escolha distribuição `App Store`.
7. Ative publicação para TestFlight, sem enviar automaticamente para a App Store na primeira execução.
8. Execute o workflow. Ao terminar, o build aparece no App Store Connect e pode ser liberado para testes internos no TestFlight.

O Codemagic pode criar certificados e perfis automaticamente a partir da integração Apple, sem Mac local.

## 4. Instalar no iPhone

1. Instale o aplicativo TestFlight no iPhone.
2. No App Store Connect, adicione seu e-mail como testador interno ou gere um convite externo.
3. Abra o convite no iPhone e instale o AtlasCampo pelo TestFlight.
4. Teste GPS, câmera, mapas offline, importação e exportação com arquivos reais.

## 5. Configurar Android

1. Crie a aplicação no Google Play Console.
2. Use o nome de pacote `br.com.atlascampo.app`; esse nome é permanente no Google Play.
3. No Codemagic, configure uma chave de assinatura Android e o formato `Android App Bundle (.aab)`.
4. No Google Cloud, crie uma service account e uma chave JSON.
5. Convide o e-mail dessa service account em Google Play Console > Users and permissions e conceda apenas as permissões necessárias para releases.
6. Adicione o JSON como variável secreta no Codemagic.
7. Gere o primeiro `.aab`, baixe-o e faça o primeiro upload manual no Google Play Console.
8. Use a faixa de teste interno antes de produção. Depois do primeiro upload, o Codemagic pode publicar novas versões automaticamente.

Nunca envie senhas, chave `.p8`, chave JSON ou chave Android para o chat. Cadastre esses dados diretamente nos serviços e mantenha o repositório privado.

## O que ainda depende de você

O código pode ser preparado sem esses acessos, mas a publicação não pode ser concluída sem a conta Apple Developer, a conta Google Play, o nome final, ícone, screenshots, política de privacidade e dados legais do responsável pelo aplicativo.
