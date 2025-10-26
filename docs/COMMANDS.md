# Project command reference

This file lists all supported commands and practical permutations for `./run_scraper.sh`, with short comments and tips. It mirrors the actual CLI flags in the code.

- Shell: zsh (macOS) — commands below are ready to paste.
- Env: A `.venv` is created automatically; dependencies installed from `requirements.txt`.
- Secrets: Create `.env` with TELEGRAM_API_ID and TELEGRAM_API_HASH; for fixtures also set FOOTBALL_DATA_API_TOKEN.
- 2FA: If you use Telegram two-step verification, set TELEGRAM_2FA_PASSWORD in `.env` (the shell wrapper doesn’t accept a flag for this).
- Sessions: Telethon uses a SQLite session file (default `telegram.session`). When running multiple tools in parallel, use distinct `--session-name` values.

## Common conventions

- Channels
  - Use either handle or URL: `-c @name` or `-c https://t.me/name`.
  - For replies, the channel must match the posts’ source in your CSV `url` column.
- Output behavior
  - scrape/replies/forwards overwrite unless you pass `--append`.
  - analyze always overwrites its outputs.
- Rate-limits
  - Replies/forwards log `[rate-limit]` if Telegram asks you to wait. Reduce `--concurrency` if frequent.
- Parallel runs
  - Add `--session-name <unique>` per process to avoid “database is locked”. Prefer sessions outside iCloud Drive.

---

## Scrape (posts/messages)

Minimal (overwrite output):
```zsh
./run_scraper.sh scrape -c @SomeChannel -o data/messages.csv
```

With date range and limit:
```zsh
./run_scraper.sh scrape \
  -c https://t.me/SomeChannel \
  -o data/messages.jsonl \
  --start-date 2025-01-01 \
  --end-date 2025-03-31 \
  --limit 500
```

Legacy offset date (deprecated; prefer --start-date):
```zsh
./run_scraper.sh scrape -c @SomeChannel -o data/messages.csv --offset-date 2025-01-01
```

Append to existing file and pass phone on first login:
```zsh
./run_scraper.sh scrape \
  -c @SomeChannel \
  -o data/messages.csv \
  --append \
  --phone +15551234567
```

Use a custom session (useful in parallel):
```zsh
./run_scraper.sh scrape -c @SomeChannel -o data/messages.csv --session-name telegram_scrape
```

Notes:
- Output format inferred by extension: `.csv` or `.jsonl`/`.ndjson`.
- Two-step verification: set TELEGRAM_2FA_PASSWORD in `.env` (no CLI flag in the shell wrapper).

### All valid forms (scrape)

Use one of the following combinations. Replace placeholders with your values.

- Base variables:
  - CH = @handle or https://t.me/handle
  - OUT = path to .csv or .jsonl
  - Optional value flags: [--limit N] [--session-name NAME] [--phone NUMBER]

- Date filter permutations (4) × Append flag (2) × Limit presence (2) = 16 forms

1) No dates, no append, no limit
  ./run_scraper.sh scrape -c CH -o OUT
2) No dates, no append, with limit
  ./run_scraper.sh scrape -c CH -o OUT --limit N
3) No dates, with append, no limit
  ./run_scraper.sh scrape -c CH -o OUT --append
4) No dates, with append, with limit
  ./run_scraper.sh scrape -c CH -o OUT --append --limit N
5) Start only, no append, no limit
  ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD
6) Start only, no append, with limit
  ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --limit N
7) Start only, with append, no limit
  ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --append
8) Start only, with append, with limit
  ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --append --limit N
9) End only, no append, no limit
  ./run_scraper.sh scrape -c CH -o OUT --end-date YYYY-MM-DD
10) End only, no append, with limit
   ./run_scraper.sh scrape -c CH -o OUT --end-date YYYY-MM-DD --limit N
11) End only, with append, no limit
   ./run_scraper.sh scrape -c CH -o OUT --end-date YYYY-MM-DD --append
12) End only, with append, with limit
   ./run_scraper.sh scrape -c CH -o OUT --end-date YYYY-MM-DD --append --limit N
13) Start and end, no append, no limit
   ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --end-date YYYY-MM-DD
14) Start and end, no append, with limit
   ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --end-date YYYY-MM-DD --limit N
15) Start and end, with append, no limit
   ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --end-date YYYY-MM-DD --append
