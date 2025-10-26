#!/usr/bin/env zsh


# A convenience script to set up venv, install deps, create/load .env, and run tools:
# - Telegram scraper: scrape | replies | forwards
# - Analyzer: analyze (report + sentiment + tags)
# - Fixtures: fixtures (Premier League schedule)
set -euo pipefail

# Change to script directory (handles spaces in path)
cd "${0:A:h}"

PROJECT_ROOT=$(pwd)
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
PIP="${PROJECT_ROOT}/.venv/bin/pip"
REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
SCRAPER_MODULE="src.telegram_scraper"
ANALYZE_MODULE="src.analyze_csv"
FIXTURES_MODULE="src.fetch_schedule"

usage() {
  cat <<'EOF'
Usage:
  ./run_scraper.sh scrape   -c <channel> -o <output> [--limit N] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--phone <number>] [--append]
  ./run_scraper.sh replies  -c <channel> (--ids "1,2,3" | --from-csv <path>) -o <output_csv> [--append] [--min-replies N] [--concurrency K] [--resume]
  ./run_scraper.sh forwards -c <channel> (--ids "1,2,3" | --from-csv <path>) -o <output_csv> [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--scan-limit N] [--append] [--concurrency K] [--chunk-size M]
  ./run_scraper.sh analyze  -i <input_csv> [-o <report_md>] [--channel @handle] [--tags-config config/tags.yaml] [--replies-csv <csv>] [--fixtures-csv <csv>] [--write-augmented-csv] [--write-combined-csv] [--emoji-mode keep|demojize|strip] [--emoji-boost] [--save-plots] [--sentiment-backend vader|transformers] [--transformers-model <hf_or_path>] [--export-transformers-details]
                            [--plot-width-scale <float>] [--plot-max-width <inches>] [--plot-height <inches>] [--activity-top-n <int>] \
                            [--labels-max-per-day <int>] [--labels-per-line <int>] [--labels-band-y <float>] [--labels-stagger-rows <int>] [--labels-annotate-mode ticks|all|ticks+top]
                            [--sentiment-backend gpt] [--gpt-model <name>] [--gpt-base-url <http://localhost:11434>] [--gpt-batch-size <int>]
  ./run_scraper.sh fixtures --start-date YYYY-MM-DD --end-date YYYY-MM-DD -o <output.{csv|json}>

Examples:
  ./run_scraper.sh scrape -c @python -o data.jsonl --limit 200
  ./run_scraper.sh scrape -c https://t.me/python -o data.csv --start-date 2025-01-01 --end-date 2025-03-31
  ./run_scraper.sh replies -c @python --from-csv data/messages.csv -o data/replies.csv
  ./run_scraper.sh forwards -c @python --from-csv data/messages.csv -o data/forwards.csv --start-date 2025-01-01 --end-date 2025-03-31 --scan-limit 20000
  ./run_scraper.sh analyze -i data/messages.csv --channel @python --tags-config config/tags.yaml --replies-csv data/replies.csv --fixtures-csv data/fixtures.csv --write-augmented-csv
  ./run_scraper.sh analyze -i data/messages.csv --sentiment-backend transformers --transformers-model distilbert-base-uncased --export-transformers-details --write-augmented-csv --write-combined-csv
  ./run_scraper.sh fixtures --start-date 2025-08-15 --end-date 2025-10-15 -o data/pl_fixtures.csv

Notes:
- If .env is missing, you'll be prompted to create it when needed (Telegram or fixtures commands).
- First Telegram login will prompt for phone, code, and optionally 2FA password.
EOF
}

