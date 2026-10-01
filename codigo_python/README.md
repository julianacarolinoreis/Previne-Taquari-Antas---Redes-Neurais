# Código Python — PREVINE Taquari-Antas (Santa Tereza)

Esta pasta reúne **todo o código Python** usado para construir a camada de
previsão em tempo real e a espacialização da inundação (mancha) da estação
**Santa Tereza — 86472600**, na bacia Taquari-Antas.

O objetivo do projeto é **antecipar avisos de cheia**: a rede neural (RNA)
prevê o nível do rio nas próximas horas, e o terreno (MDT + HAND) transforma
esse nível em **até onde a água chega na cidade**.

> **PREVINE ≠ PMRR.** Este código pertence ao PREVINE (redes neurais /
> previsão). A metodologia das redes (treino em MATLAB) é do grupo; aqui está
> a parte de **operação, validação e espacialização** feita em Python.

---

## Visão geral do pipeline

```
   Telemetria ANA (níveis, 4 estações)
              │
              ▼
   [01] RNA 2h (.mat treinado)  ──►  nível previsto para +2h
              │
              ▼
   [02] LiDAR bruto + FLOWDIR/FLOWACC + HAND hidráulico ──► mancha: até onde a água chega
              │
              ▼
   Site (GitHub Pages) se atualiza sozinho a cada 30 min
```

As três etapas correspondem às três subpastas.

---

## `01_previsao_ao_vivo/` — a RNA rodando em tempo real

| Arquivo | O que faz |
|---|---|
| `gerar_previsao_ao_vivo.py` | **O robô.** Busca a telemetria da ANA das 4 estações, monta os 15 inputs, roda a RNA (`.mat`) e escreve `previsao_ao_vivo.json` (nível atual → previsão de 2h). Roda no GitHub Actions a cada 30 min. |
| `validar_forward_pass.py` | **Prova de que o Python reproduz o modelo treinado.** Abre o `.mat`, refaz o forward-pass e compara com as previsões gravadas — resultado: **RMSE 0,0** (reprodução exata). |
| `previsao-ao-vivo.yml` | Agendador (GitHub Actions, `cron */30`) que roda o robô e publica o JSON. |

### A rede (decodificada a partir do `.mat`, sem MATLAB)

- **Modelo:** 2h, tipo **ALT** (a rede prevê a *variação* do nível; nível
  previsto = nível atual + variação), combo **C0472**, 30 neurônios.
- **Normalização de entrada:** `pn = (P − be) / ae` (média/desvio por input).
- **Camada oculta e saída:** ativação **logsig** (sigmoide unipolar).
- **Desnormalização:** `variação = yn·au + bu`.
- **Qualidade (gravada no `.mat`):** NASH = 0,988 · PERS = 0,613 · E95 = 18,3 cm.

### Os 15 inputs (ordem e definição validadas 9677/9677 linhas)

Todos são **níveis** (sem chuva), a cada hora. Convenções:
`D-Xh = n(t) − n(t−Xh)` (diferença) e
`A-Xh = [n(t) − n(t−1h)] − [n(t−Xh) − n(t−Xh−1h)]` (aceleração).

```
 1 nível ST 86472600           9 Carreiro 86507000 D-16h
 2 ST D-1h                     10 ST D-2h
 3 nível R.Antas 86472000      11 ST D-4h
 4 R.Antas D-5h                12 ST A-1h
 5 R.Antas A-20h               13 ST A-2h
 6 nível Ituim 86125130        14 ST A-4h
 7 Ituim D-12h                 15 ST A-12h
 8 nível Carreiro 86507000
```

---

## `02_mdt_hand_mancha/` — do nível à mancha de inundação

Para **Santa Tereza**, o produto atual usa exclusivamente o conjunto LiDAR em
`D:\\PREVINE\\hand\\santa tereza`:

- `CLIP_MOSAICO_LIDAR_RS.tif`: superfície física do terreno e das barreiras;
- `FILL_CLIP_MOSAICO_LIDAR_RS.tif`: somente apoio ao roteamento;
- `FLOWDIR_CLIP_MOSAICO_LIDAR_RS.tif`: direção D8;
- `FLOWACC_CLIP_MOSAICO_LIDAR_RS.tif`: definição do rio principal.

O gerador segue o fluxo D8 até o rio principal e calcula também um limiar
hidráulico pela **maior cota do LiDAR bruto ao longo do caminho**. Assim, uma
depressão atrás de rua, aterro ou divisor não é inundada apenas por ser baixa.