16) Start and end, with append, with limit
   ./run_scraper.sh scrape -c CH -o OUT --start-date YYYY-MM-DD --end-date YYYY-MM-DD --append --limit N

Optional add-ons valid for any form above:
- Append [--session-name NAME] and/or [--phone NUMBER]
- Deprecated alternative to start-date: add [--offset-date YYYY-MM-DD]

---

## Replies (fetch replies to posts)

From a posts CSV (fast path; skip posts with 0 replies in CSV):
```zsh
./run_scraper.sh replies \
  -c https://t.me/SourceChannel \
  --from-csv data/messages.csv \
  -o data/replies.csv \
  --min-replies 1 \
  --concurrency 15 \
  --resume \
  --append
```

Using explicit message IDs:
```zsh
./run_scraper.sh replies \
  -c @SourceChannel \
  --ids "123,456,789" \
  -o data/replies.csv \
  --concurrency 5 \
  --append
```

IDs from a file (one per line) using zsh substitution:
```zsh
IDS=$(tr '\n' ',' < parent_ids.txt | sed 's/,$//')
./run_scraper.sh replies -c @SourceChannel --ids "$IDS" -o data/replies.csv --concurrency 8 --append
```

Parallel-safe session name:
```zsh
./run_scraper.sh replies -c @SourceChannel --from-csv data/messages.csv -o data/replies.csv --concurrency 12 --resume --append --session-name telegram_replies
```

What the flags do:
- `--from-csv PATH` reads parent IDs from a CSV with an `id` column (optionally filtered by `--min-replies`).
- `--ids` provides a comma-separated list of parent IDs.
- `--concurrency K` processes K parent IDs in parallel (default 5).
- `--resume` dedupes by `(parent_id,id)` pairs already present in the output.
- `--append` appends to output instead of overwriting.

Notes:
- The channel (`-c`) must match the posts’ source in your CSV URLs (the tool warns on mismatch).
- First login may require `--phone` (interactive prompt). For 2FA, set TELEGRAM_2FA_PASSWORD in `.env`.

### All valid forms (replies)

- Base variables:
  - CH = @handle or https://t.me/handle
  - OUT = path to .csv
  - Source: exactly one of S1 or S2
    - S1: --ids "id1,id2,..."
    - S2: --from-csv PATH [--min-replies N]
  - Optional: [--concurrency K] [--session-name NAME] [--phone NUMBER]
  - Binary: [--append], [--resume]

- Enumerated binary permutations for each source (4 per source = 8 total):

S1 + no append + no resume
  ./run_scraper.sh replies -c CH --ids "IDLIST" -o OUT
S1 + no append + resume
  ./run_scraper.sh replies -c CH --ids "IDLIST" -o OUT --resume
S1 + append + no resume
  ./run_scraper.sh replies -c CH --ids "IDLIST" -o OUT --append
S1 + append + resume
  ./run_scraper.sh replies -c CH --ids "IDLIST" -o OUT --append --resume

S2 + no append + no resume
  ./run_scraper.sh replies -c CH --from-csv PATH -o OUT
S2 + no append + resume
  ./run_scraper.sh replies -c CH --from-csv PATH -o OUT --resume
S2 + append + no resume
  ./run_scraper.sh replies -c CH --from-csv PATH -o OUT --append
S2 + append + resume
  ./run_scraper.sh replies -c CH --from-csv PATH -o OUT --append --resume

Optional add-ons valid for any form above:
- Add [--concurrency K] to tune speed; recommended 8–20
- With S2 you may add [--min-replies N] to prioritize parents with replies
- Add [--session-name NAME] and/or [--phone NUMBER]

---

## Forwards (same-channel forwards referencing posts)

Typical concurrent scan (best-effort; often zero results):
```zsh
./run_scraper.sh forwards \
  -c https://t.me/SourceChannel \
  --from-csv data/messages.csv \
  -o data/forwards.csv \
  --scan-limit 20000 \
  --concurrency 10 \
  --chunk-size 1500
```

With date filters (applied to scanned messages):
```zsh
./run_scraper.sh forwards \
  -c @SourceChannel \
  --from-csv data/messages.csv \
  -o data/forwards.csv \
  --start-date 2025-01-01 \
  --end-date 2025-03-31 \
  --scan-limit 10000 \
  --concurrency 8 \
  --chunk-size 1000
```

