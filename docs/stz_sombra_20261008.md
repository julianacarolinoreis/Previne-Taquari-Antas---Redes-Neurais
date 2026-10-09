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
- Feed `previsao_sombra_stz_n5.json`, historico permanente em `assets/data/stz_shadow_history/n5/`.

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
Feed `previsao_sombra_stz_usuario.json`, historico em `assets/data/stz_shadow_history/usuario/`.

### Revisao r2 (calibracao)

- Redes temporais: na rodada r1 (90 passos em lote completo) sete das 24 redes
  pararam no teto ainda melhorando. A r2 treina um candidato com mini-lotes de
  64, Adam 1e-3, ate 300 epocas e parada apos 25 epocas sem melhora na
  particao 2. Cada rede publica o artefato (r1 ou r2) com menor MSE de
  validacao; o teste nunca decide. Em 8 e 12 h o mini-lote atinge o otimo da
  validacao em poucas epocas e varias redes r1 continuam melhores: o limite de
  passos funcionava como regularizacao. Um estudo de regularizacao (weight
  decay, dropout, validacao cruzada por evento) fica como proximo passo; com
  6 eventos de validacao e 4 de teste, diferencas de poucos cm sao ruido.
- SVR: alvo padronizado (`TransformedTargetRegressor`). Com o delta em cm, C=10
  limitava a amplitude e achatava as subidas grandes.
- Modelos estaticos que dao exatamente a mesma saida em todas as linhas mantem
  arquivo e hash; a serie ao vivo deles continua. Modelos com hash novo comecam
  uma serie nova; os registros antigos ficam no historico com o hash anterior.
- `reference_n5_test`: N5 nas mesmas linhas de teste de 4 h, para comparar.

### Limites conhecidos

- Os nomes seguem o comparativo de 15/09. Seq2Seq tem um unico passo de
  decodificador; o Transformer nao tem codificacao posicional; o TCN nao e
  dilatado nem estritamente causal. Detalhes em `architecture_notes` do manifesto.
- Chuva: uma hora com parte das leituras de 15 min entra como completa, a mesma
  regra do treino (`02_SERIES_HORARIAS/montar_series_horarias.py`, soma por
  `ceil("h")` sem minimo de leituras; 0,5-1,4% das horas dos postos locais desde
  2023 sao parciais). Diferencas restantes: o treino descarta so a leitura
  negativa, o robo descarta a hora; o QC diario contra vizinhos do treino
  (`montar_base_v2.qc_chuva`) nao e causal e nao roda ao vivo; leituras que a
  ANA ainda nao transmitiu deixam a ultima hora incompleta ao vivo.

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
  visualizacao conserva ate oito dias de pontos (so modelo, alvo, previsto e
  observado, da versao atual de cada modelo), e os historicos sao permanentes.
- Historicos em particoes mensais pelo mes de emissao (`AAAA-MM.json`, um
  registro por linha), para ficar abaixo do limite de 100 MB por arquivo do
  GitHub. Na primeira execucao o robo migra os JSON da raiz e so remove o
  legado depois de reler as particoes e conferir todos os registros.
- A pagina busca os feeds a cada 5 min (o robo publica a cada 30 min) e
  redesenha a cada minuto.
- Ausencia de dados e alvo vencido ficam explicitos. Zero pares nao e erro zero.

Agendamento: workflow `stz-shadow.yml`, minutos 17 e 47 de cada hora (horario UTC
do GitHub, equivalente aos mesmos minutos em BRT). O servico pode atrasar
execucoes agendadas. O painel mostra o horario real da atualizacao.

Validacao: testes de contrato, MAT original, chuva, lacunas, hashes, separacao
publico/usuario, eventos disjuntos, historico prospectivo e exportacao dos 52
modelos. EXPERIMENTAL: nao e alerta oficial.