| Arquivo | O que faz |
|---|---|
| `gerar_hand_lidar_santa_tereza.py` | **Pipeline atual de Santa Tereza.** Gera HAND hidráulico, payload web ~5 m, contornos de 0–25 m e MDT same-source ~10 m a partir do LiDAR bruto. |
| `gerar_contornos_extravasamento.py` | Deriva a camada visual fora do contorno-base HAND 0 sem alterar o terreno nem o HAND. |
| `gerar_mosaico_mdt.py`, `gerar_mancha_mosaico.py`, `gerar_contornos_vetoriais.py` | Pipeline legado drone + ANADEM. O código está bloqueado para Santa Tereza e permanece apenas para rastreabilidade/uso de Muçum onde aplicável. |
| `hand.py`, `hand2.py`, `hand3.py`, `hand4.py` | Iterações históricas do HAND; não são a fonte publicada de Santa Tereza. |

**Contrato atual de Santa Tereza:** régua **1,60 m = HAND 0**; superfície de
inundação = LiDAR bruto; FILL/FLOWDIR/FLOWACC = roteamento; payload de consulta
~5 m; grade de altitude same-source ~10 m. O deploy falha automaticamente se a
página voltar a referenciar o mosaico drone + ANADEM.

---

## `03_experimento_corte_subida/` — remover o “efeito cobrinha” das barragens

Experimento para treinar as redes **só na subida** dos eventos de cheia,
descartando a oscilação de água baixa regulada pelas barragens (o
“efeito cobrinha” abaixo de 5 m).

| Arquivo | O que faz |
|---|---|
| `seg.py` | Segmenta cada evento: mantém **um bloco contíguo** — a subida (mesmo abaixo de 5 m) até o pico — e corta quando o nível cai abaixo de 5 m depois do pico. |
| `build_clean.py` | Monta os datasets “limpos” dos **top 10 modelos** por PERS (8h e 12h × ALT e CONV), aplicando a segmentação. |
| `make_preview.py` | Gera prévias em SVG mostrando o corte evento a evento. |
| `make_report.py` | Gera o relatório do experimento em Markdown. |

---

## `04_zero_regua/` — referência vertical da régua e do HAND

A espacialização atual de Santa Tereza usa uma referência de campo separada
da cota de atenção da estação: **1,60 m na régua = HAND 0**. Portanto, para
transformar um nível da régua em limiar espacial, o site usa:

`HAND espacial = max(0, nível_regua_m − 1,60)`.

A cota de 15 m mostrada no monitoramento é outro conceito: é uma referência de
nível da estação e **não** o zero do HAND. O antigo ajuste de aproximadamente
4 m obtido com ANADEM pertence ao pipeline legado e não deve voltar a alimentar
Santa Tereza.

Os scripts antigos de calibração permanecem apenas para rastreabilidade
metodológica. O contrato publicado é verificado pelo diagnóstico LiDAR e pela
trava automática `scripts/validate_santa_tereza_lidar_contract.py`.

---

## Programas e bibliotecas

- **Linguagem:** Python 3.11.
- **Bibliotecas:** `numpy`, `scipy` (`scipy.io.loadmat` lê o `.mat` do MATLAB;
  `scipy.ndimage` para o HAND), `rasterio` (ler o MDT GeoTIFF), `Pillow` (PNG),
  `openpyxl` (ler as planilhas auditáveis `.xlsx`).
- **Treino das redes:** MATLAB (fora desta pasta — é a metodologia do grupo).
  Aqui o Python apenas **executa e valida** os `.mat` já treinados.
- **Site:** HTML/CSS/JS + Leaflet, hospedado no **GitHub Pages**; o robô roda
  no **GitHub Actions**.

Instalar: `pip install numpy scipy rasterio Pillow openpyxl`

---

## O que rodou / o que ainda não

- ✅ **Rede validada** contra o `.mat` (RMSE 0) — `validar_forward_pass.py`.
- ✅ **Robô ao vivo** buscando a ANA e prevendo, automático a cada 30 min.
- ✅ **HAND hidráulico LiDAR em Santa Tereza** — LiDAR bruto para terreno/barreiras; FILL/D8 apenas para roteamento.
- ✅ **Contrato espacial protegido no CI** — o deploy é bloqueado se Santa Tereza voltar a usar ANADEM/drone como fonte ativa.
- ✅ **Site se atualiza sozinho** e abre já mostrando a previsão.
- ✅ **Referência espacial atual:** régua 1,60 m = HAND 0; a cota de 15 m permanece separada como referência da estação.
- ⏭️ Próximos: impactos (casas/escolas atingidas), busca por endereço,
  alerta ao passar da cota de inundação (15 m), horizontes de 8 h e 12 h ao vivo.
