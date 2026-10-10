# Executor do HEC ao vivo — bacia 145 (protótipo)

**PESQUISA — não é alerta oficial.** Roda o modelo HEC-HMS da bacia Taquari-Antas (145 sub-bacias, 105 trechos) num
ciclo de previsão: chuva observada até agora, chuva prevista (ECMWF principal, GFS segundo, "sem chuva" de
referência) depois, correção aditiva pelo último observado, conversão para nível e cotas de Muçum. Acima de 15 m em
Muçum o nível é só indicativo (fim da validade da curva-chave).

**Padrão desde 10/10/2026: `pc-f8-c025` + `d_piv` `so_curva` publicado** em LJJ/Muçum/Encantado (ver "Titular"
abaixo). Rollback para a saída anterior: `--modelo md-val2-c002 --pos aditiva`.

Antes: **`md-val2-c002`** (família lrdc pura, calha trapezoidal em Muskingum-Cunge, J cal 6,73 / val
7,00; branch `cursor/hec-bacia145-modelo`). `lr-g8-c038` continua disponível (`--modelo lr-g8-c038`),
e também `vo-val-c008` (família lrdcr: `vo-rp5-c041` só com o fb regional, xfb_T 0,815 / xfb_B 1,245; J val 5,89; branch
`cursor/hec-bacia145-volume`), com τ(h) próprio (`correcao_horaria.py` nas vazões da rodada vo-val, escolha só na
calibração; na validação, MAE corrigido igual ao do τ do c002 até +24 h e ±2,5% em +48 h). Contra o c002 com o τ dele,
validação, MAE corrigido +24/+48 h: Muçum 304/327 × 316/356, Encantado 464/442 × 516/518, LJJ 307/299 × 314/310 m³/s.

Nada do motor foi reescrito: o `.basin` sai de `codigo/estrutura_v3.bacia_v3` (estado inicial pelo q0 observado no
início da janela, como na calibração), o DSS de chuva de `codigo/hec.dss_chuva` e a execução de `codigo/hec.rodar_lote`.
O executor copia `codigo/*.py` para uma pasta de trabalho, igual ao fluxo da nuvem. O estado do HMS entre ciclos usa o
Save State / Start State do próprio HMS 4.13 (`estado.py`).

## Como rodar

Requisitos: Python ≥ 3.10 com `numpy`, `requests`, `eccodes` (no Windows também `ecmwflibs`) e o HEC-HMS 4.13
(padrão: `D:\PREVINE\tools\hec-hms-4.13\portable\...\HEC-HMS.cmd`, ou `--hec-cmd`). No PC, o venv que já tem tudo:
`D:\PREVINE\repo_hec_calib\_analise_bacia145\chuva_prevista\.venv312\Scripts\python.exe`.

```powershell
cd calibracao_hec_bacia145\operacional
$py = "D:\PREVINE\repo_hec_calib\_analise_bacia145\chuva_prevista\.venv312\Scripts\python.exe"

# coletor do CEMADEN (deixar rodando: uma leitura a cada 10 min, fora do repositório)
& $py -B cemaden.py coletar --pasta $HOME\hec_aovivo_estado\cemaden --loop-min 10 --vezes 100000

# ao vivo (t0 = hora cheia atual); grava saida\hec_aovivo_aovivo_<t0>.json e saida\hec_aovivo_latest.json
# chuva em rede (ANA + CEMADEN + INMET se houver INMET_TOKEN), partida a frio adaptativa + correção aditiva
& $py -B ciclo.py --modo aovivo --horizonte 120 --cenarios ecmwf,gfs,zero

# opcional (experimental): estado entre ciclos e/ou assimilação no fim do observado
& $py -B ciclo.py --modo aovivo --estado $HOME\hec_aovivo_estado\estados --assimilar previsao

# retroativo operacional: telemetria da ANA + GRIB baixado de novo, como se fosse ao vivo em t0
& $py -B ciclo.py --modo retro --t0 2024-05-10T14:00 --fonte-obs ana --janela-arquivo S2024_05 --rotulo operacional

# retroativo de reprodução: chuva e observados arquivados + período da janela de calibração (deve bater com cp-r1)
& $py -B ciclo.py --modo retro --t0 2024-05-10T14:00 --fonte-obs arquivo --janela-arquivo S2024_05 `
      --fonte-prev arquivo --janela-mae S2024_05 --parametros parametros\lr-g8-c038.json --rotulo reproducao
& $py -B conferir_retro.py saida\hec_aovivo_retro_2024051014_reproducao.json S2024_05   # lê _analise_bacia145 (só no PC)

# conferir um conjunto de parâmetros contra uma rodada da nuvem (diferença ~0 esperada)
& $py -B validar_parametros.py parametros\md-val2-c002.json S2023_11 <pasta com <sim>\vazao.csv da rodada md-val2>

