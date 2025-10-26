"""
analyze_csv
============

Generates a Markdown report and optional plots from a Telegram posts CSV (and an optional replies CSV).

Features
--------
- Tagging from YAML keywords (config/tags.yaml)
- Sentiment via VADER (default), a local transformers model, or a local GPT (Ollama)
- Emoji-aware preprocessing with optional positivity/negativity boost
- Optional fixtures join to mark matchdays; compact team abbreviation labels inside daily charts
- Combined posts+replies augmented outputs and a merged CSV

Key CLI flags
-------------
- --sentiment-backend vader|transformers|gpt
- --transformers-model NAME_OR_PATH
- --gpt-model NAME --gpt-base-url URL --gpt-batch-size K
- --emoji-mode keep|demojize|strip [--emoji-boost]
- --plot-width-scale FLOAT --plot-max-width INCHES --plot-height INCHES
- --activity-top-n N
- --labels-max-per-day N --labels-per-line N --labels-stagger-rows N --labels-band-y FLOAT --labels-annotate-mode ticks|all|ticks+top

Plots (when --save-plots)
-------------------------
- posts_heatmap_hour_dow.png
- sentiment_by_tag_posts.png
- daily_activity_stacked.png
- daily_volume_and_sentiment.png (bars: volume; lines: positive% and negative%)
- matchday_sentiment_overall.png
- matchday_posts_volume_vs_sentiment.png
"""

import argparse
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import yaml
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import emoji as _emoji


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize columns we expect from the scraper
    # Columns: id,date,message,sender_id,views,forwards,replies,url
    # Parse date to datetime (naive)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
    for col in ['views', 'forwards', 'replies', 'sender_id']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    # Basic cleaning
    if 'message' in df.columns:
        df['message'] = df['message'].fillna('')
    return df


def summarize(df: pd.DataFrame) -> dict:
    total = len(df)
    with_text = int((df.get('message', pd.Series(dtype=str)) != '').sum()) if 'message' in df else 0
    no_text = total - with_text
    views_mean = float(df['views'].mean()) if 'views' in df and not df['views'].empty else 0.0
    views_median = float(df['views'].median()) if 'views' in df and not df['views'].empty else 0.0
    forwards_mean = float(df['forwards'].mean()) if 'forwards' in df and not df['forwards'].empty else 0.0
    replies_mean = float(df['replies'].mean()) if 'replies' in df and not df['replies'].empty else 0.0

    first_date = df['date'].min() if 'date' in df else None
    last_date = df['date'].max() if 'date' in df else None

    return {
        'total_messages': total,
        'with_text': with_text,
        'no_text': no_text,
        'views_mean': views_mean,
        'views_median': views_median,
        'forwards_mean': forwards_mean,
        'replies_mean': replies_mean,
        'first_date': first_date,
        'last_date': last_date,
    }


def top_messages(df: pd.DataFrame, by: str, k: int = 10) -> pd.DataFrame:
    if by not in df.columns:
        return pd.DataFrame()
    return df.sort_values(by=by, ascending=False).head(k)[['id', 'date', 'message', by, 'url']]


def temporal_distributions(df: pd.DataFrame) -> dict:
    if 'date' not in df:
        return {}
    out = {}
    d = df.dropna(subset=['date']).copy()
    d['day'] = d['date'].dt.date
    d['hour'] = d['date'].dt.hour
    out['per_day'] = d.groupby('day').size().reset_index(name='count')
    out['per_hour'] = d.groupby('hour').size().reset_index(name='count')
    return out


