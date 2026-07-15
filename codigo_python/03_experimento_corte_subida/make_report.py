import json

rep = json.load(open("clean_out/relatorio_corte.json"))
L = []
L.append("# Experimento — corte da subida (remover o \"show das barragens\")\n")
L.append("**Objetivo:** treinar as redes só na **subida** dos eventos de cheia, sem a oscilação de água baixa "
         "regulada pelas barragens (o \"efeito cobrinha\").\n")
L.append("## Critério de corte\n")
L.append("Aplicado por evento, sobre o nível em Santa Tereza (`NIVEL_ATUAL_CM`, em cm; 5 m = 500 cm):\n")
L.append("1. Acha o **pico** do evento (nível máximo).\n")
L.append("2. Mantém desde o **início da subida** — mesmo abaixo de 5 m — até o pico.\n")
L.append("3. **Corta no primeiro momento em que o nível cai abaixo de 5 m depois do pico.** Todo o final que fica "
         "subindo e descendo dos 5 m é descartado.\n")
L.append("4. Eventos que **nunca passam de 5 m** (ex.: 14, 18) ou que só têm um **espetinho** acima de 5 m "
         "(ex.: 7) saem **inteiros**.\n")
L.append("O corte é o mesmo para todos os conjuntos (treino, validação e teste), como combinado.\n")
L.append("## Como rodar\n")
L.append("Cada arquivo em `datasets/` é o `DADOS` da planilha auditável **já filtrado** (mesmas colunas, só as "
         "linhas mantidas). Colunas de input: `inp01..inpNN`; alvo: `saida_*`; divisão: `CONJUNTO` "
         "(Treino/Validacao/Teste). Retreine cada rede no MATLAB com esse conjunto e compare a PERS/MAE com a atual.\n")
L.append("\n---\n")

for g, models in rep["grupos"].items():
    L.append(f"\n## {g.replace('_',' ')}\n")
    L.append("| Modelo | PERS teste (atual) | linhas antes → depois | treino | validação | teste | eventos fora |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for m in models:
        pc = m["por_conjunto"]
        def cc(c):
            v = pc.get(c); return f"{v['antes']}→{v['depois']}" if v else "—"
        fora = [str(e["evento"]) for e in m["eventos"] if e["descartado_inteiro"]]
        tag = " (jul)" if m["novo"] else ""
        L.append(f"| {m['modelo']}{tag} | {m['PERS_teste']:.3f} | {m['linhas_antes']}→{m['linhas_depois']} | "
                 f"{cc('Treino')} | {cc('Validacao')} | {cc('Teste')} | {', '.join(fora)} |")

open("clean_out/RELATORIO.md", "w").write("\n".join(L))
print("ok, RELATORIO.md gerado")
