# Convenience aliases for daily runs (zsh)
# Source this file in your shell:  source scripts/aliases.zsh

# --- Project defaults (edit as needed) ---
# Channel and files
export CH="https://t.me/Premier_League_Update"
export POSTS_CSV="data/premier_league_update.csv"
export REPLIES_CSV="data/premier_league_replies.csv"
export FORWARDS_CSV="data/premier_league_forwards.csv"
export TAGS_CFG="config/tags.yaml"
export FIXTURES_CSV="data/premier_league_schedule_2025-08-15_to_2025-10-15.csv"
# Default fixtures date range (used by run_all)
export FIXTURES_START_DATE="2025-08-15"
export FIXTURES_END_DATE="2025-10-15"

# Sessions directory outside iCloud (avoid sqlite locks)
export SESSION_DIR="$HOME/.local/share/telethon_sessions"
mkdir -p "$SESSION_DIR"

# --- Aliases (zsh functions) ---

# Fast replies: resume+append, prioritizes parents with replies, tuned concurrency
fast_replies() {
  local ch="${1:-$CH}"
  local posts="${2:-$POSTS_CSV}"
  local out="${3:-$REPLIES_CSV}"
  local conc="${4:-15}"
  local sess="${5:-$SESSION_DIR/telegram_replies}"
  ./run_scraper.sh replies \
    -c "$ch" \
    --from-csv "$posts" \
    -o "$out" \
    --min-replies 1 \
    --concurrency "$conc" \
    --resume \
    --append \
    --session-name "$sess"
}

# Chunked forwards: concurrent chunk scan with progress logs
chunked_forwards() {
  local ch="${1:-$CH}"
  local posts="${2:-$POSTS_CSV}"
  local out="${3:-$FORWARDS_CSV}"
  local scan="${4:-20000}"
  local conc="${5:-10}"
  local chunk="${6:-1500}"
  local sess="${7:-$SESSION_DIR/telegram_forwards}"
  ./run_scraper.sh forwards \
    -c "$ch" \
    --from-csv "$posts" \
    -o "$out" \
    --scan-limit "$scan" \
    --concurrency "$conc" \
    --chunk-size "$chunk" \
    --append \
    --session-name "$sess"
}

# Combined analyze: posts + replies + fixtures with tags; writes augmented CSVs
analyze_combined() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local tags="${3:-$TAGS_CFG}"
  local fixtures="${4:-$FIXTURES_CSV}"
  local ch="${5:-$CH}"
  ./run_scraper.sh analyze \
    -i "$posts" \
    --channel "$ch" \
    --tags-config "$tags" \
    --replies-csv "$replies" \
    --fixtures-csv "$fixtures" \
    --write-augmented-csv \
    --write-combined-csv \
    --save-plots
  # Tip: add plot sizing/labels, e.g.: --plot-width-scale 0.8 --plot-max-width 120 --plot-height 8 --activity-top-n 8 --labels-stagger-rows 3
}

# Emoji-aware analyze with sensible defaults (keep + boost)
analyze_emoji() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local tags="${3:-$TAGS_CFG}"
  local fixtures="${4:-$FIXTURES_CSV}"
  local ch="${5:-$CH}"
  local mode="${6:-keep}"   # keep | demojize | strip
  ./run_scraper.sh analyze \
    -i "$posts" \
    --channel "$ch" \
    --tags-config "$tags" \
    --replies-csv "$replies" \
    --fixtures-csv "$fixtures" \
    --write-augmented-csv \
    --write-combined-csv \
    --save-plots \
    --emoji-mode "$mode" \
    --emoji-boost
}

# Analyze with transformers (and export labels/probs)
analyze_transformers() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local tags="${3:-$TAGS_CFG}"
  local fixtures="${4:-$FIXTURES_CSV}"
  local ch="${5:-$CH}"
  local model="${6:-distilbert-base-uncased}"
  ./run_scraper.sh analyze \
    -i "$posts" \
    --channel "$ch" \
    --tags-config "$tags" \
    --replies-csv "$replies" \
    --fixtures-csv "$fixtures" \
    --sentiment-backend transformers \
    --transformers-model "$model" \
    --export-transformers-details \
    --write-augmented-csv \
    --write-combined-csv \
    --save-plots
}

