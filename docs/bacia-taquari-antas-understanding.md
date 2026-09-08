# Compreensão estrutural da bacia Taquari–Antas

Documento de leitura humana do pacote em `assets/data/bacia_taquari_antas/`.

## O que a bacia é (neste recorte)

Corredor aninhado BHO6 a montante de Muçum (`86510000`):

1. **Rio das Antas** em Linha José Júlio (`86472000`) — ~12.919 km²
2. **Rio Taquari** em Santa Tereza (`86472600`) — ~15.775 km²
3. **Rio Taquari** em Muçum (`86510000`) — ~15.965 km²

Há **22 afluentes ≥100 km²** entrando no tronco no clip publicado.

## Entrada que o HEC apagava

O incremento Antas→Santa Tereza (~2.857 km²) **não** é um residual genérico. ~**90%** é o **sistema do Rio Carreiro** (código BHO6 `7866`, ~2.564 km²), com componentes nomeados Carreiro, São Domingos, Quatipi etc. O posto `86507000` (PCH Cotiporã / Carreiro) já entra na RNA e ainda não vira sub-bacia HEC.

Entre Santa Tereza e Muçum o incremento é só ~190 km² e **não** há afluente ≥100 km² no clip — o problema estrutural não está aí.

## A montante de Antas

A maior parte das entradas grandes (sistemas com Prata/Ituim/Telha, Tainhas, Bururi, Refugiado…) já está **dentro** do balde `SB_ANTAS`. Colapsar tudo em um Clark único apaga essas entradas.

## Regra antes de recalibrar

Não buscar parâmetros comuns no esqueleto de 3 baldes. Primeiro abrir pelo menos o Carreiro no incremento STZ e, com chuva/posto, os sistemas ≥500 km² a montante de Antas.
