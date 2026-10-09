# Bug da hora do INMET no forcamento_v3 → forcamento_v3b (bacia 145, HEC-HMS 4.13)

Branch `cursor/hec-bacia145-inmet` (worktree `D:\PREVINE\repo_hec_inmet`, a partir de `cursor/hec-bacia145-modelo`).
Eventos de teste (X20260918 = X75/X76) fechados: a janela não foi lida, refeita nem simulada.

## Em uma frase

O bug existe e é pior do que o relatado (21% da chuva do INMET some e 10% chega 27–72 h atrasada). O v3b foi refeito
com o código original e **reproduz o v3 bit a bit quando o bug é reintroduzido** (33/33 janelas). Corrigir melhora o J de
calibração de todos os 6 conjuntos de parâmetros testados (−0,08 a −0,17) e deixa o J de validação igual (±0,02).
**Recomendo adotar o forcamento_v3b como padrão.**

## 1. O bug (MEDIDO, `quantificar_bug.py` → `bug_inmet.json`)

`chuva_fontes.py` (linha 70) lê `Hora Medicao` com `str(hora)[:2]`, mas o CSV do BDMEP traz um inteiro HHMM em UTC
(0, 100, …, 2300). Por isso 100 vira 10 h, 300 vira 30 h e 800 vira 80 h. Como o dict guarda o último valor de cada
hora, todo dia sai assim (em UTC):

| hora UTC | o que fica na série com bug |
|---|---|
| 00, 10–23 | valor certo (15 h/dia) |
| 01, 03, 04, 05, 07, 09 | lacuna (6 h/dia; no IDW, os vizinhos cobrem) |
| 02 / 06 / 08 | chuva de 45 h / 27 h / 72 h antes (3 h/dia) |
| chuva de 01, 02, 04, 06, 07, 09 | perdida (sobrescrita pela hora certa) |

No registro inteiro (15 estações, 2010–2025):

| | |
|---|---|
| leituras válidas / em 01–09 UTC | 1 326 715 / 493 645 (37%) |
| chuva total | 274 604 mm |
| na hora certa | 187 204 mm (68%) |
| deslocada (+27 h: 5 215 leituras, +45 h: 5 149, +72 h: 5 646) | 28 922 mm (10,5%) |
| perdida | 58 478 mm (21%) |
| total diário com bug / certo, por estação | 0,76–0,80 (corr diária 0,85–0,90) |

A estimativa anterior ("total diário quase igual, corr 0,97–0,99") não se confirma: só as estações B817/B818, com
3 meses de dados, chegam a 0,98.

Nas janelas, 29 de 33 são afetadas, com 15 postos INMET. As 4 janelas de 2026 (S2026_07, X20260629, X20260809,
X20260827) não têm INMET: o arquivo termina em 25/11/2025. Nas afetadas, 25 434 de 85 031 horas×posto INMET (30%)
mudam, e 17 241 de 47 342 mm×posto (36%) estão fora do lugar.

Conferência independente (`teste_defasagem_inmet.py`, o mesmo teste do `teste_defasagem.py` original, INMET contra os
3 ANA mais próximos):

| | corr agrupada lag 0 (dia todo) | corr agrupada lag 0 (só 01–09 UTC) | melhor lag = 0 |
|---|---|---|---|
| com bug | 0,60 | **−0,02** | 64% |
| corrigido | 0,73 | **0,74** | 75% |

Com a hora corrigida, a melhor defasagem continua sendo 0, ou seja, `DESLOC_INMET_H = 0` estava certo; só o parse errava.

## 2. Forçamento corrigido: escolha e prova

- **(b) CEMADEN histórico**: não precisou de API. As leituras brutas mensais estão em `D:\PREVINE\estacoes_cemaden.zip`;
  a PED exige token, conforme o teste do `_analise_aovivo`. `cemaden_bruto.py` (cópia do `_analise_aovivo`) extrai as leituras
  e `cemaden.py` refaz a série horária (UTC → BRT, piso + 1 h, soma). O conjunto, a ordem, os nomes e as coordenadas das
  estações vêm dos `*_postos.json` que o próprio forcamento_v3 gravou.
- **(c) reconstrução completa — escolhida**: `reconstruir_v3.py` importa o código ORIGINAL de
  `D:\PREVINE\hec_calibracao_20261005` (`forcamento_v3.main`: todos os postos, cobertura ≥ 50%, QC iterativo por
  vizinhos, teste de defasagem, IDW p=2 por hora), sem gravar nada lá (`dont_write_bytecode`, saída redirecionada).
  Troca só `chuva_fontes.cemaden` (zip) e, no modo corrigido, `chuva_fontes.inmet` (`inmet.py`, `int(hora)//100`).
  No modo `bug`, o `inmet()` original é usado sem alteração.