# Subcommand parsing
if [[ $# -lt 1 ]]; then
  usage; exit 1
fi
COMMAND="$1"; shift || true

# Common and per-command args
CHANNEL=""; OUTPUT=""; LIMIT=""; OFFSET_DATE=""; PHONE=""; START_DATE=""; END_DATE=""; APPEND=false; SESSION_NAME=""
IDS=""; FROM_CSV=""; SCAN_LIMIT=""
INPUT_CSV=""; REPORT_OUT=""; CHANNEL_NAME=""; TAGS_CONFIG=""; REPLIES_CSV=""; FIXTURES_CSV=""; WRITE_AUG=false; WRITE_COMBINED=false; EMOJI_MODE=""; EMOJI_BOOST=false; SAVE_PLOTS=false; SENTIMENT_BACKEND=""; TRANSFORMERS_MODEL=""; EXPORT_TRANSFORMERS_DETAILS=false; PLOT_WIDTH_SCALE=""; PLOT_MAX_WIDTH=""; PLOT_HEIGHT=""; ACTIVITY_TOP_N=""; LABELS_MAX_PER_DAY=""; LABELS_PER_LINE=""; LABELS_BAND_Y=""; LABELS_STAGGER_ROWS=""; LABELS_ANNOTATE_MODE=""; GPT_MODEL=""; GPT_BASE_URL=""; GPT_BATCH_SIZE=""

case "$COMMAND" in
  scrape|replies|forwards)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -c|--channel) CHANNEL="$2"; shift 2;;
        -o|--output) OUTPUT="$2"; shift 2;;
        --session-name) SESSION_NAME="$2"; shift 2;;
        --limit) LIMIT="$2"; shift 2;;
        --offset-date) OFFSET_DATE="$2"; shift 2;;
        --start-date) START_DATE="$2"; shift 2;;
        --end-date) END_DATE="$2"; shift 2;;
        --scan-limit) SCAN_LIMIT="$2"; shift 2;;
        --ids) IDS="$2"; shift 2;;
        --from-csv) FROM_CSV="$2"; shift 2;;
        --phone) PHONE="$2"; shift 2;;
        --append) APPEND=true; shift;;
        --min-replies) MIN_REPLIES="$2"; shift 2;;
        --concurrency) CONCURRENCY="$2"; shift 2;;
        --chunk-size) CHUNK_SIZE="$2"; shift 2;;
        --resume) RESUME=true; shift;;
        -h|--help) usage; exit 0;;
        *) echo "Unknown arg: $1"; usage; exit 1;;
      esac
    done
    ;;
  analyze)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -i|--input) INPUT_CSV="$2"; shift 2;;
        -o|--output) REPORT_OUT="$2"; shift 2;;
        --channel) CHANNEL_NAME="$2"; shift 2;;
        --tags-config) TAGS_CONFIG="$2"; shift 2;;
        --replies-csv) REPLIES_CSV="$2"; shift 2;;
        --fixtures-csv) FIXTURES_CSV="$2"; shift 2;;
  --write-augmented-csv) WRITE_AUG=true; shift;;
  --write-combined-csv) WRITE_COMBINED=true; shift;;
  --emoji-mode) EMOJI_MODE="$2"; shift 2;;
        --emoji-boost) EMOJI_BOOST=true; shift;;
  --save-plots) SAVE_PLOTS=true; shift;;
        --sentiment-backend) SENTIMENT_BACKEND="$2"; shift 2;;
        --transformers-model) TRANSFORMERS_MODEL="$2"; shift 2;;
        --export-transformers-details) EXPORT_TRANSFORMERS_DETAILS=true; shift;;
    --gpt-model) GPT_MODEL="$2"; shift 2;;
    --gpt-base-url) GPT_BASE_URL="$2"; shift 2;;
    --gpt-batch-size) GPT_BATCH_SIZE="$2"; shift 2;;
    --plot-width-scale) PLOT_WIDTH_SCALE="$2"; shift 2;;
    --plot-max-width) PLOT_MAX_WIDTH="$2"; shift 2;;
        --plot-height) PLOT_HEIGHT="$2"; shift 2;;
        --activity-top-n) ACTIVITY_TOP_N="$2"; shift 2;;
        --labels-max-per-day) LABELS_MAX_PER_DAY="$2"; shift 2;;
        --labels-per-line) LABELS_PER_LINE="$2"; shift 2;;
        --labels-band-y) LABELS_BAND_Y="$2"; shift 2;;
        --labels-stagger-rows) LABELS_STAGGER_ROWS="$2"; shift 2;;
        --labels-annotate-mode) LABELS_ANNOTATE_MODE="$2"; shift 2;;
        -h|--help) usage; exit 0;;
        *) echo "Unknown arg: $1"; usage; exit 1;;
      esac
    done
  # Defaults: always use local fine-tuned transformers model if not specified
  if [[ -z "$SENTIMENT_BACKEND" ]]; then SENTIMENT_BACKEND="transformers"; fi
  if [[ -z "$TRANSFORMERS_MODEL" ]]; then TRANSFORMERS_MODEL="models/sentiment-distilbert"; fi
    ;;
  fixtures)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --start-date) START_DATE="$2"; shift 2;;
        --end-date) END_DATE="$2"; shift 2;;
        -o|--output) OUTPUT="$2"; shift 2;;
        -h|--help) usage; exit 0;;
        *) echo "Unknown arg: $1"; usage; exit 1;;
      esac
    done
    ;;
  -h|--help)
    usage; exit 0;;
  *)
    echo "Unknown command: $COMMAND"; usage; exit 1;;