Using explicit message IDs:
```zsh
./run_scraper.sh forwards -c @SourceChannel --ids "100,200,300" -o data/forwards.csv --scan-limit 8000 --concurrency 6 --chunk-size 1000
```

Sequential mode (no chunking) by omitting --scan-limit:
```zsh
./run_scraper.sh forwards -c @SourceChannel --from-csv data/messages.csv -o data/forwards.csv
```

What the flags do:
- `--scan-limit N`: enables chunked, concurrent scanning of ~N recent message IDs.
- `--concurrency K`: number of id-chunks to scan in parallel (requires `--scan-limit`).
- `--chunk-size M`: approx. IDs per chunk (trade-off between balance/overhead). Start with 1000–2000.
- `--append`: append instead of overwrite.

Notes:
- This only finds forwards within the same channel that reference your parent IDs (self-forwards). Many channels will yield zero.
- Global cross-channel forward discovery is not supported here (can be added as a separate mode).
- Without `--scan-limit`, the tool scans sequentially from newest backwards and logs progress every ~1000 messages.

### All valid forms (forwards)

- Base variables:
  - CH = @handle or https://t.me/handle
  - OUT = path to .csv
  - Source: exactly one of S1 or S2
    - S1: --ids "id1,id2,..."
    - S2: --from-csv PATH
  - Modes:
    - M1: Sequential scan (omit --scan-limit)
    - M2: Chunked concurrent scan (requires --scan-limit N; accepts --concurrency K and --chunk-size M)
  - Optional date filters for both modes: [--start-date D] [--end-date D]
  - Binary: [--append]
  - Optional: [--session-name NAME] [--phone NUMBER]

- Enumerated permutations by mode, source, and append (2 modes × 2 sources × 2 append = 8 forms):

M1 + S1 + no append
  ./run_scraper.sh forwards -c CH --ids "IDLIST" -o OUT [--start-date D] [--end-date D]
M1 + S1 + append
  ./run_scraper.sh forwards -c CH --ids "IDLIST" -o OUT --append [--start-date D] [--end-date D]
M1 + S2 + no append
  ./run_scraper.sh forwards -c CH --from-csv PATH -o OUT [--start-date D] [--end-date D]
M1 + S2 + append
  ./run_scraper.sh forwards -c CH --from-csv PATH -o OUT --append [--start-date D] [--end-date D]

M2 + S1 + no append
  ./run_scraper.sh forwards -c CH --ids "IDLIST" -o OUT --scan-limit N [--concurrency K] [--chunk-size M] [--start-date D] [--end-date D]
M2 + S1 + append
  ./run_scraper.sh forwards -c CH --ids "IDLIST" -o OUT --scan-limit N --append [--concurrency K] [--chunk-size M] [--start-date D] [--end-date D]
M2 + S2 + no append
  ./run_scraper.sh forwards -c CH --from-csv PATH -o OUT --scan-limit N [--concurrency K] [--chunk-size M] [--start-date D] [--end-date D]
M2 + S2 + append
  ./run_scraper.sh forwards -c CH --from-csv PATH -o OUT --scan-limit N --append [--concurrency K] [--chunk-size M] [--start-date D] [--end-date D]

Optional add-ons valid for any form above:
- Add [--session-name NAME] and/or [--phone NUMBER]

---

## Analyze (reports and tagging)

Posts-only report + tagged CSV:
```zsh
./run_scraper.sh analyze \
  -i data/messages.csv \
  --channel @SourceChannel \
  --tags-config config/tags.yaml \
  --fixtures-csv data/fixtures.csv \
  --write-augmented-csv
```
Outputs:
- `data/messages_report.md`
- `data/messages_tagged.csv`

Replies-only report + tagged CSV:
```zsh
./run_scraper.sh analyze \
  -i data/replies.csv \
  --channel "Replies - @SourceChannel" \
  --tags-config config/tags.yaml \
  --write-augmented-csv
```
Outputs:
- `data/replies_report.md`
- `data/replies_tagged.csv`

Combined (posts report augmented with replies):
```zsh
./run_scraper.sh analyze \
  -i data/messages.csv \
  --channel @SourceChannel \
  --tags-config config/tags.yaml \
  --replies-csv data/replies.csv \
  --fixtures-csv data/fixtures.csv \
  --write-augmented-csv \
  --write-combined-csv \
  --emoji-mode keep \
  --emoji-boost \
  --save-plots
```
Adds to posts dataset:
- `sentiment_compound` for posts (VADER)
- `replies_sentiment_mean` (avg reply sentiment per post)
- `replies_count_scraped` and `replies_top_tags` (rollup from replies)

