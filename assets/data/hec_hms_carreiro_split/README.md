# HEC-HMS · split do Carreiro

Proposta estrutural: separar `SB_CARREIRO_7866` do antigo `SB_INC_STZ`.

- `index.html` — diagrama
- `carreiro_split_structure_latest.json` — schema auditável
- `Taquari_Antas_CarreiroSplit.basin.txt` — lista de elementos (não é projeto binário HMS)

**Não calibrado.** Não gera NSE. Não é alerta.

```bash
python scripts/build_hec_hms_carreiro_split_structure.py
```