# Plot graphs from labeled sentiment CSV
plot_labeled() {
  local labeled_csv="${1:-data/labeled_sentiment.csv}"
  local out_dir="${2:-data}"
  ./.venv/bin/python -m src.plot_labeled \
    --input "$labeled_csv" \
    --out-dir "$out_dir"
}

# Merge labeled CSV back into posts/replies to reuse analyzer plots
apply_labels_and_analyze() {
  local labeled_csv="${1:-data/labeled_sentiment.csv}"
  local posts_in="${2:-$POSTS_CSV}"
  local replies_in="${3:-$REPLIES_CSV}"
  local posts_out="${4:-data/premier_league_update_with_labels.csv}"
  local replies_out="${5:-data/premier_league_replies_with_labels.csv}"
  ./.venv/bin/python -m src.apply_labels \
    --labeled-csv "$labeled_csv" \
    --posts-csv "$posts_in" \
    --replies-csv "$replies_in" \
    --posts-out "$posts_out" \
    --replies-out "$replies_out"
  # Reuse analyzer with the merged CSVs; it will pick up sentiment_label if present
  ./run_scraper.sh analyze \
    -i "$posts_out" \
    --replies-csv "$replies_out" \
    --fixtures-csv "$FIXTURES_CSV" \
    --tags-config "$TAGS_CFG" \
    --write-augmented-csv \
    --write-combined-csv \
    --save-plots
}

# Auto-label sentiment without manual annotation (VADER backend)
auto_label_vader() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local out="${3:-data/labeled_sentiment.csv}"
  ./.venv/bin/python -m src.auto_label_sentiment \
    --posts-csv "$posts" \
    --replies-csv "$replies" \
    --backend vader \
    --vader-pos 0.05 \
    --vader-neg -0.05 \
    --vader-margin 0.20 \
    --only-confident \
    -o "$out"
}

# Auto-label sentiment using a pretrained transformers model
auto_label_transformers() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local model="${3:-cardiffnlp/twitter-roberta-base-sentiment-latest}"
  local out="${4:-data/labeled_sentiment.csv}"
  ./.venv/bin/python -m src.auto_label_sentiment \
    --posts-csv "$posts" \
    --replies-csv "$replies" \
    --backend transformers \
    --transformers-model "$model" \
    --min-prob 0.6 \
    --min-margin 0.2 \
    --only-confident \
    -o "$out"
}

# Train a transformers model with the project venv
train_transformers() {
  local train_csv="${1:-data/labeled_sentiment.csv}"
  local text_col="${2:-message}"
  local label_col="${3:-label}"
  local base_model="${4:-distilbert-base-uncased}"
  local out_dir="${5:-models/sentiment-distilbert}"
  ./.venv/bin/python -m src.train_sentiment \
    --train-csv "$train_csv" \
    --text-col "$text_col" \
    --label-col "$label_col" \
    --model-name "$base_model" \
    --output-dir "$out_dir" \
    --epochs 3 \
    --batch-size 16
}

# Evaluate a fine-tuned transformers model
eval_transformers() {
  local csv="${1:-data/labeled_holdout.csv}"
  local text_col="${2:-message}"
  local label_col="${3:-label}"
  local model_dir="${4:-models/sentiment-distilbert}"
  ./.venv/bin/python -m src.eval_sentiment \
    --csv "$csv" \
    --text-col "$text_col" \
    --label-col "$label_col" \
    --model "$model_dir"
}

# Build a labeling CSV from existing posts+replies
make_label_set() {
  local posts="${1:-$POSTS_CSV}"
  local replies="${2:-$REPLIES_CSV}"
  local out="${3:-data/labeled_sentiment.csv}"
  local n="${4:-1000}"
  ./.venv/bin/python -m src.make_labeling_set \
    --posts-csv "$posts" \
    --replies-csv "$replies" \
    --sample-size "$n" \
    -o "$out"
}

# One-shot daily pipeline: fast replies then combined analyze
run_daily() {
  local ch="${1:-$CH}"
  local posts="${2:-$POSTS_CSV}"
  local replies="${3:-$REPLIES_CSV}"
  local conc="${4:-15}"
  fast_replies "$ch" "$posts" "$replies" "$conc" "$SESSION_DIR/telegram_replies"
  analyze_emoji "$posts" "$replies" "$TAGS_CFG" "$FIXTURES_CSV" "$ch" keep
}

