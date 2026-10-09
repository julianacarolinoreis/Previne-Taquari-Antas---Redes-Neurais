"""Publica no site a última rodada do HEC-HMS ao vivo (bacia 145) — PESQUISA, não é alerta oficial.

Entrada: o JSON produzido por calibracao_hec_bacia145/operacional/ciclo.py --modo aovivo, ou a pasta do
artefato `hec-aovivo-<run_id>` (usa hec_aovivo_latest.json; senão o hec_aovivo_aovivo_*.json mais novo).

Saída (em --destino, padrão assets/data/hec_aovivo):
  latest.json  cópia compacta da rodada, lida por hec_previsao_aovivo.html;
  indice.json  resumo das últimas emissões (pico por cenário em Muçum e Encantado).

Só publica se a rodada for válida e mais nova que a publicada. Saída 0 = publicou ou "sem mudança";
saída 2 = rodada inválida (nada é escrito).

  python codigo_python/01_previsao_ao_vivo/publicar_hec_aovivo.py <arquivo-ou-pasta> [--destino DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DESTINO_PADRAO = RAIZ / "assets" / "data" / "hec_aovivo"
PRODUTO = "previne-hec-bacia145-aovivo"
ESQUEMA_CONHECIDO = 1
MAX_INDICE = 120
BRT = timezone(timedelta(hours=-3))


class RodadaInvalida(Exception):
    pass


def escolher_arquivo(entrada: Path) -> Path:
    if entrada.is_file():
        return entrada
    if not entrada.is_dir():
        raise RodadaInvalida(f"entrada não existe: {entrada}")
    latest = entrada / "hec_aovivo_latest.json"
    if latest.is_file():
        return latest
    candidatos = sorted(entrada.rglob("hec_aovivo_aovivo_*.json"))
    candidatos = [c for c in candidatos if not c.name.endswith(".conferencia.json")]
    if not candidatos:
        raise RodadaInvalida(f"nenhum hec_aovivo_aovivo_*.json em {entrada}")
    return candidatos[-1]


def quando(txt) -> datetime:
    """ISO com ou sem fuso; sem fuso = hora local de Brasília (como `t0` e `horas`)."""
    if not isinstance(txt, str) or not txt:
        raise RodadaInvalida(f"data ausente: {txt!r}")
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RodadaInvalida(f"data inválida: {txt!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=BRT)


def validar(d: dict) -> list[str]:
    """Levanta RodadaInvalida se o site não puder mostrar a rodada; devolve avisos não bloqueantes."""
    avisos: list[str] = []
    if not isinstance(d, dict):
        raise RodadaInvalida("raiz não é objeto")
    if d.get("produto") != PRODUTO:
        raise RodadaInvalida(f"produto inesperado: {d.get('produto')!r}")
    if d.get("modo") != "aovivo":
        raise RodadaInvalida(f"modo {d.get('modo')!r}: só rodadas ao vivo vão para o site")
    esquema = d.get("versao_esquema")
    if not isinstance(esquema, int) or esquema < 1:
        raise RodadaInvalida(f"versao_esquema inválida: {esquema!r}")
    if esquema > ESQUEMA_CONHECIDO:
        avisos.append(f"esquema v{esquema} mais novo que o conhecido (v{ESQUEMA_CONHECIDO}); o painel mostra o que entende")
    if not d.get("aviso"):
        raise RodadaInvalida("falta o campo `aviso` (texto de pesquisa)")
    emitido = quando(d.get("emitido_em"))
    quando(d.get("t0"))
    if emitido > datetime.now(timezone.utc) + timedelta(hours=1):
        raise RodadaInvalida(f"emitido_em no futuro: {d['emitido_em']}")

    horas = d.get("horas")
    if not isinstance(horas, list) or len(horas) < 24:
        raise RodadaInvalida("`horas` ausente ou curta demais")
    n = len(horas)
    pontos = d.get("pontos")
    if not isinstance(pontos, dict) or "MUCUM" not in pontos:
        raise RodadaInvalida("`pontos.MUCUM` ausente")
    for chave, p in pontos.items():
        for nome, serie in (p.get("observado") or {}).items():
            if isinstance(serie, list) and len(serie) != n:
                raise RodadaInvalida(f"{chave}.observado.{nome}: {len(serie)} valores, esperado {n}")
        for campo in ("simulado", "corrigido", "nivel_previsto_cm"):
            for cen, serie in (p.get(campo) or {}).items():
                if not isinstance(serie, list) or len(serie) != n:
                    raise RodadaInvalida(f"{chave}.{campo}.{cen}: tamanho diferente de `horas` ({n})")

    niveis = pontos["MUCUM"].get("nivel_previsto_cm") or {}
    if not any(any(v is not None for v in s) for s in niveis.values()):
        raise RodadaInvalida("Muçum sem nenhum nível previsto")
    cenarios = d.get("cenarios") or []
    falhos = [c.get("id") for c in cenarios if str(c.get("status", "ok")).lower() not in ("ok", "")]
    if falhos:
        avisos.append("cenários com falha: " + ", ".join(map(str, falhos)))
    return avisos


def ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"aviso: não consegui ler {caminho} ({exc}); tratando como ausente")
        return None


def pico_do_ponto(d: dict, chave: str) -> dict:
    p = d["pontos"].get(chave) or {}
    horas = d["horas"]
    t0 = quando(d["t0"])
    k0 = next((i for i, h in enumerate(horas) if quando(h) >= t0), 0)
    cotas = (p.get("cotas_previstas") or {}) if chave == "MUCUM" else {}
    saida = {}
    for cen, serie in (p.get("nivel_previsto_cm") or {}).items():
        trecho = [(v, i) for i, v in enumerate(serie) if i >= k0 and v is not None]
        if not trecho:
            continue
        v, i = max(trecho, key=lambda par: par[0])
        item = {"pico_nivel_cm": round(v, 1), "t_pico": horas[i]}
        info = cotas.get(cen) or {}
        cruzadas = [nome for nome, c in (info.get("cotas") or {}).items() if c.get("cruza")]
        if cruzadas:
            item["cotas_cruzadas"] = cruzadas
        if info.get("pico_acima_validade"):
            item["pico_acima_validade"] = True
        saida[cen] = item
    return saida


def resumo(d: dict) -> dict:
    return {
        "emitido_em": d["emitido_em"],
        "t0": d["t0"],
        "versao_esquema": d["versao_esquema"],
        "parametros": (d.get("parametros") or {}).get("id"),
        "cenarios": {c.get("id"): {"status": c.get("status"), "rodada_utc": c.get("rodada_utc")}
                     for c in d.get("cenarios") or [] if c.get("papel") != "membro"},
        "picos": {chave: pico_do_ponto(d, chave) for chave in ("MUCUM", "ENCANTADO") if chave in d["pontos"]},
    }


def publicar(entrada: Path, destino: Path, origem: str | None = None) -> int:
    arquivo = escolher_arquivo(entrada)
    d = ler_json(arquivo)
    if d is None:
        raise RodadaInvalida(f"não consegui ler {arquivo}")
    for aviso in validar(d):
        print("aviso:", aviso)

    destino.mkdir(parents=True, exist_ok=True)
    atual = ler_json(destino / "latest.json")
    if isinstance(atual, dict) and atual.get("emitido_em"):
        try:
            emit_atual = quando(atual["emitido_em"])
        except RodadaInvalida:
            emit_atual = None
        if emit_atual is not None and quando(d["emitido_em"]) <= emit_atual:
            print(f"sem mudança: rodada {d['emitido_em']} não é mais nova que a publicada ({atual['emitido_em']})")
            return 0

    d = dict(d)
    d["publicacao_site"] = {
        "publicado_em": datetime.now(BRT).isoformat(timespec="seconds"),
        "arquivo_origem": arquivo.name,
        **({"origem": origem} if origem else {}),
    }
    tmp = destino / "latest.json.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(destino / "latest.json")

    indice = ler_json(destino / "indice.json")
    emissoes = indice.get("emissoes", []) if isinstance(indice, dict) else []
    emissoes = [e for e in emissoes if e.get("emitido_em") != d["emitido_em"]]
    emissoes.append(resumo(d))
    emissoes.sort(key=lambda e: quando(e["emitido_em"]))
    novo_indice = {
        "produto": PRODUTO + "-indice",
        "aviso": "PESQUISA — não é alerta oficial. Resumo das últimas rodadas do HEC-HMS ao vivo publicadas no site.",
        "atualizado_em": d["publicacao_site"]["publicado_em"],
        "emissoes": emissoes[-MAX_INDICE:],
    }
    (destino / "indice.json").write_text(json.dumps(novo_indice, ensure_ascii=False, indent=1), encoding="utf-8")

    muc = novo_indice["emissoes"][-1]["picos"].get("MUCUM", {})
    picos = ", ".join(f"{c} {v['pico_nivel_cm'] / 100:.2f} m" for c, v in muc.items())
    print(f"publicado: {arquivo.name} emitido {d['emitido_em']} · Muçum pico {picos}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path, help="JSON da rodada ou pasta do artefato")
    ap.add_argument("--destino", type=Path, default=DESTINO_PADRAO)
    ap.add_argument("--origem", help="texto livre gravado em publicacao_site.origem (ex.: run id)")
    a = ap.parse_args(argv)
    try:
        return publicar(a.entrada, a.destino, a.origem)
    except RodadaInvalida as exc:
        print(f"rodada inválida, nada publicado: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
