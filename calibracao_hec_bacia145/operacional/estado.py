"""Estado do HEC-HMS entre ciclos (Save State / Start State do HMS 4.13).

Sintaxe (conferida no hms.jar 4.13 e testada; ver LEIAME):
  proj.run   Save State Name: fim / Save State Type: At Specified Time / Save State Date: 3 May 2024 /
             Save State Time: 00:00          → <projeto>/basinStates/fim.state + proj.stateIndex
             Start State Name: ini           → lê basinStates/ini.state; o Control tem de começar no instante dele
  .state     texto: por sub-bacia (dossel, superfície, déficit, resíduos do Clark, saída dos 2 reservatórios lineares)
             e por trecho (vazões por subtrecho do Muskingum-Cunge). Começar de um estado salvo reproduz a rodada
             contínua (diferença 0,000 m³/s nos controles).

Loja: <raiz>/<id dos parâmetros>_<sha8>/<AAAAMMDDHH>/{ini.state, meta.json}. Cada ciclo começa do estado mais recente
com instante <= t0 − dias_antes e grava o estado em t0 + passo − dias_antes (o que o próximo ciclo vai procurar).
Assim a janela de saída continua com os mesmos dias de observado, a chuva desses dias é refeita com o dado mais novo
e a cadeia equivale a uma rodada contínua desde a primeira partida a frio.

Assimilação (opcional): no instante do estado, razão observado/simulado por região de controle (vazão incremental:
controle menos os controles imediatamente a montante; média das 3 últimas horas; razão total se algum controle a
montante não tem dado; controle sem dado herda a razão total do primeiro a jusante com dado), limitada a [0,33; 3].
Sub-bacia: resíduos do Clark e saída dos reservatórios lineares × razão da sua região (menor controle a jusante).
Trecho: vazões dos subtrechos × média das razões das sub-bacias a montante ponderada pela vazão simulada que cada
uma manda (vazão incremental simulada da região por km² × área). O déficit de umidade não muda.
"""
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

H = timedelta(hours=1)
NOME_INI, NOME_FIM = "ini", "fim"
CHAVES_VAZAO = re.compile(r"^(\s+)(Residual Runoff|Residual Outflow|Subreach Outflow|Subreach Inflow|Flow at Node|"
                          r"Outflow|Inflow|Previous Outflow|Previous Inflow|Current Outflow|Current Inflow"
                          r"|Lateral Inflow|Storage Outflow): ([-+0-9.Ee]+)\s*$")
LIM_RAZAO = (1 / 3, 3.0)


def linhas_run(hec, salvar_em=None, iniciar=False):
    s = ""
    if salvar_em is not None:
        s += (f"     Save State Name: {NOME_FIM}\n     Save State Type: At Specified Time\n"
              f"     Save State Date: {hec.data_longa(salvar_em)}\n     Save State Time: {salvar_em:%H:%M}\n")
    else:
        s += "     Save State Type: None\n"
    if iniciar:
        s += f"     Start State Name: {NOME_INI}\n"
    return s


def instalar(d: Path, arquivo_state: Path):
    """Põe um .state salvo como estado inicial 'ini' do projeto em d."""
    bs = d / "basinStates"
    bs.mkdir(parents=True, exist_ok=True)
    txt = Path(arquivo_state).read_text(encoding="utf-8")
    txt = re.sub(r"(?m)^Snapshot: .*$", f"Snapshot: {NOME_INI}", txt, count=1)
    (bs / f"{NOME_INI}.state").write_text(txt, encoding="utf-8")
    m = re.search(r"(?m)^\s*Snapshot Time: (\d+ \w+ \d{4}), (\d\d:\d\d)", txt)
    base = re.search(r"(?m)^\s*Basin Model: (.+)$", txt)[1].strip()
    (bs / "proj.stateIndex").write_text(
        f"Snapshot: {NOME_INI}\n     Snapshot Date: {m[1]}\n     Snapshot Time: {m[2]}\n     Basin Name: {base}\nEnd:\n\n",
        encoding="utf-8")