Report sections include:
- Summary, top posts by views/forwards/replies
- Temporal distributions
- Per-tag engagement
- Per-tag sentiment (posts)
- Replies per-tag summary
- Per-tag sentiment (replies)
 - Combined sentiment (posts + replies)
 - Matchday cross-analysis (when `--fixtures-csv` is provided):
   - Posts: on vs off matchdays (counts and sentiment shares)
  - Posts engagement vs matchday (replies per post: total, mean, median, share of posts with replies)
   - Replies: on vs off matchdays (counts and sentiment shares)
  - Replies by parent matchday and by reply date are both shown; parent-based classification is recommended for engagement.

Notes:
- Analyze overwrites outputs; use `-o` to customize report filename if needed.
- Emoji handling: add `--emoji-mode keep|demojize|strip` (default keep). Optionally `--emoji-boost` to gently tilt scores when clearly positive/negative emojis are present.
 - Add `--write-combined-csv` to emit a unified CSV of posts+replies with a `content_type` column.

### All valid forms (analyze)

- Base variables:
  - IN = input CSV (posts or replies)
  - Optional outputs/labels: [-o REPORT.md] [--channel @handle]
  - Optional configs/data: [--tags-config config/tags.yaml] [--replies-csv REPLIES.csv] [--fixtures-csv FIXTURES.csv]
  - Binary: [--write-augmented-csv]

- Core permutations across replies-csv, fixtures-csv, write-augmented-csv (2×2×2 = 8 forms):

1) No replies, no fixtures, no aug
  ./run_scraper.sh analyze -i IN
2) No replies, no fixtures, with aug
  ./run_scraper.sh analyze -i IN --write-augmented-csv
3) No replies, with fixtures, no aug
  ./run_scraper.sh analyze -i IN --fixtures-csv FIXTURES.csv
4) No replies, with fixtures, with aug
  ./run_scraper.sh analyze -i IN --fixtures-csv FIXTURES.csv --write-augmented-csv
5) With replies, no fixtures, no aug
  ./run_scraper.sh analyze -i IN --replies-csv REPLIES.csv
6) With replies, no fixtures, with aug
  ./run_scraper.sh analyze -i IN --replies-csv REPLIES.csv --write-augmented-csv
7) With replies, with fixtures, no aug
  ./run_scraper.sh analyze -i IN --replies-csv REPLIES.csv --fixtures-csv FIXTURES.csv
8) With replies, with fixtures, with aug
  ./run_scraper.sh analyze -i IN --replies-csv REPLIES.csv --fixtures-csv FIXTURES.csv --write-augmented-csv

Optional add-ons valid for any form above:
- Append [-o REPORT.md] to control output filename
- Append [--channel @handle] for title
- Append [--tags-config config/tags.yaml] to enable tagging and per-tag summaries
- Append [--emoji-mode keep|demojize|strip] and optionally [--emoji-boost]
- Append [--write-combined-csv] to produce a merged posts+replies CSV
 - Append [--save-plots] to emit plots to the data folder
 - Append [--sentiment-backend transformers] and [--transformers-model <name-or-path>] to use a local HF model instead of VADER
 - Append [--export-transformers-details] to include `sentiment_label` and `sentiment_probs` in augmented/combined CSVs
 - Append [--sentiment-backend gpt] and optionally [--gpt-model MODEL] [--gpt-base-url URL] [--gpt-batch-size K] to use a local GPT (Ollama) backend
 - Plot sizing and label controls (daily charts):
   - [--plot-width-scale FLOAT] [--plot-max-width INCHES] [--plot-height INCHES]
   - [--activity-top-n N]
   - [--labels-max-per-day N] [--labels-per-line N] [--labels-band-y FLOAT] [--labels-stagger-rows N] [--labels-annotate-mode ticks|all|ticks+top]

When fixtures are provided (`--fixtures-csv`):
- The report adds a "## Matchday cross-analysis" section with on vs off matchday tables.
- Plots include:
  - daily_activity_stacked.png with match labels inside the chart
  - daily_volume_and_sentiment.png (bars: volume; lines: pos%/neg%)
  - matchday_sentiment_overall.png (time series on fixture days)
  - matchday_posts_volume_vs_sentiment.png (scatter)