esac

# Required args validation
if [[ "$COMMAND" == "scrape" ]]; then
  if [[ -z "$CHANNEL" || -z "$OUTPUT" ]]; then echo "Error: scrape needs --channel and --output"; usage; exit 1; fi
elif [[ "$COMMAND" == "replies" || "$COMMAND" == "forwards" ]]; then
  if [[ -z "$CHANNEL" || -z "$OUTPUT" ]]; then echo "Error: $COMMAND needs --channel and --output"; usage; exit 1; fi
  if [[ -z "$IDS" && -z "$FROM_CSV" ]]; then echo "Error: $COMMAND needs --ids or --from-csv"; usage; exit 1; fi
elif [[ "$COMMAND" == "analyze" ]]; then
  if [[ -z "$INPUT_CSV" ]]; then echo "Error: analyze needs --input"; usage; exit 1; fi
elif [[ "$COMMAND" == "fixtures" ]]; then
  if [[ -z "$START_DATE" || -z "$END_DATE" || -z "$OUTPUT" ]]; then echo "Error: fixtures needs --start-date, --end-date, and --output"; usage; exit 1; fi
fi

echo "[1/4] Ensuring virtual environment..."
if [[ ! -x "$PYTHON" ]]; then
  echo "Creating virtual environment at .venv"
  python3 -m venv .venv
fi

echo "Activating virtual environment"
source .venv/bin/activate

echo "[2/4] Installing dependencies"
"$PIP" install -q --upgrade pip
"$PIP" install -q -r "$REQUIREMENTS_FILE"

echo "[3/4] Environment setup"
NEEDS_TELEGRAM=false
NEEDS_FIXTURES_TOKEN=false
if [[ "$COMMAND" == "scrape" || "$COMMAND" == "replies" || "$COMMAND" == "forwards" ]]; then NEEDS_TELEGRAM=true; fi
if [[ "$COMMAND" == "fixtures" ]]; then NEEDS_FIXTURES_TOKEN=true; fi

if [[ "$NEEDS_TELEGRAM" == true || "$NEEDS_FIXTURES_TOKEN" == true ]]; then
  if [[ ! -f .env ]]; then
    echo ".env not found. Let's create one now."
    if [[ "$NEEDS_TELEGRAM" == true ]]; then
      print -n "Enter TELEGRAM_API_ID (from my.telegram.org): "
      read -r TELEGRAM_API_ID
      print -n "Enter TELEGRAM_API_HASH (from my.telegram.org): "
      read -r TELEGRAM_API_HASH
      : ${TELEGRAM_SESSION_NAME:=telegram}
    fi
    cat > .env <<EOF
${TELEGRAM_API_ID:+TELEGRAM_API_ID=${TELEGRAM_API_ID}}
${TELEGRAM_API_HASH:+TELEGRAM_API_HASH=${TELEGRAM_API_HASH}}
${TELEGRAM_SESSION_NAME:+TELEGRAM_SESSION_NAME=${TELEGRAM_SESSION_NAME}}
${FOOTBALL_DATA_API_TOKEN:+FOOTBALL_DATA_API_TOKEN=${FOOTBALL_DATA_API_TOKEN}}
EOF
    echo "Created .env"
  fi

  echo "Loading environment from .env"
  set -a
  source .env
  set +a

  if [[ "$NEEDS_TELEGRAM" == true ]]; then
    if [[ -z "${TELEGRAM_API_ID:-}" || -z "${TELEGRAM_API_HASH:-}" ]]; then
      echo "Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env"
      exit 1
    fi
  fi
  if [[ "$NEEDS_FIXTURES_TOKEN" == true ]]; then
    if [[ -z "${FOOTBALL_DATA_API_TOKEN:-}" ]]; then
      echo "Error: FOOTBALL_DATA_API_TOKEN must be set in .env for fixtures"
      exit 1
    fi
  fi
