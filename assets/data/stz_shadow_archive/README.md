# Arquivo prospectivo de Santa Tereza em sombra

Cada coleta publica arquivos `.json.gz` imutaveis para N5 e modelos do usuario. O indice registra SHA-256, tamanho, horario da emissao e contagens. O arquivo guarda as previsoes, entradas efetivamente usadas, telemetria ANA recebida, hashes dos contratos e versoes do runtime. A primeira rodada inclui a semente dos historicos anteriores; as demais guardam alteracoes, permitindo reconstrucao verificavel.

Os historicos completos permanecem nos JSON da raiz e no Git. O grafico apresenta ate oito dias; esse limite visual nao apaga o historico. A primeira previsao por modelo, hash, base e horizonte fica congelada. A primeira observacao valida exatamente no horario-alvo tambem fica congelada. Arquivo ausente, invalido ou perda de registros bloqueia a publicacao; nunca inicia silenciosamente um historico vazio.

O workflow salva uma copia adicional em GitHub Actions por 90 dias, inclusive em falha parcial, antes de tentar publicar no Git. Falha de push nao autoriza sobrescrever historico remoto. O arquivo versionado no Git nao tem a expiracao do artifact.

Para recuperar, execute na raiz do repositorio, escolhendo um destino novo:

```powershell
python -B -m scripts.recover_stz_shadow_history --source n5 --output work/historico_n5_recuperado.json
python -B -m scripts.recover_stz_shadow_history --source usuario --output work/historico_usuario_recuperado.json
```

A recuperacao verifica cada SHA e o estado completo de cada ciclo; nao sobrescreve o destino existente nem substitui automaticamente o historico operacional.

As 39 emissoes iniciais do usuario sao preservadas, mas nao tinham entradas arquivadas. Essa lacuna permanece explicita. As novas emissoes incluem entradas e horarios. Nenhum resultado e um alerta oficial; os modelos continuam experimentais em sombra.
