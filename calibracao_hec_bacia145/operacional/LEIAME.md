# Executor do HEC ao vivo — bacia 145 (protótipo)

**PESQUISA — não é alerta oficial.** Roda o modelo HEC-HMS da bacia Taquari-Antas (145 sub-bacias, 105 trechos,
parâmetros `lr-g8-c038`) num ciclo de previsão: chuva observada até agora, chuva prevista (ECMWF principal, GFS
segundo, "sem chuva" de referência) depois, correção aditiva pelo último observado, conversão para nível e cotas de
Muçum. Acima de 15 m em Muçum o nível é só indicativo (fim da validade da curva-chave).

Nada do motor foi reescrito: o `.basin` sai de `codigo/estrutura_v3.bacia_v3` (estado inicial pelo q0 observado no
início da janela, como na calibração), o DSS de chuva de `codigo/hec.dss_chuva` e a execução de `codigo/hec.rodar_lote`.
O executor copia `codigo/*.py` para uma pasta de trabalho, igual ao fluxo da nuvem.

## Como rodar

Requisitos: Python ≥ 3.10 com `numpy`, `requests`, `eccodes` (no Windows também `ecmwflibs`) e o HEC-HMS 4.13
(padrão: `D:\PREVINE\tools\hec-hms-4.13\portable\...\HEC-HMS.cmd`, ou `--hec-cmd`). No PC, o venv que já tem tudo:
`D:\PREVINE\repo_hec_calib\_analise_bacia145\chuva_prevista\.venv312\Scripts\python.exe`.

```powershell
cd calibracao_hec_bacia145\operacional
$py = "D:\PREVINE\repo_hec_calib\_analise_bacia145\chuva_prevista\.venv312\Scripts\python.exe"

# ao vivo (t0 = hora cheia atual); grava saida\hec_aovivo_aovivo_<t0>.json e saida\hec_aovivo_latest.json
& $py -B ciclo.py --modo aovivo --horizonte 120 --cenarios ecmwf,gfs,zero

# retroativo operacional: telemetria da ANA + GRIB baixado de novo, como se fosse ao vivo em t0
& $py -B ciclo.py --modo retro --t0 2024-05-10T14:00 --janela-arquivo S2024_05 --rotulo operacional

# retroativo de reprodução: chuva e observados arquivados + período da janela de calibração (deve bater com cp-r1)
& $py -B ciclo.py --modo retro --t0 2024-05-10T14:00 --fonte-obs arquivo --janela-arquivo S2024_05 `
      --fonte-prev arquivo --janela-mae S2024_05 --rotulo reproducao
