# Auditoria da calibração espacializada · Muçum · 03/09/2026

## Resultado

Foi executado um piloto HEC-HMS 4.13 semidistribuído, com duas sub-bacias de Thiessen delimitadas dentro da bacia obtida do MDT regional. Cada zona recebeu sua própria série horária observada; as duas foram roteadas para o posto de resposta 86510000 com um único conjunto comum de parâmetros.

O piloto é reproduzível, mas **não substitui o replay agregado publicado**. O melhor candidato espacial não é automaticamente o mais seguro para interpretação: o atraso, o erro do pico, o NSE e a cobertura temporal precisam fechar juntos.

## MDT e zonas

| elemento | resultado |
|---|---:|
| bacia SRTM + D8 | 15.690,722 km² |
| área declarada ANA | 16.000 km² |
| razão SRTM/ANA | 98,07% |
| zona 86472000 | 8.550,194 km² · 54,49% |
| zona 02851072 | 7.140,529 km² · 45,51% |

Não houve aumento artificial da bacia para forçar 16.000 km². A drenagem foi preparada em EPSG:31982 e os produtos cartográficos publicados em EPSG:4326.

## Busca HEC-HMS semidistribuída

Os números abaixo vêm da busca de 60 candidatos por evento. “Zero-lag” significa que o melhor candidato encontrado dentro da busca teve diferença de pico igual a 0 h; não significa que o timestamp foi deslocado.

| evento | melhor espacial: NSE / atraso / erro pico | melhor zero-lag: NSE / erro pico | decisão |
|---|---:|---:|---|
| E19 | −1,506 / +28 h / 3,89% | nenhum | não reproduz a resposta |
| E22 | 0,550 / 0 h / 52,06% | 0,550 / 52,06% | diagnóstico, pico ruim |
| E24 | bloqueado | bloqueado | lacunas locais de 02851072 dentro do período |
| E26 | bloqueado | bloqueado | não há janela contínua das duas chuvas |
| E27 | 0,857 / +5 h / 6,14% | 0,792 / 0 h / 26,35% | agregado ainda melhor para zero-lag+pico |
| E28 | 0,815 / +1 h / 29,58% | 0,488 / 0 h / 6,75% | agregado ainda melhor em forma e pico |

## Comparação com o replay agregado publicado

| evento | agregado publicado: NSE / atraso / erro pico | conclusão |
|---|---:|---|
| E19 | 0,209 / −3 h / 10,02% | espacial não melhora |
| E22 | 0,652 / 0 h / 33,73% | espacial não melhora o pico |
| E24 | 0,863 / 0 h / 0,003% | manter agregado; espacial bloqueado por lacunas |
| E26 | 0,378 / +2 h / 12,74% | manter diagnóstico; espacial bloqueado |
| E27 | 0,785 / 0 h / 7,07% | manter agregado para decisão temporal/pico |
| E28 | 0,912 / −1 h / 0,54% | manter agregado |

## Pendências objetivas

1. Reconciliar a série horária de 02851072 nos períodos E24 e E26, preservando lacunas explícitas.
2. Delimitar a rede de drenagem e os reaches do modelo HEC-HMS com hidrografia validada; o piloto atual roteia diretamente as duas zonas ao outlet.
3. Recalibrar com mais postos pluviométricos e, quando disponível, integrar o cenário precipitação → vazão do HEC-HMS com a espacialização de nível/HAND.
4. Só então testar um protocolo de validação fora da amostra e comparar com a RNA; nenhum resultado deste pacote autoriza operação de Defesa Civil.