fi

echo "[4/4] Running $COMMAND"
PY_ARGS=()
case "$COMMAND" in
  scrape)
    PY_ARGS=( -m "$SCRAPER_MODULE" scrape "$CHANNEL" --output "$OUTPUT" )
    if [[ -n "$SESSION_NAME" ]]; then PY_ARGS+=( --session-name "$SESSION_NAME" ); fi
    if [[ -n "$LIMIT" ]]; then PY_ARGS+=( --limit "$LIMIT" ); fi
    if [[ -n "$OFFSET_DATE" ]]; then PY_ARGS+=( --offset-date "$OFFSET_DATE" ); fi
    if [[ -n "$START_DATE" ]]; then PY_ARGS+=( --start-date "$START_DATE" ); fi
    if [[ -n "$END_DATE" ]]; then PY_ARGS+=( --end-date "$END_DATE" ); fi
    if [[ -n "$PHONE" ]]; then PY_ARGS+=( --phone "$PHONE" ); fi
    if [[ "$APPEND" == true ]]; then PY_ARGS+=( --append ); fi
    ;;
  replies)
  PY_ARGS=( -m "$SCRAPER_MODULE" replies "$CHANNEL" --output "$OUTPUT" )
    if [[ -n "$SESSION_NAME" ]]; then PY_ARGS+=( --session-name "$SESSION_NAME" ); fi
    if [[ -n "$IDS" ]]; then PY_ARGS+=( --ids "$IDS" ); fi
    if [[ -n "$FROM_CSV" ]]; then PY_ARGS+=( --from-csv "$FROM_CSV" ); fi
    if [[ -n "$PHONE" ]]; then PY_ARGS+=( --phone "$PHONE" ); fi
    if [[ "$APPEND" == true ]]; then PY_ARGS+=( --append ); fi
  if [[ -n "${MIN_REPLIES:-}" ]]; then PY_ARGS+=( --min-replies "$MIN_REPLIES" ); fi
  if [[ -n "${CONCURRENCY:-}" ]]; then PY_ARGS+=( --concurrency "$CONCURRENCY" ); fi
  if [[ "${RESUME:-false}" == true ]]; then PY_ARGS+=( --resume ); fi
    ;;
  forwards)
    PY_ARGS=( -m "$SCRAPER_MODULE" forwards "$CHANNEL" --output "$OUTPUT" )
    if [[ -n "$SESSION_NAME" ]]; then PY_ARGS+=( --session-name "$SESSION_NAME" ); fi
    if [[ -n "$IDS" ]]; then PY_ARGS+=( --ids "$IDS" ); fi
    if [[ -n "$FROM_CSV" ]]; then PY_ARGS+=( --from-csv "$FROM_CSV" ); fi
    if [[ -n "$START_DATE" ]]; then PY_ARGS+=( --start-date "$START_DATE" ); fi
    if [[ -n "$END_DATE" ]]; then PY_ARGS+=( --end-date "$END_DATE" ); fi
    if [[ -n "$SCAN_LIMIT" ]]; then PY_ARGS+=( --scan-limit "$SCAN_LIMIT" ); fi
    if [[ -n "${CONCURRENCY:-}" ]]; then PY_ARGS+=( --concurrency "$CONCURRENCY" ); fi
    if [[ -n "${CHUNK_SIZE:-}" ]]; then PY_ARGS+=( --chunk-size "$CHUNK_SIZE" ); fi
    if [[ -n "$PHONE" ]]; then PY_ARGS+=( --phone "$PHONE" ); fi
    if [[ "$APPEND" == true ]]; then PY_ARGS+=( --append ); fi
    ;;
  analyze)
    PY_ARGS=( -m "$ANALYZE_MODULE" "$INPUT_CSV" )
    if [[ -n "$REPORT_OUT" ]]; then PY_ARGS+=( -o "$REPORT_OUT" ); fi
    if [[ -n "$CHANNEL_NAME" ]]; then PY_ARGS+=( --channel "$CHANNEL_NAME" ); fi
    if [[ -n "$TAGS_CONFIG" ]]; then PY_ARGS+=( --tags-config "$TAGS_CONFIG" ); fi
    if [[ -n "$REPLIES_CSV" ]]; then PY_ARGS+=( --replies-csv "$REPLIES_CSV" ); fi
    if [[ -n "$FIXTURES_CSV" ]]; then PY_ARGS+=( --fixtures-csv "$FIXTURES_CSV" ); fi
    if [[ "$WRITE_AUG" == true ]]; then PY_ARGS+=( --write-augmented-csv ); fi
  if [[ "$WRITE_COMBINED" == true ]]; then PY_ARGS+=( --write-combined-csv ); fi
  if [[ -n "$EMOJI_MODE" ]]; then PY_ARGS+=( --emoji-mode "$EMOJI_MODE" ); fi
  if [[ "${EMOJI_BOOST:-false}" == true ]]; then PY_ARGS+=( --emoji-boost ); fi
  if [[ "${SAVE_PLOTS:-false}" == true ]]; then PY_ARGS+=( --save-plots ); fi
    if [[ -n "$SENTIMENT_BACKEND" ]]; then PY_ARGS+=( --sentiment-backend "$SENTIMENT_BACKEND" ); fi
    if [[ -n "$TRANSFORMERS_MODEL" ]]; then PY_ARGS+=( --transformers-model "$TRANSFORMERS_MODEL" ); fi
    if [[ "${EXPORT_TRANSFORMERS_DETAILS:-false}" == true ]]; then PY_ARGS+=( --export-transformers-details ); fi
    if [[ -n "$GPT_MODEL" ]]; then PY_ARGS+=( --gpt-model "$GPT_MODEL" ); fi
    if [[ -n "$GPT_BASE_URL" ]]; then PY_ARGS+=( --gpt-base-url "$GPT_BASE_URL" ); fi
    if [[ -n "$GPT_BATCH_SIZE" ]]; then PY_ARGS+=( --gpt-batch-size "$GPT_BATCH_SIZE" ); fi
      if [[ -n "$PLOT_WIDTH_SCALE" ]]; then PY_ARGS+=( --plot-width-scale "$PLOT_WIDTH_SCALE" ); fi
      if [[ -n "$PLOT_MAX_WIDTH" ]]; then PY_ARGS+=( --plot-max-width "$PLOT_MAX_WIDTH" ); fi
  if [[ -n "$PLOT_HEIGHT" ]]; then PY_ARGS+=( --plot-height "$PLOT_HEIGHT" ); fi
    if [[ -n "$ACTIVITY_TOP_N" ]]; then PY_ARGS+=( --activity-top-n "$ACTIVITY_TOP_N" ); fi
    if [[ -n "$LABELS_MAX_PER_DAY" ]]; then PY_ARGS+=( --labels-max-per-day "$LABELS_MAX_PER_DAY" ); fi
    if [[ -n "$LABELS_PER_LINE" ]]; then PY_ARGS+=( --labels-per-line "$LABELS_PER_LINE" ); fi
    if [[ -n "$LABELS_BAND_Y" ]]; then PY_ARGS+=( --labels-band-y "$LABELS_BAND_Y" ); fi
    if [[ -n "$LABELS_STAGGER_ROWS" ]]; then PY_ARGS+=( --labels-stagger-rows "$LABELS_STAGGER_ROWS" ); fi
    if [[ -n "$LABELS_ANNOTATE_MODE" ]]; then PY_ARGS+=( --labels-annotate-mode "$LABELS_ANNOTATE_MODE" ); fi
    ;;
  fixtures)
    PY_ARGS=( -m "$FIXTURES_MODULE" --start-date "$START_DATE" --end-date "$END_DATE" -o "$OUTPUT" )
    ;;
esac

echo "Command: $PYTHON ${PY_ARGS[@]}"
"$PYTHON" ${PY_ARGS[@]}
