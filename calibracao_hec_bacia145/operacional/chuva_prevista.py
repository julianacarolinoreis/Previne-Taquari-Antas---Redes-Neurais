"""Fontes de chuva PREVISTA por sub-bacia, em CENÁRIOS (um HEC por cenário).

Interface (para plugar o ensemble ECMWF e a correção de viés da outra frente):
    fonte.cenarios(t0, inicio, fim, modo) -> [Cenario]
    `inicio` = primeira hora sem chuva observada; `fim` = t0 + horizonte. Cada Cenario traz a chuva horária de
    `inicio` a `fim` (None onde a rodada não cobre), a rodada, a idade e, para ensemble, `grupo`/`membro`/`peso`.
    Pós-processadores de chuva (ex.: correção de viés) são funções Cenario -> Cenario aplicadas em sequência.

Implementações:
  ModeloAberto('ecmwf' | 'gfs') — rodadas abertas por byte-range (só a mensagem de precipitação), igual a
      _analise_bacia145/chuva_prevista/baixar_aws.py: GFS 0,25° (noaa-gfs-bdp-pds, APCP acumulada desde o início,
      diferença hora a hora); ECMWF IFS open data (tp, passos de 3 h divididos por igual nas 3 horas; data.ecmwf.int,
      espelho Google e AWS). Média na área da sub-bacia. Ao vivo: a rodada mais nova que já tem o último passo
      necessário publicado. Retroativo: a regra do estudo (início + atraso ≤ t0; GFS 5 h, ECMWF 7 h, só 00/12z).
  ArquivoPrevista — forcamento_prevista/<mãe>__<modelo>.json.gz (emissões do estudo), para conferência.
  SemChuva — zero depois da chuva observada (limite inferior; referência do estudo).
"""
import gzip
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import geo

H = timedelta(hours=1)
UTC = 3 * H                        # hora local = UTC − 3
ATRASO_RETRO = {"gfs": 5, "ecmwf": 7}
GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{d:%Y%m%d}/{d:%H}/atmos/gfs.t{d:%H}z.pgrb2.0p25.f{s:03d}"
ECM = "{base}{d:%Y%m%d}/{d:%H}z/{res}/{stream}/{d:%Y%m%d%H}0000-{s}h-{stream}-fc"
ECM_BASES_VIVO = ["https://data.ecmwf.int/forecasts/", "https://storage.googleapis.com/ecmwf-open-data/",
                  "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/"]
ECM_BASES_RETRO = ECM_BASES_VIVO[1:]


@dataclass
class Cenario:
    id: str
    modelo: str
    papel: str                       # principal | secundario | referencia | membro
    horas: list                      # datetimes locais
    chuva: dict                      # {sub_id: [mm ou None]}
    fonte: str = ""
    rodada_utc: str | None = None
    idade_h: float | None = None     # idade da rodada em t0
    cobre_ate: str | None = None
    grupo: str | None = None         # ensemble: cenários do mesmo grupo formam um conjunto
    membro: int | None = None
    peso: float = 1.0
    status: str = "ok"
    avisos: list = field(default_factory=list)
    pos_processamento: list = field(default_factory=list)


class FonteChuvaPrevista:
    def cenarios(self, t0, inicio, fim, modo="aovivo") -> list:
        raise NotImplementedError


class SemChuva(FonteChuvaPrevista):
    def cenarios(self, t0, inicio, fim, modo="aovivo"):
        horas = _grade(inicio, fim)
        return [Cenario(id="zero", modelo="zero", papel="referencia", horas=horas,
                        chuva={n: [0.0] * len(horas) for n in geo.nomes()}, fonte="sem chuva depois da observada",
                        cobre_ate=str(fim))]


def _grade(a, b):
    out, t = [], a
    while t <= b:
        out.append(t)
        t += H
    return out


# ------------------------------------------------------------------ rodadas abertas por byte-range
_S = None
_TRAVA_EC = threading.Lock()


def _sessao():
    global _S
    if _S is None:
        import requests
        _S = requests.Session()
        _S.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=32))
    return _S