def configurar(d: Path, hec, salvar_em=None, arquivo_inicial=None):
    run = (d / "proj.run").read_text(encoding="utf-8")
    run = run.replace("     Save State Type: None\n", linhas_run(hec, salvar_em, arquivo_inicial is not None))
    (d / "proj.run").write_text(run, encoding="utf-8")
    if arquivo_inicial is not None:
        instalar(d, arquivo_inicial)


def salvo(d: Path):
    f = d / "basinStates" / f"{NOME_FIM}.state"
    return f if f.exists() else None


def instante(arquivo_state):
    """Instante (hora local) do estado; o HMS escreve meia-noite como 24:00 do dia anterior."""
    with open(arquivo_state, encoding="utf-8") as h:
        cab = h.read(2000)
    m = re.search(r"(?m)^\s*Snapshot Time: (\d+) (\w+) (\d{4}), (\d\d):(\d\d)", cab)
    dia = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%d %B %Y")
    return dia + timedelta(hours=int(m[4]), minutes=int(m[5]))


# ---------------------------------------------------------------- assimilação
def regioes(e3):
    """{elemento: nome do menor controle a jusante} para sub-bacias e trechos (ENCANTADO se nenhum)."""
    ordem = sorted(e3.CTRL_NOS, key=lambda c: e3.AREA_UP[c[1]])
    out = {}
    for n, jus in e3.JUS.items():
        out[n] = next((nome for nome, no in ordem if no in jus), "ENCANTADO")
    return out


def montantes_imediatos(e3):
    nos = dict(e3.CTRL_NOS)
    acima = {c: [o for o in nos if o != c and nos[c] in e3.JUS[nos[o]]] for c in nos}
    return {c: [o for o in acima[c] if not any(o in acima[x] for x in acima[c])] for c in nos}


def razoes(sim_q, obs_q, ts, e3, horas=3):
    """sim_q/obs_q: {controle: {t: q}}. Razão incremental obs/sim por controle em ts (média das últimas `horas`)."""
    def media(s):
        v = [s[ts - k * H] for k in range(horas) if (ts - k * H) in s and s[ts - k * H] is not None]
        return sum(v) / len(v) if v else None
    mi = montantes_imediatos(e3)
    S = {c: media(sim_q.get(c, {})) for c, _ in e3.CTRL_NOS}
    O = {c: media(obs_q.get(c, {})) for c, _ in e3.CTRL_NOS}
    out = {}
    for c, _ in e3.CTRL_NOS:
        if S[c] is None or O[c] is None or S[c] <= 0:
            out[c] = dict(razao=1.0, tipo="sem dado", sim=S[c], obs=O[c])
            continue
        up = mi[c]
        r, tipo = O[c] / S[c], "total"
        if up and all(S[u] is not None and O[u] is not None for u in up):
            si = S[c] - sum(S[u] for u in up)
            oi = O[c] - sum(O[u] for u in up)
            if si > 0.1 * S[c] and oi > 0:
                r, tipo = oi / si, "incremental"
        out[c] = dict(razao=round(min(max(r, LIM_RAZAO[0]), LIM_RAZAO[1]), 4), bruta=round(r, 4), tipo=tipo,
                      sim=round(S[c], 1), obs=round(O[c], 1), montante=up)
    # controle sem dado herda a razão TOTAL do primeiro controle a jusante com dado (a razão total dele já inclui a
    # vazão que vem daqui)
    nos = dict(e3.CTRL_NOS)
    ordem = sorted(nos, key=lambda c: e3.AREA_UP[nos[c]])
    for c in ordem:
        if out[c]["tipo"] != "sem dado":
            continue
        for d in ordem:
            if d != c and nos[d] in e3.JUS[nos[c]] and out[d]["tipo"] != "sem dado":
                if out[d]["tipo"] == "total":
                    out[c].update(razao=out[d]["razao"], tipo=f"herdada de {d}")
                break
    return out


