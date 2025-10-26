import argparse
import os
import pandas as pd


def read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise SystemExit(f"CSV not found: {path}")
    return pd.read_csv(path)


def main():
    p = argparse.ArgumentParser(description='Apply labeled sentiments to posts/replies CSVs for analysis plots.')
    p.add_argument('--labeled-csv', required=True, help='Path to labeled_sentiment.csv (must include id and label columns)')
    p.add_argument('--posts-csv', required=True, help='Original posts CSV')
    p.add_argument('--replies-csv', required=True, help='Original replies CSV')
    p.add_argument('--posts-out', default=None, help='Output posts CSV path (default: <posts> with _with_labels suffix)')
    p.add_argument('--replies-out', default=None, help='Output replies CSV path (default: <replies> with _with_labels suffix)')
    args = p.parse_args()

    labeled = read_csv(args.labeled_csv)
    if 'id' not in labeled.columns:
        raise SystemExit('labeled CSV must include an id column to merge on')
    # normalize label column name to sentiment_label
    lab_col = 'label' if 'label' in labeled.columns else ('sentiment_label' if 'sentiment_label' in labeled.columns else None)
    if lab_col is None:
        raise SystemExit("labeled CSV must include a 'label' or 'sentiment_label' column")
    labeled = labeled[['id', lab_col] + (['confidence'] if 'confidence' in labeled.columns else [])].copy()
    labeled = labeled.rename(columns={lab_col: 'sentiment_label'})

    posts = read_csv(args.posts_csv)
    replies = read_csv(args.replies_csv)

    if 'id' not in posts.columns or 'id' not in replies.columns:
        raise SystemExit('posts/replies CSVs must include id columns')

    posts_out = args.posts_out or os.path.splitext(args.posts_csv)[0] + '_with_labels.csv'
    replies_out = args.replies_out or os.path.splitext(args.replies_csv)[0] + '_with_labels.csv'

    posts_merged = posts.merge(labeled, how='left', on='id', validate='m:1')
    replies_merged = replies.merge(labeled, how='left', on='id', validate='m:1')

    posts_merged.to_csv(posts_out, index=False)
    replies_merged.to_csv(replies_out, index=False)
    print(f"Wrote posts with labels -> {posts_out} (rows={len(posts_merged)})")
    print(f"Wrote replies with labels -> {replies_out} (rows={len(replies_merged)})")


if __name__ == '__main__':
    main()