def _get(url, rng=None, tent=6):
    for k in range(tent):
        try:
            r = _sessao().get(url, headers={"Range": "bytes=%d-%d" % rng} if rng else {}, timeout=90)
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            return r.content
        except Exception:  # noqa: BLE001
            if k == tent - 1:
                raise
            time.sleep(min(60, 3 * 2 ** k))


def _decodificar(msg, fator, cache_pesos):
    import eccodes
    with _TRAVA_EC:   # o eccodes não é thread-safe
        h = eccodes.codes_new_from_message(msg)
        try:
            g = tuple(eccodes.codes_get(h, k) for k in (
                "Ni", "Nj", "latitudeOfFirstGridPointInDegrees", "longitudeOfFirstGridPointInDegrees",
                "iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees", "jScansPositively", "iScansNegatively"))
            v = np.asarray(eccodes.codes_get_values(h), dtype=float) * fator
        finally:
            eccodes.codes_release(h)
    ni, nj, la0, lo0, di, dj, jpos, ineg = g
    assert ineg == 0
    if g not in cache_pesos:
        cache_pesos[g] = geo.pesos_grade(la0, lo0, dj * (1 if jpos else -1), di, ni, nj)[0]
    area = cache_pesos[g]
    return np.array([float(v[k] @ w) for k, w in (area[s] for s in geo.nomes())]), f"{ni}x{nj}"


