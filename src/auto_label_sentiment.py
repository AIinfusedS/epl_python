import argparse
import os
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

try:
    # Allow both package and direct script execution
    from .make_labeling_set import load_messages as _load_messages
except Exception:
    from make_labeling_set import load_messages as _load_messages


def _combine_inputs(posts_csv: Optional[str], replies_csv: Optional[str], text_col: str = 'message', min_length: int = 3) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    if posts_csv:
        frames.append(_load_messages(posts_csv, text_col=text_col))
    if replies_csv:
        # include parent_id if present for replies
        frames.append(_load_messages(replies_csv, text_col=text_col, extra_cols=['parent_id']))
    if not frames:
        raise SystemExit('No input provided. Use --input-csv or --posts-csv/--replies-csv')
    df = pd.concat(frames, ignore_index=True)
    df['message'] = df['message'].fillna('').astype(str)
    df = df[df['message'].str.len() >= min_length]
    df = df.drop_duplicates(subset=['message']).reset_index(drop=True)
    return df


def _map_label_str_to_int(labels: List[str]) -> List[int]:
    mapping = {'neg': 0, 'negative': 0, 'neu': 1, 'neutral': 1, 'pos': 2, 'positive': 2}
    out: List[int] = []
    for lab in labels:
        lab_l = (lab or '').lower()
        if lab_l in mapping:
            out.append(mapping[lab_l])
        else:
            # fallback: try to parse integer
            try:
                out.append(int(lab))
            except Exception:
                out.append(1)  # default to neutral
    return out


def _vader_label(compound: float, pos_th: float, neg_th: float) -> str:
    if compound >= pos_th:
        return 'pos'
    if compound <= neg_th:
        return 'neg'
    return 'neu'


def _auto_label_vader(texts: List[str], pos_th: float, neg_th: float, min_margin: float) -> Tuple[List[str], List[float]]:
    analyzer = SentimentIntensityAnalyzer()
    labels: List[str] = []
    confs: List[float] = []
    for t in texts:
        s = analyzer.polarity_scores(t or '')
        comp = float(s.get('compound', 0.0))
        lab = _vader_label(comp, pos_th, neg_th)
        # Confidence heuristic: distance from neutral band edges
        if lab == 'pos':
            conf = max(0.0, comp - pos_th)
        elif lab == 'neg':
            conf = max(0.0, abs(comp - neg_th))
        else:
            # closer to 0 is more neutral; confidence inversely related to |compound|
            conf = max(0.0, (pos_th - abs(comp)))
        labels.append(lab)
        confs.append(conf)
    # Normalize confidence roughly to [0,1] by clipping with a reasonable scale
    confs = [min(1.0, c / max(1e-6, min_margin)) for c in confs]
    return labels, confs


def _auto_label_transformers(texts: List[str], model_name_or_path: str, batch_size: int, min_prob: float, min_margin: float) -> Tuple[List[str], List[float]]:
    try:
        from .transformer_sentiment import TransformerSentiment
    except Exception:
        from transformer_sentiment import TransformerSentiment

    clf = TransformerSentiment(model_name_or_path)
    probs_all, labels_all = clf.predict_probs_and_labels(texts, batch_size=batch_size)
    confs: List[float] = []
    for row in probs_all:
        row = np.array(row, dtype=float)
        if row.size == 0:
            confs.append(0.0)
            continue
        top2 = np.sort(row)[-2:] if row.size >= 2 else np.array([0.0, row.max()])
        max_p = float(row.max())
        margin = float(top2[-1] - top2[-2]) if row.size >= 2 else max_p
        # Confidence must satisfy both conditions
        conf = min(max(0.0, (max_p - min_prob) / max(1e-6, 1 - min_prob)), max(0.0, margin / max(1e-6, min_margin)))
        confs.append(conf)
    # Map arbitrary id2label names to canonical 'neg/neu/pos' when obvious; else keep as-is
    canonical = []
    for lab in labels_all:
        ll = (lab or '').lower()
        if 'neg' in ll:
            canonical.append('neg')
        elif 'neu' in ll or 'neutral' in ll:
            canonical.append('neu')
        elif 'pos' in ll or 'positive' in ll:
            canonical.append('pos')
        else:
            canonical.append(lab)
    return canonical, confs


