# Acompanhamento prospectivo de Santa Tereza

A RNA STZ_4H_N5, sem Castro Alves, aparece como comparativa em sombra no painel
publico. As outras arquiteturas aparecem somente na versao de usuario, nos
horizontes de 2, 4, 8 e 12 horas. A RNA principal de 2 h e o feed principal
permanecem com seus contratos atuais. Nao existe promocao automatica.

## N5 publica

- MAT: `RNAPREV__SANTA_TEREZA__04h__ALT__STZ_4H_N5__11inputs_22hiddens_20261006.mat`.
- SHA-256: `90D3D32C3BD25BD22C57191E0D5A4CB0F3972B26ED4DA9746A5FC6F7A2ADA49B`.
- Nove sinais de nivel de Santa Tereza e dois acumulados de chuva local (6 e 18 h).
- Nivel somente da estacao 86472600. Chuva: 86472600 e 86472000.
- Inferencia direta de delta de 4 h, reconstruida como nivel-base + delta.
- Feed `previsao_sombra_stz_n5.json`, historico permanente `historico_sombra_stz_n5.json`.

## Arquiteturas da versao de usuario

13 arquiteturas por horizonte, 52 modelos congelados:
CNN-1D, LSTM, GRU, TCN, Seq2Seq, Transformer, Ridge, Elastic Net, SVR,
Random Forest, Extra Trees, HistGradientBoosting e XGBoost.

O comparativo de 15/09/2026 preservou metricas e previsoes, sem todos os pesos.
Esta e uma nova execucao das arquiteturas, com os mesmos 11 sinais do contrato
N5 para permitir acompanhamento sem Castro Alves. Nao e uma recuperacao dos
pesos antigos. 12 h e uma extensao nova. DCRNN/GraphGRU e Transformer+GNN
permanecem nao executados por ausencia de grafo hidrologico validado.

As fontes congeladas estao em `assets/data/stz_user_models/training_n5*.csv`.
O manifesto guarda os hashes, versoes, particoes, metricas historicas de teste
e diferenca numerica de exportacao. O treino usa apenas a particao 1; a
particao 2 seleciona a epoca dos modelos temporais; a particao 3 fica para
avaliacao. Os eventos sao disjuntos. Janelas temporais tem quatro horas
consecutivas dentro do mesmo evento e da mesma particao. Alvos de 2/8/12 h sao
observacoes historicas na hora exata, dentro do mesmo evento; sem interpolacao.

O workflow executa os pesos congelados, sem retreino com telemetria recente.
Feed `previsao_sombra_stz_usuario.json`, historico `historico_sombra_stz_usuario.json`.

## Dados e avaliacao ao vivo

- Hora H da chuva soma leituras em (H-1h, H].
- Cada acumulado de chuva exige todas as horas de um posto; media somente
  entre postos com acumulado completo. Nao preenche horas ausentes com zero.
- Niveis somente na hora cheia exata. QC conserva os limites do contrato N5.
- Busca base completa nas ultimas tres horas; publica base, alvo e
  antecedencia efetiva. Alvo ja vencido nao e uma previsao disponivel.
- A primeira emissao por modelo/hash/base fica congelada no historico.
- Somente emissoes anteriores ao alvo entram na avaliacao prospectiva.
- A observacao e conferida na hora-alvo exata depois que ela chega da ANA;
  preserva-se a primeira observacao usada, com horario de conferencia.
- MAE, RMSE, vies, maior erro e persistencia sao calculados por modelo, sem
  misturar as metricas historicas de teste com os erros ao vivo.
- As janelas da interface sao 24 h, 72 h, 168 h e desde a ativacao; o feed de
  visualizacao conserva ate oito dias de pontos, e os historicos sao permanentes.
- Ausencia de dados e alvo vencido ficam explicitos. Zero pares nao e erro zero.

Agendamento: workflow `stz-shadow.yml`, minutos 17 e 47 de cada hora (horario UTC
do GitHub, equivalente aos mesmos minutos em BRT). O servico pode atrasar
execucoes agendadas. O painel mostra o horario real da atualizacao.

Validacao: testes de contrato, MAT original, chuva, lacunas, hashes, separacao
publico/usuario, eventos disjuntos, historico prospectivo e exportacao dos 52
modelos. EXPERIMENTAL: nao e alerta oficial.
