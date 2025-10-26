# Telegram analytics toolkit

Scrape public Telegram channel posts, fetch replies and forwards, and generate rich analytics reports with tagging, sentiment, matchday overlays, and plots. Use VADER, a local transformers model, or a local GPT (Ollama) backend for sentiment.

Highlights:
- Fast replies scraping with concurrency, resume/append, and rate-limit visibility
- Forwards scanning with chunked, concurrent search
- Analyzer: tagging from YAML keywords; sentiment via VADER, transformers, or local GPT; emoji-aware modes; combined posts+replies metrics; and matchday cross-analysis
- Plots: daily activity with in-plot match labels, daily volume vs sentiment (new), heatmaps, and per-tag (team) sentiment shares
- Local learning: fine-tune and evaluate a transformers classifier and use it in analysis

Full command reference is in `docs/COMMANDS.md`.

## Quick start

1) Configure secrets in `.env` (script will prompt if absent):
```
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
# Optional
TELEGRAM_SESSION_NAME=telegram
TELEGRAM_2FA_PASSWORD=your_2fa_password
FOOTBALL_DATA_API_TOKEN=your_token
```

2) Run any command via the wrapper (creates venv and installs deps automatically):

```zsh
# Fetch messages to CSV
./run_scraper.sh scrape -c https://t.me/Premier_League_Update -o data/premier_league_update.csv --start-date 2025-08-15 --end-date 2025-10-15

# Fetch replies fast
./run_scraper.sh replies -c https://t.me/Premier_League_Update --from-csv data/premier_league_update.csv -o data/premier_league_replies.csv --min-replies 1 --concurrency 15 --resume --append

# Analyze with tags, fixtures, emoji handling and plots
./run_scraper.sh analyze -i data/premier_league_update.csv --replies-csv data/premier_league_replies.csv --fixtures-csv data/premier_league_schedule_2025-08-15_to_2025-10-15.csv --tags-config config/tags.yaml --write-augmented-csv --write-combined-csv --emoji-mode keep --emoji-boost --save-plots
```

3) Use transformers sentiment instead of VADER:

```zsh
# Off-the-shelf fine-tuned sentiment head
./run_scraper.sh analyze -i data/premier_league_update.csv --replies-csv data/premier_league_replies.csv \
  --sentiment-backend transformers \
  --transformers-model distilbert-base-uncased-finetuned-sst-2-english \
  --export-transformers-details \
  --write-augmented-csv --write-combined-csv --save-plots
```

4) Use a local GPT backend (Ollama) for sentiment (JSON labels+confidence mapped to a compound score):

```zsh
# Ensure Ollama is running locally and the model is available (e.g., llama3)
./run_scraper.sh analyze -i data/premier_league_update.csv --replies-csv data/premier_league_replies.csv \
  --sentiment-backend gpt \
  --gpt-model llama3 \
  --gpt-base-url http://localhost:11434 \
  --write-augmented-csv --write-combined-csv --save-plots
```

## Aliases

Convenient zsh functions live in `scripts/aliases.zsh`:

- `fast_replies` — resume+append replies with concurrency
- `chunked_forwards` — concurrent forwards scan
- `analyze_combined` — posts+replies+fixtures with tags
- `analyze_emoji` — emoji-aware analyze with boost
- `analyze_transformers` — analyze with transformers and export details
- `apply_labels_and_analyze` — merge a labeled CSV into posts/replies and run analyzer (reuses sentiment_label)
- `plot_labeled` — QA plots from a labeled CSV (class distribution, confidence, lengths)
- `train_transformers` — fine-tune a model on a labeled CSV
- `eval_transformers` — evaluate a fine-tuned model

Source them:
```zsh
source scripts/aliases.zsh
```

## Local transformers (optional)

Train a classifier:
```zsh
./.venv/bin/python -m src.train_sentiment \
  --train-csv data/labeled_sentiment.csv \
  --text-col message \
  --label-col label \
  --model-name distilbert-base-uncased \
  --output-dir models/sentiment-distilbert \
  --epochs 3 --batch-size 16
```

Evaluate it:
```zsh
./.venv/bin/python -m src.eval_sentiment \
  --csv data/labeled_holdout.csv \
  --text-col message \
  --label-col label \
  --model models/sentiment-distilbert
```

Use it in analyze:
```zsh
./run_scraper.sh analyze -i data/premier_league_update.csv --replies-csv data/premier_league_replies.csv \
  --sentiment-backend transformers \
  --transformers-model models/sentiment-distilbert \
  --export-transformers-details \
  --write-augmented-csv --write-combined-csv --save-plots
```

