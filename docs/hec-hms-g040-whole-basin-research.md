# Pesquisa HEC-HMS G040 — modelo de bacia inteira

**Estado de pesquisa:** 30/09/2026  
**Escopo:** Bacia Hidrográfica Taquari–Antas (G040), aproximadamente 26.430 km².  
**Uso:** pesquisa e validação; não é sistema oficial de alerta.

## 1. Objetivo

Generalizar o avanço obtido no HEC-HMS de Muçum para toda a G040 sem perder rastreabilidade física. O alvo final continua sendo a discretização original documentada em julho de 2026:

- 145 sub-bacias HEC-HMS;
- 72 trechos de rio;
- exutório na confluência Taquari–Jacuí;
- Muçum e Estrela como controles históricos já documentados.

Os 32 polígonos de enquadramento/gestão do IEDE são usados somente para auditoria, agrupamento e apoio ao forçamento. Eles **não** são sub-bacias computacionais HEC.

## 2. Arquitetura intermediária por ramos observados

Antes de reconstruir integralmente as 145 geometrias, a pesquisa usa uma arquitetura intermediária que estende o princípio validado em Muçum:

1. condição observada no eixo Antas–Taquari;
2. condições observadas independentes em grandes tributários quando houver vazão fresca;
3. chuva–vazão explícita apenas nas áreas não representadas por essas fronteiras;
4. roteamento pela topologia oficial BHO;
5. validação em múltiplos postos ao longo do eixo principal.

### Controles principais

**Fronteira do eixo superior**
- 86472000 — Linha José Júlio.

**Tributários independentes preferenciais**
- 86500000 — Passo Carreiro;
- 86595000 — Barra do Zeferino / Guaporé;
- 86746000 — Rio Forqueta / Travesseiro.

**Prata**
- 86447000 — Balsa do Prata é controle de estado a montante.
- Não é somado a Linha José Júlio, pois sua contribuição já está contida na vazão observada de Linha José Júlio.

**Controles do eixo Taquari**
- 86510000 — Muçum;
- 86720000 — Encantado;
- 86743000 — Arroio do Meio;
- 86879000 — Lajeado;
- 86879300 — Estrela;
- 86895000 — Porto Mariante;
- 86950000 — Taquari;
- 86996000 — Triunfo.

## 3. Topologia BHO6

A topologia foi reconstruída com a camada oficial ANA/SNIRH BHO6, usando:

- direção: `noorigem -> nodestino`;
- encaixe dos postos por área de drenagem + distância espacial;
- verificação explícita do caminho entre todos os controles.

A cadeia principal fechou:

`86472000 -> 86510000 -> 86720000 -> 86743000 -> 86879000 -> 86879300 -> 86895000 -> 86950000 -> 86996000`

Os três tributários preferenciais também conectaram corretamente ao eixo principal:

- Carreiro: conectado;
- Guaporé: conectado;
- Forqueta: conectado.

Todos os gates topológicos passaram.

## 4. Balanço de áreas incrementais

O balanço usa a área acumulada BHO6 nos controles e remove apenas as áreas já representadas por vazões observadas independentes.

### Fechamento global

- área em Linha José Júlio: **12.918,656 km²**;
- áreas dos ramos observados preferenciais: **6.475,075 km²**;
- área residual chuva–vazão: **6.981,323 km²**;
- área BHO6 no controle próximo a Triunfo: **26.375,054 km²**;
- erro de fechamento: **0,000 km²**.

### Áreas residuais por intervalo no cenário com todas as fronteiras preferenciais

| Intervalo | Área residual (km²) | Fronteira independente que entra |
|---|---:|---|
| Linha José Júlio → Muçum | 1.230,192 | Carreiro |
| Muçum → Encantado | 652,970 | Guaporé |
| Encantado → Arroio do Meio | 515,674 | — |
| Arroio do Meio → Lajeado | 749,492 | Forqueta |
| Lajeado → Estrela | 579,543 | — |
| Estrela → Porto Mariante | 1.410,921 | — |
| Porto Mariante → Taquari | 1.217,731 | — |
| Taquari → Triunfo | 624,799 | — |

## 5. Política para fronteiras ausentes

Uma vazão de tributário nunca é preenchida com zero, estimativa visual ou dado sintético apresentado como observado.

Quando uma fronteira preferencial não tem `Vazao` fresca:

1. a Source observada é desativada para aquela rodada;
2. a área drenada por essa fronteira é devolvida à área chuva–vazão do intervalo correspondente;
3. a geometria/forçamento da rodada deve refletir essa mudança de balanço;
4. o motivo fica registrado no manifesto da rodada.

