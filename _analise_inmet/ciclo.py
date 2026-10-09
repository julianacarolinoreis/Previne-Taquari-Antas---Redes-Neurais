"""Push do PEDIDO.json na branch cursor/hec-bacia145-inmet -> espera o run -> baixa resultado-<rodada> em res/<rodada>/.

  python ciclo.py enviar <rodada> "<mensagem>"     (commit só do PEDIDO.json + push + espera + baixa)
  python ciclo.py esperar <rodada>                 (espera o run do HEAD e baixa)
  python ciclo.py es <rodada> <sigma> <semente> [--resultados pastas...]   (ES lrdc no forcamento_v3b a partir de res/)
O fluxo cancela o run anterior da mesma branch a cada push: um lote por vez.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WT = AQUI.parent
BR = "cursor/hec-bacia145-inmet"
RES = AQUI / "res"
URL = "https://github.com/previne-taquari-antas/Previne-Taquari-Antas---Redes-Neurais/actions/runs/"


def sh(cmd, cwd=WT, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def esperar(sha):
    t0 = time.time()
    while True:
        try:
            runs = json.loads(sh(["gh", "run", "list", "--branch", BR, "--limit", "10", "--json", "databaseId,headSha,status,conclusion"]))
        except RuntimeError as e:
            print("gh falhou, tento de novo:", str(e)[:200], flush=True)
            runs = []
        r = next((x for x in runs if x["headSha"] == sha), None)
        if r and r["status"] == "completed":
            return r["databaseId"], r["conclusion"]
        if time.time() - t0 > 3 * 3600:
            sys.exit("timeout")
        time.sleep(60)


def baixar(rid, rodada):
    dest = RES / rodada
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / "resultado.json").exists():
        sh(["gh", "run", "download", str(rid), "-n", f"resultado-{rodada}", "-D", str(dest)])
    (dest / "run.txt").write_text(URL + f"{rid}\n", encoding="utf-8")
    R = json.loads((dest / "resultado.json").read_text(encoding="utf-8"))
    ok = sorted((c for c in R if c["J"] is not None and c["J"] < 1e9), key=lambda c: c["J"])
    print(f"{time.strftime('%H:%M')} {rodada}: {len(ok)}/{len(R)} ok", flush=True)
    for c in ok[:5]:
        print(f"   {c['id']} J={c['J']:.3f} J_pico={c.get('J_pico', float('nan')):.3f}", flush=True)


def enviar(rodada, msg):
    sh(["git", "add", "calibracao_hec_bacia145/rodadas/PEDIDO.json"])
    sh(["git", "commit", "-q", "-m", msg])
    sh(["git", "push", "-q", "origin", f"HEAD:{BR}"])
    sha = sh(["git", "rev-parse", "HEAD"])
    print(f"{time.strftime('%H:%M')} {rodada} enviado {sha[:9]}", flush=True)
    rid, concl = esperar(sha)
    print(f"{time.strftime('%H:%M')} {rodada} run {URL}{rid}: {concl}", flush=True)
    if concl != "success":
        sys.exit(1)
    baixar(rid, rodada)


def main():
    modo, rodada = sys.argv[1:3]
    if modo == "enviar":
        enviar(rodada, sys.argv[3])
    elif modo == "esperar":
        rid, concl = esperar(sh(["git", "rev-parse", "HEAD"]))
        print(rodada, URL + str(rid), concl, flush=True)
        if concl == "success":
            baixar(rid, rodada)
    elif modo == "es":
        sigma, semente, *resto = sys.argv[3:]
        res = resto[resto.index("--resultados") + 1:] if "--resultados" in resto else [str(RES)]
        cod = WT / "calibracao_hec_bacia145" / "codigo"
        print(sh([sys.executable, "-B", "rodada_dc.py", "es", "--familia", "lrdc", "--rodada", rodada, "--lam", "48", "--mu", "8",
                  "--sigma", sigma, "--semente", semente, "--objetivo", "J_pico", "--forcamento", "forcamento_v3b",
                  "--saida", str(WT / "calibracao_hec_bacia145" / "rodadas" / "PEDIDO.json"), "--resultados", *res], cod))
        enviar(rodada, f"rodada {rodada}: ES lrdc no forcamento_v3b (J_pico, sigma {sigma}, semente {semente})")


if __name__ == "__main__":
    main()
