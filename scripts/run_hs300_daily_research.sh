#!/usr/bin/env bash
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-ashare-research-lab}"

DB="${DB:-data/processed/hs300_daily.duckdb}"
SOURCE="${SOURCE:-akshare-hs300-daily}"
INDEX_CODE="${INDEX_CODE:-000300.SH}"
UNIVERSE="${UNIVERSE:-hs300}"
CACHE_DIR="${CACHE_DIR:-data/raw/cache}"
REPORT_ROOT="${REPORT_ROOT:-data/reports/generated/hs300-daily}"
TOP_N="${TOP_N:-300}"
CACHE_MODE="${CACHE_MODE:-use}"
SCORING_CONFIG="${SCORING_CONFIG:-configs/scoring_hs300_daily_exploratory.yaml}"

ASOF="${ASOF:-}"
STOCK_CODE="${STOCK_CODE:-002594.SZ}"
INGEST_FROM="${INGEST_FROM:-}"
UNIVERSE_AS_OF="${UNIVERSE_AS_OF:-}"
FACTOR_FROM="${FACTOR_FROM:-}"
VALIDATION_FROM="${VALIDATION_FROM:-}"
VALIDATION_TO="${VALIDATION_TO:-}"
MAX_SYMBOLS="${MAX_SYMBOLS:-}"

DRY_RUN=0
SKIP_INGEST=0

usage() {
  cat <<'EOF'
Usage:
  scripts/run_hs300_daily_research.sh --as-of YYYY-MM-DD [options]

Required:
  --as-of DATE              Explicit research as-of date. There is no today default.

Options:
  --stock-code CODE         Stock report target. Default: 002594.SZ
  --ingest-from DATE        AkShare ingest start date. Default: previous year-01-01.
  --universe-as-of DATE     Universe snapshot effective date. Default: ingest-from.
  --factor-from DATE        Factor calculation start date. Default: previous month-01.
  --validation-from DATE    Factor validation start date. Default: factor-from.
  --validation-to DATE      Factor validation end date. Default: as-of.
  --cache-mode MODE         AkShare cache mode: use, refresh, or offline. Default: use.
  --scoring-config PATH     Scoring config. Default: configs/scoring_hs300_daily_exploratory.yaml.
  --max-symbols N           Limit ingest to the first N symbols for smoke testing.
  --skip-ingest             Reuse existing DB rows and run downstream steps only.
  --dry-run                 Print resolved variables and commands without executing them.
  -h, --help                Show this help.

Environment overrides:
  CONDA_ENV DB SOURCE INDEX_CODE UNIVERSE CACHE_DIR REPORT_ROOT TOP_N CACHE_MODE
  SCORING_CONFIG
  ASOF STOCK_CODE INGEST_FROM UNIVERSE_AS_OF FACTOR_FROM VALIDATION_FROM
  VALIDATION_TO MAX_SYMBOLS
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --as-of)
      ASOF="${2:-}"
      shift 2
      ;;
    --stock-code)
      STOCK_CODE="${2:-}"
      shift 2
      ;;
    --ingest-from)
      INGEST_FROM="${2:-}"
      shift 2
      ;;
    --universe-as-of)
      UNIVERSE_AS_OF="${2:-}"
      shift 2
      ;;
    --factor-from)
      FACTOR_FROM="${2:-}"
      shift 2
      ;;
    --validation-from)
      VALIDATION_FROM="${2:-}"
      shift 2
      ;;
    --validation-to)
      VALIDATION_TO="${2:-}"
      shift 2
      ;;
    --cache-mode)
      CACHE_MODE="${2:-}"
      shift 2
      ;;
    --scoring-config)
      SCORING_CONFIG="${2:-}"
      shift 2
      ;;
    --max-symbols)
      MAX_SYMBOLS="${2:-}"
      shift 2
      ;;
    --skip-ingest)
      SKIP_INGEST=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ASOF" ]]; then
  echo "ASOF is required. Pass --as-of YYYY-MM-DD; there is no today default." >&2
  exit 2
fi