- The combined CSV (with `--write-combined-csv`) includes `is_matchday` and, for replies, `parent_is_matchday` when available.
- Replies are classified two ways: by reply date (`is_matchday` on the reply row) and by their parent post (`parent_is_matchday`). The latter better reflects matchday-driven engagement.

Emoji and plots examples:
```zsh
# Keep emojis (default) and boost for strong positive/negative emojis
./run_scraper.sh analyze -i data/messages.csv --emoji-mode keep --emoji-boost --save-plots

# Demojize to :smiling_face: tokens (helps some tokenizers), with boost
./run_scraper.sh analyze -i data/messages.csv --emoji-mode demojize --emoji-boost

# Strip emojis entirely (if they add noise)
./run_scraper.sh analyze -i data/messages.csv --emoji-mode strip --save-plots

# Use a transformers model for sentiment (will auto-download on first use unless a local path is provided).
# Tip: for an off-the-shelf sentiment head, try a fine-tuned model like SST-2:
./run_scraper.sh analyze -i data/messages.csv --replies-csv data/replies.csv \
  --sentiment-backend transformers \
  --transformers-model distilbert-base-uncased-finetuned-sst-2-english

## Local GPT backend (Ollama)

Use a local GPT model that returns JSON {label, confidence} per message; the analyzer maps this to a compound score and falls back to VADER on errors.

```zsh
./run_scraper.sh analyze -i data/messages.csv --replies-csv data/replies.csv \
  --sentiment-backend gpt \
  --gpt-model llama3 \
  --gpt-base-url http://localhost:11434 \
  --write-augmented-csv --write-combined-csv --save-plots
```
```

---

## Train a local transformers sentiment model

Prepare a labeled CSV with at least two columns: `message` and `label` (e.g., neg/neu/pos or 0/1/2).

Don’t have one yet? Create a labeling set from your existing posts/replies:

```zsh
# Generate a CSV to annotate by hand (adds a blank 'label' column)
./.venv/bin/python -m src.make_labeling_set \
  --posts-csv data/premier_league_update.csv \
  --replies-csv data/premier_league_replies.csv \
  --sample-size 1000 \
  -o data/labeled_sentiment.csv

# Or via alias (after sourcing scripts/aliases.zsh)
make_label_set "$POSTS_CSV" "$REPLIES_CSV" data/labeled_sentiment.csv 1000
```

Then fine-tune:

```zsh
# Ensure the venv exists (run any ./run_scraper.sh command once), then:
./.venv/bin/python -m src.train_sentiment \
  --train-csv data/labeled_sentiment.csv \
  --text-col message \
  --label-col label \
  --model-name distilbert-base-uncased \
  --output-dir models/sentiment-distilbert \
  --epochs 3 --batch-size 16
```

Use it in analyze:

```zsh
./run_scraper.sh analyze -i data/messages.csv --replies-csv data/replies.csv \
  --sentiment-backend transformers \
  --transformers-model models/sentiment-distilbert
```

Export details (labels, probabilities) into CSVs:

```zsh
./run_scraper.sh analyze -i data/messages.csv --replies-csv data/replies.csv \
  --sentiment-backend transformers \
  --transformers-model models/sentiment-distilbert \
  --export-transformers-details \
  --write-augmented-csv --write-combined-csv
```

Notes:
- The analyzer maps model class probabilities to a VADER-like compound score in [-1, 1] for compatibility with the rest of the report.
- If the model has id2label including 'neg','neu','pos' labels, the mapping is more accurate; otherwise it defaults to pos - neg.
- GPU/Apple Silicon (MPS) will be used automatically if available.

Torch install note (macOS):
- `requirements.txt` uses conditional pins: `torch==2.3.1` for Python < 3.13 and `torch>=2.7.1` for Python ≥ 3.13. This keeps installs smooth on macOS. If you hit install issues, let us know.

## Evaluate a fine-tuned model

```zsh
./.venv/bin/python -m src.eval_sentiment \
  --csv data/labeled_holdout.csv \
  --text-col message \
  --label-col label \
  --model models/sentiment-distilbert
```
Prints accuracy, macro-precision/recall/F1, and a classification report.

## Fixtures (Premier League schedule via football-data.org)

