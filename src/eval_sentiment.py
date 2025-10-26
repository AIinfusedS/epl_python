import argparse
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, classification_report

try:
    from .transformer_sentiment import TransformerSentiment
except ImportError:
    # Allow running as a script via -m src.eval_sentiment
    from transformer_sentiment import TransformerSentiment


def main():
    parser = argparse.ArgumentParser(description='Evaluate a fine-tuned transformers sentiment model on a labeled CSV')
    parser.add_argument('--csv', required=True, help='Labeled CSV path with message and label columns')
    parser.add_argument('--text-col', default='message')
    parser.add_argument('--label-col', default='label')
    parser.add_argument('--model', required=True, help='Model name or local path')
    parser.add_argument('--batch-size', type=int, default=64)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    df = df[[args.text_col, args.label_col]].dropna().copy()
    texts = df[args.text_col].astype(str).tolist()
    true_labels = df[args.label_col].astype(str).tolist()

    clf = TransformerSentiment(args.model)
    _, pred_labels = clf.predict_probs_and_labels(texts, batch_size=args.batch_size)

    y_true = np.array(true_labels)
    y_pred = np.array(pred_labels)

    # If labels differ from model id2label names, normalize to strings for comparison
    acc = accuracy_score(y_true, y_pred)
    f1_macro = f1_score(y_true, y_pred, average='macro', zero_division=0)
    prec_macro = precision_score(y_true, y_pred, average='macro', zero_division=0)
    rec_macro = recall_score(y_true, y_pred, average='macro', zero_division=0)

    print('Accuracy:', f"{acc:.4f}")
    print('F1 (macro):', f"{f1_macro:.4f}")
    print('Precision (macro):', f"{prec_macro:.4f}")
    print('Recall (macro):', f"{rec_macro:.4f}")
    print('\nClassification report:')
    print(classification_report(y_true, y_pred, zero_division=0))


if __name__ == '__main__':
    main()
