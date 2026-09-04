# Código Python — PREVINE Taquari-Antas

Scripts e robôs usados no site e nos experimentos. **Produção ao vivo ≠ rascunho legado.**

## O que é produção (GitHub Actions / Pages)

| Fluxo | Caminho real | Cadência | Notas |
|-------|--------------|----------|-------|
| Previsão STZ | `previne/robo/gerar_previsao_ao_vivo.py` | a cada **5 min** (`previsao-ao-vivo.yml`) | modelo principal `RNA_2HORAS_R09` (+ horizontes auxiliares no mesmo robô) |
| Previsão Muçum | `codigo_python/01_previsao_ao_vivo/gerar_previsao_ao_vivo_mucum.py` | a cada **5 min** (`previsao-ao-vivo-mucum.yml`) | multi-horizonte 2h/4h/8h via `mucum_modelos_ao_vivo.json` |
| Clima / IFS pesquisa | `codigo_python/05_pesquisa_climatica/` + workflows `*-weather-*` | horário | **não** é alerta operacional |

Saídas publicadas (contratos):

- `previsao_ao_vivo.json` / espelho em `assets/data/` conforme o workflow
- `previsao_ao_vivo_mucum.json`
- `assets/data/research_weather_santa_tereza_latest.json` (schema v3)
- `assets/data/research_weather_mucum_latest.json`

## O que **não** é produção

| Pasta / arquivo | Status |
|-----------------|--------|
| `01_previsao_ao_vivo/gerar_previsao_ao_vivo.py` | **STUB legado STZ** (modelo C0472, cron 30 min no docstring). O Actions **não** chama este arquivo. |
| `11_experimento_mimo/` | Pesquisa MIMO multi-horizonte (branch/PR científicos). |
| Pacotes HEC-HMS / calibragem Muçum | Ownership com Codex; não misturar com RNA ao vivo. |

## Outros módulos úteis

- `02_auditoria_dados/` — inventário ANA / Excel / .mat
- `03_treino_e_avaliacao/` — treino e métricas offline
- `04_pesquisa_espacial/` — DEM, mapas, inventários
- `06_pesquisa_chuva_forte/` — chuva forte / thresholds
- `scripts/` na raiz — testes de contrato, rebuild de catálogo, QA

## Testes rápidos

```bash
python3 -m unittest scripts.test_pesquisa_status_weather_schema
python3 -c "import scripts.test_research_agenda as t; t.test_catalog_entries_are_unique_and_local_links_exist(); t.test_agenda_schema_and_inline_copy(); print('agenda OK')"
python3 scripts/validate_research_dashboard.py
```