# experimento do estado entre ciclos (retroativo, ~1 h no PC)
& $py -B experimento_estado.py --janelas S2025_06,S2024_05
```

Opções úteis do `ciclo.py`: `--modelo ID` (padrão `pc-f8-c025`, ou `$HEC_MODELO`), `--pos hibrido|aditiva` (padrão
`hibrido`, ou `$HEC_POS`), `--porte auto|nao|sempre|ARQUIVO` (sombra da regra por porte; `$HEC_PORTE`),
`--horizonte` (48–120 h), `--cenarios`, `--pos-chuva fator:1.2`, `--parametros ARQUIVO` (substitui `--modelo`),
`--fonte-obs rede|ana|arquivo` (padrão `rede`), `--cemaden DIR` (histórico do coletor; padrão `$HEC_CEMADEN_DIR` ou
`~\hec_aovivo_estado\cemaden`), `--estado DIR` (loja de estados; padrão `$HEC_ESTADO_DIR` ou desligado),
`--assimilar nao|previsao` (padrão `nao`), `--sombra auto|nao|ARQUIVO` (híbrido em sombra; padrão `$HEC_SOMBRA`
ou `auto`), `--passo-estado-h 6`, `--inicio-fixo`, `--trabalho` (rodadas; padrão `~\hec_aovivo_trabalho`, com `cache_prev\`).

Retroativas que encostam na janela de teste (`X20260918`, 18/09–04/10/2026) são recusadas; ao vivo, a janela nunca
começa dentro dela. Nenhuma métrica é calculada nesses eventos.

**Nuvem** (os dois fluxos rodam por push nesta branch; `workflow_dispatch` e `schedule` só valem quando os arquivos
estiverem na branch padrão):

- `.github/workflows/hec-bacia145-aovivo.yml` — um ciclo no Linux (HEC-HMS 4.13 linux64). Lê o histórico do CEMADEN
  da branch de dados e o `INMET_TOKEN` dos secrets (se existir) e sobe o JSON como artefato `hec-aovivo-<run>`.
  Estado entre ciclos desligado (ver resultados); para ligar: `--estado DIR` + `actions/cache` de DIR.
- `.github/workflows/hec-bacia145-cemaden.yml` — coletor a cada 10 min; anexa uma linha em `cemaden/AAAA-MM-DD.jsonl`
  na branch órfã **`cursor/hec-bacia145-sistema-dados`** (só dados, sem workflows: o push nela não dispara nada).

O fluxo de lote (`hec-bacia145-lote.yml`) não dispara nesta branch.

## Arquivos

| arquivo | papel |
|---|---|
| `ciclo.py` | orquestrador de um ciclo (janela/estado, fontes, HEC, assimilação opcional, pós-processamento, JSON) |
| `executor.py` | pasta de trabalho, gerador do `.basin`, `hec.rodar_lote` com um projeto por cenário; Save/Start State |
| `estado.py` | sintaxe do Save/Start State, loja de estados por conjunto de parâmetros, assimilação por razão obs/sim |
| `chuva_observada.py` | `FonteChuvaObservada` → `ChuvaObservada`; `TelemetriaANA` (fase 1), `ArquivoForcamento` |
| `chuva_rede.py` | `RedeAoVivo(FonteChuvaObservada)`: ANA + CEMADEN + INMET, QC causal avtelqc2, IDW, cobertura |
| `cemaden.py` | coletor do JSON público do CEMADEN e reconstrução horária das leituras |
| `inmet.py` | cliente do apitempo do INMET (só com `INMET_TOKEN`) |
| `chuva_prevista.py` | `FonteChuvaPrevista` → `[Cenario]`; ECMWF/GFS por byte-range, `SemChuva`, `ArquivoPrevista`; pós-processadores |
| `vazao_observada.py` | `FonteObservados` dos postos de controle (estado inicial e correção) |
| `posproc.py` | correção aditiva, curva nível × vazão, cotas de Muçum, resumo de conjunto; `d_piv` titular e em sombra |
| `porte.py` | sombra da regra por porte: índice S (chuva na bacia de Muçum) e parâmetros `parametros/porte_*.json` |
| `teste_posproc.py` | testes do `d_piv`, titular/sombra, ligação parâmetros ↔ modelo e índice S (`python -B teste_posproc.py`) |
| `telemetria_ana.py`, `geo.py` | cliente do HidroTelemetria (com espera em HTTP 429); sub-bacias, UTM 22S, pesos de grade |
| `validar_parametros.py` | roda um `parametros/*.json` numa janela e compara com a `vazao.csv` de uma rodada da nuvem |
| `experimento_estado.py` | experimento retroativo do estado entre ciclos (V0–V3) |
| `conferir_retro.py` | compara uma retroativa com `nuvem/cp-r1` e com o estudo `correcao/horaria` |
| `preparar_dados.py` | gera `dados/` e `parametros/` a partir das fontes do PC (`c002`, `rede`; só quando elas mudarem) |
| `dados/` | sub-bacias, 130 postos ANA (fase 1), `postos_rede.json` (rede ao vivo), curvas da telemetria, τ(h) do c038 |
| `parametros/*.json` | `pc-f8-c025` (padrão), `md-val2-c002` (rollback), `vo-val-c008`, `lr-g8-c038`; τ(h) em `correcao` |
| `parametros/hibrido_<id>.json` | `d_piv` do conjunto `<id>` (`pc-f8-c025`, `vo-val-c008`): `so_curva` publicada, `todos_picos` em sombra |
| `parametros/porte_po-r4-c008.json` | regra por porte (limiar, sub-bacias de Muçum), conjunto G robusto e `d_piv` reajustado |
| `exemplos/` | JSON da fase 1 (ao vivo 09/10/2026 13h, retroativa 10/05/2024 14h) |

### Ponto de encaixe dos parâmetros

Um conjunto é um arquivo `parametros/<id>.json` com `id`, `familia`, `rota`, `gerador` (`"modulo.funcao"`, hoje
`estrutura_v3.bacia_v3`, que recebe `(p, sim, rota)` e devolve o `.basin`), `p`, `sha256_p` e, opcionalmente,
`correcao` (`tau_h` por ponto; sem ela vale `dados/correcao.json`). Trocar de modelo (ex.: recalibração do volume a
jusante, chuva de calibração com a hora do INMET corrigida) = gerar o novo JSON (como `preparar_dados.py c002`),
conferir com `validar_parametros.py` e mudar o padrão de `--modelo` no `ciclo.py`. A loja de estados é separada por
`id` + `sha256_p`, então a troca começa uma cadeia nova (partida a frio no primeiro ciclo).

## O que um ciclo faz

1. **Janela e estado inicial**: de `início` a t0 + horizonte, passo de 10 min no modelo e saída horária.
   - Padrão: partida a frio na hora mais recente em [t0 − 30 d, t0 − 5 d] com Muçum ≤ 1,25 × a mínima do período
     (`escolher_inicio`), estado pelo q0 observado (como na calibração).
   - Com `--estado DIR`: `início` = o estado mais recente da loja com instante ≤ t0 − 5 d (até 30 d), carregado pelo
     Start State do HMS; cada ciclo salva o estado em t0 + 6 h − 5 d (o que o próximo vai procurar). A cadeia equivale
     a uma rodada contínua desde a primeira partida a frio, e os últimos 5 dias são sempre refeitos com a chuva mais
     nova. Sem estado na loja (primeiro ciclo, troca de parâmetros), partida a frio.
2. **Observados dos controles** (ANA, 10 postos): só o que é ≤ t0 no horário corrigido (relógio de Muçum).
3. **Chuva observada** (`chuva_rede.RedeAoVivo`, recomendação da frente de chuva ao vivo, versão `avtelqc2`):
   - Rede `dados/postos_rede.json`: 72 ANA + 66 CEMADEN + 13 INMET, sem a lista negra (86403000, 86450000, 86479000).
   - Hora H = (H − 1 h, H] em BRT, como no `forcamento_v3`.
   - ANA: HidroTelemetria **em série** (paralelo dá HTTP 429), espera de 10/20/30 s se vier 429. A hora só conta com
     todos os registros da cadência; relógio de Muçum corrigido; > 90 mm/h fora.
   - CEMADEN: o JSON público só tem os acumulados até o último dado (1…96 h). O coletor guarda uma leitura a cada
     10 min; cada leitura vale para a hora cheia mais próxima do seu último dado (até ±30 min). Horas sem leitura saem
     do rateio dos blocos (t−3, t−1] / (t−6, t−3] de uma leitura posterior. Blocos de 12–96 h não são usados: com eles
     o total de 48 h saía certo, mas o pico horário da bacia caía à metade.
   - INMET: só com `INMET_TOKEN` (env/secret); sem ele a fonte é pulada e o JSON registra `pulado`.
   - QC causal: por hora, valor travado (6 h ≥ 2 mm com amplitude ≤ 1 mm; não se aplica às horas rateadas) e chuva
     isolada (≥ 10 mm com os 3 vizinhos < 1 mm); depois, total das 72 h anteriores contra a média dos 3 vizinhos
     (vizinhos > 30 mm e posto < 0,4× ou > 2,5× → fora naquela hora).
   - IDW p = 2 nos centróides; hora sem posto = 0 (contada); vai até a última hora com ≥ max(5, metade da mediana) de
     postos. A cobertura por fonte, as exclusões do QC e as falhas vão para o JSON.
4. **Chuva prevista**: ECMWF IFS 0,25° e GFS 0,25° por byte-range (inalterado da fase 1).
5. **HEC**: um projeto por cenário, em paralelo, a partir do mesmo estado; muda só a chuva depois da última hora
   observada. Com `--assimilar previsao`: o observado roda antes (salvando o estado da cadeia e o do fim do observado),
   o estado do fim do observado é escalado pela razão obs/sim por região de controle e os cenários partem dele
   (`estado.assimilar`; detalhes e resultado abaixo). A loja guarda só a cadeia pura.
6. **Pós-processamento** (LJJ, Muçum, Encantado; Estrela só simulado e observado): Q = S + e(tv)·exp(−(t − tv)/τ(h)),
   τ(h) do conjunto de parâmetros; com assimilação, sem correção aditiva (ela dobraria o ajuste). Com `--pos hibrido`
   (padrão) e `parametros/hibrido_<id>.json`, o publicado em LJJ/Muçum/Encantado é o `d_piv` `so_curva` e a aditiva
   fica em `pontos.*.aditiva`. Nível pela curva da telemetria; cotas de Muçum 5/10/15/18 m.
7. **Híbrido em sombra** (só se houver `parametros/hibrido_<id>.json`; ver abaixo): a variante não publicada.
8. **Sombra da regra por porte** (`--porte auto`, só com `--pos hibrido`): se S ≥ 83,4 mm, roda também o HEC com o G
   robusto; ver "Titular".

## Titular: `pc-f8-c025` + `d_piv` (10/10/2026)

- **Modelo base** `pc-f8-c025` (família lrdcf do branch `cursor/hec-bacia145-perda-cheia`: DC + Linear Reservoir +
  xfb_T/xfb_B) = a lrdcr do sistema com xdmax = xperc = 1; `.basin` idêntico ao do branch de perda (S2023_11, S2024_05,
  X20200626). τ(h) da aditiva escolhido na calibração (rodada pc-valx).
- **Publicado**: `d_piv` `so_curva` (`parametros/hibrido_pc-f8-c025.json`, ajuste só na calibração, rodada hb-f8 =
  mesmas 386 emissões da hb-r1) em LJJ/Muçum/Encantado; nos demais pontos, como antes. `todos_picos` em
  `pontos.*.hibrido_sombra`. Muçum `so_curva`: q0 2601, b 0,99, qmax 4728, τd 24 h (≈ aditiva); Encantado 3042 /
  1,31 / 5463 / 24; LJJ 1944 / 1,37 / 3700 / 12. `curva_extrapolada` marcada no pico (> limite da curva).
- **Validação** (ECMWF, médias+grandes, erro de pico 1–6/7–12/13–24 h): Muçum −5/−7/−17 % (c008+d_piv −6/−8/−18);
  Encantado −1/−7/−14 (−2/−7/−14); LJJ −6/−6/−7 (−5/−7/−10). MAE +6…+48 h igual ao c008+d_piv (±3 %). Alarme 15 m
  em Muçum: 11 acertos / 0 falsos (c008: 9 / 0). Tabelas: `_analise_hibrido/comparar_f8.md`.
- **Rollback**: `--modelo md-val2-c002 --pos aditiva` → JSON idêntico ao do código anterior (retro maio/2024: 0
  diferenças fora `emitido_em`/`tempos_s`; ao vivo 10/10 11h: pontos idênticos refazendo com o `posproc.py` antigo).
  `--pos aditiva` com o pc-f8 publica a aditiva com o τ(h) novo.
- **Sombra da regra por porte** (`porte.py`, frente `cursor/hec-bacia145-porte`): S = chuva das 24 h até t0 +
  prevista 48 h (ECMWF; GFS se faltar), média na bacia de Muçum (87 sub-bacias). S ≥ 83,4 mm → HEC com `po-r4-c008`
  (G robusto) + `d_piv` reajustado → `pontos.*.porte_sombra` (S, decisão, simulado, série corrigida, pico). S <
  limiar → nada extra (só o bloco `porte_sombra` do topo com S e a decisão). Desligada com estado salvo ou
  assimilação. Custo quando dispara: +1 rodada do HEC (≈ +19 s ao vivo com 3 cenários; +32 s no retro maio/2024).
  `--porte sempre` força a rodada (teste), `--porte nao` desliga.

## Híbrido `d_piv` em sombra

Corrige o viés de porte do HEC (subestima mais as cheias maiores) sobre a saída do HEC rodado com chuva; roda ao lado
da correção aditiva e **não muda nada do que é publicado** (`corrigido`, `nivel_previsto_cm`, `cotas_previstas`,
`conjunto`, `avisos`). Estudo: `_analise_hibrido/LEIAME.md` (branch `cursor/hec-bacia145-hibrido`, rodada hb-r1).

    F(S) = S·(min(S, qmax)/q0)^(b−1) se S > q0, senão S       (F/S limitado a [1/3; 3])
    Q(t) = F(S(t)) + (O(tv) − F(S(tv)))·exp(−(t − tv)/τd),  Q ≥ 1 m³/s   (mesmo tv da correção aditiva)

- Abaixo de q0 (mediana dos picos simulados da calibração) é a correção aditiva com τd constante; acima de qmax (maior
  pico simulado da amostra de ajuste) o fator fica congelado. Sem observado válido em 72 h: só F(S).
- Só LJJ, Muçum e Encantado, ligado ao conjunto do arquivo (`pc-f8-c025`, `vo-val-c008`; confere `modelo` e
  `sha256_p`; o c002 não gera sombra). Com o `d_piv` titular, a sombra traz só a variante não publicada. Desligado com `--assimilar previsao` (avaliado sem assimilação).
- Duas variantes: `todos_picos` (b com todos os picos de calibração; Muçum b 1,20, fator máx. 1,28; Encantado 1,41 /
  1,63; LJJ 1,47 / 1,90) e `so_curva` (só picos com nível dentro da curva: Muçum ≤ 15 m, LJJ ≤ 18 m, Encantado
  ≤ 19,2 m; Muçum b 1,04 / 1,02; Encantado 1,35 / 1,22; LJJ 1,47 / 1,32).
- Validação com ECMWF (médias+grandes, erro de pico 1–12 h / 13–24 h; aditiva do estudo com τ constante): Muçum
  HEC −24/−23 %, aditiva −7/−19 %, `d_piv` −2/−12 %; Encantado HEC −31/−29 %,
  aditiva −6/−23 %, `d_piv` −3/−8 %. Avaliado até 47 h; de 25 a 47 h nenhum método melhora (falta chuva na previsão).
- Ligar/desligar: `--sombra auto` (padrão) / `--sombra nao` (ou `HEC_SOMBRA=nao`); `--sombra ARQUIVO` usa outro
  arquivo de parâmetros. Para outro modelo: gravar `parametros/hibrido_<id>.json` com o `sha256_p` dele.

Saída: `hibrido_sombra{estado, arquivo, pontos}` no topo e, em cada ponto, `pontos.<P>.hibrido_sombra{metodo,
modelo, arquivo, limite_curva_cm, horizonte_avaliado_h, aviso, variantes{todos_picos, so_curva: {q0, b, qmax, tau_h,
fator_maximo, erro_em_tv_m3s{cen}, corrigido{cen}, nivel_previsto_cm{cen}, pico{cen: pico_vazao_m3s, pico_nivel_cm,
t_pico, curva_extrapolada, fator_congelado}}}}`. `curva_extrapolada` = pico da sombra acima do limite da curva do
ponto (em Muçum, 15 m).

Conferência (09/10/2026): ciclo ao vivo completo com o `vo-val-c008` (rede + ECMWF 12z + GFS 18z, t0 09/10 20h) e
retroativo de maio/2024 (t0 01/05 00h, arquivos). Refazendo o pós-processamento com o `posproc.py` anterior sobre as
mesmas vazões do HEC, os `pontos` publicados saem idênticos; no retroativo, antigo × novo, o JSON inteiro é igual
fora `hibrido_sombra`, `emitido_em` e `tempos_s`. Com o c002 a sombra não sai.

## Saída (JSON)

Campo **`versao`** (e `versao_esquema`, igual): **2**. Histórico:

- **2** + titular (10/10/2026): com `--pos hibrido`, `corrigido`/`nivel_previsto_cm`/`erro_em_tv_m3s` de
  LJJ/Muçum/Encantado passam a ser o `d_piv` (`pontos.*.correcao` diz qual); a aditiva vai para `pontos.*.aditiva`;
  novas chaves `pos_processamento` (topo e por ponto: método, variante, q0, b, qmax, τd, pico com
  `curva_extrapolada`) e `porte_sombra` (topo: S, limiar, decisão, tempo; por ponto só quando S ≥ limiar). Com
  `--pos aditiva` nada disso aparece.
- **2** + sombra: novas chaves `hibrido_sombra` (topo) e `pontos.*.hibrido_sombra` (só com parâmetros do híbrido);
  nenhum campo existente mudou.
- **2** (fase 2): `versao`; `parametros` ganhou `rota`, `J_cal`, `J_val`, `arquivo`, `correcao{fonte, tau_h_6h}`;
  `q0_especifica_m3s_km2` = `null` quando o ciclo começa de estado salvo; novo bloco `estado{loja, inicial, salvo,
  podados, assimilacao, instante_assimilacao, razoes{controle: razao, bruta, tipo, sim, obs}, metodo}`;
  `janela.inicio_escolhido` pode trazer `estado_instante` e `estado_meta`; `chuva_observada` (fonte `rede`) traz
  `por_fonte{ANA, CEMADEN, INMET}` (consultados, com dado, falhas, 429, coletas, horas exatas/por bloco, `pulado`),
  `postos_usados_por_fonte`, `qc_horas_fora_trava_ou_isolada`, `qc_horas_fora_72h_vizinhos`,
  `estacoes_por_hora_por_fonte`, `horas_degradadas_menos_10_postos`, `tempos_s` por fonte; com assimilação,
  `pontos.*.correcao` explica que não há correção aditiva. Os demais campos não mudaram de nome nem de sentido.
- **1** (fase 1): primeiro formato.

Campos: `emitido_em`, `t0`, `janela`, `parametros`, `estado`, `chuva_observada`, `cenarios[]` (id, modelo, papel,
status, rodada UTC, idade em t0 e na emissão, cobertura, chuva prevista na bacia, ensemble, avisos), `horas[]`,
`chuva_media_bacia_mm{cen}`, `pontos{LJJ, MUCUM, ENCANTADO, ESTRELA}` (`observado`, `simulado{cen}`,
`corrigido{cen}`, `nivel_previsto_cm{cen}`, `ultimo_observado_valido`, `erro_em_tv_m3s`, `tau_h_usado`, `curva`; em
Muçum `cotas_previstas`; com ensemble `conjunto`; no retroativo `verificacao_apos_t0`), `avisos[]`, `tempos_s`.

## Onde guardar o histórico do CEMADEN e o estado

| opção | prós | contras | uso |
|---|---|---|---|
| branch órfã de dados (`cursor/hec-bacia145-sistema-dados`) | persistente, auditável, qualquer fluxo lê com `git fetch --depth 1`; não dispara workflows | 144 commits/dia (~0,7 MB/dia de JSONL, comprime bem); precisa `contents: write`; cresce sem limite (podar/espremer o histórico de tempos em tempos) | **histórico do CEMADEN** |
| cache do Actions | sem commits; restauração pelo prefixo da chave | some após 7 dias sem uso e por pressão de espaço (10 GB); escopo por branch | estado do HMS, se for ligado (≈6 MB por estado; perder = uma partida a frio) |
| artefato | simples de gravar | difícil de consumir em outro run (API + token), retenção limitada | só o JSON de saída |

O histórico do CEMADEN não pode ser refeito depois (o JSON público não tem passado), por isso vai para git. O estado
pode: se o cache sumir, o ciclo volta à partida a frio e a cadeia recomeça.

## Resultados (fase 2, 09/10/2026)

### md-val2-c002 integrado

- `preparar_dados.py c002` lê o `PEDIDO.json` da rodada md-val2 (branch do modelo), confere rota `mc` e atraso zero
  e grava `parametros/md-val2-c002.json` (sha256 de `p` incluso). A `estrutura_v3` desta branch já gera o `.basin`
  igual: `validar_parametros.py` na janela S2023_11 contra a `vazao.csv` da nuvem → **diferença máxima 0,000 m³/s
  nos 10 controles** (HEC 17,7 s).
- τ(h) da correção aditiva re-escolhido para o c002 com `correcao_horaria.py` (só eventos de calibração; vazões da
  rodada md-val2). Mudou pouco: Muçum 72/36/36/36 h (1/6/24/48+ h; c038 72/36/24/36), Encantado igual
  (96/72/24/18), LJJ 48/36/18/12 (c038 48/36/24/18). Na validação, o c002 melhora o MAE corrigido em relação ao c038
  em todos os pontos e horizontes avaliados (Muçum +6 h 201 → 180, +24 h 360 → 316, +48 h 389 → 356 m³/s; bruto
  +24 h 483 → 426; Encantado +24 h 549 → 516; LJJ +24 h 320 → 314).

### Chuva em rede × só ANA (últimas 48 h até 09/10 16:00)

| fonte | postos usados | postos/hora (típico) | total na bacia 48 h | 24 h | maior hora | tempo |
|---|---|---|---|---|---|---|
| rede (ANA 71 + CEMADEN 66; INMET pulado, sem token) | 137 | ~70 → 135 nas horas com leitura do CEMADEN | 28,5 mm | 4,1 mm | 6,5 mm | 91 s |
| só ANA (fase 1, 130 postos consultados) | 78 | ~75 | 28,4 mm | 3,9 mm | 6,3 mm | 131 s |

Correlação horária da média na bacia 0,996; razão dos totais 1,006. Só o CEMADEN (66 postos, blocos de até 96 h da
primeira coleta) deu 25,9 mm contra 28,2 mm da ANA nas mesmas 48 h — os totais batem; o horário só vem com o coletor.
A ANA em série (72 postos) levou 60–90 s sem nenhum 429. O coletor começou hoje às 16:15: por enquanto o CEMADEN cobre
só as últimas horas; a cobertura horária cheia vem com o histórico.

### Estado entre ciclos

Sintaxe do HMS 4.13 (conferida no `hms.jar` e testada): no `.run`, `Save State Name`, `Save State Type: At Specified
Time`, `Save State Date`, `Save State Time` → `basinStates/<nome>.state` (texto, ~6 MB) + `proj.stateIndex`;
`Start State Name: <nome>` lê o estado (o Control tem de começar no instante dele; o HMS escreve meia-noite como
24:00 do dia anterior). Começar de um estado salvo reproduz a rodada contínua: **diferença 0,000 m³/s** em LJJ, Muçum
e Encantado (conferido no experimento, nas duas janelas).

**Assimilação** (`estado.assimilar`), quando pedida:
- Razão obs/sim por controle (Tainhas, Castro Alves, Monte Claro, LJJ, Muçum, Encantado), média das 3 últimas horas,
  incremental (menos o controle imediatamente a montante), limitada a [0,33; 3].
- Sub-bacias escaladas pela razão da sua região; trechos pela média ponderada pela vazão que cada sub-bacia a montante
  manda (a calha carrega a vazão de montante).
- Escala resíduos do Clark, saída dos reservatórios lineares e vazões dos subtrechos; o déficit de umidade não muda.

**Experimento** (`experimento_estado.py`; resultado completo em `_analise_sistema/estado/resultado.json`, fora do
commit):
- Ciclos a cada 6 h, horizonte 48 h, chuva "perfeita" (a observada arquivada do `forcamento_v3`), md-val2-c002.
- S2025_06: 45 ciclos de 20/06 a 01/07/2025 (eventos de validação E27/E28). S2024_05: 63 ciclos de 01/05 a
  17/05/2024 (E18 cal / E19 val). Nenhuma janela de teste.
- MAE em m³/s; "corrigido" = com a correção aditiva do τ(h) do c002.

Variantes:
- **V0**: partida a frio adaptativa em cada ciclo (o ciclo atual; em média 10–12 dias antes de t0).
- **V1**: estado encadeado (= rodada contínua desde o início da janela).
- **V2**: estado + assimilação com memória (o estado assimilado segue para o próximo ciclo).
- **V3**: estado de V1 + assimilação só para a previsão (= `--estado … --assimilar previsao`).

Muçum, todos os ciclos:

| janela | variante | sim/obs em t0 | MAE bruto +6/+24/+48 h | MAE corrigido +6/+24/+48 h |
|---|---|---|---|---|
| S2025_06 | V0 | 0,78 | 547 / 562 / 581 | **149** / 373 / **473** |
| | V1 | 0,72 | 689 / 692 / 703 | 159 / 406 / 540 |
| | V2 | 0,99 | **135 / 336** / 481 | 145 / 344 / 486 |
| | V3 | 1,00 | 208 / 385 / 528 | 219 / 400 / 532 |
| S2024_05 | V0 | 0,82 | 854 / 700 / 666 | 564 / **656 / 656** |
| | V1 | 0,82 | 868 / 709 / 674 | 564 / 658 / 663 |
| | V2 | 1,00 | 584 / 927 / 756 | **514** / 933 / 748 |
| | V3 | 1,01 | 767 / 1094 / 800 | 682 / 1100 / 807 |

Encantado e LJJ na S2025_06 (corrigido para V0/V1, bruto para V2/V3):

| ponto | V0 | V1 | V2 | V3 |
|---|---|---|---|---|
| Encantado | 199 / 508 / 671 | 197 / 566 / 782 | 213 / 436 / 614 | 191 / 382 / 628 |
| LJJ | 156 / 347 / 383 | 160 / 396 / 484 | 128 / 376 / 462 | 150 / 362 / 476 |

Em maio/2024 LJJ e Encantado quase não têm observado na telemetria; ficaram fora da tabela.

Leitura:
- O estado do HMS funciona e é exato, mas **o estado encadeado sozinho (V1) não melhora**: empata com a partida a frio
  em 2024 e piora em 2025. Rodando sem parar, o modelo acumula o próprio erro de volume (subestima ~30 % em
  jun/2025); a partida a frio refaz o q0 pelo observado a cada ciclo.
- **A assimilação zera o viés em t0** (razão 0,99–1,01 contra 0,72–0,82). Ganha em +6 h nas duas janelas e em +24 h
  em 2025, mas **piora muito em +24 h na enchente de 2024** (933 contra 656). Na média dos 108 ciclos, a partida a
  frio com correção aditiva continua melhor em +24 e +48 h; por isso ela continua sendo o padrão.
- Com assimilação, a correção aditiva não acrescenta nada (bruto ≈ corrigido) e o ciclo a desliga.
- Tempo do experimento: 13 min (S2025_06, com cache) + 30 min (S2024_05) no PC, com 4 HEC em paralelo.

### Ciclo ao vivo de hoje (PC, t0 09/10/2026 16:00, c002, chuva em rede)

- Janela 04/10 14:00 → 14/10 16:00. O início ficou preso logo depois da janela de teste, com Muçum em 1112 m³/s.
- Chuva observada até 16:00 com 137 postos (ANA 71, CEMADEN 66; INMET pulado, sem token). Controles 10/10.
- ECMWF 06z (a 12z ainda não tinha o último passo publicado; 64,5 mm na bacia); GFS 12z (25,9 mm).
- Em t0, Muçum observado 383 cm (633 m³/s) contra 1416 m³/s simulados (2,2×). Encantado 832 × 1636, LJJ 556 (15 h) ×
  1172. O c002 parte da mesma recessão alta que o c038 de manhã (1,7×).

| cenário (corrigido) | pico em Muçum | quando | 5 m | 10 m |
|---|---|---|---|---|
| ECMWF 06z | 894 cm (2762 m³/s) | 13/10 18:00 | 10/10 11:00 | não |
| GFS 12z | 596 cm (1445 m³/s) | 11/10 06:00 | 10/10 18:00 | não |
| sem chuva | 439 cm (824 m³/s) | 11/10 01:00 | não | não |

Mesmo t0 com o ECMWF 12z (50,6 mm), sem e com assimilação:

| cenário | sem assimilação (corrigido) | com `--assimilar previsao` |
|---|---|---|
| ECMWF 12z | 874 cm em 13/10 10:00; 5 m em 11/10 00:00 | 828 cm em 13/10 11:00; 5 m em 12/10 12:00 |
| GFS 12z | 598 cm em 11/10 06:00; 5 m em 10/10 18:00 | 540 cm em 11/10 07:00; 5 m em 10/10 22:00 |
| sem chuva | 442 cm em 11/10 01:00 | 445 cm em 09/10 23:00 |

Com a assimilação, Muçum em t0 vai de 1416 para 820 m³/s (observado 633) e Encantado de 1636 para 971 (832).

Cuidado de leitura: com o simulado 2,2× acima, a correção é de −783 m³/s e decai com τ ≈ 36 h. Por isso, mesmo sem
chuva, o corrigido sobe até 11/10 (volta em direção ao simulado alto). Isso puxa para mais cedo o cruzamento de 5 m
do ECMWF; com a assimilação esse efeito some. No experimento retroativo esse efeito não pesou na média, mas num dia
como hoje ele antecipa o 5 m em ~1,5 dia.

### Fase 1 (lr-g8-c038, só ANA)

A reprodução da `cp-r1` (diferença ≤ 0,05 m³/s), a retroativa operacional de 10/05/2024, o ciclo ao vivo de
09/10/2026 13h (PC e nuvem, run 37959276471) e a análise do início adaptativo estão no LEIAME do commit `553154b83`
e nos JSON de `exemplos/`.

## Tempo por ciclo

| ciclo (PC, 3 cenários, 120 h, c002) | total | chuva observada | chuva prevista | HEC |
|---|---|---|---|---|
| rede, partida a frio, ECMWF + GFS baixados agora | 179 s | 123 s | 24 s | 29 s |
| rede + assimilação, rodadas em cache | 116 s | 72 s | 3 s | 36 s (observado 20 + previsão 16) |
| retro ao vivo do mesmo t0 (PC ocupado com o experimento) | 196 s | 142 s | 1 s | 22 s |
| estado encadeado, arquivos locais (retro maio/2024, só "sem chuva") | 20–34 s | — | — | 20–34 s |

A chuva observada passou a ser o gargalo no PC. A ANA em série (72 postos) leva 60–120 s, mais 1–2 s da coleta do
CEMADEN e o QC. A assimilação acrescenta uma rodada do HEC (+7–20 s).

Nuvem (run 37987492580, t0 09/10 17h, rede, partida a frio): **202 s** de ciclo (chuva observada 148 s, sendo ANA
146 s em série sem nenhum 429 e CEMADEN 1,4 s com 66/66 postos; chuva prevista 8 s; HEC 41 s). INMET pulado (sem
`INMET_TOKEN`). Esse ciclo rodou antes da primeira gravação da branch de dados, então o CEMADEN entrou só pela
coleta do instante (135-137 postos/hora nas últimas 6 h, ~70 antes).

Fase 1 (lr-g8-c038, só ANA): ao vivo no PC 75–196 s (o download do GFS domina); na nuvem 89 s (job 1 min 46 s).

## Proposta para o site (não aplicada no repo_site)

1. **Publicação**: o workflow passa a gravar `hec_aovivo_latest.json` num lugar público estável (ex.: a branch de
   dados, ou `assets/data/hec_aovivo/latest.json` por commit do robô), no mesmo esquema de leitura que o site já usa
   para `previsao_ao_vivo.json` (API do GitHub + `cb=` contra cache). O site deve checar `versao` (hoje 2).
2. **Painel de Muçum**: `pontos.MUCUM.observado.nivel_cm` até t0 e `nivel_previsto_cm[cen]` depois (ECMWF em
   destaque), cotas 5/10/15/18 m, tracejado acima de 15 m; cartão com `cotas_previstas.ecmwf`; rodapé com
   `emitido_em`, idade das rodadas, cobertura da chuva (`chuva_observada.postos_usados_por_fonte`), `estado.inicial`
   (partida a frio ou estado) e `avisos`. Se `emitido_em` tiver mais de ~8 h, "previsão desatualizada".
3. **Mancha de Santa Tereza**: ponto `SANTA_TEREZA` em `posproc.PONTOS` (86472600, nó `J_208`) com curva própria —
   proposta da fase 1, ainda não feita (falta a compatibilização de datum).

## Pendências

- **INMET_TOKEN**: sem token os 13 postos do INMET ficam fora (registrado em `chuva_observada.por_fonte.INMET`).
  Criar o secret `INMET_TOKEN` no repositório; no PC, a variável de ambiente.
- **Agendamento**: `schedule` dos dois fluxos (ciclo 4×/dia, coletor a cada 10 min) só vale com os arquivos na branch
  padrão. Até lá o histórico do CEMADEN depende do coletor local (`cemaden.py coletar --loop-min 10`) ou de pushes.
  Atrasos do cron do GitHub (às vezes > 10 min) viram horas por bloco de 3–6 h.
- Branch de dados: podar/espremer o histórico (ex.: mensal) para não crescer sem limite.
- Estado/assimilação: implementados e medidos, mas fora do padrão (ver resultados). A variante que mais ajudou no
  curto prazo (V2, assimilação com memória) precisa de uma cadeia diferente da do `ciclo.py` (começar do estado
  assimilado do ciclo anterior, 6 h antes) e falhou em +24 h na enchente de maio/2024; vale testar um fator parcial
  (ex.: razão^0,5) e mais janelas de validação antes de ligar. O viés de hoje vem também do início preso logo depois
  da janela de teste (04/10, Muçum 1112 m³/s) e do volume do modelo (frente de recalibração a jusante).
- Estrela sem correção nem curva; Santa Tereza sem ponto próprio; ensemble ECMWF e viés da chuva prevista: só os
  encaixes da fase 1.
