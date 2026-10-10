# Calibração HEC-HMS da bacia Taquari-Antas (modelo de 145 sub-bacias) — lote na nuvem

**Pesquisa. Nada aqui é alerta, previsão operacional ou orientação de evacuação.**

Executa no GitHub Actions (Linux, HEC-HMS 4.13) lotes de simulações do modelo reconstruído de 145 sub-bacias e
105 trechos, para calibrar e avaliar parâmetros em dezenas de eventos históricos (catálogo de Muçum, 2018–2026).
Um lote é dividido em até 20 jobs em paralelo.

## O que tem aqui

| Pasta | Conteúdo |
|---|---|
| `codigo/` | Gerador do modelo (`estrutura_v3.py`), métricas (`metricas.py`, `bacia_inteira.py`), executor do HEC (`hec.py`), `nuvem_lote.py` (um pedaço do lote), `nuvem_agregar.py` (métricas e J por candidato) |
| `dados/basin/` | Modelo-base (`a00_E27.basin`: 145 sub-bacias, 105 trechos, Clark, Initial+Constant, Recession, Muskingum) |
| `dados/forcamento_v3/` | Chuva horária por sub-bacia, 34 janelas (ANA + CEMADEN + INMET, controle de qualidade por vizinhos) |
| `dados/observados/` | Vazão e nível observados nos 10 controles (telemetria ANA, 15 min), já com o relógio de Muçum corrigido na leitura |
| `dados/catalogo_ampliado.json` | Janelas e eventos, com os papéis congelados: calibração / validação / teste |
| `dados/smoke/` | Teste de fumaça: 2 candidatos × 2 janelas com os resultados esperados do PC |

Tamanho total: ~4 MB. Todos os dados são abertos (ANA, CEMADEN, INMET).

## Como usar

1. **Teste de fumaça** (a cada push na branch de teste): roda o HEC no Linux e confere as métricas com as do PC
   (tolerância de 5%). Se passar, o ambiente está validado.
2. **Lote**: `gh workflow run hec-bacia145-lote.yml -f candidatos_json='[...]' -f janelas=cal -f shards=20 -f rodada=r01`
   (exige o fluxo na branch padrão). Resultado: artefato `resultado-<rodada>` (`resultado.json`) e os `vazao.csv` por shard.
3. **Eventos de teste** (set/2026) ficam fora de qualquer resultado até a configuração estar congelada.

## Famílias novas (branch `cursor/hec-bacia145-perda-dc`, 09/10/2026)

Gerador: `codigo/rodada_dc.py` (`--familia dc|lric|lrdc`, aceita várias separadas por vírgula; modos `lhs`, `es`, `top`).
Mesmas 17 janelas de calibração das famílias g1/g2/g4/g6, para o J ser comparável com lib-A (7,13) e scs-A (8,94).

| Família | Perda | Base | Por quê |
|---|---|---|---|
| `dc` | Deficit and Constant + dossel/superfície simples + ET mensal | Recession | solo com capacidade limitada (I+C não satura) |
| `lric` | Initial+Constant | Linear Reservoir (2 camadas) | a Recession descarta a perda; o reservatório linear a devolve ao rio |
| `lrdc` | Deficit and Constant | Linear Reservoir (2 camadas) | idem, só a percolação |

Resultado (lr-g0..g8: LHS + 8 gerações de estratégia evolutiva, 48 candidatos por geração; lr-av1: validação em
`todas`). J de validação = mesma regra do J_evento (média da penalidade dos 6 controles do objetivo), nos 28 eventos de
validação; "passa" conta controle×evento que atende os 4 critérios.

| Candidato | Família | J cal | J val | passa val | imp |
|---|---|---|---|---|---|
| lr-g8-c038 (lr-av1-c003) | lrdc | **6,98** | **7,24** | 13/144 | 3,4% |
| lr-g8-c027 (lr-av1-c004) | lrdc | 7,09 | 7,48 | 10/144 | 3,3% |
| lr-g8-c016 (lr-av1-c001) | lric | 7,41 | 7,63 | 11/144 | 11,0% |
| lib-A (referência) | I+C + Recession | 7,13 | 7,72 | 3/144 | 41,3% |
| scs-A (referência) | SCS + Recession | 8,94 | 6,50 | 11/144 | 40,8% |