- **(a) isolar o peso IDW do INMET**: descartada. Com o bug, as lacunas do INMET mudam o denominador do IDW hora a hora,
  e o QC muda os postos usados em 8 janelas. Uma correção aditiva não seria exata, e (c) dá a prova completa.

**Prova de equivalência (`provar_equivalencia.py` → `equivalencia.json`): 33/33 janelas idênticas.** O modo `bug`
reproduz o `forcamento_v3` commitado com diferença 0,0 em todas as 145 sub-bacias × horas. Também são iguais a média da
bacia, os postos usados, os excluídos no QC, as razões com os vizinhos e as estações por hora, além do registro por posto
(horas válidas, total, usado, excluído, defasagem). O v3 do repositório também é idêntico ao do PC.

X20260918 no v3b é **cópia byte a byte** do v3 (`exportar_v3b.py`). Ela não foi lida nem refeita: o INMET termina em
25/11/2025 e o deslocamento máximo é +81 h. As outras 4 janelas de 2026 saíram idênticas na reconstrução.

## 3. Efeito na chuva (MEDIDO, `efeito_chuva.py` → `efeito_chuva.md`, figura `hietograma_v3_v3b.png`)

Nas 29 janelas afetadas:

| | mediana | faixa |
|---|---|---|
| total médio da bacia v3b / v3 | −0,2% | −3,9% (X20180821) a +3,0% (X20241006) |
| razão do total por sub-bacia | ~1,00 (p10–p90 0,91–1,08) | 0,69–2,69 nos extremos (janelas pequenas) |
| centro de massa do hietograma | **−0,6 h** (v3b mais cedo) | −1,7 h a +0,2 h |
| sub-bacia×hora com \|Δ\| > 0,05 mm | 7,6% | 1,4–13,8% |
| maior \|Δ\| horário numa sub-bacia | – | 1,5–28,5 mm |
| peso IDW médio do INMET | 0,12 | 0,07–0,21 (2018–2022, sem CEMADEN: ~0,20) |

Postos usados ou QC mudam em 8 janelas: por exemplo, INMET_A839, A844, A837 e A883 entram em algumas janelas, porque
eram excluídos por "sub-registro" justamente por causa do bug. No v3, também aparecem picos "fantasma" de madrugada
1–3 dias depois da chuva.

## 4. Efeito no modelo (MEDIDO na nuvem, 33 janelas, papéis E18/E22 = validação como no md-val2)

As rodadas de controle reproduzem a referência exatamente: c002 com J 6,731 / 6,998 e c038 com 6,979 / 7,243.

| modelo | forçamento | J cal | J_pico cal | J val | passa cal / val |
|---|---|---|---|---|---|
| md-val2-c002 | v3 | 6,731 | 5,938 | 6,998 | 5 / 11 |
| md-val2-c002 | **v3b** | **6,623** (−0,108) | 5,827 (−0,111) | 7,011 (+0,013) | 6 / 12 |
| lr-g8-c038 | v3 | 6,979 | 6,404 | 7,243 | 6 / 13 |
| lr-g8-c038 | **v3b** | **6,898** (−0,081) | 6,298 (−0,106) | 7,256 (+0,013) | 8 / 14 |

Por controle (mediana; NSE / vol / pico / lag h). Tabela completa em `tabela_v3_v3b.md`, com o J por evento:

| controle | c002 cal v3 → v3b | c002 val v3 → v3b | c038 val v3 → v3b |
|---|---|---|---|
| Tainhas | 0,64→0,70 / +0,22 / +0,28→+0,32 / −3,5→−4,5 | 0,50→0,42 / +0,22→+0,23 / +0,13→+0,15 / −1 | 0,61→0,52 / … / +0,04→+0,08 / 0 |
| Castro Alves | 0,52→0,53 / −0,10→−0,09 / −0,17 / −2,0→−1,5 | 0,69→0,66 / −0,10 / −0,19 / +1 | 0,63 / −0,15 / −0,22 / +1 |
| Monte Claro | 0,58→0,59 / +0,02→+0,04 / +0,03→+0,04 / −8 | 0,67→0,65 / −0,12→−0,11 / −0,25→−0,24 / −0,5 | 0,62→0,61 / −0,15 / −0,30→−0,29 / +1 |
| LJJ | 0,72 / −0,02→0,00 / −0,09→−0,07 / −1,5 | 0,59 / −0,05 / −0,04→−0,03 / **+1→+2** | 0,50→0,51 / −0,06→−0,05 / −0,07→−0,06 / +2 |
| Muçum | 0,62→0,67 / −0,02→−0,01 / −0,03→−0,01 / −2,5 | 0,68→0,66 / −0,14→−0,15 / −0,05→−0,02 / 0 | 0,54 / −0,18 / −0,07→−0,05 / **+2→+1** |
| Encantado | 0,58→0,56 / −0,09 / −0,12 / −1 | 0,60 / −0,21 / −0,23 / −1 | 0,49 / −0,25→−0,24 / −0,27 / **+1→+2** |

