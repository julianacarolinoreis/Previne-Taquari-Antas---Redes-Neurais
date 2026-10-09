# HEC-HMS ao vivo no site (PESQUISA — não é alerta oficial)

Painel `hec_previsao_aovivo.html`: nível observado e previsto em Muçum (e Encantado e Linha José Júlio,
quando vierem no JSON) por cenário de chuva — ECMWF principal, GFS segundo, "sem chuva" como piso —,
cotas de referência, idade das rodadas, cobertura da chuva observada e avisos de validade
(acima de 15 m em Muçum o nível é só indicativo). A seção de Santa Tereza fica **desligada** (ver abaixo).

## Arquivos desta pasta

| arquivo | quem escreve | para quê |
|---|---|---|
| `config.json` | à mão | URLs, limites de frescor (8 h desatualizada, 24 h sem previsão) e a chave `mancha_santa_tereza` |
| `latest.json` | robô (`hec-aovivo-site.yml`) | última rodada válida; **não versionado ainda** — o painel mostra "sem previsão recente" até existir |
| `indice.json` | robô | resumo das últimas 120 emissões (pico por cenário em Muçum/Encantado) |
| `exemplo_aovivo_2026100913.json` | cópia do artefato real (run 37959276471) | revisão local e testes |
| `curva_mucum_santa_tereza.json` | `codigo_python/01_previsao_ao_vivo/hec_curva_santa_tereza.py` | curva empírica Muçum → régua 86472600 e sua validação |

Contrato: o JSON de `calibracao_hec_bacia145/operacional/ciclo.py` (`produto = previne-hec-bacia145-aovivo`,
`versao_esquema = 1`). O publicador (`codigo_python/01_previsao_ao_vivo/publicar_hec_aovivo.py`) recusa
rodada que não seja `modo = aovivo`, sem `aviso`, com séries de tamanho diferente de `horas` ou sem nível
previsto em Muçum, e ignora rodada que não seja mais nova que a publicada. Esquema mais novo é aceito
com aviso; o painel mostra o que entende e avisa o leitor.

## Como o JSON chega ao site

O workflow do HEC (`.github/workflows/hec-bacia145-aovivo.yml`, branch `cursor/hec-bacia145-sistema`) roda
com `contents: read` e só sobe o artefato `hec-aovivo-<run_id>`. O site **puxa** esse artefato:

```
HEC (cron 40 1,7,13,19 UTC, main) ──artefato──▶ hec-aovivo-site.yml (workflow_run) ──▶ publicar_hec_aovivo.py ──▶ commit em main
```

Por que puxar em vez de o HEC escrever no site: o HEC continua só-leitura (não ganha permissão de
escrita na main), o site decide o que publica (validação + "mais novo que o atual") e uma rodada
quebrada nunca substitui a última boa.

## O que precisa ser ligado (nada disso foi feito)

1. **Workflow do HEC na branch padrão (`main`)** — `schedule` e `workflow_run` só valem para arquivos
   na branch padrão. Sem isso o HEC só roda em push na branch do sistema e nada é publicado.
2. **Este workflow (`hec-aovivo-site.yml`) e o painel na `main`.**
3. **Variável de repositório `HEC_SITE_PUBLICAR=true`** (Settings → Secrets and variables → Actions →
   Variables). Enquanto não existir, o job é pulado.
4. **Permissão de escrita do `GITHUB_TOKEN`** (Settings → Actions → General → Workflow permissions →
   "Read and write"), como já usam os robôs de previsão. Se a `main` tiver proteção que bloqueie push de
   robô, liberar o `github-actions[bot]` ou trocar o push por PR.
5. Opcional: link para o painel no `index.html` / página de Muçum (abaixo).

Teste antes de ligar o automático: `Actions → HEC ao vivo - publicar no site → Run workflow` (com
`HEC_SITE_PUBLICAR=true`), deixando `run_id` vazio para pegar a última rodada com sucesso na `main`.

### Segredos

- **Mesmo repositório:** nenhum. O `GITHUB_TOKEN` (com `actions: read`) baixa o artefato.
- **HEC em outro repositório:** `workflow_run` não cruza repositórios. Defina a variável `HEC_REPO`
  (`dono/repo`), o segredo `HEC_ARTIFACT_TOKEN` (PAT *fine-grained* só com **Actions: read** no repo do
  HEC) e descomente o `schedule` do workflow.

## Ver localmente

```
cd <raiz do repo>
python -m http.server 18473 --bind 127.0.0.1
```

`http://127.0.0.1:18473/hec_previsao_aovivo.html?fonte=assets/data/hec_aovivo/exemplo_aovivo_2026100913.json`

Parâmetros que só funcionam em `localhost`/`127.0.0.1` (em produção são ignorados):

- `fonte=<caminho>` — lê outro JSON;
- `agora=2026-10-10T01:30` — simula o relógio (testa "desatualizada" e "sem previsão recente");
- `st=1` — liga a prévia de Santa Tereza mesmo com `mancha_santa_tereza=false`.

## Santa Tereza: por que a ligação está desligada

A mancha de Santa Tereza é escolhida pela régua 86472600 (contorno HAND = régua − 4,0 m,
`santa_tereza_inundacao/contornos_extravasamento.json`), mas o HEC prevê Muçum (86510000). Foi testada uma
curva empírica Muçum → Santa Tereza (telemetria ANA, médias horárias, 1 675 pares, defasagem −2 h),
validada deixando uma cheia de fora:

| cheia fora | erro médio | viés | p95 |
|---|---|---|---|
| nov/2023 | 19 cm | −7 cm | 52 cm |
| mai/2024 | 53 cm | −25 cm | 262 cm |
| jun/2024 | 31 cm | −12 cm | 82 cm |
| set–out/2026 | 26 cm | +22 cm | 83 cm |

Geral: 31 cm de erro médio, p95 98 cm. Só com Linha José Júlio o erro médio sobe para 49 cm. Motivos para
não ligar:

- erro de até 2,6 m na maior cheia (mai/2024), justamente onde o mapa importa;
- o viés troca de sinal entre 2023–24 e 2026 (possível mudança de régua/datum);
- o relógio de Muçum estava ~105 min adiantado em 2023–24, o que mistura a defasagem;
- o zero da régua 86472600 e o MDT (HAND 0 = 400 cm) ainda não foram compatibilizados;
- o erro soma-se ao da própria previsão HEC em Muçum.

O que destrava: um ponto `SANTA_TEREZA` no executor HEC com curva própria (o painel já usa
`pontos.SANTA_TEREZA.nivel_previsto_cm` se existir, sem a conversão), a compatibilização régua × MDT e a
validação da mancha numa cheia observada. Aí basta `mancha_santa_tereza: true` no `config.json`.

## Link sugerido (não aplicado)

`index.html` e `mucum_previsao_inundacao.html` têm mudanças locais não commitadas, então o link não foi
inserido. Sugestão, perto do card de previsão de Muçum:

```html
<a href="hec_previsao_aovivo.html">Previsão HEC-HMS ao vivo (pesquisa) →</a>
```