`lrdc` é a primeira estrutura que fica no nível do lib-A na calibração e o supera na validação sem área impermeável
irreal. Na validação por controle (mediana), o NSE sobe em Tainhas, Castro Alves, Monte Claro, LJJ e Encantado; em
Muçum fica igual (0,54 contra 0,56). Ainda falta volume a jusante (Muçum −18%, Encantado −25%), e o pico em Monte Claro e
Encantado fica 27–30% baixo. Nenhuma estrutura atende os critérios na maioria dos eventos: o J ~7 ainda está longe de 1.
Próximos passos: Clark variável (lag não linear) e mais peso nos eventos grandes.

Achados da revisão das rodadas anteriores:

- **Área impermeável de ~41%** no melhor I+C: com base Recession, toda a perda some da bacia, e a busca fecha o volume
  aumentando `imp`. Nas famílias `lric`/`lrdc`, `imp` fica limitado a 15% e 5%, e a perda volta ao rio por GW-1
  (rápido, `k1` h) e GW-2 (lento, `k2` h); `fb` é a fração que volta (o resto é recarga profunda).
- `dc` com Recession é estruturalmente errada (dc-g0: volume −38%, atraso de 10–24 h): o manual do HMS só liga a
  percolação da Deficit Constant ao fluxo de base em reservatório linear.
- Parâmetros encostados no limite nas rodadas lib/scs: `mr`, `s0`, `thr`.
- J de famílias com conjuntos de janelas diferentes não é comparável; compare só com as mesmas janelas.
- `nuvem_agregar.py` descartava as métricas de papel "teste" sem `--teste`, e a rodada teste1 saiu vazia. O fluxo agora
  passa `--teste` quando o PEDIDO traz `"abrir_teste": true`. Os eventos de teste continuam fechados.

## Perda que cresce com a cheia (branch `cursor/hec-bacia145-perda-cheia`, 09/10/2026)

O melhor modelo (vo-rp5-c041 / vo-val-c008, `lrdcr` só com fb regional) subestima os picos grandes a jusante, e o
coeficiente de escoamento simulado fica ~0,5 em todo porte, enquanto o observado cresce com o evento (Muçum 0,50 →
0,63; Encantado 0,50 → 0,67). Três famílias novas, todas com Linear Reservoir e `xfb_T`/`xfb_B` regionais:

| Família | Perda | Por quê |
|---|---|---|
| `lrdcf` | Deficit and Constant (controle: `lrdc` + fb regional, sem os outros multiplicadores do `lrdcr`) | controle justo |
| `lrscsf` | SCS Curve Number, `S = s0·exp(−q0/q*)` (CN ≤ 98), `Ia = iar·S` | C = Pe/P cresce com a chuva acumulada; sem recuperação entre eventos |
| `lrsmaf` | Soil Moisture Accounting (solo = zona de tensão `dmax` + gravitacional `sup`; GW1/GW2), regional `xpdeep_T`/`xpdeep_B`; o reservatório linear vira só o trecho de propagação (`K_LR_SMA` = 1 h) | excesso por saturação: a infiltração cai quando o solo enche; seca por ET entre eventos |

Green-Ampt ficou de fora (excesso hortoniano, depende de intensidade; as cheias do Taquari são de saturação após dias
de chuva). Uma DC "reformulada" é o SMA com uma camada. O HEC-HMS recusa camadas do SMA acima de 1500 mm (ERROR 42001).
Novas opções do `rodada_dc.py`: `--livres` e `--sem-centro` (modo `viz`) e `--forcamento`.

Comparação justa (forcamento_v3b, objetivo J_pico): g0 = 48 vizinhos de vo-val-c008 com a perda livre, mais 5
gerações de ES (λ 48, μ 8). Depois, 3 gerações a mais só para controle e SMA. Validação em todas as janelas menos a de teste.

