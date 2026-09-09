# Handoff MATLAB — OPCIONAL (espelho do Python)

> **Prioridade = Python.** O treino canônico está em
> `codigo_python/11_experimento_mimo/` (`fit_previne`, `run_research_round*.py`).
> Este diretório só existe para quem quiser reproduzir o mesmo protocolo no MATLAB.
> Não é gate da pesquisa nem caminho operacional.

## 1. Gerar CSVs (Python)

```bash
cd /caminho/do/repo
python3 -c "import sys; sys.path.insert(0,'codigo_python/11_experimento_mimo'); import export_matlab_mimo_package as e; print(e.export_package())"
```

Saída: `assets/data/research_mimo_matlab_handoff/` (deltas = observação `Ttot1`).

## 2. Treinar no MATLAB (opcional)

```matlab
cd codigo_python/11_experimento_mimo/matlab
train_mimo_2h4h_stz
```

## 3. Protocolo (igual ao Python PREVINE)

- ae/be = mean / std(ddof=1); au/bu = liminf/limsup(f=0.05)
- dunisig piso 0,01; GD full-batch; TX adaptativo
- Alvos observados; sem promoção ao vivo
