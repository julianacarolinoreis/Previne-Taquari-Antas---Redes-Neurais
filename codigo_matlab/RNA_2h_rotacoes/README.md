# RNA 2h — Santa Tereza — banco de rotações (MATLAB)

Monta **vários candidatos** da rede neural de 2 h (Santa Tereza) fazendo
**rotação entre os eventos** — igual às redes que já temos (`rot_001`, `rot_002`…) —
e gera, para cada rotação, os **mesmos artefatos** de sempre:

- `saida/<nome>.mat` — no formato dos `RNAPREV__*` do PREVINE (mesmos campos,
  mesmo forward já usado no site);
- `saida/<nome>_AUDITAVEL_INPUTS_RNA.xlsx` — planilha auditável de 6 abas,
  idêntica às de `assets/audit_workbooks/`;
- `saida/ranking_rotacoes.xlsx` — compara todas as rotações (para escolher a melhor).

> **Você monta aqui, o MATLAB roda.** Este pacote só prepara os dados, as
> rotações e a receita de treino. Quem treina é o MATLAB, na sua máquina.

---

## Como rodar

1. Coloque a planilha **`modelo_2h_novo.xlsx`** nesta pasta (mesma que gerou o
   `.mat` entregue — abas `DADOS_FORM` e `VAR`).
2. No MATLAB, com esta pasta como *Current Folder*:

   ```matlab
   rodar_rotacoes
   ```

3. Os resultados aparecem em `saida/`. O `ranking_rotacoes.xlsx` já vem ordenado
   pelo coeficiente de persistência (PERS) do conjunto de **verificação (teste)**.

Requisitos: MATLAB R2019a ou mais novo (usa `readtable`, `writecell`, `save -v7.3`).
Não precisa de nenhum toolbox — o treino, as métricas e o percentil são próprios.

---

## O que é uma "rotação"

Uma rotação é só a atribuição dos **eventos inteiros** aos três conjuntos —
exatamente o que a coluna `SERIE` da aba `VAR` já codifica:

| SERIE | conjunto |
|:---:|---|
| 1 | Treino |
| 2 | Validação |
| 3 | Verificação (teste) |

Girar os eventos entre validação/teste = novas rotações. Tudo se edita em
**`config_rotacoes.m`**, na tabela `cfg.rotacoes`:

```matlab
%   nome                 eventos_validacao      eventos_verificacao(teste)
'rot_00_original',  [1 5 10 15 17 21],     [12]     % reproduz o modelo entregue
'rot_04_teste_e20', [1 5 10 15 17],        [20]     % cheia de jul/2026 como teste
...
```

`rot_00_original` reproduz o *split* do modelo entregue — serve de **controle**:
se ele bater com o `.mat` entregue, a receita está fiel.

---

## Receita (lida de dentro do próprio `.mat` entregue)

Tudo abaixo foi recuperado dos *function handles* e hiperparâmetros gravados no
`RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat`:

- arquitetura **15 → 31 → 1**, ativação `logsig` nas duas camadas;
- derivada com piso `max(a·(1-a), 0.01)`;
- normalização de entrada: *z-score* com média/desvio do **treino**;
- normalização de saída: `(alvo − li)/(ls − li)`, com `li = min − f·amp`,
  `ls = max + f·amp`, `f = 0.05`;
- otimização: gradiente descendente em lote, taxa adaptativa, `Mom = 0`;
- `nit = 10` reinícios aleatórios — fica o melhor pela **validação**;
- `Cic = 30000` ciclos, parada antecipada por paciência.

O modelo é **ALT**: prevê a *variação* de nível em 2 h. O nível previsto é
`nível_atual + variação`. A base de comparação (persistência) é "variação zero".

---

## Já tem o seu treinador MATLAB original?

Se você tem a rotina de treino original, **troque só o corpo de `rna_treina.m`**
pela sua chamada, devolvendo os mesmos campos (`W1, b1, W2, b2`). Todo o resto
(leitura, split das rotações, `.mat`, auditável, ranking) continua igual.

O treinador reconstruído aqui foi validado contra o modelo entregue: no *split*
original ele reproduz **teste MAE ≈ 5,0 cm / NASH ≈ 0,93** (entregue: 4,55 / 0,948) —
mesma ordem de grandeza. Plugando o seu treinador original, os números batem exatos.

---

## Arquivos

| arquivo | papel |
|---|---|
| `config_rotacoes.m` | **edite aqui**: origem, hiperparâmetros e as rotações |
| `rodar_rotacoes.m` | driver: lê os dados, treina cada rotação, grava tudo |
| `rna_treina.m` | treinador fiel (ponto de troca pelo seu, se tiver) |
| `rna_forward.m` | passagem direta (reproduz o forward do site, RMSE 3,6·10⁻¹⁴) |
| `salva_mat.m` | grava o `.mat` no formato PREVINE |
| `escreve_auditavel.m` | grava o Excel auditável de 6 abas |
| `pctl.m` | percentil sem depender de toolbox |