| Candidato | J cal | J_pico cal | J val | J_pico val | passa val |
|---|---|---|---|---|---|
| vo-val-c008 (referência) | 6,11 | 5,29 | 5,84 | 6,04 | 14/144 |
| vo-rp5-c041 (referência) | 6,07 | 5,24 | 5,89 | 6,13 | 13/144 |
| pc-f5-c004 (`lrdcf`, g5) | 6,11 | 5,23 | 5,77 | 5,89 | 22/144 |
| pc-f8-c025 (`lrdcf`, g8) | 5,92 | **5,12** | 5,68 | 5,91 | 17/144 |
| pc-scs5-c026 (`lrscsf`, g5) | 7,40 | 6,35 | **5,33** | **5,45** | 6/144 |
| pc-sma5-c025 (`lrsmaf`, g5) | 6,95 | 5,78 | 6,14 | 6,11 | 13/144 |
| pc-sma8-c027 (`lrsmaf`, g8) | 6,51 | 5,34 | 6,22 | 6,05 | 11/144 |

- Pela regra (escolha só na calibração), o melhor é o controle recalibrado `lrdcf` (pc-f8-c025). Ele melhora pouco
  sobre o vo-val-c008, e o pico grande segue baixo: mediana em Muçum −22%, em Encantado −31%.
- O SMA reproduz o C crescente (Muçum, cheias grandes: 0,66 contra 0,63 observado) e o pico grande em Muçum
  (mediana −3%; −18% só dentro da curva). Mas passa do pico em mai/2024 (+44%) e jul/2020 (+36%), os dois com
  Q obs extrapolada; produz volume demais em Tainhas (+25–36%) e não melhora o J de validação.
- O SCS tem o melhor J de validação (5,21–5,33 nos 3 melhores), mas o pior de calibração: piora a forma dos
  eventos pequenos (NSE em Encantado 0,20–0,35 contra 0,52–0,54). O ganho na validação pode ser da época (a divisão cal/val é temporal).
- Fora dos eventos (dentro das janelas, partindo da vazão observada), SCS e SMA sobem a vazão de recessão
  ~7–12% sobre o controle. A tendência é aumentar o excesso do sistema ao vivo, não reduzir.

Segunda rodada justa (10/10): `lrsmar` = `lrsmaf` + multiplicadores T/B de zona de tensão, zona gravitacional,
infiltração e percolação do solo (`dmax + sup` ≤ 1499 mm), a partir do pc-sma8-c027. O controle `lrdcf` parte do
pc-f8-c025. Cada linha: g0 = 48 vizinhos + 6 gerações de ES iguais (forcamento_v3b, J_pico; branches `-e` e `-f`).

| Candidato | J cal | J_pico cal | J val | J_pico val | passa val |
|---|---|---|---|---|---|
| pc-f8-c025 (referência) | 5,92 | 5,12 | 5,68 | 5,91 | 17/144 |
| pr-f6-c007 (`lrdcf`) | 5,85 | **5,07** | 5,83 | 5,89 | 18/144 |
| pr-smar6-c004 (`lrsmar`) | 6,40 | 5,13 | 6,41 | 6,16 | 8/144 |

A linha SMA fica encerrada: perde na calibração e na validação. Os multiplicadores regionais não tiram o excesso de
Tainhas (C das cheias grandes 0,63 contra 0,44 observado; NSE 0,05–0,45). Contando só os picos dentro da curva-chave,
o pico grande em Muçum é igual ao do controle (−22%). O ganho aparente vem dos picos acima da curva, onde o SMA passa
do valor (mai/2024 +46%, jul/2020 +39%).

Análises: `_analise_perda/` (não versionada).

## Janelas derivadas com chuva prevista (09/10/2026)

`<mãe>__<t0 AAAAMMDDHH>__<modelo>` (ex.: `S2023_09__2023090313__gfs`) é uma emissão de previsão: mesmo período,
observados e estado inicial da janela-mãe; chuva observada até a hora t0 (hora local) e, depois, a do modelo
(`gfs`, `ecmwf`: `dados/forcamento_prevista/<mãe>__<modelo>.json.gz`, 72 h horárias a partir de t0+1 h; além disso,
zero) ou nenhuma (`zero`). Registradas por `comum.janela` quando listadas em `janelas` do PEDIDO; não têm eventos
próprios (o `resultado.json` não muda). As janelas antigas não mudam.

## Regras

- Uma física por vez; escolhas só com eventos de **calibração**; a validação só relata; o teste é aberto uma vez.
- Vazão de Muçum só abaixo de 15 m e de LJJ abaixo de 18 m (curva-chave); acima disso vale só o horário do pico pelo nível.