Notes:
- GPU/Apple Silicon (MPS) is auto-detected; CPU is the fallback.
- Torch pinning in `requirements.txt` uses conditional versions for smooth installs across Python versions.

## Plots produced (when --save-plots is used)

- `daily_activity_stacked.png` — stacked bar chart of posts vs replies per day.
  - Dynamic sizing: `--plot-width-scale`, `--plot-max-width`, `--plot-height`
  - Top-N highlights: `--activity-top-n` (labels show total and posts+replies breakdown)
  - Match labels inside the plot using team abbreviations; control density with:
    - `--labels-max-per-day`, `--labels-per-line`, `--labels-stagger-rows`, `--labels-band-y`, `--labels-annotate-mode`
- `daily_volume_and_sentiment.png` — total volume (posts+replies) per day as bars (left Y) and positive%/negative% as lines (right Y). Uses `sentiment_label` when present, otherwise `sentiment_compound` thresholds.
- `posts_heatmap_hour_dow.png` — heatmap of posts activity by hour and day-of-week.
- `sentiment_by_tag_posts.png` — stacked shares of pos/neu/neg by team tag (tags starting with `club_`), with dynamic width.
- Matchday rollups (when fixtures are provided):
  - `matchday_sentiment_overall.csv` — per-fixture-day aggregates for posts (and replies when provided)
  - `matchday_sentiment_overall.png` — mean sentiment time series on matchdays (posts, replies)
  - `matchday_posts_volume_vs_sentiment.png` — scatter of posts volume vs mean sentiment on matchdays
- Diagnostics:
  - `match_labels_debug.csv` — per-day list of rendered match labels (helps tune label density)

Tip: The analyzer adapts plot width to the number of days; for very long ranges, raise `--plot-max-width`.

## Plot sizing and label flags (analyze)

- `--plot-width-scale` (default 0.8): inches per day for the daily charts width.
- `--plot-max-width` (default 104): cap on width in inches.
- `--plot-height` (default 6.5): figure height in inches.
- `--activity-top-n` (default 5): highlight top-N activity days; 0 disables.
- Match label controls:
  - `--labels-max-per-day` (default 3): cap labels per day (+N more).
  - `--labels-per-line` (default 2): labels per line in the band.
  - `--labels-band-y` (default 0.96): vertical position of the band (axes coords).
  - `--labels-stagger-rows` (default 2): stagger rows to reduce collisions.
  - `--labels-annotate-mode` (ticks|all|ticks+top): which x positions get labels.

## Automatic labeling (no manual annotation)

If you don't want to label data by hand, generate a labeled training set automatically and train a local model.

Label with VADER (fast) or a pretrained transformers model (higher quality):

```zsh
# Load aliases
source scripts/aliases.zsh

# VADER: keeps only confident predictions by default
auto_label_vader

# Or Transformers: CardiffNLP 3-class sentiment (keeps confident only)
auto_label_transformers

# Output: data/labeled_sentiment.csv (message, label, confidence, ...)
```

Then fine-tune a classifier on the generated labels and use it in analysis:

```zsh
# Train on the auto-labeled CSV
train_transformers

# Analyze using your fine-tuned model
./run_scraper.sh analyze -i data/premier_league_update.csv \
  --replies-csv data/premier_league_replies.csv \
  --fixtures-csv data/premier_league_schedule_2025-08-15_to_2025-10-15.csv \
  --tags-config config/tags.yaml \
  --sentiment-backend transformers \
  --transformers-model models/sentiment-distilbert \
  --export-transformers-details \
  --write-augmented-csv --write-combined-csv --save-plots
```

Advanced knobs (optional):
- VADER thresholds: `--vader-pos 0.05 --vader-neg -0.05 --vader-margin 0.2`
- Transformers acceptance: `--min-prob 0.6 --min-margin 0.2`
- Keep all predictions (not just confident): remove `--only-confident`

## Local GPT backend (Ollama)

You can use a local GPT model for sentiment. The analyzer requests strict JSON `{label, confidence}` and maps it to a compound score. If the GPT call fails for any rows, it gracefully falls back to VADER for those rows.

Example:
```zsh
./run_scraper.sh analyze -i data/premier_league_update.csv \
  --replies-csv data/premier_league_replies.csv \
  --fixtures-csv data/premier_league_schedule_2025-08-15_to_2025-10-15.csv \
  --tags-config config/tags.yaml \
  --sentiment-backend gpt \
  --gpt-model llama3 \
  --gpt-base-url http://localhost:11434 \
  --write-augmented-csv --write-combined-csv --save-plots
```

## License
MIT (adjust as needed)