# Handoff MATLAB — MIMO 2h+4h (Santa Tereza)

Pacote de pesquisa para treinar uma RNA **multi-saída** nativa em MATLAB,
espelhando o experimento Python (`codigo_python/11_experimento_mimo/`).

**Não é promoção operacional.** HMS continua com Codex.

## 1. Gerar os CSVs (Python, neste repo)

```bash
cd /caminho/do/repo
python3 -c "import sys; sys.path.insert(0,'codigo_python/11_experimento_mimo'); import export_matlab_mimo_package as e; print(e.export_package())"
```

Saída em `assets/data/research_mimo_matlab_handoff/`:

- `mimo_aligned_2h4h_15in.csv` — todas as linhas alinhadas
- `mimo_aligned_2h4h_15in_{treino,validacao,teste}.csv`
- `manifest.json`

## 2. Treinar no MATLAB

No MATLAB (Windows/Linux com toolbox básico — o script **não** exige Neural Network Toolbox):

```matlab
cd codigo_python/11_experimento_mimo/matlab
train_mimo_2h4h_stz   % usa nh=40 por padrão
% ou:
train_mimo_2h4h_stz('../../../assets/data/research_mimo_matlab_handoff', 52)
```

O script grava `mimo_2h4h_stz_nh*_matlab.mat` no diretório de dados, com
`Wh,bh,Ws,bs,ae,be,au,bu` e métricas por split.

## 3. Como ler o resultado

| Comparação | Uso |
|------------|-----|
| Direct scratch Python (mesmo CSV) | comparação justa de arquitetura |
| `mat_reference_metrics_teste` (~0,996 / ~0,993) | **teto operacional** dos Direct `.mat` |
| Replay alinhado NASH≈1 | **só auditoria** — não é teto |

Ganho relevante: MIMO MATLAB ≥ Direct scratch no 4h **e** aproximar o teto do `.mat` sem piorar o 2h.

## 4. Protocolo

- Ativação: logsig (unisig PREVINE)
- Alvos: Δ nível 2h e 4h (ALT)
- Split: coluna `split` do CSV (1 treino / 2 validação / 3 teste)
- Early stopping na validação (patience 40)
- Não publicar no robô ao vivo sem revisão humana