Isso permite três cenários auditáveis:

- **preferred_all_boundaries** — todas as fronteiras preferenciais;
- **live_available_boundaries** — apenas as que têm vazão fresca;
- **ljj_only** — sensibilidade com apenas Linha José Júlio como fronteira observada.

## 6. Estado hidrométrico da rodada de 30/09/2026

Na coleta das 19:56 UTC:

- 13 controles consultados;
- 8 retornaram dados;
- 8 tinham estado fresco;
- das 4 fronteiras de balanço incluindo Linha José Júlio, 2 tinham vazão fresca.

Valores úteis:

- Linha José Júlio: **2.828 m³/s**;
- Passo Carreiro: **413,89 m³/s**;
- Muçum: **3.817,24 m³/s**;
- Encantado: **4.741,99 m³/s**;
- Estrela: **8.214,57 m³/s**;
- Porto Mariante: **7.805,34 m³/s**;
- Taquari: nível disponível, mas sem `Vazao` na resposta usada.

Guaporé preferencial (86595000) e Forqueta preferencial (86746000) não retornaram série nessa rodada. Portanto, não podem ser usados como fronteiras observadas dessa simulação sem um fallback validado.

## 7. Chuva

### Observada

- resolução temporal: horária;
- semântica: precipitação acumulada no intervalo;
- todas as estações válidas podem participar da espacialização;
- faltante permanece faltante;
- milímetros de estações diferentes não são somados como se fossem uma única lâmina física da bacia.

### Prevista

- ECMWF/IFS espacial;
- ciclo e lead time preservados;
- transição observado → previsão explícita.

O contrato G040 já registra uma grade de 600 células (30 × 20, 0,1°) para o forçamento espacial de pesquisa.

## 8. Geometria residual

A pesquisa está cruzando a topologia BHO6 de 2022 com a camada poligonal oficial ANA **BHO 2017 50K — Área de Drenagem**.

A regra é conservadora:

- correspondência apenas por código Otto `COBACIA`;
- nenhuma substituição espacial por proximidade se o código não casar;
- cobertura e área são auditadas por intervalo;
- essa geometria é candidata para o modelo intermediário e não substitui silenciosamente as 145 sub-bacias ANADEM do modelo final.

## 9. Roteamento

Os tempos observados entre postos serão usados como restrição empírica, mas **não** serão igualados automaticamente a Muskingum `K`.

A calibração por reach deverá considerar:

- hidrograma completo;
- tempo de subida;
- recessão;
- volume;
- magnitude do pico;
- horário do pico;
- múltiplos eventos;
- validação independente.

## 10. Matriz de experimentos

A sequência de pesquisa permanece controlada:

- **E0:** reprodução do HEC original — SCS-CN + SCS UH + Muskingum-Cunge;
- **E1:** mesma física + estado/fronteiras observadas;
- **E2:** Soil Moisture Accounting + Clark;
- **E3:** SMA + ModClark com chuva espacial;
- **E4:** 2D Diffusion Wave somente em domínios onde houver justificativa;
- **E5:** acoplamento HEC-HMS → HEC-RAS 1D/2D.

Uma alteração de física por vez, para que o ganho de desempenho seja atribuível.

## 11. Critérios mínimos de validação

- NSE;
- KGE;
- PBIAS;
- RMSE;
- MAE;
- erro de volume;
- erro de pico;
- erro de horário do pico;
- habilidade na subida;
- habilidade na recessão.

Nenhuma configuração é promovida por um único evento ou um único posto.

## 12. Regra de estado

O estado nativo do HEC precisa reproduzir adequadamente as observações.

Uma curva deslocada graficamente para coincidir com o nível observado pode existir como diagnóstico, mas **não** transforma a rodada em assimilação e não permite promoção/publicação do HEC como validado.

## 13. Próximos gates

1. fechar o cruzamento poligonal das áreas residuais;
2. gerar forçamento observado/ECMWF por área residual;
3. definir automaticamente as fronteiras observadas disponíveis em cada rodada;
4. construir o primeiro projeto HEC-HMS G040 por ramos;
5. calibrar tempos de propagação e armazenamento por trecho;
6. replay multi-evento;
7. validação independente;
8. reconstrução/recuperação das 145 geometrias ANADEM;
9. transferência do aprendizado do modelo por ramos para o HEC completo de 145 sub-bacias.
