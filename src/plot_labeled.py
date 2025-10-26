import argparse
import os
from typing import Optional

import pandas as pd


def safe_read(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise SystemExit(f"Input labeled CSV not found: {path}")
    df = pd.read_csv(path)
    if 'label' not in df.columns:
        raise SystemExit("Expected a 'label' column in the labeled CSV")
    if 'message' in df.columns:
        df['message'] = df['message'].fillna('').astype(str)
    if 'confidence' in df.columns:
        df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce')
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
    return df


def ensure_out_dir(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def plot_all(df: pd.DataFrame, out_dir: str) -> None:
    import matplotlib.pyplot as plt
    import seaborn as sns
    sns.set_style('whitegrid')

    out_dir = ensure_out_dir(out_dir)

    # 1) Class distribution
    try:
        plt.figure(figsize=(6,4))
        ax = (df['label'].astype(str).str.lower().value_counts()
              .reindex(['neg','neu','pos'])
              .fillna(0)
              .rename_axis('label').reset_index(name='count')
              .set_index('label')
              .plot(kind='bar', legend=False, color=['#d62728','#aaaaaa','#2ca02c']))
        plt.title('Labeled class distribution')
        plt.ylabel('Count')
        plt.tight_layout()
        path = os.path.join(out_dir, 'labeled_class_distribution.png')
        plt.savefig(path, dpi=150)
        plt.close()
        print(f"[plots] Saved {path}")
    except Exception as e:
        print(f"[plots] Skipped class distribution: {e}")

    # 2) Confidence histogram (overall)
    if 'confidence' in df.columns and df['confidence'].notna().any():
        try:
            plt.figure(figsize=(6,4))
            sns.histplot(df['confidence'].dropna(), bins=30, color='#1f77b4')
            plt.title('Confidence distribution (overall)')
            plt.xlabel('Confidence'); plt.ylabel('Frequency')
            plt.tight_layout()
            path = os.path.join(out_dir, 'labeled_confidence_hist.png')
            plt.savefig(path, dpi=150); plt.close()
            print(f"[plots] Saved {path}")
        except Exception as e:
            print(f"[plots] Skipped confidence histogram: {e}")

        # 3) Confidence by label (boxplot)
        try:
            plt.figure(figsize=(6,4))
            t = df[['label','confidence']].dropna()
            t['label'] = t['label'].astype(str).str.lower()
            order = ['neg','neu','pos']
            sns.boxplot(data=t, x='label', y='confidence', order=order, palette=['#d62728','#aaaaaa','#2ca02c'])
            plt.title('Confidence by label')
            plt.xlabel('Label'); plt.ylabel('Confidence')
            plt.tight_layout()
            path = os.path.join(out_dir, 'labeled_confidence_by_label.png')
            plt.savefig(path, dpi=150); plt.close()
            print(f"[plots] Saved {path}")
        except Exception as e:
            print(f"[plots] Skipped confidence by label: {e}")

    # 4) Message length by label
    if 'message' in df.columns:
        try:
            t = df[['label','message']].copy()
            t['label'] = t['label'].astype(str).str.lower()
            t['len'] = t['message'].astype(str).str.len()
            plt.figure(figsize=(6,4))
            sns.boxplot(data=t, x='label', y='len', order=['neg','neu','pos'], palette=['#d62728','#aaaaaa','#2ca02c'])
            plt.title('Message length by label')
            plt.xlabel('Label'); plt.ylabel('Length (chars)')
            plt.tight_layout()
            path = os.path.join(out_dir, 'labeled_length_by_label.png')
            plt.savefig(path, dpi=150); plt.close()
            print(f"[plots] Saved {path}")
        except Exception as e:
            print(f"[plots] Skipped length by label: {e}")

    # 5) Daily counts per label (if date present)
    if 'date' in df.columns and df['date'].notna().any():
        try:
            t = df[['date','label']].dropna().copy()
            t['day'] = pd.to_datetime(t['date'], errors='coerce').dt.date
            t['label'] = t['label'].astype(str).str.lower()
            pv = t.pivot_table(index='day', columns='label', values='date', aggfunc='count').fillna(0)
            # ensure consistent column order
            for c in ['neg','neu','pos']:
                if c not in pv.columns:
                    pv[c] = 0
            pv = pv[['neg','neu','pos']]
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,4))
            pv.plot(kind='bar', stacked=True, color=['#d62728','#aaaaaa','#2ca02c'])
            plt.title('Daily labeled counts (stacked)')
            plt.xlabel('Day'); plt.ylabel('Count')
            plt.tight_layout()
            path = os.path.join(out_dir, 'labeled_daily_counts.png')
            plt.savefig(path, dpi=150); plt.close()
            print(f"[plots] Saved {path}")
        except Exception as e:
            print(f"[plots] Skipped daily counts: {e}")


def main():
    parser = argparse.ArgumentParser(description='Plot graphs from labeled sentiment data.')
    parser.add_argument('-i', '--input', default='data/labeled_sentiment.csv', help='Path to labeled CSV')
    parser.add_argument('-o', '--out-dir', default='data', help='Output directory for plots')
    args = parser.parse_args()

    df = safe_read(args.input)
    plot_all(df, args.out_dir)


if __name__ == '__main__':
    main()