def write_markdown_report(
    df: pd.DataFrame,
    out_path: str,
    channel: Optional[str] = None,
    replies_df: Optional[pd.DataFrame] = None,
):
    summ = summarize(df)
    tops_views = top_messages(df, 'views', 10)
    tops_forwards = top_messages(df, 'forwards', 10)
    tops_replies = top_messages(df, 'replies', 10)
    temps = temporal_distributions(df)

    lines = []
    title = f"Telegram Channel Report{f' - {channel}' if channel else ''}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total messages: {summ['total_messages']}")
    lines.append(f"- With text: {summ['with_text']}")
    lines.append(f"- Without text: {summ['no_text']}")
    lines.append(f"- Views (mean/median): {summ['views_mean']:.1f} / {summ['views_median']:.1f}")
    lines.append(f"- Forwards (mean): {summ['forwards_mean']:.2f}")
    lines.append(f"- Replies (mean): {summ['replies_mean']:.2f}")
    if summ['first_date'] is not None and summ['last_date'] is not None:
        lines.append(f"- Date range: {summ['first_date']} — {summ['last_date']}")

    # Sentiment summary if available
    if 'sentiment_compound' in df.columns:
        lines.append("\n### Sentiment summary")
        sent = df['sentiment_compound'].dropna()
        if not sent.empty:
            lines.append(f"- Mean compound: {sent.mean():.3f}")
            lines.append(f"- Median compound: {sent.median():.3f}")
            pos_share = (sent > 0.05).mean()
            neg_share = (sent < -0.05).mean()
            neu_share = max(0.0, 1.0 - pos_share - neg_share)
            lines.append(f"- Share positive (compound > 0.05): {pos_share:.2%}")
            lines.append(f"- Share neutral  (|compound| ≤ 0.05): {neu_share:.2%}")
            lines.append(f"- Share negative (compound < -0.05): {neg_share:.2%}")

    def table(df_small: pd.DataFrame, caption: str) -> None:
        if df_small is None or df_small.empty:
            lines.append(f"\n### {caption}\n\n_No data_\n")
            return
        lines.append(f"\n### {caption}\n")
        # Limit message preview to first 120 chars
        df_disp = df_small.copy()
        if 'message' in df_disp.columns:
            df_disp['message'] = df_disp['message'].astype(str).str.replace("\n", " ").str.slice(0, 120)
        lines.append(df_disp.to_markdown(index=False))

    table(tops_views, "Top 10 posts by views")
    table(tops_forwards, "Top 10 posts by forwards")
    table(tops_replies, "Top 10 posts by replies (channel field)")

    # If we computed scraped reply counts, include that ranking
    if 'replies_count_scraped' in df.columns:
        cols = ['id', 'date', 'message', 'replies_count_scraped']
        if 'replies_top_tags' in df.columns:
            cols.append('replies_top_tags')
        if 'url' in df.columns:
            cols.append('url')
        top_scraped = df.sort_values('replies_count_scraped', ascending=False).head(10)[cols]
        lines.append("\n### Top 10 posts by scraped reply count")
        df_disp = top_scraped.copy()
        if 'message' in df_disp.columns:
            df_disp['message'] = df_disp['message'].astype(str).str.replace("\n", " ").str.slice(0, 120)
        lines.append(df_disp.to_markdown(index=False))

    # Temporal distributions
    if temps:
        lines.append("\n## Temporal distribution")
        if 'per_day' in temps and not temps['per_day'].empty:
            lines.append("\n### Messages per day")
            lines.append(temps['per_day'].to_markdown(index=False))
        if 'per_hour' in temps and not temps['per_hour'].empty:
            lines.append("\n### Messages per hour (0-23)")
            lines.append(temps['per_hour'].to_markdown(index=False))

    # Per-tag engagement (if tags exist)
    if 'tags' in df.columns:
        tagged = df.copy()
        # Normalize tags column to list
        tagged['tags'] = tagged['tags'].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) else [x]))
        exploded = tagged.explode('tags')
        exploded = exploded[exploded['tags'].notna() & (exploded['tags'] != '')]
        if not exploded.empty:
            grp = (
                exploded.groupby('tags')
                .agg(
                    count=('id', 'count'),
                    views_mean=('views', 'mean'),
                    views_median=('views', 'median'),
                    replies_mean=('replies', 'mean'),
                    forwards_mean=('forwards', 'mean'),
                    sentiment_mean=('sentiment_compound', 'mean') if 'sentiment_compound' in exploded.columns else ('id','count')
                )
                .reset_index()
                .sort_values(['count', 'views_mean'], ascending=[False, False])
            )
            lines.append("\n## Per-tag engagement")
            lines.append(grp.to_markdown(index=False))

            # Per-tag sentiment breakdown for posts
            if 'sentiment_compound' in exploded.columns:
                s = exploded[['tags', 'sentiment_compound']].dropna()
                if not s.empty:
                    s['is_pos'] = s['sentiment_compound'] > 0.05
                    s['is_neg'] = s['sentiment_compound'] < -0.05
                    sgrp = (
                        s.groupby('tags')
                        .agg(
                            n=('sentiment_compound', 'count'),
                            mean=('sentiment_compound', 'mean'),
                            median=('sentiment_compound', 'median'),
                            pos_share=('is_pos', 'mean'),
                            neg_share=('is_neg', 'mean'),
                        )
                        .reset_index()
                        .sort_values(['n', 'mean'], ascending=[False, False])
                    )
                    # Derive neutral share as residual
                    sgrp['neu_share'] = (1 - sgrp['pos_share'] - sgrp['neg_share']).clip(lower=0)
                    # Reorder columns for readability
                    cols = ['tags', 'n', 'mean', 'median', 'pos_share', 'neu_share', 'neg_share']
                    sgrp = sgrp[[c for c in cols if c in sgrp.columns]]
                    lines.append("\n### Per-tag sentiment (posts)")
                    lines.append(sgrp.to_markdown(index=False))

    # Replies per-tag summary (if provided and tagged)
    if replies_df is not None and 'tags' in replies_df.columns:
        rtagged = replies_df.copy()
        rtagged['tags'] = rtagged['tags'].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) else [x]))
        rexpl = rtagged.explode('tags')
        rexpl = rexpl[rexpl['tags'].notna() & (rexpl['tags'] != '')]
        if not rexpl.empty:
            rgrp = (
                rexpl.groupby('tags')
                .agg(
                    replies_count=('id', 'count'),
                    replies_sentiment_mean=('sentiment_compound', 'mean') if 'sentiment_compound' in rexpl.columns else ('id','count'),
                )
                .reset_index()
                .sort_values(['replies_count'], ascending=[False])
            )
            lines.append("\n## Replies per-tag summary")
            lines.append(rgrp.to_markdown(index=False))

            # Per-tag sentiment breakdown for replies
            if 'sentiment_compound' in rexpl.columns:
                rs = rexpl[['tags', 'sentiment_compound']].dropna()
                if not rs.empty:
                    rs['is_pos'] = rs['sentiment_compound'] > 0.05
                    rs['is_neg'] = rs['sentiment_compound'] < -0.05
                    rsgrp = (
                        rs.groupby('tags')
                        .agg(
                            n=('sentiment_compound', 'count'),
                            mean=('sentiment_compound', 'mean'),
                            median=('sentiment_compound', 'median'),
                            pos_share=('is_pos', 'mean'),
                            neg_share=('is_neg', 'mean'),
                        )
                        .reset_index()
                        .sort_values(['n', 'mean'], ascending=[False, False])
                    )
                    rsgrp['neu_share'] = (1 - rsgrp['pos_share'] - rsgrp['neg_share']).clip(lower=0)
                    cols = ['tags', 'n', 'mean', 'median', 'pos_share', 'neu_share', 'neg_share']
                    rsgrp = rsgrp[[c for c in cols if c in rsgrp.columns]]
                    lines.append("\n### Per-tag sentiment (replies)")
                    lines.append(rsgrp.to_markdown(index=False))

    # Combined sentiment (posts + replies) if replies are provided
    if 'sentiment_compound' in df.columns and replies_df is not None and 'sentiment_compound' in replies_df.columns:
        combined_cols = ['sentiment_compound']
        if 'tags' in df.columns or ('tags' in replies_df.columns):
            combined_cols.append('tags')
        posts_part = df[['sentiment_compound'] + (['tags'] if 'tags' in df.columns else [])].copy()
        posts_part['content_type'] = 'post'
        reps_part = replies_df[['sentiment_compound'] + (['tags'] if 'tags' in replies_df.columns else [])].copy()
        reps_part['content_type'] = 'reply'
        combined = pd.concat([posts_part, reps_part], ignore_index=True)

        lines.append("\n## Combined sentiment (posts + replies)")
        sent_all = combined['sentiment_compound'].dropna()
        if not sent_all.empty:
            lines.append(f"- Mean compound: {sent_all.mean():.3f}")
            lines.append(f"- Median compound: {sent_all.median():.3f}")
            pos_share = (sent_all > 0.05).mean()
            neg_share = (sent_all < -0.05).mean()
            neu_share = max(0.0, 1.0 - pos_share - neg_share)
            lines.append(f"- Share positive (compound > 0.05): {pos_share:.2%}")
            lines.append(f"- Share neutral  (|compound| ≤ 0.05): {neu_share:.2%}")
            lines.append(f"- Share negative (compound < -0.05): {neg_share:.2%}")

        # Per-tag combined sentiment if tags exist
        if 'tags' in combined.columns:
            ctag = combined.copy()
            ctag['tags'] = ctag['tags'].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) else [x]))
            cexpl = ctag.explode('tags')
            cexpl = cexpl[cexpl['tags'].notna() & (cexpl['tags'] != '')]
            if not cexpl.empty:
                cexpl['is_pos'] = cexpl['sentiment_compound'] > 0.05
                cexpl['is_neg'] = cexpl['sentiment_compound'] < -0.05
                cgrp = (
                    cexpl.groupby('tags')
                    .agg(
                        n=('sentiment_compound', 'count'),
                        mean=('sentiment_compound', 'mean'),
                        median=('sentiment_compound', 'median'),
                        pos_share=('is_pos', 'mean'),
                        neg_share=('is_neg', 'mean'),
                    )
                    .reset_index()
                    .sort_values(['n', 'mean'], ascending=[False, False])
                )
                cgrp['neu_share'] = (1 - cgrp['pos_share'] - cgrp['neg_share']).clip(lower=0)
                cols = ['tags', 'n', 'mean', 'median', 'pos_share', 'neu_share', 'neg_share']
                cgrp = cgrp[[c for c in cols if c in cgrp.columns]]
                lines.append("\n### Per-tag sentiment (combined posts + replies)")
                lines.append(cgrp.to_markdown(index=False))

    # Matchday cross-analysis: on vs off matchdays for posts and replies
    def _matchday_table(d: pd.DataFrame, col: str = 'is_matchday') -> Optional[pd.DataFrame]:
        if d is None or d.empty or col not in d.columns:
            return None
        t = d.copy()
        t = t.dropna(subset=[col])
        if t.empty:
            return None
        # Sentiment shares if sentiment available
        has_sent = 'sentiment_compound' in t.columns and t['sentiment_compound'].notna().any()
        if has_sent:
            t['is_pos'] = t['sentiment_compound'] > 0.05
            t['is_neg'] = t['sentiment_compound'] < -0.05
        agg = {
            'id': 'count'
        }
        if has_sent:
            agg.update({
                'sentiment_compound': 'mean',
                'is_pos': 'mean',
                'is_neg': 'mean',
            })
        g = t.groupby(col).agg(agg).rename(columns={'id': 'count'})
        if has_sent:
            g = g.rename(columns={'sentiment_compound': 'sentiment_mean', 'is_pos': 'pos_share', 'is_neg': 'neg_share'})
            g['neu_share'] = (1 - g['pos_share'] - g['neg_share']).clip(lower=0)
            # Reorder
            g = g[['count', 'sentiment_mean', 'pos_share', 'neu_share', 'neg_share']]
        return g.reset_index()

    posts_md_tbl = _matchday_table(df)
    replies_md_tbl_parent = _matchday_table(replies_df, col='parent_is_matchday') if (replies_df is not None and 'parent_is_matchday' in replies_df.columns) else None
    replies_md_tbl_reply = _matchday_table(replies_df, col='is_matchday') if (replies_df is not None and 'is_matchday' in replies_df.columns) else None
    if posts_md_tbl is not None or replies_md_tbl_parent is not None or replies_md_tbl_reply is not None:
        lines.append("\n## Matchday cross-analysis")
        if posts_md_tbl is not None:
            lines.append("\n### Posts: on vs off matchdays")
            lines.append(posts_md_tbl.to_markdown(index=False))
            # If per-post replies are available, show engagement breakdown
            if 'replies_count_scraped' in df.columns:
                tmp = df.copy()
                tmp['replies_count_scraped'] = pd.to_numeric(tmp['replies_count_scraped'], errors='coerce').fillna(0)
                eng = (
                    tmp.groupby('is_matchday')
                    .agg(
                        posts=('id','count'),
                        posts_with_replies=('replies_count_scraped', lambda s: (s>0).mean()),
                        replies_total=('replies_count_scraped','sum'),
                        replies_mean_per_post=('replies_count_scraped','mean'),
                        replies_median_per_post=('replies_count_scraped','median'),
                    )
                    .reset_index()
                )
                lines.append("\n### Posts engagement vs matchday (replies per post)")
                lines.append(eng.to_markdown(index=False))
        if replies_md_tbl_parent is not None:
            lines.append("\n### Replies (by parent matchday): on vs off matchdays")
            lines.append(replies_md_tbl_parent.to_markdown(index=False))
        if replies_md_tbl_reply is not None:
            lines.append("\n### Replies (by reply date): on vs off matchdays")
            lines.append(replies_md_tbl_reply.to_markdown(index=False))

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Analyze Telegram CSV and generate a Markdown report")
    parser.add_argument('csv', help='Path to CSV file exported by the scraper')
    parser.add_argument('-o', '--output', default=None, help='Output Markdown path (default: alongside CSV with .md)')
    parser.add_argument('--channel', default=None, help='Optional channel name for the report title')
    parser.add_argument('--tags-config', default=None, help='Path to YAML config for keyword tags (e.g., config/tags.yaml)')
    parser.add_argument('--replies-csv', default=None, help='Optional CSV of replies with parent_id and sentiment_compound to aggregate per message')
    parser.add_argument('--fixtures-csv', default=None, help='Optional fixtures CSV to derive a matchday flag (matches on date)')
    parser.add_argument('--write-augmented-csv', action='store_true', help='Also write a CSV with computed fields (sentiment, tags) alongside the input')
    parser.add_argument('--write-combined-csv', action='store_true', help='If replies are provided, also write a merged posts+replies CSV with a content_type column')
    parser.add_argument('--save-plots', action='store_true', help='Also save common plots (daily sentiment, posts heatmap, sentiment-by-tag) next to the report')
    parser.add_argument('--emoji-mode', choices=['keep', 'demojize', 'strip'], default='keep', help='How to treat emojis before sentiment: keep (default), demojize to :keywords:, or strip emojis')
    parser.add_argument('--emoji-boost', action='store_true', help='If set with keep/demojize, gently boost VADER for clearly positive/negative emojis')
    parser.add_argument('--sentiment-backend', choices=['vader', 'transformers', 'gpt'], default='vader', help='Choose sentiment engine: vader (default), transformers, or gpt (local via Ollama)')
    parser.add_argument('--transformers-model', default='distilbert-base-uncased', help='HF model name or local path for transformers backend')
    parser.add_argument('--export-transformers-details', action='store_true', help='When using transformers backend, also export predicted label and raw class probabilities')
    # GPT local model knobs (Ollama)
    parser.add_argument('--gpt-model', default='llama3', help='Local GPT model name (Ollama)')
    parser.add_argument('--gpt-base-url', default='http://localhost:11434', help='Base URL for local GPT server (Ollama)')
    parser.add_argument('--gpt-batch-size', type=int, default=8, help='Batch size for GPT requests')
    # Plot sizing controls
    parser.add_argument('--plot-width-scale', type=float, default=0.8,
                        help='Scale factor (inches per day) for dynamic plot width of daily activity chart. Default doubled from 0.4 to 0.8.')
    parser.add_argument('--plot-max-width', type=float, default=104.0,
                        help='Maximum figure width (inches) clamp for daily activity chart. Default doubled from 52 to 104. Override to a larger value if needed.')
    parser.add_argument('--plot-height', type=float, default=6.5,
                        help='Figure height (inches) for bar charts. Default 6.5 inches (taller than previous 5).')
    parser.add_argument('--activity-top-n', type=int, default=5,
                        help='Number of top-activity days to highlight and annotate. Use 0 to disable highlighting.')
    # Match label rendering controls
    parser.add_argument('--labels-max-per-day', type=int, default=3,
                        help='Maximum number of match labels to show per day before collapsing into +N more.')
    parser.add_argument('--labels-per-line', type=int, default=2,
                        help='Number of match labels per line when stacking within the label band.')
    parser.add_argument('--labels-band-y', type=float, default=0.96,
                        help='Vertical position of the labels band in axes coordinates (inside the axes; 1.0 is top).')
    parser.add_argument('--labels-stagger-rows', type=int, default=2,
                        help='Number of staggered rows in the label band to reduce neighbor collisions (1-3 recommended).')
    parser.add_argument('--labels-annotate-mode', choices=['ticks','all','ticks+top'], default='ticks+top',
                        help='Which days to annotate with match labels: only ticked days, all days, or ticked days plus top-N highlighted days (default).')
    args = parser.parse_args()

    df = load_csv(args.csv)
    replies_df: Optional[pd.DataFrame] = None

    # Optional tagging step
    if args.tags_config and os.path.exists(args.tags_config):
        with open(args.tags_config, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}

        # Compile patterns list: List[(tag, List[(pattern, is_regex)])]
        patterns: List[Tuple[str, List[Tuple[str, bool]]]] = []
        for tag, arr in (cfg.items() if isinstance(cfg, dict) else []):
            compiled: List[Tuple[str, bool]] = []
            for pat in (arr or []):
                if isinstance(pat, str) and pat.startswith('re:'):
                    compiled.append((pat[3:], True))
                else:
                    compiled.append((str(pat), False))
            patterns.append((tag, compiled))

        def tag_message(text: str) -> List[str]:
            t = text or ''
            tags: List[str] = []
            for tag, pats in patterns:
                for pat, is_re in pats:
                    if is_re:
                        if re.search(pat, t, flags=re.IGNORECASE):
                            tags.append(tag)
                            break
                    else:
                        if pat.lower() in t.lower():
                            tags.append(tag)
                            break
            return tags

        if 'message' in df.columns:
            df['tags'] = df['message'].apply(tag_message)

        # If replies CSV provided, apply tags to replies as well
        if args.replies_csv and os.path.exists(args.replies_csv):
            replies_df = pd.read_csv(args.replies_csv)
            if 'message' in replies_df.columns:
                replies_df['message'] = replies_df['message'].fillna('')
                replies_df['tags'] = replies_df['message'].apply(tag_message)

    # Sentiment scoring
    analyzer = SentimentIntensityAnalyzer()
    tmodel = None
    gpt = None
    if args.sentiment_backend == 'transformers':
        try:
            from .transformer_sentiment import TransformerSentiment
            tmodel = TransformerSentiment(args.transformers_model)
            print(f"[transformers] Using model: {args.transformers_model} on {tmodel.device}")
        except Exception as e:
            print(f"[transformers] Falling back to VADER due to error: {e}")
            args.sentiment_backend = 'vader'
    elif args.sentiment_backend == 'gpt':
        try:
            from .gpt_sentiment import GPTSentiment
        except Exception:
            from gpt_sentiment import GPTSentiment
        try:
            gpt = GPTSentiment(base_url=args.gpt_base_url, model=args.gpt_model)
            # Light connectivity probe: do a tiny call that should fail gracefully without raising here
            print(f"[gpt] Using local GPT model: {args.gpt_model} at {args.gpt_base_url}")
        except Exception as e:
            print(f"[gpt] Falling back to VADER (init error): {e}")
            args.sentiment_backend = 'vader'

    def _strip_emojis(text: str) -> str:
        # Remove all emoji code points
        return _emoji.replace_emoji(text or '', replace='')

    def _demojize(text: str) -> str:
        return _emoji.demojize(text or '', delimiters=(":", ":"))

    # Simple emoji valence hints for boosting
    POS_EMOJI_HINTS = {"😀", "😃", "😄", "😁", "😆", "😊", "🙂", "😍", "🥳", "👍", "🔥", "👏", "💯", "😺", "🤩", "🙌", "🫶", "⚽️", "🏆"}
    NEG_EMOJI_HINTS = {"😞", "😟", "😠", "😡", "😢", "😭", "👎", "💔", "🤬", "🤢", "😫", "😩"}

    def _emoji_valence_boost(text: str, base: float) -> float:
        if not args.emoji_boost:
            return base
        # Look at original text to preserve emoji presence regardless of preprocessing
        pos_hits = any(ch in POS_EMOJI_HINTS for ch in text)
        neg_hits = any(ch in NEG_EMOJI_HINTS for ch in text)
        boost = 0.0
        if pos_hits and not neg_hits:
            boost = 0.05
        elif neg_hits and not pos_hits:
            boost = -0.05
        # Clamp to VADER range [-1, 1]
        return max(-1.0, min(1.0, base + boost))

    def _prep_for_sentiment(text: str) -> str:
        if args.emoji_mode == 'strip':
            return _strip_emojis(text or '')
        if args.emoji_mode == 'demojize':
            return _demojize(text or '')
        return text or ''

    if 'message' in df.columns:
        def _score_msg(t: str) -> float:
            raw = t or ''
            if args.sentiment_backend == 'transformers' and tmodel is not None:
                # Use transformer model in batches later
                return None  # placeholder, fill after batch
            if args.sentiment_backend == 'gpt' and gpt is not None:
                return None
            proc = _prep_for_sentiment(raw)
            score = analyzer.polarity_scores(proc).get('compound')
            return _emoji_valence_boost(raw, score)
        df['sentiment_compound'] = df['message'].apply(_score_msg)
    # Ensure replies have sentiment if present and missing
    if replies_df is not None:
        if 'message' in replies_df.columns and 'sentiment_compound' not in replies_df.columns:
            def _score_rep(t: str) -> float:
                raw = t or ''
                if args.sentiment_backend == 'transformers' and tmodel is not None:
                    return None
                if args.sentiment_backend == 'gpt' and gpt is not None:
                    return None
                proc = _prep_for_sentiment(raw)
                score = analyzer.polarity_scores(proc).get('compound')
                return _emoji_valence_boost(raw, score)
            replies_df['sentiment_compound'] = replies_df['message'].apply(_score_rep)

    # If transformers backend was selected, fill in sentiment_compound in batches
    if args.sentiment_backend == 'transformers' and tmodel is not None:
        if 'message' in df.columns:
            mask = df['sentiment_compound'].isna()
            texts = df.loc[mask, 'message'].astype(str).tolist()
            if texts:
                preds = tmodel.predict_compound_batch(texts, batch_size=32)
                df.loc[mask, 'sentiment_compound'] = preds
                if args.export_transformers_details:
                    # Re-run to get probabilities and labels
                    from .transformer_sentiment import TransformerSentiment
                    probs, labels = tmodel.predict_probs_and_labels(texts, batch_size=32)
                    df.loc[mask, 'sentiment_label'] = labels
                    df.loc[mask, 'sentiment_probs'] = [','.join(f"{p:.6f}" for p in row) for row in probs]
        if replies_df is not None and 'message' in replies_df.columns and 'sentiment_compound' in replies_df.columns:
            rmask = replies_df['sentiment_compound'].isna()
            rtexts = replies_df.loc[rmask, 'message'].astype(str).tolist()
            if rtexts:
                rpreds = tmodel.predict_compound_batch(rtexts, batch_size=64)
                replies_df.loc[rmask, 'sentiment_compound'] = rpreds
                if args.export_transformers_details:
                    probs, labels = tmodel.predict_probs_and_labels(rtexts, batch_size=64)
                    replies_df.loc[rmask, 'sentiment_label'] = labels
                    replies_df.loc[rmask, 'sentiment_probs'] = [','.join(f"{p:.6f}" for p in row) for row in probs]
    elif args.sentiment_backend == 'gpt' and gpt is not None:
        def _vader_compounds_for(texts: List[str]) -> List[float]:
            out_vals: List[float] = []
            for raw in texts:
                proc = _prep_for_sentiment(raw)
                sc = analyzer.polarity_scores(proc).get('compound')
                out_vals.append(_emoji_valence_boost(raw, sc))
            return out_vals
        # Fill posts sentiment via local GPT
        if 'message' in df.columns:
            mask = df['sentiment_compound'].isna()
            texts = df.loc[mask, 'message'].astype(str).tolist()
            if texts:
                try:
                    preds = gpt.predict_compound_batch(texts, batch_size=int(getattr(args, 'gpt_batch_size', 8)))
                    df.loc[mask, 'sentiment_compound'] = preds
                except Exception as e:
                    print(f"[gpt] Prediction error; falling back to VADER for remaining rows: {e}")
                    preds = _vader_compounds_for(texts)
                    df.loc[mask, 'sentiment_compound'] = preds
        if replies_df is not None and 'message' in replies_df.columns and 'sentiment_compound' in replies_df.columns:
            rmask = replies_df['sentiment_compound'].isna()
            rtexts = replies_df.loc[rmask, 'message'].astype(str).tolist()
            if rtexts:
                try:
                    rpreds = gpt.predict_compound_batch(rtexts, batch_size=int(getattr(args, 'gpt_batch_size', 8)))
                    replies_df.loc[rmask, 'sentiment_compound'] = rpreds
                except Exception as e:
                    print(f"[gpt] Replies prediction error; falling back to VADER for remaining rows: {e}")
                    rpreds = _vader_compounds_for(rtexts)
                    replies_df.loc[rmask, 'sentiment_compound'] = rpreds

    # Optional: aggregate replies sentiment per parent and join
    if replies_df is not None and 'parent_id' in replies_df.columns and 'sentiment_compound' in replies_df.columns:
        agg = replies_df.groupby('parent_id')['sentiment_compound'].mean().reset_index().rename(columns={'sentiment_compound':'replies_sentiment_mean'})
        if 'id' in df.columns:
            df = df.merge(agg, how='left', left_on='id', right_on='parent_id').drop(columns=['parent_id'])

    # Optional: matchday flag by joining on date with fixtures (same day) for posts and replies
    fixtures_present = bool(args.fixtures_csv and os.path.exists(args.fixtures_csv))
    matchdays = None
    fixtures_by_day = None  # map: date -> ["Home vs Away" or "Home X-Y Away"]
    if fixtures_present:
        fix = pd.read_csv(args.fixtures_csv)
        if 'utcDate' in fix.columns:
            fix['utcDate'] = pd.to_datetime(fix['utcDate'], errors='coerce')
            fix['match_day'] = fix['utcDate'].dt.date
            matchdays = fix[['match_day']].dropna().drop_duplicates()
            # Build per-day match labels
            try:
                # Map full club names to standard PL 3-letter abbreviations
                PL_ABBR = {
                    'arsenal': 'ARS',
                    'astonvilla': 'AVL',
                    'bournemouth': 'BOU',
                    'brentford': 'BRE',
                    'brightonandhovealbion': 'BHA',
                    'chelsea': 'CHE',
                    'crystalpalace': 'CRY',
                    'everton': 'EVE',
                    'fulham': 'FUL',
                    'ipswichtown': 'IPS',
                    'leicestercity': 'LEI',
                    'liverpool': 'LIV',
                    'manchestercity': 'MCI',
                    'manchesterunited': 'MUN',
                    'newcastleunited': 'NEW',
                    'nottinghamforest': 'NFO',
                    'southampton': 'SOU',
                    'tottenhamhotspur': 'TOT',
                    'westhamunited': 'WHU',
                    'wolverhamptonwanderers': 'WOL',
                }

                def _canon_team_key(name: str) -> str:
                    s = str(name or '')
                    s = s.lower().replace('&', 'and')
                    # keep letters and spaces only
                    import re as _re
                    s = ''.join(ch if ch.isalpha() or ch.isspace() else ' ' for ch in s)
                    # collapse whitespace
                    s = ' '.join(s.split())
                    # remove standalone fc/afc tokens
                    tokens = [t for t in s.split(' ') if t not in ('fc', 'afc')]
                    return ''.join(tokens)

                def _abbr_team(name: str) -> str:
                    key = _canon_team_key(name)
                    if key in PL_ABBR:
                        return PL_ABBR[key]
                    # Fallback: build a 3-letter code from initials or first letters
                    import re as _re
                    toks = _re.findall(r"[A-Za-z]+", str(name or ''))
                    toks = [t for t in toks if t.lower() not in ('fc', 'afc')]
                    if toks:
                        initials = ''.join(t[0] for t in toks).upper()
                        if len(initials) >= 3:
                            return initials[:3]
                        joined = ''.join(toks).upper()
                        return (joined + 'XXX')[:3]
                    return str(name or '')[:3].upper()
                cols = [c for c in ['match_day','homeTeam','awayTeam','homeScore','awayScore'] if c in fix.columns]
                lab_df = fix[cols].dropna(subset=['match_day']).copy()
                def _mk_label(row):
                    # Only team abbreviations, no scores
                    ht = _abbr_team(row.get('homeTeam', ''))
                    at = _abbr_team(row.get('awayTeam', ''))
                    # Use a short separator to keep labels compact
                    return f"{ht}–{at}"
                lab_df['label'] = lab_df.apply(_mk_label, axis=1)
                fixtures_by_day = lab_df.groupby('match_day')['label'].apply(list).to_dict()
            except Exception:
                fixtures_by_day = None
    if matchdays is not None:
        if 'date' in df.columns:
            df['post_day'] = pd.to_datetime(df['date'], errors='coerce').dt.date
            df = df.merge(matchdays, how='left', left_on='post_day', right_on='match_day')
            df['is_matchday'] = df['match_day'].notna()
            df = df.drop(columns=['match_day', 'post_day'])
        if replies_df is not None and 'date' in replies_df.columns:
            replies_df['reply_day'] = pd.to_datetime(replies_df['date'], errors='coerce').dt.date
            replies_df = replies_df.merge(matchdays, how='left', left_on='reply_day', right_on='match_day')
            replies_df['is_matchday'] = replies_df['match_day'].notna()
            replies_df = replies_df.drop(columns=['match_day', 'reply_day'])
            # Also derive parent-based matchday classification for replies if possible
            if 'parent_id' in replies_df.columns and 'id' in df.columns and 'is_matchday' in df.columns:
                parent_map = df[['id', 'is_matchday']].rename(columns={'id': 'parent_id', 'is_matchday': 'parent_is_matchday'})
                replies_df = replies_df.merge(parent_map, how='left', on='parent_id')
        # Diagnostics
        try:
            posts_md = int(df['is_matchday'].sum()) if 'is_matchday' in df.columns else 0
            replies_md = int(replies_df['is_matchday'].sum()) if (replies_df is not None and 'is_matchday' in replies_df.columns) else 0
            parent_md = int(replies_df['parent_is_matchday'].sum()) if (replies_df is not None and 'parent_is_matchday' in replies_df.columns) else 0
            print(f"[fixtures] Matchday join: posts matchday rows={posts_md}; replies by reply-date matchday rows={replies_md}; replies by parent matchday rows={parent_md}")
        except Exception:
            pass

    # Per-parent reply tag rollup: replies_count_scraped and replies_top_tags
    if replies_df is not None and 'parent_id' in replies_df.columns:
        # Replies count per parent
        rcount = replies_df.groupby('parent_id').agg(replies_count_scraped=('id', 'count')).reset_index()
        if 'id' in df.columns:
            df = df.merge(rcount, how='left', left_on='id', right_on='parent_id').drop(columns=['parent_id'])
        # Top tags per parent (if tagged)
        if 'tags' in replies_df.columns:
            rtagged = replies_df.copy()
            rtagged['tags'] = rtagged['tags'].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) else [x]))
            rexpl = rtagged.explode('tags')
            rexpl = rexpl[rexpl['tags'].notna() & (rexpl['tags'] != '')]
            if not rexpl.empty:
                tag_counts = rexpl.groupby(['parent_id', 'tags']).size().reset_index(name='count')
                # Build top-3 tag string per parent
                def top3(group: pd.DataFrame) -> str:
                    g = group.sort_values('count', ascending=False).head(3)
                    return '|'.join(f"{row['tags']}({int(row['count'])})" for _, row in g.iterrows())
                top_tags = tag_counts.groupby('parent_id').apply(top3).reset_index(name='replies_top_tags')
                if 'id' in df.columns:
                    df = df.merge(top_tags, how='left', left_on='id', right_on='parent_id').drop(columns=['parent_id'])

    out = args.output
    if out is None:
        base, _ = os.path.splitext(args.csv)
        out = base + '_report.md'
    write_markdown_report(df, out_path=out, channel=args.channel, replies_df=replies_df)
    print(f"Report written to {out}")

    if args.write_augmented_csv:
        base, ext = os.path.splitext(args.csv)
        aug = base + '_tagged.csv'
        # Serialize tags list to a semicolon-separated string for CSV
        if 'tags' in df.columns:
            df_out = df.copy()
            df_out['tags'] = df_out['tags'].apply(lambda xs: ';'.join(xs) if isinstance(xs, list) else '')
        else:
            df_out = df
        df_out.to_csv(aug, index=False)
        print(f"Augmented CSV written to {aug}")

        # Also write a tagged replies CSV if provided
        if replies_df is not None:
            rbase, rext = os.path.splitext(args.replies_csv)
            raug = rbase + '_tagged.csv'
            r_out = replies_df.copy()
            if 'tags' in r_out.columns:
                r_out['tags'] = r_out['tags'].apply(lambda xs: ';'.join(xs) if isinstance(xs, list) else '')
            r_out.to_csv(raug, index=False)
            print(f"Replies augmented CSV written to {raug}")

    # Optional: write combined posts+replies CSV
    if args.write_combined_csv and replies_df is not None:
        # Normalize posts columns
        p = df.copy()
        p['content_type'] = 'post'
        # Ensure shared sentiment/tags columns exist
        if 'sentiment_compound' not in p.columns and 'message' in p.columns:
            analyzer = SentimentIntensityAnalyzer()
            p['sentiment_compound'] = p['message'].apply(lambda t: analyzer.polarity_scores(t or '').get('compound'))
        # Harmonize tag serialization to list before final serialization
        if 'tags' in p.columns:
            p_tags = p['tags']
        else:
            p['tags'] = [[] for _ in range(len(p))]

        # Normalize replies columns
        r = replies_df.copy()
        r['content_type'] = 'reply'
        # For replies, the post id is parent_id; ensure a common column 'parent_id' exists
        if 'parent_id' not in r.columns and 'id' in r.columns:
            r['parent_id'] = None

        # Select a union of reasonable columns
        sel_cols = []
        for c in ['content_type', 'id', 'parent_id', 'date', 'message', 'sender_id', 'views', 'forwards', 'replies', 'sentiment_compound', 'sentiment_label', 'sentiment_probs', 'url', 'tags', 'is_matchday', 'parent_is_matchday']:
            if c in p.columns or c in r.columns:
                sel_cols.append(c)
        p_sel = p.reindex(columns=sel_cols)
        r_sel = r.reindex(columns=sel_cols)

        combined_df = pd.concat([p_sel, r_sel], ignore_index=True)
        # Serialize tags for CSV
        if 'tags' in combined_df.columns:
            combined_df['tags'] = combined_df['tags'].apply(lambda xs: ';'.join(xs) if isinstance(xs, list) else ('' if pd.isna(xs) else str(xs)))

        base, _ = os.path.splitext(args.csv)
        comb_path = base + '_combined.csv'
        combined_df.to_csv(comb_path, index=False)
        print(f"Combined posts+replies CSV written to {comb_path}")

    # Optional: save plots
    if args.save_plots:
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
        except Exception as e:
            print(f"[plots] Skipping plots; matplotlib/seaborn not available: {e}")
        else:
            out_dir = os.path.dirname(out) or "."

            # Removed: Daily average sentiment (combined posts + replies)

            # 2) Posts heatmap by day-of-week and hour
            try:
                if 'date' in df.columns and not df.empty:
                    t = df.dropna(subset=['date']).copy()
                    if not t.empty:
                        t['date'] = pd.to_datetime(t['date'], errors='coerce')
                        t = t.dropna(subset=['date'])
                        if not t.empty:
                            t['dow'] = t['date'].dt.day_name()
                            t['hour'] = t['date'].dt.hour
                            pivot = t.pivot_table(index='dow', columns='hour', values='id', aggfunc='count').fillna(0)
                            order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
                            pivot = pivot.reindex(order)
                            plt.figure(figsize=(10,5))
                            sns.heatmap(pivot, cmap='Blues')
                            plt.title('Posts heatmap by day-of-week and hour')
                            plt.xlabel('Hour'); plt.ylabel('Day of week')
                            plt.tight_layout()
                            plt.savefig(os.path.join(out_dir, 'posts_heatmap_hour_dow.png'), dpi=150)
                            plt.close()
                            print(f"[plots] Saved {os.path.join(out_dir, 'posts_heatmap_hour_dow.png')}")
            except Exception as e:
                print(f"[plots] Failed posts heatmap: {e}")

            # 3) Sentiment shares by tag (posts) stacked bars
            try:
                if 'tags' in df.columns and ('sentiment_compound' in df.columns or 'sentiment_label' in df.columns):
                    p = df.copy()
                    p['tags'] = p['tags'].apply(lambda s: s if isinstance(s, list) else ([] if pd.isna(s) else [s]))
                    e = p.explode('tags')
                    # Keep rows with a tag and either a sentiment label or compound value
                    e = e[(e['tags'].notna()) & (e['tags']!='')]
                    if 'sentiment_label' in e.columns:
                        e = e[e['sentiment_label'].notna()]
                    else:
                        e = e[e['sentiment_compound'].notna()]
                    # Filter to team tags only (those starting with 'club_')
                    e = e[e['tags'].astype(str).str.startswith('club_')]
                    if not e.empty:
                        if 'sentiment_label' in e.columns:
                            # Use model-predicted labels when available
                            lab = e['sentiment_label'].astype(str).str.lower()
                            e['pos'] = lab.str.contains('pos|positive').astype(int)
                            e['neg'] = lab.str.contains('neg|negative').astype(int)
                            e['neu'] = (~(e['pos'].astype(bool) | e['neg'].astype(bool))).astype(int)
                        else:
                            # Fallback to compound thresholds
                            e['pos'] = (e['sentiment_compound'] > 0.05).astype(int)
                            e['neg'] = (e['sentiment_compound'] < -0.05).astype(int)
                            e['neu'] = 1 - e['pos'] - e['neg']
                        # Group by team tag and compute average shares, include all teams (no top-N cap)
                        g = e.groupby('tags')[['pos','neu','neg']].mean().sort_values('pos', ascending=False)
                        # Dynamic width based on number of teams; reuse plot flags
                        n_teams = len(g.index)
                        fig_w = max(16, min(float(args.plot_max_width), float(args.plot_width_scale) * n_teams))
                        try:
                            print(f"[plots] sentiment_by_tag_posts: teams={n_teams}, width_in={fig_w:.2f}, scale={float(args.plot_width_scale):.2f}, max={float(args.plot_max_width):.2f}")
                        except Exception:
                            pass
                        fig, ax = plt.subplots(figsize=(fig_w, float(args.plot_height)))
                        g[['pos','neu','neg']].plot(kind='bar', stacked=True, color=['#2ca02c','#aaaaaa','#d62728'], ax=ax)
                        ax.set_title('Sentiment shares by team (posts)')
                        ax.set_ylabel('Share')
                        # Improve label readability for many teams
                        for label in ax.get_xticklabels():
                            label.set_rotation(45)
                            label.set_ha('right')
                        plt.tight_layout()
                        plt.savefig(os.path.join(out_dir, 'sentiment_by_tag_posts.png'), dpi=150)
                        plt.close()
                        print(f"[plots] Saved {os.path.join(out_dir, 'sentiment_by_tag_posts.png')}")
            except Exception as e:
                print(f"[plots] Failed sentiment-by-tag plot: {e}")

            # Removed: Replies daily average sentiment plot

            # 5) Combined activity: stacked counts by content_type per day
            try:
                if 'date' in df.columns:
                    posts_activity = df[['id','date']].dropna().copy()
                    posts_activity['date'] = pd.to_datetime(posts_activity['date'], errors='coerce')
                    posts_activity = posts_activity.dropna(subset=['date'])
                    posts_activity['day'] = posts_activity['date'].dt.date
                    posts_activity['content_type'] = 'post'
                    combined_act = posts_activity
                    if replies_df is not None and 'date' in replies_df.columns:
                        replies_activity = replies_df[['id','date']].dropna().copy()
                        replies_activity['date'] = pd.to_datetime(replies_activity['date'], errors='coerce')
                        replies_activity = replies_activity.dropna(subset=['date'])
                        replies_activity['day'] = replies_activity['date'].dt.date
                        replies_activity['content_type'] = 'reply'
                        combined_act = pd.concat([posts_activity, replies_activity], ignore_index=True)
                    if not combined_act.empty:
                        pv = combined_act.pivot_table(index='day', columns='content_type', values='id', aggfunc='count').fillna(0)
                        totals = pv.sum(axis=1)
                        num_days = len(pv.index)
                        # Determine top-N days to highlight (0 disables)
                        req_top_n = int(args.activity_top_n) if hasattr(args, 'activity_top_n') else 5
                        top_n = max(0, min(num_days, req_top_n))
                        top_days = list(totals.nlargest(top_n).index) if top_n > 0 else []
                        # Improve readability for long ranges: scale width and thin x-ticks
                        # Reuse num_days defined above
                        # Make the figure wider for better x-axis readability using CLI-tunable params.
                        # Dynamic width scaled by the number of days, clamped to [16, plot_max_width].
                        fig_w = max(16, min(float(args.plot_max_width), float(args.plot_width_scale) * num_days))
                        # Debug print to help users verify width computation
                        try:
                            print(f"[plots] daily_activity_stacked: days={num_days}, width_in={fig_w:.2f}, scale={float(args.plot_width_scale):.2f}, max={float(args.plot_max_width):.2f}")
                        except Exception:
                            pass
                        fig, ax = plt.subplots(figsize=(fig_w, float(args.plot_height)))
                        pv.plot(kind='bar', stacked=True, color={'post':'#9467bd','reply':'#8c564b'}, ax=ax)
                        ax.set_title('Daily activity (posts vs replies)')
                        ax.set_xlabel('Day'); ax.set_ylabel('Count')
                        labels_in_band = False
                        show_pos = None
                        show_pos_set = set()
                        # Thin tick labels to ~12 evenly spaced labels for large ranges
                        try:
                            import numpy as _np
                            # Base tick positions (0..num_days-1) and labels
                            base_idx = list(range(num_days))
                            # Positions of top days
                            highlight_pos = [pv.index.get_loc(d) for d in top_days]
                            if num_days > 20:
                                desired = 12
                                step = max(1, int(_np.ceil(num_days / desired)))
                                show_pos = list(range(0, num_days, step))
                                # Ensure highlight positions are included
                                show_pos = sorted(set(show_pos + highlight_pos))
                                ax.set_xticks(show_pos)
                                labels_all = [f"{d} ({d.strftime('%a')})" if hasattr(d, 'strftime') else str(d) for d in pv.index]
                                show_labels = [labels_all[i] for i in show_pos]
                                ax.set_xticklabels(show_labels, rotation=45, ha='right')
                                show_pos_set = set(show_pos)
                            else:
                                # Set all labels with day names
                                labels = [f"{d} ({d.strftime('%a')})" if hasattr(d, 'strftime') else str(d) for d in pv.index]
                                ax.set_xticks(base_idx)
                                ax.set_xticklabels(labels)
                                for label in ax.get_xticklabels():
                                    label.set_rotation(45)
                                    label.set_ha('right')
                                show_pos = base_idx
                                show_pos_set = set(base_idx)
                            # Color highlighted tick labels and annotate totals
                            # After setting ticks/labels, get back the positions we set
                            current_ticks = ax.get_xticks()
                            tick_to_pos = {i: i for i in current_ticks}
                            # Map current tick order to positions for styling
                            for tick_label, xpos in zip(ax.get_xticklabels(), current_ticks):
                                pos_int = int(round(xpos))
                                if pos_int in highlight_pos:
                                    tick_label.set_color('crimson')
                                    tick_label.set_fontweight('bold')
                                    # Annotate total above the stacked bar
                                    y = float(totals.iloc[pos_int])
                                    # Compute breakdown for this day
                                    try:
                                        p_val = float(pv.iloc[pos_int]['post']) if 'post' in pv.columns else 0.0
                                    except Exception:
                                        p_val = 0.0
                                    try:
                                        r_val = float(pv.iloc[pos_int]['reply']) if 'reply' in pv.columns else 0.0
                                    except Exception:
                                        r_val = 0.0
                                    lbl = f"{int(y)} ({int(p_val)}+{int(r_val)})"
                                    ax.text(pos_int, y, lbl, color='crimson', fontsize=8, fontweight='bold', ha='center', va='bottom')
                        except Exception:
                            pass
                        # If fixtures are available, annotate games per day above bars
                        try:
                            if fixtures_by_day is not None and len(fixtures_by_day) > 0:
                                # Reserve a fixed band above the bars for match labels (axes coordinates)
                                from matplotlib import transforms as _mtrans
                                # Diagnostics: see how many pivot days have fixtures
                                try:
                                    keys = list(fixtures_by_day.keys())
                                    matched_days = sum(1 for d in pv.index if d in fixtures_by_day)
                                    print(f"[plots] fixtures days={len(keys)}; pivot days={len(pv.index)}; matched days={matched_days}")
                                except Exception:
                                    pass
                                annotated_days = 0
                                # Fixed band just above the axes (y in axes coords)
                                trans_xdata_yaxes = ax.get_xaxis_transform()
                                y_band = float(getattr(args, 'labels_band_y', 0.96))
                                rows = max(1, int(getattr(args, 'labels_stagger_rows', 2)))
                                rows = min(rows, 4)
                                offset_step = 0.055  # vertical offset between stagger rows (in axes coords)
                                # Write a small debug CSV of expected labels
                                try:
                                    dbg_path = os.path.join(out_dir, 'match_labels_debug.csv')
                                    _rows = []
                                    for d, labs in fixtures_by_day.items():
                                        _rows.append({'day': str(d), 'labels': ' | '.join(str(x) for x in labs)})
                                    pd.DataFrame(_rows).to_csv(dbg_path, index=False)
                                    print(f"[plots] wrote {dbg_path} with {len(_rows)} days")
                                except Exception:
                                    pass
                                # Determine which positions to annotate based on mode
                                mode = getattr(args, 'labels_annotate_mode', 'ticks+top')
                                pos_all = set(range(num_days))
                                pos_ticks = set(show_pos or [])
                                pos_top = set(highlight_pos)
                                if mode == 'all':
                                    annotate_positions = pos_all
                                elif mode == 'ticks':
                                    annotate_positions = pos_ticks
                                else:  # ticks+top (default)
                                    annotate_positions = pos_ticks | pos_top

                                max_per_day = max(1, int(getattr(args, 'labels_max_per_day', 3)))
                                per_line = max(1, int(getattr(args, 'labels_per_line', 2)))

                                def _chunk(xs, n):
                                    return [xs[i:i+n] for i in range(0, len(xs), n)]

                                for i, day in enumerate(pv.index):
                                    if i not in annotate_positions:
                                        continue
                                    labels = fixtures_by_day.get(day)
                                    if not labels:
                                        continue
                                    labs_all = [str(x) for x in labels]
                                    if len(labs_all) > max_per_day:
                                        extra = len(labs_all) - max_per_day
                                        labs = labs_all[:max_per_day] + [f"+{extra} more"]
                                    else:
                                        labs = labs_all
                                    # Build multi-line text: per_line entries per row
                                    lines = [' • '.join(chunk) for chunk in _chunk(labs, per_line)]
                                    text = '\n'.join(lines)
                                    # Stagger vertically by index to reduce neighbor collisions
                                    row_id = i % rows
                                    # Stagger downward inside the axes, away from the title
                                    y = y_band - (row_id * offset_step)
                                    # Keep within the axes area
                                    y = max(0.02, min(0.98, y))
                                    # Center above the bar; small bbox for readability
                                    ax.text(i, y, text,
                                            fontsize=7, ha='center', va='bottom', rotation=0,
                                            clip_on=False, zorder=5, color='forestgreen', transform=trans_xdata_yaxes,
                                            bbox=dict(facecolor='white', edgecolor='none', alpha=0.6, pad=1.5))
                                    annotated_days += 1
                                if annotated_days > 0:
                                    # Leave extra headroom above axes for the label band
                                    try:
                                        labels_in_band = True
                                        # Add y-margin so tallest bars don't collide with labels
                                        base_margin = 0.10
                                        extra = (rows - 1) * 0.03
                                        ax.margins(y=min(0.30, base_margin + extra))
                                        print(f"[plots] match labels annotated (inside band): days={annotated_days}; mode={mode}; max/day={max_per_day}; per_line={per_line}; rows={rows}; y_band={y_band:.2f}")
                                    except Exception:
                                        pass
                        except Exception as e:
                            print(f"[plots] match labels annotation skipped: {e}")
                        # First tighten layout, then reserve top margin if label band is used
                        plt.tight_layout()
                        try:
                            # If labels are placed inside (y_band < 1), no need to push the title
                            pass
                        except Exception:
                            pass
                        plt.savefig(os.path.join(out_dir, 'daily_activity_stacked.png'), dpi=150)
                        plt.close()
                        print(f"[plots] Saved {os.path.join(out_dir, 'daily_activity_stacked.png')}")
            except Exception as e:
                print(f"[plots] Failed daily activity stacked: {e}")

            # 5b) Daily volume (posts+replies) with positive/negative sentiment shares (twin y-axes)
            try:
                if 'date' in df.columns:
                    # Build per-day combined data with sentiment flags
                    parts = []
                    # Posts
                    p = df[['id','date']].copy()
                    p['date'] = pd.to_datetime(p['date'], errors='coerce')
                    p = p.dropna(subset=['date'])
                    if not p.empty:
                        if 'sentiment_label' in df.columns and df['sentiment_label'].notna().any():
                            lab = df.loc[p.index, 'sentiment_label'].astype(str).str.lower()
                            p['is_pos'] = lab.str.contains('pos|positive', regex=True, na=False)
                            p['is_neg'] = lab.str.contains('neg|negative', regex=True, na=False)
                        else:
                            # Fallback to compound thresholds
                            if 'sentiment_compound' in df.columns:
                                sc = pd.to_numeric(df.loc[p.index, 'sentiment_compound'], errors='coerce')
                                p['is_pos'] = sc > 0.05
                                p['is_neg'] = sc < -0.05
                            else:
                                p['is_pos'] = False
                                p['is_neg'] = False
                        p['day'] = p['date'].dt.date
                        parts.append(p[['day','is_pos','is_neg']])
                    # Replies
                    if replies_df is not None and 'date' in replies_df.columns:
                        r = replies_df[['id','date']].copy()
                        r['date'] = pd.to_datetime(r['date'], errors='coerce')
                        r = r.dropna(subset=['date'])
                        if not r.empty:
                            if 'sentiment_label' in replies_df.columns and replies_df['sentiment_label'].notna().any():
                                lab = replies_df.loc[r.index, 'sentiment_label'].astype(str).str.lower()
                                r['is_pos'] = lab.str.contains('pos|positive', regex=True, na=False)
                                r['is_neg'] = lab.str.contains('neg|negative', regex=True, na=False)
                            else:
                                if 'sentiment_compound' in replies_df.columns:
                                    sc = pd.to_numeric(replies_df.loc[r.index, 'sentiment_compound'], errors='coerce')
                                    r['is_pos'] = sc > 0.05
                                    r['is_neg'] = sc < -0.05
                                else:
                                    r['is_pos'] = False
                                    r['is_neg'] = False
                            r['day'] = r['date'].dt.date
                            parts.append(r[['day','is_pos','is_neg']])
                    if parts:
                        all_rows = pd.concat(parts, ignore_index=True)
                        grp = (
                            all_rows.groupby('day')
                            .agg(
                                volume_total=('is_pos','count'),
                                pos_share=('is_pos','mean'),
                                neg_share=('is_neg','mean')
                            )
                            .sort_index()
                        )
                        if not grp.empty:
                            num_days = len(grp.index)
                            fig_w = max(16, min(float(args.plot_max_width), float(args.plot_width_scale) * num_days))
                            import matplotlib.pyplot as _plt
                            from matplotlib.ticker import PercentFormatter as _PercentFormatter
                            try:
                                print(f"[plots] daily_volume_and_sentiment: days={num_days}, width_in={fig_w:.2f}")
                            except Exception:
                                pass
                            fig, ax1 = _plt.subplots(figsize=(fig_w, float(args.plot_height)))
                            x = range(num_days)
                            # Bars: total volume (posts+replies)
                            ax1.bar(x, grp['volume_total'], color='#6baed6', alpha=0.8, label='Volume (posts+replies)')
                            ax1.set_xlabel('Day')
                            ax1.set_ylabel('Volume', color='#335')
                            ax1.tick_params(axis='y', labelcolor='#335')
                            # Format x-ticks with dates
                            xticklabels = [f"{d} ({d.strftime('%a')})" if hasattr(d, 'strftime') else str(d) for d in grp.index]
                            ax1.set_xticks(list(x))
                            ax1.set_xticklabels(xticklabels, rotation=45, ha='right')
                            # Lines: positive and negative sentiment shares
                            ax2 = ax1.twinx()
                            ax2.plot(x, grp['pos_share'].fillna(0), color='#2ca02c', marker='o', linewidth=1.5, label='Positive %')
                            ax2.plot(x, grp['neg_share'].fillna(0), color='#d62728', marker='o', linewidth=1.5, label='Negative %')
                            ax2.set_ylim(0, 1)
                            ax2.yaxis.set_major_formatter(_PercentFormatter(xmax=1.0))
                            ax2.set_ylabel('Sentiment share', color='#333')
                            ax2.tick_params(axis='y', labelcolor='#333')
                            # Build a combined legend
                            lines1, labels1 = ax1.get_legend_handles_labels()
                            lines2, labels2 = ax2.get_legend_handles_labels()
                            ax2.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
                            _plt.title('Daily volume vs positive/negative sentiment')
                            _plt.tight_layout()
                            outp = os.path.join(out_dir, 'daily_volume_and_sentiment.png')
                            _plt.savefig(outp, dpi=150)
                            _plt.close()
                            print(f"[plots] Saved {outp}")
            except Exception as e:
                print(f"[plots] Failed daily volume and sentiment plot: {e}")

            # 6) Tag co-occurrence heatmap (posts, top 15 tags)
            try:
                if 'tags' in df.columns:
                    # Prepare list of tag lists per message
                    tags_series = df['tags'].apply(lambda s: s if isinstance(s, list) else ([] if pd.isna(s) else [s]))
                    # Frequency of tags
                    from collections import Counter
                    freq = Counter()
                    for ts in tags_series:
                        freq.update(set([t for t in ts if t]))
                    # Removed: tag co-occurrence heatmap
            except Exception as e:
                print(f"[plots] Failed tag co-occurrence heatmap: {e}")

            # Removed: matchday boxplots (posts and replies)

            # 7) Overall matchday sentiment (posts and replies)
            try:
                if fixtures_present and 'date' in df.columns:
                    # Prepare posts per-day sentiment
                    pd_posts = df.copy()
                    pd_posts['date'] = pd.to_datetime(pd_posts['date'], errors='coerce')
                    pd_posts = pd_posts.dropna(subset=['date'])
                    if not pd_posts.empty and 'sentiment_compound' in pd_posts.columns:
                        pd_posts['day'] = pd_posts['date'].dt.date
                        g_posts = pd_posts.groupby('day').agg(
                            posts_n=('id','count'),
                            posts_mean=('sentiment_compound','mean')
                        )
                        # Optional label-based shares
                        if 'sentiment_label' in pd_posts.columns:
                            lab = pd_posts[['day','sentiment_label']].dropna()
                            lab_s = lab['sentiment_label'].astype(str).str.lower()
                            lab['pos'] = lab_s.str.contains('pos|positive')
                            lab['neg'] = lab_s.str.contains('neg|negative')
                            s_posts = lab.groupby('day').agg(posts_pos_share=('pos','mean'), posts_neg_share=('neg','mean'))
                            g_posts = g_posts.join(s_posts, how='left')
                    else:
                        g_posts = None

                    # Prepare replies per-day sentiment if available
                    g_replies = None
                    if replies_df is not None and 'date' in replies_df.columns and 'sentiment_compound' in replies_df.columns:
                        pd_rep = replies_df.copy()
                        pd_rep['date'] = pd.to_datetime(pd_rep['date'], errors='coerce')
                        pd_rep = pd_rep.dropna(subset=['date'])
                        if not pd_rep.empty:
                            pd_rep['day'] = pd_rep['date'].dt.date
                            g_replies = pd_rep.groupby('day').agg(
                                replies_n=('id','count'),
                                replies_mean=('sentiment_compound','mean')
                            )
                            if 'sentiment_label' in pd_rep.columns:
                                lab = pd_rep[['day','sentiment_label']].dropna()
                                lab_s = lab['sentiment_label'].astype(str).str.lower()
                                lab['pos'] = lab_s.str.contains('pos|positive')
                                lab['neg'] = lab_s.str.contains('neg|negative')
                                s_rep = lab.groupby('day').agg(replies_pos_share=('pos','mean'), replies_neg_share=('neg','mean'))
                                g_replies = g_replies.join(s_rep, how='left')

                    # Build fixtures day index
                    fix_days = None
                    try:
                        # re-use 'fix' if available; else build from fixtures_by_day keys
                        if 'fix' in locals() and isinstance(fix, pd.DataFrame) and 'utcDate' in fix.columns:
                            ftmp = fix.copy()
                            ftmp['utcDate'] = pd.to_datetime(ftmp['utcDate'], errors='coerce')
                            fix_days = ftmp.dropna(subset=['utcDate'])['utcDate'].dt.date.drop_duplicates().sort_values()
                        elif fixtures_by_day is not None:
                            fix_days = pd.Series(sorted(list(fixtures_by_day.keys())))
                    except Exception:
                        pass

                    if fix_days is not None:
                        # Join per-day aggregates on fixture days only
                        idx = pd.Index(fix_days, name='day')
                        agg = pd.DataFrame(index=idx)
                        if g_posts is not None:
                            agg = agg.join(g_posts, how='left')
                        if g_replies is not None:
                            agg = agg.join(g_replies, how='left')
                        out_csv = os.path.join(out_dir, 'matchday_sentiment_overall.csv')
                        agg.reset_index().to_csv(out_csv, index=False)
                        print(f"[plots] Wrote {out_csv}")

                        # Plot time series of mean compound for posts/replies on match days
                        import matplotlib.pyplot as plt
                        plt.figure(figsize=(max(12, len(idx)*0.3), 4))
                        if 'posts_mean' in agg.columns:
                            plt.plot(range(len(idx)), agg['posts_mean'], marker='o', label='Posts mean')
                        if 'replies_mean' in agg.columns:
                            plt.plot(range(len(idx)), agg['replies_mean'], marker='o', label='Replies mean')
                        plt.axhline(0.0, color='#888', linestyle='--', linewidth=1)
                        plt.xticks(range(len(idx)), [str(d) for d in idx], rotation=45, ha='right')
                        plt.ylabel('Compound sentiment (mean)')
                        plt.title('Matchday sentiment (overall)')
                        plt.legend()
                        plt.tight_layout()
                        path = os.path.join(out_dir, 'matchday_sentiment_overall.png')
                        plt.savefig(path, dpi=150); plt.close()
                        print(f"[plots] Saved {path}")

                        # Scatter: posts_n vs posts_mean on matchdays
                        if 'posts_n' in agg.columns and 'posts_mean' in agg.columns:
                            plt.figure(figsize=(5,4))
                            plt.scatter(agg['posts_n'].fillna(0), agg['posts_mean'].fillna(0), alpha=0.7, color='#1f77b4')
                            plt.xlabel('Posts count (matchday)')
                            plt.ylabel('Mean compound (posts)')
                            plt.title('Posts volume vs sentiment on matchdays')
                            plt.tight_layout()
                            sp = os.path.join(out_dir, 'matchday_posts_volume_vs_sentiment.png')
                            plt.savefig(sp, dpi=150); plt.close()
                            print(f"[plots] Saved {sp}")
            except Exception as e:
                print(f"[plots] Failed matchday sentiment overall: {e}")


if __name__ == '__main__':
    main()