Por evento, o efeito é grande: X09 11,5→8,5, X16 4,7→3,7, X12 3,3→2,6, X04 9,5→10,5, X24 9,7→10,8, E9 6,2→7,0 e
X61 6,9→8,1. As médias se compensam. As medianas de lag mudam 0,5–1 h em 4 controles, sem direção única.

### Re-otimização (critério |ΔJ| > 0,1 e mudança de lag atingido)

`geracoes.py`: in-g0 (LHS de 48 com raio 0,05 em torno do c002) e in-g1..g3 (ES lrdc, 48 por geração, sigma
0,03/0,025/0,02, ordenação por J_pico como na linhagem do c002), só com resultados v3b. Depois, in-val (top 4 por J_pico
de calibração nas 33 janelas) e o controle in-valv3 (os mesmos 4 no v3).

| candidato | J cal v3b | J_pico v3b | J val v3b | J cal v3 | J_pico v3 | J val v3 |
|---|---|---|---|---|---|---|
| md-val2-c002 | 6,623 | 5,827 | 7,011 | 6,731 | 5,938 | 6,998 |
| in-g3-c029 (= in-val-c000, melhor J_pico) | 6,605 | **5,720** | 6,897 | 6,760 | 5,872 | 6,897 |
| in-g3-c020 (in-val-c001) | 6,593 | 5,727 | 6,720 | 6,765 | 5,914 | 6,734 |
| in-g3-c033 (in-val-c002) | 6,645 | 5,734 | 6,823 | 6,787 | 5,889 | 6,843 |
| in-g3-c008 (in-val-c003) | 6,653 | 5,735 | 6,903 | 6,789 | 5,871 | 6,904 |

Leitura: os 4 re-otimizados validam melhor que o c002 (6,72–6,90 contra 7,01), **mas o ganho é igual no v3**. Ou seja,
vem da busca extra, não da chuva corrigida. A chuva corrigida baixa o J de calibração de forma consistente (6 de 6
conjuntos, −0,08 a −0,17) e não mexe na validação. Uma explicação plausível (não testada): a calibração tem muitas
janelas de 2018–2022, em que o INMET pesa ~20%, enquanto parte da validação está em 2026, sem INMET. O c029 escolhido
pelo critério de calibração tem `perc` = 12,0, no limite superior da família. Parâmetros:
`{"qstar":0.0148,"mr":11.83463,"v_alto":0.68142,"v_resto":0.81301,"mn":0.94546,"mk":0.66667,"v_grandes":0.80658,
"ks":0.36333,"dmax":51.1807,"perc":12.0,"imp":0.0385,"k1":30.12912,"k2":812.86729,"fb":0.59033,"p1":0.85914,"s1":0.29074}`.
Diferença em 0,1 no J val está perto do ruído de uma semente; escolher o c020 pelo J val seria usar a validação para
selecionar.

### Medido × estimado
| | estimado antes de rodar | medido |
|---|---|---|
| total diário com bug | "quase igual (corr 0,97–0,99)" (outro agente) | 76–80% do certo, corr 0,85–0,90 |
| total por sub-bacia na janela | pouco muda (o IDW cobre as lacunas) | mediana −0,2%, faixa −3,9 a +3,0% |
| ΔJ | < 0,1 (hietograma médio quase igual) | cal −0,08/−0,11; val +0,01 |
| lag | 0 a −1 h (centro de massa −0,6 h) | medianas mudam ±0,5–1 h, sem direção única |

## 5. Recomendação

1. **Adotar `forcamento_v3b` como padrão.** Ele é o v3 exato menos o bug (provado), o INMET passa a correlacionar na
   madrugada (−0,02 → 0,74) e a calibração melhora em todos os conjuntos testados, sem custo na validação.
