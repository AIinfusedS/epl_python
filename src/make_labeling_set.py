import argparse
import os
import pandas as pd


def load_messages(csv_path: str, text_col: str = 'message', extra_cols=None) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    if text_col not in df.columns:
        return pd.DataFrame()
    cols = ['id', text_col, 'date']
    if extra_cols:
        for c in extra_cols:
            if c in df.columns:
                cols.append(c)
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.rename(columns={text_col: 'message'}, inplace=True)
    return out


def main():
    parser = argparse.ArgumentParser(description='Create a labeling CSV from posts and/or replies.')
    parser.add_argument('--posts-csv', required=False, help='Posts CSV path (e.g., data/..._update.csv)')
    parser.add_argument('--replies-csv', required=False, help='Replies CSV path')
    parser.add_argument('-o', '--output', default='data/labeled_sentiment.csv', help='Output CSV for labeling')
    parser.add_argument('--sample-size', type=int, default=1000, help='Total rows to include (after combining)')
    parser.add_argument('--min-length', type=int, default=3, help='Minimum message length to include')
    parser.add_argument('--shuffle', action='store_true', help='Shuffle before sampling (default true)')
    parser.add_argument('--no-shuffle', dest='shuffle', action='store_false')
    parser.set_defaults(shuffle=True)
    args = parser.parse_args()

    frames = []
    if args.posts_csv:
        frames.append(load_messages(args.posts_csv))
    if args.replies_csv:
        # For replies, include parent_id if present
        r = load_messages(args.replies_csv, extra_cols=['parent_id'])
        frames.append(r)
    if not frames:
        raise SystemExit('No input CSVs provided. Use --posts-csv and/or --replies-csv.')

    df = pd.concat(frames, ignore_index=True)
    # Basic filtering: non-empty text, min length, drop duplicates by message text
    df['message'] = df['message'].fillna('').astype(str)
    df = df[df['message'].str.len() >= args.min_length]
    df = df.drop_duplicates(subset=['message']).reset_index(drop=True)

    if args.shuffle:
        df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    if args.sample_size and len(df) > args.sample_size:
        df = df.head(args.sample_size)

    # Add blank label column for human annotation
    df.insert(1, 'label', '')

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"Wrote labeling CSV with {len(df)} rows to {args.output}")


if __name__ == '__main__':
    main()