if [[ ! "$ASOF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "ASOF must use ISO format YYYY-MM-DD: $ASOF" >&2
  exit 2
fi

ASOF_YEAR="${ASOF:0:4}"
ASOF_MONTH="${ASOF:5:2}"
PREVIOUS_YEAR=$((10#$ASOF_YEAR - 1))
PREVIOUS_MONTH=$((10#$ASOF_MONTH - 1))
FACTOR_YEAR=$((10#$ASOF_YEAR))
if [[ "$PREVIOUS_MONTH" -eq 0 ]]; then
  PREVIOUS_MONTH=12
  FACTOR_YEAR=$((FACTOR_YEAR - 1))
fi

INGEST_FROM="${INGEST_FROM:-$(printf "%04d-01-01" "$PREVIOUS_YEAR")}"
UNIVERSE_AS_OF="${UNIVERSE_AS_OF:-$INGEST_FROM}"
FACTOR_FROM="${FACTOR_FROM:-$(printf "%04d-%02d-01" "$FACTOR_YEAR" "$PREVIOUS_MONTH")}"
VALIDATION_FROM="${VALIDATION_FROM:-$FACTOR_FROM}"
VALIDATION_TO="${VALIDATION_TO:-$ASOF}"

ASOF_NODASH="${ASOF//-/}"
STOCK_CODE_SLUG="${STOCK_CODE//./-}"
FACTOR_RUN="hs300-factor-${ASOF_NODASH}"
VALIDATION_RUN="hs300-factor-validation-${ASOF_NODASH}"
SCAN_RUN="hs300-scan-${ASOF_NODASH}"
SCORE_RUN="hs300-score-${ASOF_NODASH}"
STOCK_REPORT_RUN="hs300-stock-${STOCK_CODE_SLUG}-${ASOF_NODASH}"

RUN_ROOT="${REPORT_ROOT}/${ASOF_NODASH}"
QUALITY_DIR="${RUN_ROOT}/data-quality"
VALIDATION_DIR="${RUN_ROOT}/factor-validation"
SCAN_DIR="${RUN_ROOT}/scan"
SCORE_DIR="${RUN_ROOT}/score"
STOCK_REPORT_DIR="${RUN_ROOT}/stock-${STOCK_CODE_SLUG}"

run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

echo "Daily HS300 personal research workflow"
echo "candidate list is not a trading instruction"
echo "composite score is not a trading instruction"
echo "factor validation forward return is a statistical label"
echo "stock report is for research review only"
echo
echo "Resolved names:"
echo "DB=${DB}"
echo "SOURCE=${SOURCE}"
echo "ASOF=${ASOF}"
echo "FACTOR_RUN=${FACTOR_RUN}"
echo "VALIDATION_RUN=${VALIDATION_RUN}"
echo "SCAN_RUN=${SCAN_RUN}"
echo "SCORE_RUN=${SCORE_RUN}"
echo "STOCK_CODE=${STOCK_CODE}"
echo "SCORING_CONFIG=${SCORING_CONFIG}"
echo
echo "Resolved windows:"
echo "INGEST_FROM=${INGEST_FROM}"
echo "UNIVERSE_AS_OF=${UNIVERSE_AS_OF}"
echo "FACTOR_FROM=${FACTOR_FROM}"
echo "VALIDATION_FROM=${VALIDATION_FROM}"
echo "VALIDATION_TO=${VALIDATION_TO}"
echo
echo "Output paths:"
echo "QUALITY_DIR=${QUALITY_DIR}"
echo "VALIDATION_DIR=${VALIDATION_DIR}"
echo "SCAN_DIR=${SCAN_DIR}"
echo "SCORE_DIR=${SCORE_DIR}"
echo "STOCK_REPORT_DIR=${STOCK_REPORT_DIR}"
echo
echo "Universe note: AkShare HS300 members are a current snapshot, not strict historical PIT."
echo

ASHARE=(conda run -n "$CONDA_ENV" ashare)

if [[ "$SKIP_INGEST" -eq 0 ]]; then
  INGEST_CMD=(
    "${ASHARE[@]}" ingest
    --source akshare
    --source-tag "$SOURCE"
    --universe "$UNIVERSE"
    --index-code "$INDEX_CODE"
    --from "$INGEST_FROM"
    --to "$ASOF"
    --universe-as-of "$UNIVERSE_AS_OF"
    --db-path "$DB"
    --cache-dir "$CACHE_DIR"
    --cache-mode "$CACHE_MODE"
    --quality-report-dir "$QUALITY_DIR"
    --overwrite-report
  )
  if [[ -n "$MAX_SYMBOLS" ]]; then
    INGEST_CMD+=(--max-symbols "$MAX_SYMBOLS")
  fi
  run_cmd "${INGEST_CMD[@]}"
else
  echo "+ skip ingest"
fi

run_cmd \
  "${ASHARE[@]}" as-of \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --index-code "$INDEX_CODE" \
  --stock-code "$STOCK_CODE" \
  --data-source "$SOURCE"

run_cmd \
  "${ASHARE[@]}" calculate-factors \
  --db-path "$DB" \
  --from "$FACTOR_FROM" \
  --to "$ASOF" \
  --index-code "$INDEX_CODE" \
  --data-source "$SOURCE" \
  --source-run-id "$FACTOR_RUN" \
  --run-mode exploratory \
  --overwrite-run \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --factor is_st \
  --factor is_suspended \
  --factor is_delisted \
  --factor low_liquidity

run_cmd \
  "${ASHARE[@]}" report \
  --kind factor-validation \
  --db-path "$DB" \
  --from "$VALIDATION_FROM" \
  --to "$VALIDATION_TO" \
  --source-run-id "$FACTOR_RUN" \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --horizon 5,20 \
  --n-groups 5 \
  --output-dir "$VALIDATION_DIR" \
  --run-id "$VALIDATION_RUN" \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run

run_cmd \
  "${ASHARE[@]}" scan \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --index-code "$INDEX_CODE" \
  --sort-factor return_20d \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --top "$TOP_N" \
  --output-dir "$SCAN_DIR" \
  --run-id "$SCAN_RUN" \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run

run_cmd \
  "${ASHARE[@]}" score \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --index-code "$INDEX_CODE" \
  --data-source "$SOURCE" \
  --scoring-config "$SCORING_CONFIG" \
  --validation-dir "$VALIDATION_DIR" \
  --top "$TOP_N" \
  --skip-diagnostics \
  --output-dir "$SCORE_DIR" \
  --run-id "$SCORE_RUN" \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run

run_cmd \
  "${ASHARE[@]}" stock-report \
  --db-path "$DB" \
  --code "$STOCK_CODE" \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --score-run-id "$SCORE_RUN" \
  --scan-run-id "$SCAN_RUN" \
  --output-dir "$STOCK_REPORT_DIR" \
  --run-id "$STOCK_REPORT_RUN" \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run
