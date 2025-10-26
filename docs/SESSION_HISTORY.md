# Session history (Oct 25, 2025)

This document captures the key decisions, features added, and workflows established in the current development session so that future runs have quick context.

## Highlights
- Added a new plot: `daily_volume_and_sentiment.png` showing bars for total volume (posts+replies) and lines for positive% and negative% per day.
- Improved daily activity chart with in-plot match labels (team abbreviations), density controls, and dynamic width/height.
- Implemented matchday sentiment rollups and plots: `matchday_sentiment_overall.csv/.png`, `matchday_posts_volume_vs_sentiment.png`.
- Integrated multiple sentiment backends:
  - VADER (default)
  - Transformers (local model at `models/sentiment-distilbert`)
  - Local GPT via Ollama (JSON {label, confidence} mapped to compound) with graceful fallback to VADER
- Labeled data workflow:
  - `src/apply_labels.py` merges labels back into posts/replies as `sentiment_label`
  - Analyzer reuses `sentiment_label` when present
  - `src/plot_labeled.py` provides QA plots
- Convenience: created `run_all` alias to run from scratch (scrape → replies → fixtures → analyze) non-interactively.

## Key files and outputs
- Code
  - `src/analyze_csv.py` — analyzer with plots and matchday integration (now with module docstring)
  - `src/gpt_sentiment.py`, `src/transformer_sentiment.py`, `src/auto_label_sentiment.py`, `src/apply_labels.py`, `src/plot_labeled.py`
  - `scripts/aliases.zsh` — includes `run_all`, `apply_labels_and_analyze`, and more
- Outputs (examples)
  - `data/daily_activity_stacked.png`
  - `data/daily_volume_and_sentiment.png`
  - `data/posts_heatmap_hour_dow.png`
  - `data/sentiment_by_tag_posts.png`
  - `data/matchday_sentiment_overall.csv/.png`
  - `data/matchday_posts_volume_vs_sentiment.png`

## Important flags (analyze)
- Sizing: `--plot-width-scale`, `--plot-max-width`, `--plot-height`
- Labels: `--activity-top-n`, `--labels-max-per-day`, `--labels-per-line`, `--labels-stagger-rows`, `--labels-band-y`, `--labels-annotate-mode`
- Sentiment backends: `--sentiment-backend vader|transformers|gpt`, plus `--transformers-model` or `--gpt-model`/`--gpt-base-url`
- Emoji: `--emoji-mode keep|demojize|strip` and `--emoji-boost`

## Aliases summary
- `run_all [CH] [START] [END] [POSTS] [REPLIES] [FIXTURES] [TAGS] [SESS_SCRAPE] [SESS_REPLIES] [CONC] [BACKEND] [MODEL] [GPT_MODEL] [GPT_URL]`
  - Full pipeline non-interactive, defaults set in `scripts/aliases.zsh`
- `apply_labels_and_analyze [LABELED_CSV] [POSTS_IN] [REPLIES_IN] [POSTS_OUT] [REPLIES_OUT]`
- `analyze_transformers`, `analyze_emoji`, `analyze_combined`, `fast_replies`, `chunked_forwards`, `plot_labeled`

## Old vs New outputs
- We maintain side-by-side outputs under `data/old` and `data/new` when running legacy vs labeled pipelines.

## Next ideas
- Per-club matchday sentiment breakdowns (fixture-level small multiples)
- Side-by-side montage generation for old vs new plots