2. **Não comparar J entre forçamentos.** A régua muda: c002 = 6,623 / 7,011 no v3b. Ao trocar, rode de novo as
   referências (como in-v3b) e não misture rodadas v3 e v3b no `--resultados` do ES (`rodada_dc.py` não sabe com que
   chuva cada resultado foi feito).
3. Não é preciso recalibrar por causa da chuva: o c002 continua válido. A busca extra (c029, J val 6,90 nos dois
   forçamentos) é um ganho à parte, que a frente de volume pode usar como ponto de partida.
4. Corrigir a mesma linha (fora desta branch; não alterei): `D:\PREVINE\hec_calibracao_20261005\chuva_fontes.py:70`,
   `repo_hec_aovivo\_analise_aovivo\estacoes.py:114` e `repo_hec_aovivo\calibracao_hec_bacia145\aovivo\estacoes.py:114`
   (as versões ao vivo com INMET herdam o bug), além de `hec_calibracao_20261005\revisao_especialistas_2\h8_et0.py:15`
   (ET0 do INMET). A linha correta é `d["hora"] = pd.to_numeric(d.hora, errors="coerce") // 100`.

## 6. Como apontar para o forçamento corrigido (frente de volume a jusante)

1. Trazer o commit `7f1471d7c` para a sua branch (`git cherry-pick 7f1471d7c`). Ele traz
   `calibracao_hec_bacia145/dados/forcamento_v3b/` (34 `.json.gz`, mesmo formato do v3), o fluxo
   `.github/workflows/hec-bacia145-lote.yml`, que aceita a chave `forcamento`, e `rodada_dc.py --forcamento`.
2. Lote na nuvem: no `PEDIDO.json`, acrescente `"forcamento": "forcamento_v3b"`. O fluxo descompacta
   `dados/forcamento_v3b/*.gz` na pasta de trabalho `forcamento_v3`, então nada mais muda. Sem a chave, continua o
   `forcamento_v3`. O log do job mostra `forcamento: forcamento_v3b`.
3. Gerador: `python rodada_dc.py es|top|lhs|viz ... --forcamento forcamento_v3b` grava a chave no pedido. Em `es`/`top`,
   passe em `--resultados` só rodadas feitas no v3b.
4. No PC: descompacte `dados/forcamento_v3b/*.json.gz` em `<pasta de trabalho>\forcamento_v3b\` e use
   `HEC_FORC=forcamento_v3b` (`comum.FORC = AQUI / HEC_FORC`).
5. Referências no v3b, para comparar: c002 J cal 6,623 / J_pico 5,827 / J val 7,011; c038 6,898 / 6,298 / 7,256.

## Rodadas

| rodada | conteúdo | run |
|---|---|---|
| in-v3 | c002 + c038, 33 janelas, v3 (controle) | [37979089542](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37979089542) |
| in-v3b | c002 + c038, 33 janelas, v3b | [37980051525](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37980051525) |
| in-g0 | LHS raio 0,05 em torno do c002, v3b | [37980330860](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37980330860) |
| in-g1..g3 | ES lrdc (J_pico), v3b | [g1](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37981499471) [g2](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37983699526) [g3](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37985774803) |
| in-val | top 4 (J_pico), 33 janelas, v3b | [37988211608](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37988211608) |
| in-valv3 | os mesmos 4 no v3 (controle) | [37989026312](https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/37989026312) |

Resultados em `res/<rodada>/resultado.json`. Os das gerações in-g* (1,7 MB cada) não foram commitados; o `run.txt` tem o link.

## Arquivos

`inmet.py` (leitor com/sem bug), `quantificar_bug.py`, `cemaden_bruto.py` + `cemaden.py` (CEMADEN do zip),
`reconstruir_v3.py` (pipeline original; `python reconstruir_v3.py bug|corrigido`), `provar_equivalencia.py`,
`efeito_chuva.py`, `teste_defasagem_inmet.py`, `figura_hietograma.py`, `exportar_v3b.py`, `gerar_pedido.py`,
`geracoes.py`, `ciclo.py` (push → espera → baixa), `comparar.py` (tabelas). Não commitados (grandes ou regeneráveis):
`cemaden_leituras.pkl`, `forc_bug/`, `forc_corrigido/` e os logs. Para refazer, rode `cemaden_bruto.py`, depois
`reconstruir_v3.py bug` e `reconstruir_v3.py corrigido`.
