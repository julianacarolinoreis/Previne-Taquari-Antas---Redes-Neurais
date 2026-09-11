"""Nested multi-station Muçum corridor helpers (HEC twin v1.7).

Stage A: upstream zone vs Antas Q (86472000)
Stage B: downstream zone vs Muçum Q (86510000)
Polish: 0.4·Antas + 0.6·Muçum research_score

Does not invent STZ rating curves. Rejects 86507000 as confluence control.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


CONTROL_ANTAS = "86472000"
CONTROL_MUCUM = "86510000"
CONTROL_CARREIRO_REJECTED = "86507000"
NESTED_W_ANTAS = 0.40
NESTED_W_MUCUM = 0.60


@dataclass
class ZoneParams:
    initial_loss: float
    constant_loss: float
    tc: float
    storage: float
    recession: float
    initial_flow_ratio: float


@dataclass
class NestedParams:
    up: ZoneParams
    dn: ZoneParams
    k1: float
    k2: float
    k3: float
    x: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return {
            "upstream": asdict(self.up),
            "downstream": asdict(self.dn),
            "k1": self.k1,
            "k2": self.k2,
            "k3": self.k3,
            "x": self.x,
        }


def zone_seeds() -> list[ZoneParams]:
    return [
        ZoneParams(2.5, 2.0, 25.0, 25.0, 0.80, 0.003),
        ZoneParams(2.5, 2.0, 25.0, 45.0, 0.80, 0.0025),
        ZoneParams(5.5, 0.88, 22.5, 34.3, 0.70, 0.001),
        ZoneParams(1.0, 4.0, 4.0, 90.0, 0.98, 0.005),
        ZoneParams(0.0, 2.0, 10.0, 60.0, 0.85, 0.0025),
        ZoneParams(0.0, 0.5, 10.0, 45.0, 0.98, 0.01),
        ZoneParams(0.0, 0.25, 10.0, 15.0, 0.85, 0.0025),
        ZoneParams(0.0, 0.5, 4.0, 25.0, 0.85, 0.001),
        ZoneParams(1.0, 0.5, 15.0, 30.0, 0.85, 0.0025),
        ZoneParams(0.0, 1.0, 8.0, 20.0, 0.9, 0.002),
    ]


def zone_grid(thin_every: int = 13) -> list[ZoneParams]:
    out: list[ZoneParams] = list(zone_seeds())
    i = 0
    for il in (0.0, 1.0, 2.5, 5.5):
        for cl in (0.25, 0.5, 1.0, 2.0, 4.0):
            for tc in (4.0, 10.0, 20.0, 25.0):
                for storage in (15.0, 25.0, 45.0, 60.0, 90.0):
                    for rec in (0.7, 0.85, 0.98):
                        for ratio in (0.001, 0.0025, 0.005):
                            if i % thin_every == 0:
                                out.append(ZoneParams(il, cl, tc, storage, rec, ratio))
                            i += 1
    seen: set[tuple] = set()
    uniq: list[ZoneParams] = []
    for z in out:
        key = tuple(asdict(z).values())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(z)
    return uniq[:320]


def local_zone_neighbors(seed: ZoneParams) -> list[ZoneParams]:
    base = asdict(seed)
    out: list[ZoneParams] = [seed]
    deltas = {
        "initial_loss": (-1.0, -0.5, 0.5, 1.0),
        "constant_loss": (-1.0, -0.5, -0.25, 0.25, 0.5),
        "tc": (-10.0, -5.0, -2.0, 2.0, 5.0, 10.0),
        "storage": (-20.0, -10.0, -5.0, 5.0, 10.0, 20.0),
        "recession": (-0.1, -0.05, 0.05, 0.1),
        "initial_flow_ratio": (-0.002, -0.001, 0.001, 0.002, 0.005),
    }
    for field, ds in deltas.items():
        for d in ds:
            kw = dict(base)
            val = float(base[field]) + d
            if field == "recession":
                val = min(0.995, max(0.55, val))
            elif field in ("tc", "storage"):
                val = max(0.25, val)
            else:
                val = max(0.0, val)
            kw[field] = val
            out.append(ZoneParams(**kw))
    seen: set[tuple] = set()
    uniq: list[ZoneParams] = []
    for z in out:
        key = tuple(asdict(z).values())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(z)
    return uniq


def nested_combined_score(
    score_antas: float | None,
    score_mucum: float,
    *,
    antas_available: bool,
    antas_nse: float | None = None,
) -> float:
    if not antas_available or score_antas is None or score_antas != score_antas:
        return score_mucum
    # If Antas fit is weak, do not let it dominate Muçum (helps E30-like cases).
    w_a = NESTED_W_ANTAS
    w_m = NESTED_W_MUCUM
    if antas_nse is not None and antas_nse == antas_nse and antas_nse < 0.60:
        w_a, w_m = 0.15, 0.85
    return w_a * float(score_antas) + w_m * float(score_mucum)


def attenuation_zone_seeds() -> list[ZoneParams]:
    """Downstream seeds that cut oversimulated peaks (more loss / storage / lag)."""
    out: list[ZoneParams] = []
    for il in (0.0, 2.5, 5.5):
        for cl in (2.0, 3.0, 4.0, 6.0):
            for tc in (25.0, 35.0, 45.0, 55.0):
                for storage in (60.0, 90.0, 120.0):
                    for rec in (0.7, 0.85, 0.98):
                        out.append(ZoneParams(il, cl, tc, storage, rec, 0.001))
    return out


def best_nested_for_event(
    *,
    precip: dict[str, list[float]],
    areas: dict[str, float],
    hours: list[str],
    flow_mucum: dict[str, float],
    flow_antas: dict[str, float],
    core_offset: int,
    core_hours: list[str],
    zones: list[ZoneParams],
    score_junction: Callable[..., tuple[dict[str, float], float, list[float]]],
    run_network: Callable[..., dict[str, list[float]]],
) -> tuple[NestedParams, dict[str, Any], float, dict[str, list[float]]]:
    antas_pairs = sum(1 for h in core_hours if h in flow_antas)
    mucum_pairs = sum(1 for h in core_hours if h in flow_mucum)
    antas_ok = antas_pairs >= 12

    best_up = zones[0]
    best_k1 = 1.0
    best_a_score = float("-inf")
    best_a_metrics: dict[str, float] | None = None
    dummy_dn = zones[0]

    def score_up(up: ZoneParams, k1: float) -> tuple[dict[str, float], float]:
        cand = NestedParams(up=up, dn=dummy_dn, k1=k1, k2=1.0, k3=1.0, x=0.2)
        if antas_ok:
            m, sc, _ = score_junction(
                precip,
                areas,
                cand,
                hours,
                flow_antas,
                core_offset=core_offset,
                core_hours=core_hours,
                junction="at_antas",
            )
        else:
            m, sc, _ = score_junction(
                precip,
                areas,
                cand,
                hours,
                flow_mucum,
                core_offset=core_offset,
                core_hours=core_hours,
                junction="at_mucum",
            )
        return m, sc

    for up in zones:
        for k1 in (0.5, 1.0, 2.0):
            m, sc = score_up(up, k1)
            if sc > best_a_score:
                best_a_score, best_up, best_k1, best_a_metrics = sc, up, k1, m
    assert best_a_metrics is not None
    for up in local_zone_neighbors(best_up):
        for k1 in (max(0.25, best_k1 - 0.5), best_k1, best_k1 + 0.5):
            m, sc = score_up(up, k1)
            if sc > best_a_score:
                best_a_score, best_up, best_k1, best_a_metrics = sc, up, k1, m

    best_dn = zones[0]
    best_k2, best_k3 = 1.0, 1.0
    best_m_score = float("-inf")
    best_m_metrics: dict[str, float] | None = None
    best_sim_mucum: list[float] | None = None

    for dn in zones:
        for k2 in (0.5, 1.0, 2.0):
            for k3 in (0.5, 1.0, 2.0):
                cand = NestedParams(up=best_up, dn=dn, k1=best_k1, k2=k2, k3=k3, x=0.2)
                m, sc, sim = score_junction(
                    precip,
                    areas,
                    cand,
                    hours,
                    flow_mucum,
                    core_offset=core_offset,
                    core_hours=core_hours,
                    junction="at_mucum",
                )
                if sc > best_m_score:
                    best_m_score, best_dn, best_k2, best_k3 = sc, dn, k2, k3
                    best_m_metrics, best_sim_mucum = m, sim
    assert best_m_metrics is not None and best_sim_mucum is not None

    for dn in local_zone_neighbors(best_dn):
        for k2 in (max(0.25, best_k2 - 0.5), best_k2, best_k2 + 0.5):
            for k3 in (max(0.25, best_k3 - 0.5), best_k3, best_k3 + 0.5):
                cand = NestedParams(up=best_up, dn=dn, k1=best_k1, k2=k2, k3=k3, x=0.2)
                m, sc, sim = score_junction(
                    precip,
                    areas,
                    cand,
                    hours,
                    flow_mucum,
                    core_offset=core_offset,
                    core_hours=core_hours,
                    junction="at_mucum",
                )
                if sc > best_m_score:
                    best_m_score, best_dn, best_k2, best_k3 = sc, dn, k2, k3
                    best_m_metrics, best_sim_mucum = m, sim

    best = NestedParams(up=best_up, dn=best_dn, k1=best_k1, k2=best_k2, k3=best_k3, x=0.2)
    best_combo = nested_combined_score(
        best_a_score if antas_ok else None,
        best_m_score,
        antas_available=antas_ok,
        antas_nse=(None if not best_a_metrics else best_a_metrics.get("nse")),
    )
    best_antas_metrics = best_a_metrics
    best_net = run_network(precip, areas, best, include_mucum_increment=True)

    polish: list[NestedParams] = [best]
    up_nb = local_zone_neighbors(best_up)[:20]
    dn_nb = local_zone_neighbors(best_dn)[:20]
    for up in up_nb:
        for dn in dn_nb:
            polish.append(NestedParams(up=up, dn=dn, k1=best_k1, k2=best_k2, k3=best_k3, x=0.2))
    polish = polish[:180]

    for cand in polish:
        m_m, sc_m, sim_m = score_junction(
            precip,
            areas,
            cand,
            hours,
            flow_mucum,
            core_offset=core_offset,
            core_hours=core_hours,
            junction="at_mucum",
        )
        if antas_ok:
            m_a, sc_a, _ = score_junction(
                precip,
                areas,
                cand,
                hours,
                flow_antas,
                core_offset=core_offset,
                core_hours=core_hours,
                junction="at_antas",
            )
        else:
            m_a, sc_a = None, None
        combo = nested_combined_score(
            sc_a,
            sc_m,
            antas_available=antas_ok,
            antas_nse=(None if m_a is None else m_a.get("nse")),
        )
        if combo > best_combo:
            best_combo = combo
            best = cand
            best_m_metrics, best_m_score, best_sim_mucum = m_m, sc_m, sim_m
            if m_a is not None and sc_a is not None:
                best_antas_metrics, best_a_score = m_a, sc_a
            best_net = run_network(precip, areas, best, include_mucum_increment=True)

    # Stage C — Muçum peak polish with soft Antas floor (+ attenuation grid if overpeak)
    antas_nse_now = None if not best_antas_metrics else best_antas_metrics.get("nse")
    floor_antas = None if not antas_ok else (best_a_score - 0.20)
    peak_w = 2.5
    if float(best_m_metrics.get("peak_relative_error") or 0) > 0.05:
        peak_w = 4.0
    peak_pool: list[NestedParams] = [best]
    for dn in local_zone_neighbors(best.dn):
        for k2 in (max(0.25, best.k2 - 0.5), best.k2, best.k2 + 0.5, best.k2 + 1.0):
            for k3 in (max(0.25, best.k3 - 0.5), best.k3, best.k3 + 0.5, best.k3 + 1.0):
                peak_pool.append(
                    NestedParams(up=best.up, dn=dn, k1=best.k1, k2=k2, k3=k3, x=best.x)
                )
    if float(best_m_metrics.get("peak_relative_error") or 0) > 0.05:
        for dn in attenuation_zone_seeds():
            for k2 in (0.25, 0.5, 1.0, 2.0):
                for k3 in (1.0, 2.0, 3.0, 4.0):
                    for up_cl in (1.0, 1.25, 1.5):
                        up = ZoneParams(
                            best.up.initial_loss,
                            min(8.0, max(0.0, best.up.constant_loss * up_cl)),
                            best.up.tc,
                            best.up.storage,
                            best.up.recession,
                            best.up.initial_flow_ratio,
                        )
                        peak_pool.append(
                            NestedParams(up=up, dn=dn, k1=best.k1, k2=k2, k3=k3, x=best.x)
                        )
    # Deduplicate / cap
    seen: set[tuple] = set()
    uniq_pool: list[NestedParams] = []
    for cand in peak_pool:
        key = (
            *asdict(cand.up).values(),
            *asdict(cand.dn).values(),
            cand.k1,
            cand.k2,
            cand.k3,
            cand.x,
        )
        if key in seen:
            continue
        seen.add(key)
        uniq_pool.append(cand)
    peak_pool = uniq_pool[:900]

    best_peak_obj = (
        best_m_metrics["nse"]
        - 0.02 * abs(best_m_metrics.get("peak_lag_hours", 0) or 0)
        - peak_w * float(best_m_metrics.get("peak_relative_error") or 9)
    )
    # Prefer staying in core library (NSE>=0.75) when a feasible peak cut exists.
    def peak_rank(m: dict[str, float]) -> tuple:
        nse = float(m["nse"])
        peak = float(m.get("peak_relative_error") or 9)
        lag = abs(float(m.get("peak_lag_hours") or 0))
        core_ok = 1 if nse >= 0.75 else 0
        # higher is better: core_ok first, then lower peak, then higher nse
        return (core_ok, -peak, nse - 0.02 * lag)

    best_rank = peak_rank(best_m_metrics)
    for cand in peak_pool:
        m_m, sc_m, sim_m = score_junction(
            precip,
            areas,
            cand,
            hours,
            flow_mucum,
            core_offset=core_offset,
            core_hours=core_hours,
            junction="at_mucum",
        )
        # Keep Muçum NSE in library range when possible
        if m_m["nse"] < 0.72:
            continue
        if antas_ok:
            m_a, sc_a, _ = score_junction(
                precip,
                areas,
                cand,
                hours,
                flow_antas,
                core_offset=core_offset,
                core_hours=core_hours,
                junction="at_antas",
            )
            if floor_antas is not None and sc_a < floor_antas:
                continue
        else:
            m_a, sc_a = None, None
        rank = peak_rank(m_m)
        peak_obj = (
            m_m["nse"]
            - 0.02 * abs(m_m.get("peak_lag_hours", 0) or 0)
            - peak_w * float(m_m.get("peak_relative_error") or 9)
        )
        if rank > best_rank or (rank == best_rank and peak_obj > best_peak_obj):
            best_rank = rank
            best_peak_obj = peak_obj
            best = cand
            best_m_metrics, best_m_score, best_sim_mucum = m_m, sc_m, sim_m
            if m_a is not None and sc_a is not None:
                best_antas_metrics, best_a_score = m_a, sc_a
                antas_nse_now = m_a.get("nse")
            best_combo = nested_combined_score(
                sc_a if antas_ok else None,
                sc_m,
                antas_available=antas_ok,
                antas_nse=antas_nse_now,
            )
            best_net = run_network(precip, areas, best, include_mucum_increment=True)

    detail = {
        "mucum": best_m_metrics,
        "antas": best_antas_metrics if antas_ok else None,
        "antas_control_used": antas_ok,
        "antas_observed_points": antas_pairs,
        "mucum_observed_points": mucum_pairs,
        "score_mucum": best_m_score,
        "score_antas": best_a_score if antas_ok else None,
        "score_combined": best_combo,
        "stage": (
            "antas_then_mucum_combined_then_mucum_peak_polish_v1_8"
            if antas_ok
            else "mucum_only_fallback_no_antas_q"
        ),
    }
    return best, detail, best_combo, best_net
