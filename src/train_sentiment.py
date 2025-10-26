import argparse
import os
from typing import Optional

import pandas as pd
from datasets import Dataset, ClassLabel
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
import inspect
import numpy as np
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score


def build_dataset(df: pd.DataFrame, text_col: str, label_col: str, label_mapping: Optional[dict] = None) -> Dataset:
    d = df[[text_col, label_col]].dropna().copy()
    # Normalize and drop empty labels
    d[label_col] = d[label_col].astype(str).str.strip()
    d = d[d[label_col] != '']
    if d.empty:
        raise SystemExit("No labeled rows found. Please fill the 'label' column in your CSV (e.g., neg/neu/pos or 0/1/2).")
    if label_mapping:
        d[label_col] = d[label_col].map(label_mapping)
    # If labels are strings, factorize them
    if d[label_col].dtype == object:
        d[label_col] = d[label_col].astype('category')
        label2id = {k: int(v) for v, k in enumerate(d[label_col].cat.categories)}
        id2label = {v: k for k, v in label2id.items()}
        d[label_col] = d[label_col].cat.codes
    else:
        # Assume numeric 0..N-1
        classes = sorted(d[label_col].unique().tolist())
        label2id = {str(c): int(c) for c in classes}
        id2label = {int(c): str(c) for c in classes}
    hf = Dataset.from_pandas(d.reset_index(drop=True))
    hf = hf.class_encode_column(label_col)
    hf.features[label_col] = ClassLabel(num_classes=len(id2label), names=[id2label[i] for i in range(len(id2label))])
    return hf, label2id, id2label


def tokenize_fn(examples, tokenizer, text_col):
    return tokenizer(examples[text_col], truncation=True, padding=False)


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        'accuracy': accuracy_score(labels, preds),
        'precision_macro': precision_score(labels, preds, average='macro', zero_division=0),
        'recall_macro': recall_score(labels, preds, average='macro', zero_division=0),
        'f1_macro': f1_score(labels, preds, average='macro', zero_division=0),
    }


def main():
    parser = argparse.ArgumentParser(description='Fine-tune a transformers model for sentiment.')
    parser.add_argument('--train-csv', required=True, help='Path to labeled CSV')
    parser.add_argument('--text-col', default='message', help='Text column name')
    parser.add_argument('--label-col', default='label', help='Label column name (e.g., pos/neu/neg or 2/1/0)')
    parser.add_argument('--model-name', default='distilbert-base-uncased', help='Base model name or path')
    parser.add_argument('--output-dir', default='models/sentiment-distilbert', help='Where to save the fine-tuned model')
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--lr', type=float, default=5e-5)
    parser.add_argument('--eval-split', type=float, default=0.1, help='Fraction of data for eval')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    df = pd.read_csv(args.train_csv)
    ds, label2id, id2label = build_dataset(df, args.text_col, args.label_col)
    if args.eval_split > 0:
        ds = ds.train_test_split(test_size=args.eval_split, seed=42, stratify_by_column=args.label_col)
        train_ds, eval_ds = ds['train'], ds['test']
    else:
        train_ds, eval_ds = ds, None

    num_labels = len(id2label)
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=num_labels,
        id2label=id2label,
        label2id={k: int(v) for k, v in label2id.items()},
    )

    tokenized_train = train_ds.map(lambda x: tokenize_fn(x, tokenizer, args.text_col), batched=True)
    tokenized_eval = eval_ds.map(lambda x: tokenize_fn(x, tokenizer, args.text_col), batched=True) if (eval_ds is not None) else None

    # Build TrainingArguments with compatibility across transformers versions
    base_kwargs = {
        'output_dir': args.output_dir,
        'per_device_train_batch_size': args.batch_size,
        'per_device_eval_batch_size': args.batch_size,
        'num_train_epochs': args.epochs,
        'learning_rate': args.lr,
        'fp16': False,
        'logging_steps': 50,
    }
    eval_kwargs = {}
    if tokenized_eval is not None:
        # Set both evaluation_strategy and eval_strategy for compatibility across transformers versions
        eval_kwargs.update({
            'evaluation_strategy': 'epoch',
            'eval_strategy': 'epoch',
            'save_strategy': 'epoch',
            'load_best_model_at_end': True,
            'metric_for_best_model': 'f1_macro',
            'greater_is_better': True,
        })

    # Filter kwargs to only include parameters supported by this transformers version
    sig = inspect.signature(TrainingArguments.__init__)
    allowed = set(sig.parameters.keys())
    def _filter(d: dict) -> dict:
        return {k: v for k, v in d.items() if k in allowed}

    training_args = TrainingArguments(**_filter(base_kwargs), **_filter(eval_kwargs))

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_eval,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics if tokenized_eval else None,
    )

    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"Model saved to {args.output_dir}")


if __name__ == '__main__':
    main()