def escalar(txt, fator_de):
    """Multiplica as vazões do estado (texto .state) pelo fator da região de cada elemento."""
    out, f = [], 1.0
    for ln in txt.splitlines(keepends=True):
        m = re.match(r"^(Subbasin|Reach|Junction|Sink|Source|Reservoir): (.+?)\s*$", ln)
        if m:
            f = fator_de.get(m[2], 1.0)
        elif ln.startswith("End:"):
            f = 1.0
        elif f != 1.0:
            k = CHAVES_VAZAO.match(ln)
            if k:
                ln = f"{k[1]}{k[2]}: {float(k[3]) * f!r}\n"
        out.append(ln)
    return "".join(out)


def fatores(rz, e3):
    """Sub-bacia: razão da sua região. Trecho (e nó): média das razões das sub-bacias a montante ponderada pela vazão
    simulada que cada uma manda (vazão incremental simulada da região por km² × área; por área se faltar) — a calha
    carrega a vazão de montante, não só a da região incremental onde está."""
    reg = regioes(e3)
    f_sub = {s: rz[reg[s]]["razao"] for s in e3.AREA}
    area_reg = {}
    for s, a in e3.AREA.items():
        area_reg[reg[s]] = area_reg.get(reg[s], 0.0) + a
    mi = montantes_imediatos(e3)
    dens = {}
    for c in area_reg:
        s_c = rz.get(c, {}).get("sim")
        ups = [rz.get(u, {}).get("sim") for u in mi.get(c, [])]
        if s_c is not None and all(u is not None for u in ups) and area_reg[c] > 0:
            dens[c] = max(s_c - sum(ups), 0.0) / area_reg[c]
    ref = sorted(dens.values())[len(dens) // 2] if dens else 1.0
    peso = {s: a * (dens.get(reg[s], ref) or 1e-9) for s, a in e3.AREA.items()}
    acum = {}
    for s in e3.AREA:
        for n in e3.JUS[s][1:]:
            p = acum.setdefault(n, [0.0, 0.0])
            p[0] += peso[s] * f_sub[s]
            p[1] += peso[s]
    out = {n: p[0] / p[1] for n, p in acum.items() if p[1] > 0}
    out.update(f_sub)
    return out


def assimilar(arquivo_state, destino, sim_q, obs_q, ts, e3):
    rz = razoes(sim_q, obs_q, ts, e3)
    fator = fatores(rz, e3)
    txt = Path(arquivo_state).read_text(encoding="utf-8")
    Path(destino).write_text(escalar(txt, fator), encoding="utf-8")
    return rz


# ---------------------------------------------------------------- loja
class Loja:
    def __init__(self, raiz, parametros):
        self.dir = Path(raiz) / f"{parametros['id']}_{(parametros.get('sha256_p') or 'x')[:8]}"

    def guardar(self, arquivo_state, meta):
        ts = instante(arquivo_state)
        d = self.dir / f"{ts:%Y%m%d%H}"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arquivo_state, d / "ini.state")
        (d / "meta.json").write_text(json.dumps(dict(meta, instante=str(ts)), ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        return ts, d

    def buscar(self, ate, desde):
        """Estado mais recente com desde <= instante <= ate: (instante, arquivo, meta) ou None."""
        if not self.dir.exists():
            return None
        cand = []
        for d in self.dir.iterdir():
            try:
                ts = datetime.strptime(d.name, "%Y%m%d%H")
            except ValueError:
                continue
            if desde <= ts <= ate and (d / "ini.state").exists():
                cand.append((ts, d))
        if not cand:
            return None
        ts, d = max(cand)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
        return ts, d / "ini.state", meta

    def podar(self, antes_de):
        n = 0
        if self.dir.exists():
            for d in self.dir.iterdir():
                try:
                    if datetime.strptime(d.name, "%Y%m%d%H") < antes_de:
                        shutil.rmtree(d)
                        n += 1
                except ValueError:
                    continue
        return n
