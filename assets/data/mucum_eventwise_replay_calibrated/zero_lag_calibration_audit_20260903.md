# Auditoria de calibração sem atraso · Muçum

## Resultado direto

Foi feita uma busca adicional orientada a eliminar o atraso do pico sem
deslocar timestamps observados, sem preencher falhas de chuva e sem
interpolar vizinhos. O resultado não sustenta declarar `0 h` para todos os
eventos:

| Evento | Melhor candidato com pico em 0 h | Melhor compromisso de série | Conclusão |
| --- | --- | --- | --- |
| E19 | NSE -0,4176 · erro de pico 23,21% · 0 h | NSE 0,2091 · atraso 3 h | 0 h destrói a curva; diagnóstico |
| E26 | NSE 0,3257 · erro de pico 12,41% · 0 h | NSE 0,3784 · atraso 2 h | 0 h não melhora o ajuste global; diagnóstico |
| E28 | NSE 0,8798 · erro de pico 17,91% · 0 h | NSE 0,9739 · atraso 0,5 h | 0 h aumenta o erro do pico; não promover |

Os três eventos fechados anteriormente permanecem assim:

- E24: 0 h, NSE 0,8625, erro de pico 0,003%.
- E27: 0 h, NSE 0,7853, erro de pico 7,066%.
- E28: 1 h no replay publicado de passo horário; a rodada de 15 minutos
  reduziu o melhor compromisso para 0,5 h, mas ainda não para 0 h com erro
  baixo.

## O que foi testado

O HEC-HMS usado foi o 4.13, com a bacia agregada de 16.000 km², resposta no
posto ANA 86510000 e chuva candidata ANA 86472000. Foram executadas buscas
adicionais com:

- 180 combinações completas para E19, E26 e E28 no passo de 1 hora;
- 180 combinações completas para cada evento no passo de 15 minutos;
- busca local de 63 combinações para E26 com Tc fracionário entre 29 e 31
  minutos e armazenamento entre 10 e 20 minutos;
- busca local adicional para E28 em torno do melhor candidato da série, com
  variação de perdas, recessão, Tc e armazenamento;
- comparação das configurações que minimizam atraso, erro de pico e erro da
  série completa.

O atraso foi calculado diretamente como o timestamp do pico simulado menos o
timestamp do pico observado. O passo de 15 minutos foi usado apenas para
reduzir a quantização temporal do modelo; ele não cria observações novas.

## Interpretação hidrológica

No E19, a vazão observada começa a subir enquanto a chuva pontual disponível
no recorte ainda está zerada. No E26, há poucas horas pareadas e a subida
observada não é explicada pela chuva pontual disponível. Nesses dois casos,
forçar o pico para a hora observada troca atraso por erro de forma e volume.

No E28, o modelo consegue coincidir o horário quando usa uma configuração que
subestima ou distorce o pico. A configuração com 0,5 h e NSE 0,9739 é um
avanço temporal, mas continua sendo compromisso de pesquisa, não uma solução
sem atraso.

Portanto, não há evidência para substituir as configurações publicadas por
candidatos de `0 h` com desempenho inferior. O próximo avanço técnico é
chuva espacializada e um modelo distribuído ou semidistribuído derivado do
MDT, além de séries de resposta completas.

## Limite de uso

Esta é uma auditoria de replay histórico. Os números não são previsão em
tempo real e não autorizam alerta, evacuação, despacho, rota ou capacidade de
abrigo. Santa Teresa continua com replay da RNA; a calibração HEC-HMS de vazão
permanece bloqueada até existir vazão/curva-chave reconciliada.

Veja também a [matriz completa de calibração HEC-HMS](matriz_calibracao_hec_hms_mucum_20260903.html), o [visualizador por evento](index.html) e o [README do pacote](README.md).