class ModeloAberto(FonteChuvaPrevista):
    def __init__(self, modelo, cache, papel="principal", paralelo=12, recuo_max=4):
        assert modelo in ("ecmwf", "gfs")
        self.modelo, self.papel, self.paralelo, self.recuo_max = modelo, papel, paralelo, recuo_max
        self.cache = Path(cache) / modelo
        self.ciclo = 6
        self._pesos = {}
        self.log = []

    # -- passos (h desde o início da rodada) que cobrem as horas locais [inicio, fim]
    def _passos(self, run, inicio, fim):
        s0 = int((inicio + UTC - run) / H)
        s1 = int((fim + UTC - run) / H)
        if self.modelo == "gfs":   # horário até 120 h; depois, de 3 em 3 h
            if s1 <= 120:
                return list(range(max(0, s0 - 1), s1 + 1))
            return list(range(max(0, s0 - 1), 121)) + list(range(123, 3 * math.ceil(s1 / 3) + 1, 3))
        lo = 3 * (max(0, s0 - 1) // 3)
        if s1 <= 144:
            return list(range(lo, 3 * math.ceil(s1 / 3) + 1, 3))
        return list(range(lo, 145, 3)) + list(range(150, 6 * math.ceil(s1 / 6) + 1, 6))   # depois de 144 h, de 6 em 6 h

    # -- localização da mensagem
    def _faixa(self, run, s, base_res):
        if s == 0:
            return "zero"
        if self.modelo == "gfs":
            idx = _get(GFS.format(d=run, s=s) + ".idx")
            if idx is None:
                return None
            ls = idx.decode().splitlines()
            alvo = None
            for i, ln in enumerate(ls):
                p = ln.split(":")
                if p[3] == "APCP" and (p[5] == f"0-{s} hour acc fcst" or (s % 24 == 0 and p[5] == f"0-{s // 24} day acc fcst")):
                    alvo = (int(p[1]), int(ls[i + 1].split(":")[1]) - 1)
            return (GFS.format(d=run, s=s), alvo) if alvo else None
        base, res, stream = base_res
        url = ECM.format(base=base, d=run, s=s, res=res, stream=stream)
        idx = _get(url + ".index")
        if idx is None:
            return None
        for ln in idx.decode().splitlines():
            j = json.loads(ln)
            if j.get("param") == "tp":
                return (url + ".grib2", (j["_offset"], j["_offset"] + j["_length"] - 1))
        return None

    def _onde_ecmwf(self, run, s_final, bases):
        """(base, resolução, stream) em que a rodada tem o último passo necessário publicado."""
        streams = ("oper",) if run.hour in (0, 12) else ("oper", "scda")   # 06/18z: "oper" (2026) ou "scda" (antes)
        for base in bases:
            for res in (("0p4-beta", "ifs/0p25") if run < datetime(2024, 2, 1) else ("ifs/0p25",)):
                for stream in streams:
                    url = ECM.format(base=base, d=run, s=s_final, res=res, stream=stream)
                    if _get(url + ".index") is not None:
                        return base, res, stream
        return None

    def _disponivel(self, run, s_final, modo):
        if self.modelo == "gfs" and s_final > 384:
            return None
        if self.modelo == "gfs":
            return "aws" if _get(GFS.format(d=run, s=s_final) + ".idx") is not None else None
        return self._onde_ecmwf(run, s_final, ECM_BASES_VIVO if modo == "aovivo" else ECM_BASES_RETRO)

    def rodadas_candidatas(self, t0, inicio, fim, modo):
        """Da mais nova para a mais velha: (run, passos, onde) com o último passo necessário publicado."""
        t = t0 + UTC
        if modo == "retro":
            t = t - ATRASO_RETRO[self.modelo] * H
            ciclo = 6 if self.modelo == "gfs" else 12          # estudo: ECMWF só 00/12z
        else:
            ciclo = 6
        r0 = t.replace(minute=0, second=0, microsecond=0) - timedelta(hours=t.hour % ciclo)
        for k in range(self.recuo_max + 1):
            run = r0 - k * ciclo * H
            ss = self._passos(run, inicio, fim)
            onde = self._disponivel(run, ss[-1], modo)
            self.log.append(f"{self.modelo} {run:%Y-%m-%d %H}z passo final {ss[-1]}: {'ok' if onde else 'indisponível'}")
            if onde:
                yield run, ss, onde

    def _baixar(self, run, ss, onde):
        arq = self.cache / f"{run:%Y%m%d%H}.npz"
        feitos = {}
        if arq.exists():
            try:
                z = np.load(arq)
                feitos = {int(s): z["area"][i] for i, s in enumerate(z["passos"])}
            except Exception:  # noqa: BLE001 — cache truncado
                feitos = {}
        falta = [s for s in ss if s not in feitos]
        grade_txt = ""
        if falta:
            fator = 1.0 if self.modelo == "gfs" else 1000.0
            with ThreadPoolExecutor(self.paralelo) as ex:
                loc = list(ex.map(lambda s: self._faixa(run, s, onde), falta))
                if any(x is None for x in loc):
                    faltando = [s for s, x in zip(falta, loc) if x is None]
                    raise RuntimeError(f"{self.modelo} {run:%Y%m%d%H}z: passos sem mensagem {faltando[:6]}")

                def um(x):
                    if x == "zero":
                        return np.zeros(len(geo.nomes())), ""
                    return _decodificar(_get(x[0], x[1]), fator, self._pesos)
                out = list(ex.map(um, loc))
            for s, (a, g) in zip(falta, out):
                feitos[s] = a
                grade_txt = grade_txt or g
            arq.parent.mkdir(parents=True, exist_ok=True)
            ps = sorted(feitos)
            np.savez_compressed(arq, passos=np.array(ps), area=np.array([feitos[s] for s in ps]),
                                nomes=np.array(geo.nomes()))
        return feitos, len(falta)

    def cenarios(self, t0, inicio, fim, modo="aovivo"):
        horas = _grade(inicio, fim)
        nomes = geo.nomes()
        papel_id = self.modelo
        t_ini = time.time()
        A = None
        for run, ss, onde in self.rodadas_candidatas(t0, inicio, fim, modo):
            try:
                A, novos = self._baixar(run, ss, onde)    # rodada ainda sendo publicada → recua para a anterior
                break
            except RuntimeError as exc:
                self.log.append(str(exc))
        if A is None:
            return [Cenario(id=papel_id, modelo=self.modelo, papel=self.papel, horas=horas, chuva={},
                            status="indisponivel", avisos=self.log)]
        chuva = np.full((len(horas), len(nomes)), np.nan)
        for i, h in enumerate(horas):
            s = int((h + UTC - run) / H)
            if s < 1:
                continue
            if self.modelo == "gfs":
                p = 1 if s <= 120 else 3
            else:
                p = 3 if s <= 144 else 6
            s3 = p * math.ceil(s / p)
            if s3 in A and s3 - p in A:
                chuva[i] = (A[s3] - A[s3 - p]) / p
        chuva = np.maximum(chuva, 0.0)
        cob = [h for i, h in enumerate(horas) if np.isfinite(chuva[i]).all()]
        fonte = ("NOAA GFS 0,25° (AWS noaa-gfs-bdp-pds), APCP acumulada desde o início, diferença horária"
                 if self.modelo == "gfs" else
                 f"ECMWF IFS open data ({onde[0].split('/')[2]}, {onde[1]}, {onde[2]}), tp de 3 em 3 h dividida por 3")
        c = Cenario(id=papel_id, modelo=self.modelo, papel=self.papel, horas=horas,
                    chuva={n: [None if not np.isfinite(chuva[i, j]) else round(float(chuva[i, j]), 3)
                               for i in range(len(horas))] for j, n in enumerate(nomes)},
                    fonte=fonte, rodada_utc=f"{run:%Y-%m-%d %H}z", idade_h=round((t0 + UTC - run) / H, 2),
                    cobre_ate=str(cob[-1]) if cob else None)
        c.avisos += [x for x in self.log if "sem mensagem" in x or "indisponível" in x]
        c.avisos.append(f"{len(ss)} passos ({ss[0]}–{ss[-1]} h), {novos} baixados agora, {time.time() - t_ini:.0f} s")
        if cob and cob[-1] < fim:
            c.avisos.append(f"rodada só cobre até {cob[-1]}; depois disso a chuva é zero")
        return [c]


class ArquivoPrevista(FonteChuvaPrevista):
    """Emissão arquivada do estudo chuva_prevista (72 h a partir de t0 + 1 h; depois, zero)."""

    def __init__(self, mae, modelo, pasta, papel="principal"):
        self.mae, self.modelo, self.pasta, self.papel = mae, modelo, Path(pasta), papel

    def cenarios(self, t0, inicio, fim, modo="retro"):
        doc = json.loads(gzip.decompress((self.pasta / f"{self.mae}__{self.modelo}.json.gz").read_bytes()))
        e = doc["emissoes"][f"{t0:%Y%m%d%H}"]
        horas = _grade(inicio, fim)
        chuva = {}
        for n, serie in e["chuva"].items():
            v = []
            for h in horas:
                k = round((h - t0) / H) - 1
                v.append(serie[k] if 0 <= k < len(serie) else (0.0 if k >= len(serie) else None))
            chuva[n] = v
        return [Cenario(id=self.modelo, modelo=self.modelo, papel=self.papel, horas=horas, chuva=chuva,
                        fonte="arquivo " + doc.get("fonte", ""), rodada_utc=e["rodada_utc"], idade_h=e["idade_h"],
                        cobre_ate=str(t0 + 72 * H))]


# ------------------------------------------------------------------ pós-processadores de chuva (encaixe da frente 1)
def fator_multiplicativo(fator, rotulo=None):
    """Exemplo de pós-processador: multiplica a chuva prevista (ex.: correção de viés média). Não é usado por padrão."""
    def f(c: Cenario) -> Cenario:
        ch = {n: [None if x is None else x * fator for x in v] for n, v in c.chuva.items()}
        return replace(c, chuva=ch, pos_processamento=c.pos_processamento + [rotulo or f"x{fator:g}"])
    return f


POS_CHUVA = {"fator": lambda arg: fator_multiplicativo(float(arg))}   # ciclo.py --pos-chuva nome:arg[,nome:arg]


def aplicar_pos(cenarios, especificacao):
    """Aplica os pós-processadores pedidos (em ordem) aos cenários com chuva prevista; 'zero' e falhas ficam iguais."""
    fs = [POS_CHUVA[n](arg) for n, _, arg in (s.partition(":") for s in especificacao.split(",") if s)]
    out = []
    for c in cenarios:
        if c.status == "ok" and c.modelo != "zero":
            for f in fs:
                c = f(c)
        out.append(c)
    return out