def main():
    parser = argparse.ArgumentParser(description='Automatically label sentiment without manual annotation.')
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--input-csv', help='Single CSV containing a text column (default: message)')
    src.add_argument('--posts-csv', help='Posts CSV to include')
    parser.add_argument('--replies-csv', help='Replies CSV to include (combined with posts if provided)')
    parser.add_argument('--text-col', default='message', help='Text column name in input CSV(s)')
    parser.add_argument('-o', '--output', default='data/labeled_sentiment.csv', help='Output labeled CSV path')
    parser.add_argument('--limit', type=int, default=None, help='Optional cap on number of rows')
    parser.add_argument('--min-length', type=int, default=3, help='Minimum text length to consider')

    parser.add_argument('--backend', choices=['vader', 'transformers', 'gpt'], default='vader', help='Labeling backend: vader, transformers, or gpt (local via Ollama)')
    # VADER knobs
    parser.add_argument('--vader-pos', type=float, default=0.05, help='VADER positive threshold (compound >=)')
    parser.add_argument('--vader-neg', type=float, default=-0.05, help='VADER negative threshold (compound <=)')
    parser.add_argument('--vader-margin', type=float, default=0.2, help='Confidence scaling for VADER distance')
    # Transformers knobs
    parser.add_argument('--transformers-model', default='cardiffnlp/twitter-roberta-base-sentiment-latest', help='HF model for 3-class sentiment')
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--min-prob', type=float, default=0.6, help='Min top class probability to accept')
    parser.add_argument('--min-margin', type=float, default=0.2, help='Min prob gap between top-1 and top-2 to accept')

    # GPT knobs
    parser.add_argument('--gpt-model', default='llama3', help='Local GPT model name (Ollama)')
    parser.add_argument('--gpt-base-url', default='http://localhost:11434', help='Base URL for local GPT server (Ollama)')
    parser.add_argument('--gpt-batch-size', type=int, default=8)

    parser.add_argument('--label-format', choices=['str', 'int'], default='str', help="Output labels as strings ('neg/neu/pos') or integers (0/1/2)")
    parser.add_argument('--only-confident', action='store_true', help='Drop rows that do not meet confidence thresholds')

    args = parser.parse_args()

    # Load inputs
    if args.input_csv:
        if not os.path.exists(args.input_csv):
            raise SystemExit(f"Input CSV not found: {args.input_csv}")
        df = pd.read_csv(args.input_csv)
        if args.text_col not in df.columns:
            raise SystemExit(f"Text column '{args.text_col}' not in {args.input_csv}")
        df = df.copy()
        df['message'] = df[args.text_col].astype(str)
        base_cols = [c for c in ['id', 'date', 'message', 'url'] if c in df.columns]
        df = df[base_cols if base_cols else ['message']]
        df = df[df['message'].str.len() >= args.min_length]
        df = df.drop_duplicates(subset=['message']).reset_index(drop=True)
    else:
        df = _combine_inputs(args.posts_csv, args.replies_csv, text_col=args.text_col, min_length=args.min_length)

    if args.limit and len(df) > args.limit:
        df = df.head(args.limit)

    texts = df['message'].astype(str).tolist()

    # Predict labels + confidence
    if args.backend == 'vader':
        labels, conf = _auto_label_vader(texts, pos_th=args.vader_pos, neg_th=args.vader_neg, min_margin=args.vader_margin)
        # For VADER, define acceptance: confident if outside neutral band by at least margin, or inside band with closeness to 0 below threshold
        accept = []
        analyzer = SentimentIntensityAnalyzer()
        for t in texts:
            comp = analyzer.polarity_scores(t or '').get('compound')
            if comp is None:
                accept.append(False)
                continue
            comp = float(comp)
            if comp >= args.vader_pos + args.vader_margin or comp <= args.vader_neg - args.vader_margin:
                accept.append(True)
            else:
                # inside or near band -> consider less confident
                accept.append(False)
    elif args.backend == 'transformers':
        labels, conf = _auto_label_transformers(texts, args.transformers_model, args.batch_size, args.min_prob, args.min_margin)
        accept = [((c >= 1.0)) or ((c >= 0.5)) for c in conf]  # normalize conf ~[0,1]; accept medium-high confidence
    else:
        # GPT backend via Ollama: expect label+confidence
        try:
            from .gpt_sentiment import GPTSentiment
        except Exception:
            from gpt_sentiment import GPTSentiment
        clf = GPTSentiment(base_url=args.gpt_base_url, model=args.gpt_model)
        labels, conf = clf.predict_label_conf_batch(texts, batch_size=args.gpt_batch_size)
        # Accept medium-high confidence; simple threshold like transformers path
        accept = [c >= 0.5 for c in conf]

    out = df.copy()
    out.insert(1, 'label', labels)
    out['confidence'] = conf

    if args.only_confident:
        out = out[np.array(accept, dtype=bool)]
        out = out.reset_index(drop=True)

    if args.label_format == 'int':
        out['label'] = _map_label_str_to_int(out['label'].astype(str).tolist())

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    out.to_csv(args.output, index=False)
    kept = len(out)
    print(f"Wrote {kept} labeled rows to {args.output} using backend={args.backend}")
    if args.only_confident:
        print("Note: only confident predictions were kept. You can remove --only-confident to include all rows.")


if __name__ == '__main__':
    main()
