# Santa Tereza — replay por evento da RNA de nível (2 h)

Este pacote deixa a pesquisa de Santa Tereza consultável por evento. Ele usa o modelo auditável `001_alt_STZ_2H_R01_T12_V1-5-10-15-17-21` e preserva os timestamps da série de origem.

## Como ver

Abra no navegador:

`santa_tereza_event_replay.html`

Escolha o evento no seletor ou clique em uma linha da tabela. A tela mostra:

- nível observado e nível previsto pela RNA;
- pico observado e pico previsto;
- erro absoluto do pico;
- atraso do pico calculado pelos timestamps;
- MAE, período, conjunto e número de amostras.

Os arquivos `events_metrics.csv` e `series_hourly.csv` são a versão tabular para auditoria, planilha ou integração posterior. `model_snapshot.json` preserva o recorte integral do modelo usado.

## Eventos para o estudo de caso

| Evento | Período | Pico observado | Pico RNA | Atraso do pico | Papel |
|---|---|---:|---:|---:|---|
| E4 | setembro/2023 | 2365,0 cm | 2367,5 cm | 0 h | replay de treino |
| E6 | novembro/2023 | 2161,0 cm | 2151,1 cm | 0 h | replay de treino |
| E9 | maio/2024 | 2158,0 cm | 2163,6 cm | 0 h | replay de treino |
| E12 | junho/julho/2025 | 1332,0 cm | 1330,0 cm | 0 h | teste independente |

Os três primeiros são bons para reconstruir o que a rede teria indicado durante as cheias históricas, mas não podem ser apresentados como validação independente porque pertencem ao treino desse modelo. O E12 é o destaque para a avaliação fora do treino.

## Limite atual do HEC-HMS

Santa Tereza está fechada aqui como **replay de nível da RNA**, não como calibração HEC-HMS de vazão. A estação 86472600 é a estação oficial de Santa Tereza no Rio Taquari, mas o pacote de auditoria ainda não contém uma série horária de vazão reconciliada nem uma curva-chave anexada. Por isso não há conversão inventada de centímetros para m³/s.

O próximo avanço técnico é anexar vazão/curva-chave por evento e então calibrar o HEC-HMS contra a vazão; o MDT/HAND entra depois na transformação espacial do nível em mancha, com cobertura e incerteza documentadas.

## Natureza do resultado

`PESQUISA · REPLAY HISTÓRICO · NÃO OPERACIONAL`

Este pacote não emite alerta, ordem de evacuação, rota, despacho de equipes ou afirmação de capacidade de abrigo.