& $py -B conferir_retro.py saida\hec_aovivo_retro_2024051014_reproducao.json S2024_05   # lê _analise_bacia145 (só no PC)
```

Opções úteis: `--horizonte` (48–120 h), `--cenarios`, `--pos-chuva fator:1.2` (pós-processador da chuva prevista),
`--parametros outro.json`, `--inicio-fixo` (começa exatamente em t0 − `--dias-antes`), `--trabalho` (pasta das
rodadas; padrão `~\hec_aovivo_trabalho`, com o cache das rodadas de previsão em `cache_prev\`).

Retroativas que encostam na janela de teste (`X20260918`, 18/09–04/10/2026) são recusadas; ao vivo, a janela nunca
começa dentro dela. Nenhuma métrica é calculada nesses eventos.

**Nuvem:** `.github/workflows/hec-bacia145-aovivo.yml` roda um ciclo no Linux (HEC-HMS 4.13 linux64, mesmo cache do
fluxo de lote) a cada push nesta branch que mexa em `operacional/`, e sobe o JSON como artefato `hec-aovivo-<run>`.
`workflow_dispatch` (modo, t0, horizonte, cenários) e o `schedule` (4×/dia, ~1 h depois de cada rodada do ECMWF) só
passam a valer quando o arquivo estiver na branch padrão. O fluxo de lote (`hec-bacia145-lote.yml`) foi ajustado para
não disparar nesta branch (senão o `PEDIDO.json` da cp-r2 rodaria de novo).

## Arquivos

| arquivo | papel |
|---|---|
| `ciclo.py` | orquestrador de um ciclo (janela, fontes, HEC, pós-processamento, JSON) |
| `executor.py` | pasta de trabalho, gerador do `.basin`, `hec.rodar_lote` com um projeto por cenário |
| `chuva_observada.py` | `FonteChuvaObservada` → `ChuvaObservada`; `TelemetriaANA` (QC + IDW), `ArquivoForcamento` |
| `chuva_prevista.py` | `FonteChuvaPrevista` → `[Cenario]`; `ModeloAberto` (ECMWF/GFS por byte-range), `SemChuva`, `ArquivoPrevista`; pós-processadores |
| `vazao_observada.py` | `FonteObservados` dos postos de controle (estado inicial e correção) |
| `posproc.py` | correção aditiva, curva nível × vazão, cotas de Muçum, resumo de conjunto |
| `telemetria_ana.py`, `geo.py` | cliente do HidroTelemetria; sub-bacias, UTM 22S, pesos de grade |
| `conferir_retro.py` | compara uma retroativa com `nuvem/cp-r1` e com o estudo `correcao/horaria` |
| `preparar_dados.py` | gera `dados/` e `parametros/` a partir das fontes do PC (só quando elas mudarem) |
| `dados/` | sub-bacias (centróide, área, pontos a 0,01°), 130 postos ANA, curvas da telemetria, τ(h) da correção |
| `parametros/lr-g8-c038.json` | conjunto de parâmetros (id, família, gerador, `p`, sha256) |
| `exemplos/` | JSON do ciclo ao vivo de 09/10/2026 13h e da retroativa de 10/05/2024 14h, com as conferências |

## O que um ciclo faz

1. **Janela**: de t0 − 5 a 30 dias até t0 + horizonte, passo de 10 min no modelo e saída horária. O início é a hora
   mais recente em [t0 − 30 d, t0 − 5 d] com Muçum ≤ 1,25 × a mínima do período (`escolher_inicio`). Motivo: com
   início fixo em t0 − 5 d, em 10/05/2024 a janela começava numa recessão de 6892 m³/s; o q0 alto enche o
   reservatório lento (GW-2, k ≈ 1100 h) e o simulado ficava em 5428 m³/s contra 968 observados em t0. A calibração
   só viu janelas que começam em vazão baixa. Se o início ainda ficar acima de 1500 m³/s, o JSON avisa.
2. **Observados dos controles** (ANA, 10 postos): só o que é ≤ t0 no horário corrigido (o relógio de Muçum adiantado
   105 min em 2023–2024 é corrigido antes do corte — sem isso a correção de Muçum errava 47 m³/s na reprodução).
3. **Chuva observada**: telemetria da ANA (130 postos), hora H = soma de (H − 60 min, H], QC iterativo por 3
   vizinhos (subregistro < 0,4×, excesso > 2,5×), IDW p = 2 nos centróides; vai até a última hora com ao menos
   max(5, metade da mediana) de estações. Cobertura, exclusões do QC e falhas de rede vão para o JSON.
4. **Chuva prevista**: ECMWF IFS 0,25° e GFS 0,25°, só a mensagem de precipitação por byte-range, desacumulada e
   média na área de cada sub-bacia. Ao vivo: a rodada mais nova que já publicou o último passo necessário; se faltar
   algum passo (rodada ainda sendo publicada), cai para a anterior e registra o motivo. Retroativo: a regra do estudo
   (início + atraso ≤ t0; GFS 5 h, ECMWF 7 h, só 00/12z). Um cenário que falha não derruba os outros.
5. **HEC**: um projeto por cenário, em paralelo; mesmo `.basin` e mesmo trecho observado, muda só a chuva depois da
   última hora observada. Horas sem chuva (observada ou prevista) viram 0 e são contadas nos avisos.
6. **Pós-processamento** (LJJ, Muçum, Encantado; Estrela só simulado e observado): Q = S + e(tv)·exp(−(t − tv)/τ(h)),
   tv = último observado válido (nível ≤ limite da curva: LJJ 18 m, Muçum 15 m, Encantado 19,2 m) até 72 h antes,
   τ(h) do estudo `correcao/horaria`; nível pelos pares da telemetria da própria janela, fora da faixa a curva
   agregada das 33 janelas (sem a de teste). Cotas de Muçum: atenção 5 m, alerta 10 m, limite da curva 15 m,
   inundação 18 m (indicativa).

## Saída (JSON, `versao_esquema` 1)

- `emitido_em`, `t0`, `janela` (início escolhido e a regra), `parametros` (id, sha256, q0 específico dos controles)
- `chuva_observada`: fonte, `ate`, postos consultados/com registro/usados, excluídos no QC, falhas de rede, estações
  por hora
- `cenarios[]`: id, modelo, papel, status, rodada (UTC), idade da rodada em t0 e na emissão, até onde cobre, chuva
  prevista na bacia (mm), `grupo`/`membro`/`peso` (ensemble), pós-processamento aplicado, avisos
- `horas[]` e `chuva_media_bacia_mm{cenário: []}`
- `pontos{LJJ, MUCUM, ENCANTADO, ESTRELA}`: `observado{vazao_m3s, nivel_cm}`, `simulado{cen}`, `corrigido{cen}`,
  `nivel_previsto_cm{cen}`, `ultimo_observado_valido`, `erro_em_tv_m3s`, `tau_h_usado`, `curva`; em Muçum,
  `cotas_previstas{cen: pico, t_pico, cotas{cruza, primeiro_cruzamento, antecedencia_h, indicativo}}`; com ensemble,
  `conjunto{grupo: quantis p10/p50/p90 e probabilidade de cada cota}`; no retroativo, `verificacao_apos_t0`
- `avisos[]`, `tempos_s`

## Resultados

### Ao vivo, 09/10/2026, t0 13:00 (`exemplos/hec_aovivo_aovivo_2026100913.json`)

- Janela 04/10 13:00 → 14/10 13:00 (o início ficou preso logo depois do fim da janela de teste; Muçum 1006 m³/s).
- Chuva observada até 12:00: 130 postos consultados, 112 com registro, 78 usados, 2 excluídos no QC; 33,8 mm na
  bacia na janela. Controles com dado: 10/10.
- ECMWF 06z (idade 10 h, 65,9 mm previstos na bacia); GFS 06z (a 12z ainda não tinha o passo 68 publicado; 26,1 mm).
- Muçum, último observado 12:00 = 441 cm (829 m³/s); simulado 1409 m³/s → correção de −521 m³/s.

| cenário | pico em Muçum (corrigido) | quando | 5 m | 10 m |
|---|---|---|---|---|
| ECMWF | 886 cm (2725 m³/s) | 13/10 19:00 | 09/10 17:00 (+4 h) | não |
| GFS | 636 cm (1627 m³/s) | 11/10 04:00 | 09/10 17:00 | não |
| sem chuva | 529 cm (1163 m³/s) | 10/10 04:00 | 09/10 17:00 | não |

Cuidado de leitura: em t0 o modelo estava ~1,7× acima do observado em todos os postos (LJJ 1218 × 344,
Encantado 1616 × 972 m³/s). A correção decai com τ de 24–72 h, então o pico do ECMWF no dia 13 já carrega boa parte
desse excesso do simulado. É exatamente o caso que a frente 3 (modelo) e um estado inicial melhor devem atacar.

### Retroativa, 10/05/2024 14:00 (enchente de maio/2024)

**Reprodução** (chuva e observados arquivados, período da janela S2024_05): simulado idêntico ao da nuvem `cp-r1`
(diferença máxima 0,05 m³/s em LJJ, Muçum e Encantado, nos três cenários) e vazão corrigida de Muçum/Encantado
idêntica ao estudo `correcao/horaria` (≤ 0,05 m³/s em +3/6/12/24/48 h). O pipeline reproduz as análises de
`chuva_prevista`.

**Operacional** (`exemplos/hec_aovivo_retro_2024051014_operacional.json`; telemetria da ANA para tudo, GRIB baixado
de novo, início adaptativo em 14/04 02:00 com Muçum 78 m³/s):

- Chuva prevista idêntica à do arquivo do estudo (ECMWF 00z: 118,4 mm em 72 h; GFS 12z: 32,4 mm).
- Chuva observada só da ANA: 659 mm na janela inteira; no período em comum com o `forcamento_v3` (que soma CEMADEN
  e INMET), 605,8 contra 575,4 mm.
- Muçum corrigido (ECMWF) +24 h: 3056 m³/s (estudo 2899; observado 3969); diferenças de 3 a 157 m³/s em
  +3…+48 h, vindas da janela e da chuva observada diferentes.
- Pico ECMWF em Muçum 1160 cm em 13/05 19:00, cruza 10 m em 13/05 01:00 (59 h de antecedência). Observado: 2025 cm
  em 12/05 20:00 — a chuva determinística subestimou muito o evento, como no estudo.
- LJJ sem observado válido na telemetria nesse período (sem correção); Encantado com último válido 31 h antes de t0.

## Tempo por ciclo (PC, 3 cenários, horizonte 120 h)

| situação | total | chuva observada | chuva prevista | HEC |
|---|---|---|---|---|
| ao vivo, ECMWF e GFS baixados agora | 196 s | 39 s | 133 s (GFS 116 passos: 129 s) | 19 s |
| ao vivo, só ECMWF baixado agora | 116 s | 28 s | 67 s | 17 s |
| ao vivo, ECMWF em cache (GFS falhou nessa vez, 2 cenários) | 75 s | — | — | — |
| retroativa operacional, rodadas em cache | 87 s | 45 s | 1 s | 33 s |
| retroativa operacional, rodadas baixadas | 151 s | — | — | — |
| reprodução (arquivos locais) | 30 s | — | — | 29 s |

O gargalo é o download: GFS de hora em hora até 120 h são 116 mensagens; ECMWF de 3 em 3 h, 42. O HEC (3 cenários em
paralelo) leva 17–33 s conforme o comprimento da janela; membros de ensemble também rodam em paralelo, então o custo
cresce com o número de membros dividido pelos núcleos disponíveis (não medido).

## Pontos de encaixe para as outras frentes

**Frente 1 — correção de viés da chuva prevista e ensemble ECMWF.**
- Viés: uma função `Cenario → Cenario` registrada em `chuva_prevista.POS_CHUVA` e pedida com
  `--pos-chuva nome:arg` (exemplo pronto: `fator`, testado com `fator:1.2` → ECMWF 118,4 → 142,1 mm). O nome entra em
  `pos_processamento_chuva` no JSON.
- Ensemble: uma nova `FonteChuvaPrevista` que devolve um `Cenario` por membro com o mesmo `grupo` (ex.:
  `"ecmwf-ens"`), `membro` e `peso`. O executor já roda um HEC por cenário, e `posproc.resumo_conjunto` já gera os
  quantis p10/p50/p90 da vazão corrigida e a probabilidade de cada cota de Muçum por grupo. Falta só a fonte (IFS
  ENS `ef`, mesma URL com `enfo`) e decidir quantos membros cabem no tempo do ciclo.

**Frente 2 — chuva observada ao vivo por sub-bacia.** Uma subclasse de `chuva_observada.FonteChuvaObservada` com
`obter(ini, ate, contexto) → ChuvaObservada(horas, chuva{sub: [mm|None]}, ate, fonte, cobertura)`. Pode juntar
fontes (ANA + CEMADEN + INMET) e reutilizar `grade`, `chuva_horaria` e `qc_iterativo`. `ate` decide onde começa a
chuva prevista; `cobertura` vai inteira para o JSON. Escolha no `ciclo.py` (`--fonte-obs`).

**Frente 3 — melhorias do modelo (seções de canal, Clark variável).** Um novo `parametros/<id>.json` com `p`, `rota`
e `gerador` (`"modulo.funcao"`, hoje `estrutura_v3.bacia_v3`); o gerador recebe `(p, sim, rota)` e devolve o texto
do `.basin`. Rodar com `--parametros`. Se o gerador mudar o nome dos nós de controle, atualizar `posproc.PONTOS`.
Uma correção diferente (assimilação, outra curva) substitui `posproc.ponto` mantendo as chaves de saída.

## Proposta para o site (não aplicada no repo_site)

1. **Publicação**: o workflow passa a gravar `hec_aovivo_latest.json` num lugar público estável (ex.: branch de dados
   ou `assets/data/hec_aovivo/latest.json` por commit do robô, com `contents: write`), no mesmo esquema de leitura
   que o site já usa para `previsao_ao_vivo.json` (API do GitHub + `cb=` contra cache).
2. **Painel de Muçum**: gráfico com `pontos.MUCUM.observado.nivel_cm` até t0 e `nivel_previsto_cm[cen]` depois
   (ECMWF em destaque, GFS e sem chuva como faixa), linhas das cotas 5/10/15/18 m, tracejado acima de 15 m
   ("indicativo"); cartão com `cotas_previstas.ecmwf` (pico, horário, antecedência); rodapé com `emitido_em`, idade
   das rodadas (`idade_rodada_h_na_emissao`), cobertura da chuva observada e `avisos`. Se `emitido_em` tiver mais de
   ~8 h, mostrar "previsão desatualizada".
3. **Mancha de Santa Tereza**: a página `santa_tereza_previsao_inundacao.html` já escolhe o contorno de
   `assets/data/santa_tereza_inundacao/contornos_extravasamento.json` por `properties.nivel_m` (0–15 m, passo 0,1)
   a partir de (nível em 86472600 − bankfull)/100 (`achaFeature`/`setLayer`). Para ligar ao HEC: acrescentar um
   ponto `SANTA_TEREZA` em `posproc.PONTOS` (código 86472600, vazão do nó de LJJ, `J_208`) com curva própria —
   pares (vazão de LJJ, nível em 86472600) da telemetria, como em `curvas_telemetria.json` — e a página usa
   `pontos.SANTA_TEREZA.nivel_previsto_cm.ecmwf[h]` hora a hora como `foreDm`. Pendente: a compatibilização de
   datum entre a régua 86472600 e o MDT que o próprio README da pasta aponta.

## Pendências

- Estado quente: hoje cada ciclo recomeça do q0 observado no início da janela; guardar o estado do HEC (ou da
  correção) entre ciclos reduziria o viés de 1,7× visto hoje e o custo da janela longa.
- Chuva observada ao vivo só com a ANA (CEMADEN/INMET fora): frente 2.
- Estrela sem correção nem curva; Santa Tereza sem ponto próprio (ver proposta acima).
- Ensemble ECMWF e correção de viés: só os encaixes (frente 1).
- Nuvem: o workflow foi disparado por push; o agendamento só vale na branch padrão e o JSON fica como artefato (sem
  publicação).
- Telemetria da ANA às vezes devolve postos de controle com lacunas longas (LJJ em maio/2024): o ciclo segue sem
  correção nesse ponto e avisa.