# One-shot daily pipeline with forwards in parallel
run_daily_with_forwards() {
  local ch="${1:-$CH}"
  local posts="${2:-$POSTS_CSV}"
  local replies="${3:-$REPLIES_CSV}"
  local forwards="${4:-$FORWARDS_CSV}"
  local rep_conc="${5:-15}"
  local f_scan="${6:-20000}"
  local f_conc="${7:-10}"
  local f_chunk="${8:-1500}"
  local sess_r="${9:-$SESSION_DIR/telegram_replies}"
  local sess_f="${10:-$SESSION_DIR/telegram_forwards}"

  # Launch replies and forwards in parallel with separate sessions
  local pid_r pid_f
  fast_replies "$ch" "$posts" "$replies" "$rep_conc" "$sess_r" & pid_r=$!
  chunked_forwards "$ch" "$posts" "$forwards" "$f_scan" "$f_conc" "$f_chunk" "$sess_f" & pid_f=$!

  # Wait for completion and then analyze with emoji handling
  wait $pid_r
  wait $pid_f
  analyze_emoji "$posts" "$replies" "$TAGS_CFG" "$FIXTURES_CSV" "$ch" keep
}

# End-to-end, non-interactive pipeline (from scratch): scrape -> replies -> fixtures -> analyze
# Requirements:
# - .env has TELEGRAM_API_ID and TELEGRAM_API_HASH (and TELEGRAM_2FA_PASSWORD if 2FA is enabled)
# - CH/POSTS_CSV/REPLIES_CSV/FIXTURES_CSV/TAGS_CFG are set (defaults are defined above)
# - Provide optional start/end dates; defaults use FIXTURES_START_DATE/FIXTURES_END_DATE
# - Choose sentiment backend via arg 11: vader | transformers | gpt (default: transformers)
run_all() {
  local ch="${1:-$CH}"
  local start="${2:-$FIXTURES_START_DATE}"
  local end="${3:-$FIXTURES_END_DATE}"
  local posts="${4:-$POSTS_CSV}"
  local replies="${5:-$REPLIES_CSV}"
  local fixtures="${6:-$FIXTURES_CSV}"
  local tags="${7:-$TAGS_CFG}"
  local sess_scrape="${8:-$SESSION_DIR/telegram_scrape}"
  local sess_replies="${9:-$SESSION_DIR/telegram_replies}"
  local rep_conc="${10:-15}"
  local backend="${11:-transformers}"   # vader | transformers | gpt
  local model="${12:-models/sentiment-distilbert}"
  local gpt_model="${13:-llama3}"
  local gpt_url="${14:-http://localhost:11434}"

  # 1) Scrape posts (overwrite)
  ./run_scraper.sh scrape \
    -c "$ch" \
    -o "$posts" \
    --start-date "$start" \
    --end-date "$end" \
    --session-name "$sess_scrape"

  # 2) Fetch replies (resume+append safe)
  ./run_scraper.sh replies \
    -c "$ch" \
    --from-csv "$posts" \
    -o "$replies" \
    --min-replies 1 \
    --concurrency "$rep_conc" \
    --resume \
    --append \
    --session-name "$sess_replies"

  # 3) Fetch fixtures for the same period
  ./run_scraper.sh fixtures \
    --start-date "$start" \
    --end-date "$end" \
    -o "$fixtures"

  # 4) Analyze with plots (non-interactive)
  local args=(
    -i "$posts"
    --tags-config "$tags"
    --replies-csv "$replies"
    --fixtures-csv "$fixtures"
    --write-augmented-csv
    --write-combined-csv
    --emoji-mode keep
    --emoji-boost
    --save-plots
    --plot-width-scale 0.8
    --plot-max-width 120
    --plot-height 8
    --activity-top-n 8
    --labels-stagger-rows 3
  )
  if [[ "$backend" == "transformers" ]]; then
    args+=( --sentiment-backend transformers --transformers-model "$model" --export-transformers-details )
  elif [[ "$backend" == "gpt" ]]; then
    args+=( --sentiment-backend gpt --gpt-model "$gpt_model" --gpt-base-url "$gpt_url" )
  else
    args+=( --sentiment-backend vader )
  fi

  ./run_scraper.sh analyze "${args[@]}"
}
