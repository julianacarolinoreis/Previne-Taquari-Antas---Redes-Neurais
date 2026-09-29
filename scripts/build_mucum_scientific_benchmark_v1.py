#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"assets/data/estudo_bacia_taquari_antas"
MODEL=BASE/"modelo_mucum_eventwise_v1_fechado_latest.json"
CASE=BASE/"scientific_benchmark_v1/case_20260928_frozen.json"
OUT=BASE/"scientific_benchmark_v1"
OUT.mkdir(parents=True,exist_ok=True)

def load(p):
    return json.loads(p.read_text(encoding="utf-8"))

def median(vals):
    return statistics.median(vals) if vals else None

def main():
    model=load(MODEL)
    case=load(CASE)
    lib=list(model.get("params_library_eventwise") or [])
    nse=[float(x["nse"]) for x in lib if x.get("nse") is not None]
    lag=[abs(float(x.get("peak_lag_hours") or 0.0)) for x in lib if x.get("peak_lag_hours") is not None]
    perr=[100*abs(float(x.get("peak_relative_error") or 0.0)) for x in lib if x.get("peak_relative_error") is not None]

    upper_bound={
      "label":"eventwise_full_event_calibration",
      "role":"diagnostic_upper_bound_not_forecast_validation",
      "n_events":len(lib),
      "events":[x["event_id"] for x in lib],
      "mean_nse":round(statistics.fmean(nse),4) if nse else None,
      "median_nse":round(median(nse),4) if nse else None,
      "median_abs_peak_lag_h":round(median(lag),3) if lag else None,
      "median_abs_peak_error_pct":round(median(perr),3) if perr else None,
      "leakage_warning":"each eventwise parameterization was fitted with its own full event and cannot be treated as a forecast score"
    }

    common=model.get("common_search_verdict") or {}
    fixed={
      "label":"fixed_common_parameterization",
      "role":"historical_baseline",
      "holdout_e27_nse":common.get("holdout_e27_nse"),
      "loo_mean_test_nse":common.get("loo_mean_test_nse"),
      "external_mean_nse":common.get("external_mean_nse"),
      "promotion_blocked":bool(common.get("promotion_blocked",True)),
      "note":"existing repository evidence shows weak transfer of one common parameter set; these metrics are not yet the same pseudo-operational cutoff experiment as the adaptive arms"
    }

    prospective={
      "label":"adaptive_select_plus_online_recalibration",
      "role":"prospective_real_case",
      "event_id":case["event_id"],
      "issue_local":case["forecast_issue_local"],
      "selected_family":case["selected_historical_family"],
      "forecast_peak_stage_m":case["forecast"]["peak_stage_m"],
      "observed_peak_stage_m":case["verification"]["observed_peak_stage_m"],
      "peak_stage_error_cm":case["verification"]["peak_stage_error_cm"],
      "forecast_peak_time_local":case["forecast"]["peak_time_local"],
      "observed_peak_time_local":case["verification"]["observed_peak_time_local"],
      "peak_time_error_minutes":case["verification"]["peak_time_error_minutes"],
      "lookback_nse":case["lookback_at_issue"]["nse"],
      "lookback_rmse_m":case["lookback_at_issue"]["rmse_m"],
      "no_future_observations_in_calibration":not case["discipline"]["future_observations_used_in_calibration"],
    }

    arms=[
      {
        "arm":"A","name":"fixed_common","status":"baseline_available_but_not_cutoff_matched",
        "selection_data":"none","online_recalibration":False
      },
      {
        "arm":"B","name":"rain_analog_only","status":"protocol_defined_not_yet_replayed",
        "selection_data":"past/forecast rainfall fingerprint only","online_recalibration":False
      },
      {
        "arm":"C","name":"lookback_compatibility","status":"implemented_operationally_for_2026_case_not_yet_historical_crossvalidated",
        "selection_data":"observed level/discharge/trend/hydrograph up to t0","online_recalibration":False
      },
      {
        "arm":"D","name":"lookback_plus_online_recalibration","status":"prospective_case_available_historical_replay_pending",
        "selection_data":"same as C, then local parameter search using observations only up to t0","online_recalibration":True
      }
    ]

    report={
      "schema_version":"mucum_scientific_benchmark_v1",
      "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "research_question":"Does event-conditioned selection plus online recalibration improve flood forecasting at Muçum versus a fixed parameterization without using future observations?",
      "protocol":"docs/metodologia_previsao_adaptativa_mucum.md",
      "evidence_now":{
        "fixed_common":fixed,
        "eventwise_diagnostic_upper_bound":upper_bound,
        "prospective_20260928":prospective,
      },
      "arms":arms,
      "current_conclusion":"promising_but_not_yet_validated",
      "why_not_validated":"historical arms A-D still need matched pseudo-operational replay at frozen t0 values with target event excluded from the candidate library",
      "next_required_experiment":{
        "events_priority":["E24","E27","E28"],
        "cutoffs":["~12h_before_observed_peak","~6h_before_observed_peak","rising_limb_trigger"],
        "strict_rule":"target event excluded; in strict chronology only older events may be candidate families",
        "forcing_scenarios":["P1_real_forecast_available_at_t0","P2_perfect_future_observed_rain"],
        "primary_metrics":["peak_stage_error_cm","peak_time_error_h","RMSE_future","MAE_future","error_2h_4h_8h_12h_24h"]
      }
    }

    (OUT/"benchmark_status_latest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (OUT/"benchmark_arms.csv").open("w",newline="",encoding="utf-8") as fh:
      w=csv.DictWriter(fh,fieldnames=["arm","name","status","selection_data","online_recalibration"])
      w.writeheader(); w.writerows(arms)

    md=[]
    md.append("# Benchmark científico — status v1\n")
    md.append("**Conclusão atual:** promissor, mas ainda não validado.\n")
    md.append(f"- Biblioteca eventwise: {upper_bound['n_events']} eventos; mediana NSE = {upper_bound['median_nse']} (limite diagnóstico, não previsão).")
    md.append(f"- Parametrização comum: leave-one-out médio NSE = {fixed['loo_mean_test_nse']}; hold-out E27 NSE = {fixed['holdout_e27_nse']}.")
    md.append(f"- Caso prospectivo 28/09/2026: erro de pico = +{prospective['peak_stage_error_cm']:.1f} cm; erro de horário = +{prospective['peak_time_error_minutes']} min.")
    md.append("\nO próximo passo obrigatório é o replay pseudo-operacional A–D com t0 congelado e sem vazamento de informação.")
    (OUT/"benchmark_status_latest.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps(report["evidence_now"],ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
