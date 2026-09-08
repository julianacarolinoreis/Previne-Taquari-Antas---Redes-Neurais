# Handoff MATLAB — MIMO 2h+4h (Santa Tereza)

Pacote de pesquisa para treinar uma RNA **multi-saída** nativa em MATLAB,
com o **protocolo PREVINE** (mesmo do Direct `.mat`).

**Não é promoção operacional.** HMS continua com Codex.

## 1. Gerar os CSVs (Python, neste repo)

```bash
cd /caminho/do/repo
python3 -c "import sys; sys.path.insert(0,'codigo_python/11_experimento_mimo'); import export_matlab_mimo_package as e; print(e.export_package())"
```

Saída em `assets/data/research_mimo_matlab_handoff/`:

- `mimo_aligned_2h4h_15in.csv` — linhas alinhadas; **deltas = observação** (`Ttot1`)
- splits `treino` / `validacao` / `teste`
- `manifest.json`

## 2. Treinar no MATLAB

```matlab
cd codigo_python/11_experimento_mimo/matlab
train_mimo_2h4h_stz   % nh=40, Cic=40000
% ou:
train_mimo_2h4h_stz('../../../assets/data/research_mimo_matlab_handoff', 52, 42, 100000)
```

Grava `mimo_2h4h_stz_nh*_matlab.mat` com `Wh,bh,Ws,bs,ae,be,au,bu` e métricas.

## 3. Como ler o resultado

| Comparação | Uso |
|------------|-----|
| Direct scratch / PREVINE twin Python (mesmo CSV) | comparação justa |
| Direct `.mat` vs **obs** no alinhado (~0,996 / ~0,92) | **teto justo** neste recorte |
| `mat_reference_metrics_teste` (~0,996 / ~0,993) | teto operacional full-test (4h=26in) |
| Replay pred vs pred NASH≈1 | **só auditoria** — não é teto |

## 4. Protocolo PREVINE

- Ativação: logsig (`unisig`)
- Entrada: `pn=(P-be)/ae` com `be=mean`, `ae=std(ddof=1)` no treino
- Saída: `au/bu` via `liminf/limsup(f=0.05)`; `Δ = yn*au+bu`
- Derivada: `dunisig = max(a*(1-a), 0.01)`
- Otimizador: GD full-batch; `TX` inicia 0,01; ×1,1 se EV melhora; senão restaura e `TX=0,01`
- Alvos: Δ nível **observado** 2h e 4h (ALT)
- Split: coluna `split` do CSV (1/2/3)
- Não publicar no robô ao vivo sem revisão humana
