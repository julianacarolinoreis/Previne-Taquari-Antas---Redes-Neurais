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

## Regras

- Uma física por vez; escolhas só com eventos de **calibração**; a validação só relata; o teste é aberto uma vez.
- Vazão de Muçum só abaixo de 15 m e de LJJ abaixo de 18 m (curva-chave); acima disso vale só o horário do pico pelo nível.
