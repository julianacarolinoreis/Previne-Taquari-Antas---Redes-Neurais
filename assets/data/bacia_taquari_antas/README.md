# Compreensão da bacia Taquari–Antas

Artefato de **estrutura hidrológica** gerado antes de qualquer nova calibração HEC-HMS.

## O que este pacote responde

- Quais são os controles aninhados Antas → Santa Tereza → Muçum e suas áreas BHO6
- Quais afluentes ≥100 km² entram no tronco e em que trecho
- Que o incremento Antas→Santa Tereza é dominado pelo sistema do Rio Carreiro
- Quais postos do contrato RNA já observam afluentes que o HEC ainda não discretiza
- Por que o esqueleto HEC de 3 baldes + 2 reaches continua cru

## Arquivos

- `index.html` — leitura visual
- `bacia_understanding_latest.json` — relatório auditável
- `major_tributary_joins.geojson` — confluências

## Reprodução

```bash
python scripts/build_bacia_taquari_antas_understanding.py
```

Não é alerta, previsão operacional nem calibração HEC.
