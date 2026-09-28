#!/usr/bin/env bash
set -euo pipefail

HEC_SH="${1:-${HEC_SH:-}}"
if [ -z "${HEC_SH}" ] || [ ! -f "${HEC_SH}" ]; then
  echo "HEC-HMS executable not found: ${HEC_SH}" >&2
  exit 1
fi
chmod +x "${HEC_SH}"

ROOT="$(pwd)"
RUNTIME="${ROOT}/assets/data/estudo_bacia_taquari_antas/hec_hms_spatial_forecast_mucum"
CANDS="${RUNTIME}/live_candidates"
SCRIPT="${RUNTIME}/project/run_forecast.script"
RESULT="${ROOT}/assets/data/estudo_bacia_taquari_antas/hec_hms_spatial_forecast_mucum_latest.json"

rm -rf "${CANDS}"
mkdir -p "${CANDS}"

for EV in E19 E22 E27 E28; do
  echo "=== HEC-HMS live candidate ${EV} ==="
  HEC_PARAM_EVENT="${EV}" python -B scripts/build_hec_hms_spatial_forecast_mucum.py
  rm -f "${RUNTIME}/hec_output_values.csv"
  "${HEC_SH}" -s "${SCRIPT}" 2>&1 | tee "/tmp/hec-spatial-live-${EV}.log"
  test -s "${RUNTIME}/hec_output_values.csv"
  python -B scripts/postprocess_hec_hms_spatial_forecast_mucum.py

  DEST="${CANDS}/${EV}"
  mkdir -p "${DEST}"
  cp "${RESULT}" "${DEST}/result.json"
  cp "${RUNTIME}/forecast_input.json" "${DEST}/forecast_input.json"
  cp "${RUNTIME}/primary_series.csv" "${DEST}/primary_series.csv"
  cp "${RUNTIME}/hec_output_values.csv" "${DEST}/hec_output_values.csv"
  cp "/tmp/hec-spatial-live-${EV}.log" "${DEST}/hec-hms.log"
done

python -B scripts/select_hec_hms_live_candidate.py
