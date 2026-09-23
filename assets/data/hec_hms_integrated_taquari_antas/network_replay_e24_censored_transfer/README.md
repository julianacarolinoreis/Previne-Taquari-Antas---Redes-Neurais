# E24 — transferência parcial E28 → novembro de 2023

Este pacote contém um **replay histórico de pesquisa**, não previsão operacional. O HEC-HMS 4.13 foi executado novamente em dois casos pareados, com o mesmo domínio de três áreas incrementais e os parâmetros físicos da candidata híbrida E28. A única condição inicial específica de E24 é a vazão observada no primeiro horário, expressa como vazão/área.

## Janela e dados

- Avaliação: 16/11/2023 00:00 a 24/11/2023 19:00, 212 horas locais. O evento completo termina depois; a cauda foi excluída antes da primeira lacuna da chuva local. Não extrapolar as métricas para o evento inteiro.
- Vazão observada: ANA 86510000/Muçum; chuva observada 86472000/Rio das Antas, 86472600/Santa Tereza e 86510000/Muçum. Chuva medida usada em replay não é previsão meteorológica.
- Referência: chuva 86472000 aplicada às três áreas. Alternativa: cada área usa a estação correspondente. As duas séries foram pontuadas nos mesmos 212 horários e contra a mesma observação.
- O relatório JSON registra SHA-256 dos insumos, parâmetros, duração, métricas e caminhos dos projetos HEC-HMS. `e24_censored_transfer_series.csv` contém os pares horários para recalcular cada indicador.

## Checagem numérica

O projeto herdado produziu `WARNING 41169` de instabilidade Muskingum com três passos por trecho. Antes de aceitar o teste, os dois trechos de **ambos** os casos passaram a um passo, preservando K=1 h e x=0,2. As execuções incluídas têm `compute_warning_count=0`; os logs `Calibracao.log` e os arquivos `bacia_E24.basin` permitem conferir isso. Portanto a arquitetura e os parâmetros físicos escolhidos no E28 foram transferidos, mas esta discretização numérica foi corrigida; não se trata de reprodução bit a bit do projeto E28.

## Leitura

No intervalo censurado, a chuva distribuída reduz MAE e RMSE e eleva NSE, mas **aumenta o erro da magnitude do pico**. O pico simulado permanece duas horas depois do observado em ambos os casos. Não há vencedor universal nem calibração multi-evento concluída.

Santa Tereza permanece apenas nó simulado: não há vazão observada reconciliada para aferir esse ponto. Esta rede de três incrementos não deve ser confundida com o modelo reconstruído da bacia inteira. Antes de qualquer promoção, testar eventos independentes completos, chuva espacialmente representativa, estabilidade numérica e o desempenho de subida/pico.

## Reexecução local

O script `scripts/test_hec_hms_e24_censored_transfer.py` requer HEC-HMS 4.13 instalado no caminho configurado no projeto e o projeto-base E24 pré-existente. Exemplo:

```powershell
python scripts/test_hec_hms_e24_censored_transfer.py --base-dir D:\PREVINE\worktrees\previne-catalogo-pesquisas-20260828\assets\data\hec_hms_integrated_taquari_antas\network_replay_all_events
```

Os dois subdiretórios de caso preservam entradas e saídas HEC-HMS do replay para inspeção mesmo sem esse projeto-base local. A página `index.html` lê apenas o JSON e o CSV incluídos neste pacote.
