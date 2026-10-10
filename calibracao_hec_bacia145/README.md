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

## Janelas derivadas com chuva prevista (09/10/2026)

`<mãe>__<t0 AAAAMMDDHH>__<modelo>` (ex.: `S2023_09__2023090313__gfs`) é uma emissão de previsão: mesmo período,
observados e estado inicial da janela-mãe; chuva observada até a hora t0 (hora local) e, depois, a do modelo
(`gfs`, `ecmwf`: `dados/forcamento_prevista/<mãe>__<modelo>.json.gz`, 72 h horárias a partir de t0+1 h; além disso,
zero) ou nenhuma (`zero`). Registradas por `comum.janela` quando listadas em `janelas` do PEDIDO; não têm eventos
próprios (o `resultado.json` não muda). As janelas antigas não mudam.

## Parâmetros por porte de cheia (branches `cursor/hec-bacia145-porte`, `-porte-m`, `-porte-k`, 09/10/2026)

`rodada_dc.py --eventos` (objetivo = J só nos eventos de um porte), `--livres` (só esses parâmetros variam) e
`--forcamento`. Regra congelada só com eventos de calibração, antes de validar: em td = pico de Muçum − 24 h,
S = chuva observada nas 24 h anteriores + chuva prevista (ECMWF) nas 48 h seguintes, média na bacia de Muçum;
**S ≥ 83,4 mm → conjunto de cheia grande `po-g4-c008`; senão, `vo-rp5-c041` só com fb (b0)**.

Busca com o mesmo orçamento (po-0 + 4 gerações de ES, 48 por geração, forcamento_v3b): G = J nos 6 grandes de
calibração (4,21 → 3,14); M = médios + grandes (4,35 → 4,12); controle K = J_pico em todos (5,292 → 5,287, sem ganho).
Validação (po-val, 28 eventos, teste fora): nenhuma cheia grande perdida; 6 alarmes falsos (2 pequenos, 4 médios).

| validação, mediana | b0 sempre | regra |
|---|---|---|
| J todos / pequenos / médios / grandes | 5,84 / 6,17 / 4,64 / 6,49 | 5,79 / 7,35 / 4,85 / 4,71 |
| grandes: pico Muçum (3 abaixo de 15 m) / Encantado (5) | −0,26 / −0,31 | −0,03 / −0,11 |
| grandes: volume Muçum / Encantado | −0,10 / −0,20 | −0,04 / −0,11 |
| grandes: NSE Muçum / Encantado | 0,74 / 0,46 | 0,86 / 0,83 |

O conjunto G superestima eventos pequenos (+30% a +45% de pico quando usado neles); perc e mr encostam no teto (12).

```json
{"qstar": 0.0145, "mr": 12.0, "v_alto": 0.8318, "v_resto": 0.5694, "mn": 0.8884, "mk": 0.598, "v_grandes": 0.9415,
 "ks": 0.3857, "dmax": 69.0104, "perc": 12.0, "imp": 0.0443, "k1": 23.6927, "k2": 622.114, "fb": 0.6598, "p1": 0.9681,
 "s1": 0.3285, "xdmax_T": 1.0, "xperc_T": 1.0, "xfb_T": 0.7046, "xdmax_B": 1.0, "xperc_B": 1.0, "xfb_B": 1.0935}
```

## Regras

- Uma física por vez; escolhas só com eventos de **calibração**; a validação só relata; o teste é aberto uma vez.
- Vazão de Muçum só abaixo de 15 m e de LJJ abaixo de 18 m (curva-chave); acima disso vale só o horário do pico pelo nível.
