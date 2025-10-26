import argparse
import os
from typing import List

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


def parse_tags_column(series: pd.Series) -> pd.Series:
    def _to_list(x):
        if isinstance(x, list):
            return x
        if pd.isna(x):
            return []
        s = str(x)
        # Expect semicolon-delimited from augmented CSV, but also accept comma
        if ';' in s:
            return [t.strip() for t in s.split(';') if t.strip()]
        if ',' in s:
            return [t.strip() for t in s.split(',') if t.strip()]
        return [s] if s else []
    return series.apply(_to_list)


def main():
    parser = argparse.ArgumentParser(description='Audit sentiment per team tag and export samples for inspection.')
    parser.add_argument('--csv', default='data/premier_league_update_tagged.csv', help='Tagged posts CSV (augmented by analyze)')
    parser.add_argument('--team', default='club_manchester_united', help='Team tag to export samples for (e.g., club_manchester_united)')
    parser.add_argument('--out-dir', default='data', help='Directory to write audit outputs')
    parser.add_argument('--samples', type=int, default=25, help='Number of samples to export for the specified team')
    parser.add_argument('--with-vader', action='store_true', help='Also compute VADER-based sentiment shares as a sanity check')
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit(f"CSV not found: {args.csv}. Run analyze with --write-augmented-csv first.")

    df = pd.read_csv(args.csv)
    if 'message' not in df.columns:
        raise SystemExit('CSV missing message column')
    if 'sentiment_compound' not in df.columns:
        raise SystemExit('CSV missing sentiment_compound column')
    if 'tags' not in df.columns:
        raise SystemExit('CSV missing tags column')

    df = df.copy()
    df['tags'] = parse_tags_column(df['tags'])
    # Filter to team tags (prefix club_)
    e = df.explode('tags')
    e = e[e['tags'].notna() & (e['tags'] != '')]
    e = e[e['tags'].astype(str).str.startswith('club_')]
    e = e.dropna(subset=['sentiment_compound'])
    if e.empty:
        print('No team-tagged rows found.')
        return

    # Shares
    e = e.copy()
    e['is_pos'] = e['sentiment_compound'] > 0.05
    e['is_neg'] = e['sentiment_compound'] < -0.05
    grp = (
        e.groupby('tags')
        .agg(
            n=('sentiment_compound', 'count'),
            mean=('sentiment_compound', 'mean'),
            median=('sentiment_compound', 'median'),
            pos_share=('is_pos', 'mean'),
            neg_share=('is_neg', 'mean'),
        )
        .reset_index()
    )
    grp['neu_share'] = (1 - grp['pos_share'] - grp['neg_share']).clip(lower=0)
    grp = grp.sort_values(['n', 'mean'], ascending=[False, False])

    if args.with_vader:
        # Compute VADER shares on the underlying messages per team
        analyzer = SentimentIntensityAnalyzer()
        def _vader_sentiment_share(sub: pd.DataFrame):
            if sub.empty:
                return pd.Series({'pos_share_vader': 0.0, 'neg_share_vader': 0.0, 'neu_share_vader': 0.0})
            scores = sub['message'].astype(str).apply(lambda t: analyzer.polarity_scores(t or '')['compound'])
            pos = (scores > 0.05).mean()
            neg = (scores < -0.05).mean()
            neu = max(0.0, 1.0 - pos - neg)
            return pd.Series({'pos_share_vader': pos, 'neg_share_vader': neg, 'neu_share_vader': neu})
        vader_grp = e.groupby('tags').apply(_vader_sentiment_share).reset_index()
        grp = grp.merge(vader_grp, on='tags', how='left')

    os.makedirs(args.out_dir, exist_ok=True)
    out_summary = os.path.join(args.out_dir, 'team_sentiment_audit.csv')
    grp.to_csv(out_summary, index=False)
    print(f"Wrote summary: {out_summary}")

    # Export samples for selected team
    te = e[e['tags'] == args.team].copy()
    if te.empty:
        print(f"No rows for team tag: {args.team}")
        return
    # Sort by sentiment descending to inspect highly positive claims
    te = te.sort_values('sentiment_compound', ascending=False)
    cols = [c for c in ['id', 'date', 'message', 'sentiment_compound', 'url'] if c in te.columns]
    samples_path = os.path.join(args.out_dir, f"{args.team}_samples.csv")
    te[cols].head(args.samples).to_csv(samples_path, index=False)
    print(f"Wrote samples: {samples_path} ({min(args.samples, len(te))} rows)")


if __name__ == '__main__':
    main()
