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
   [02] MDT ANADEM + HAND  ──►  mancha: até onde a água chega
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

Converte um nível do rio em **área inundada**, usando o **HAND** (Height Above
Nearest Drainage — altura de cada ponto acima do rio).

| Arquivo | O que faz |
|---|---|
| `reprocess_anadem.py` | **Pipeline final.** Lê o MDT **ANADEM** (terreno nu, 30 m), traça o talvegue (leito), calcula o HAND, gera a área por cota e codifica o HAND em PNG para o site. |
| `hand.py` | Versão com *priority-flood* (Barnes 2014) para preencher depressões antes do HAND. |
| `hand2.py`, `hand3.py`, `hand4.py` | Iterações do traçado do talvegue (janela do filtro mínimo, tolerância) até a mancha seguir o rio principal e não “vazar” pelas grotas. |

**Por que ANADEM:** o MDT anterior (Copernicus GLO-30) é um modelo de
*superfície* (inclui copa das árvores) e inflava o terreno em até ~15 m em
encostas. O **ANADEM** é *terreno nu* (bare-earth), o que corrige esse viés —
a estação, por exemplo, passou a ficar corretamente em HAND ≈ 0.

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
- ✅ **HAND com ANADEM** (terreno nu) — mancha segue o rio principal.
- ✅ **Site se atualiza sozinho** e abre já mostrando a previsão.
- ⏳ **Zero da régua:** a mancha ainda usa uma calibração aproximada
  (`bankfull`); falta amarrar o **zero oficial da régua** (ficha SGB/ANA) ao
  MDT, no mesmo datum vertical, para validar em nível de rua.
- ⏭️ Próximos: impactos (casas/escolas atingidas), busca por endereço,
  alerta ao passar da cota de inundação (15 m), horizontes de 8 h e 12 h ao vivo.