Fetch fixtures between dates:
```zsh
./run_scraper.sh fixtures \
  --start-date 2025-08-15 \
  --end-date 2025-10-15 \
  -o data/fixtures.csv
```

Notes:
- Requires `FOOTBALL_DATA_API_TOKEN` in `.env`.
- Output may be `.csv` or `.json` (by extension).

### All valid forms (fixtures)

- Base variables:
  - SD = start date YYYY-MM-DD
  - ED = end date YYYY-MM-DD
  - OUT = output .csv or .json

Form:
  ./run_scraper.sh fixtures --start-date SD --end-date ED -o OUT

---

## Advanced recipes

Parallel replies + forwards with separate sessions:
```zsh
# Terminal 1 – replies
./run_scraper.sh replies \
  -c https://t.me/SourceChannel \
  --from-csv data/messages.csv \
  -o data/replies.csv \
  --min-replies 1 \
  --concurrency 15 \
  --resume \
  --append \
  --session-name "$HOME/.local/share/telethon_sessions/telegram_replies"

# Terminal 2 – forwards
./run_scraper.sh forwards \
  -c https://t.me/SourceChannel \
  --from-csv data/messages.csv \
  -o data/forwards.csv \
  --scan-limit 20000 \
  --concurrency 10 \
  --chunk-size 1500 \
  --session-name "$HOME/.local/share/telethon_sessions/telegram_forwards"
```

Tuning for rate limits:
- If `[rate-limit]` logs are frequent, reduce `--concurrency` (start -3 to -5) and keep `--chunk-size` around 1000–2000.
- For replies, prioritize with `--min-replies 1` to avoid parents with zero replies.

Safety:
- Use `--append` with replies and `--resume` to avoid truncating and to dedupe.
- Forwards and scrape don’t dedupe; prefer writing to a new file or dedupe after.

---

## Environment setup quick-start

Create `.env` (script will prompt if missing):
```
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
# Optional defaults
TELEGRAM_SESSION_NAME=telegram
TELEGRAM_2FA_PASSWORD=your_2fa_password
FOOTBALL_DATA_API_TOKEN=your_token
```

First run will prompt for phone and code (and 2FA if enabled).

---

## Troubleshooting

- Empty replies file
  - Ensure `-c` matches the channel in your posts CSV URLs.
  - Use `--append` so the file isn’t truncated before writing.
- “database is locked”
  - Use unique `--session-name` per parallel process; store sessions outside iCloud Drive.
- Forwards empty
  - Same-channel forwards are rare. This tool only finds self-forwards (not cross-channel).
- Analyze errors
  - Ensure CSVs have expected columns. Posts: `id,date,message,...`; Replies: `parent_id,id,date,message,...`.
- Exit code 1 when starting
  - Check the last log lines. Common causes: missing TELEGRAM_API_ID/HASH in `.env`, wrong channel handle vs CSV URLs, session file locked by another process (use distinct `--session-name`), or a bad output path.

---

## Quick aliases for daily runs (zsh) ⚡

Paste this section into your current shell or your `~/.zshrc` to get convenient Make-like commands.

### Project defaults (edit as needed)

```zsh
# Channel and files
export CH="https://t.me/Premier_League_Update"
export POSTS_CSV="data/premier_league_update.csv"
export REPLIES_CSV="data/premier_league_replies.csv"
export FORWARDS_CSV="data/premier_league_forwards.csv"
export TAGS_CFG="config/tags.yaml"
export FIXTURES_CSV="data/premier_league_schedule_2025-08-15_to_2025-10-15.csv"

# Sessions directory outside iCloud (avoid sqlite locks)
export SESSION_DIR="$HOME/.local/share/telethon_sessions"
mkdir -p "$SESSION_DIR"
```

### Aliases (zsh functions)

```zsh
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
    --write-combined-csv
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
    --emoji-mode "$mode" \
    --emoji-boost
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
```

### Usage

```zsh
# Use project defaults
fast_replies
chunked_forwards
analyze_combined

# Override on the fly (channel, files, or tuning)
fast_replies "https://t.me/AnotherChannel" data/other_posts.csv data/other_replies.csv 12
chunked_forwards "$CH" "$POSTS_CSV" data/alt_forwards.csv 30000 12 2000
analyze_combined data/other_posts.csv data/other_replies.csv "$TAGS_CFG" "$FIXTURES_CSV" "$CH"
```
