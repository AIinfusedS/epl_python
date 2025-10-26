from typing import List, Optional

import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


class TransformerSentiment:
    def __init__(self, model_name_or_path: str, device: Optional[str] = None, max_length: int = 256):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name_or_path)
        self.max_length = max_length
        if device is None:
            if torch.cuda.is_available():
                device = 'cuda'
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = 'mps'
            else:
                device = 'cpu'
        self.device = device
        self.model.to(self.device)
        self.model.eval()

        # Expect labels roughly like {0:'neg',1:'neu',2:'pos'} or similar
        self.id2label = self.model.config.id2label if hasattr(self.model.config, 'id2label') else {0:'0',1:'1',2:'2'}

    def _compound_from_probs(self, probs: np.ndarray) -> float:
        # Map class probabilities to a [-1,1] compound-like score.
        # If we have exactly 3 labels and names look like neg/neu/pos (any case), use that mapping.
        labels = [self.id2label.get(i, str(i)).lower() for i in range(len(probs))]
        try:
            neg_idx = labels.index('neg') if 'neg' in labels else labels.index('negative')
        except ValueError:
            neg_idx = 0
        try:
            neu_idx = labels.index('neu') if 'neu' in labels else labels.index('neutral')
        except ValueError:
            neu_idx = 1 if len(probs) > 2 else None
        try:
            pos_idx = labels.index('pos') if 'pos' in labels else labels.index('positive')
        except ValueError:
            pos_idx = (len(probs)-1)

        p_neg = float(probs[neg_idx]) if neg_idx is not None else 0.0
        p_pos = float(probs[pos_idx]) if pos_idx is not None else 0.0
        # A simple skew: pos - neg; keep within [-1,1]
        comp = max(-1.0, min(1.0, p_pos - p_neg))
        return comp

    @torch.no_grad()
    def predict_compound_batch(self, texts: List[str], batch_size: int = 32) -> List[float]:
        out: List[float] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors='pt'
            )
            enc = {k: v.to(self.device) for k, v in enc.items()}
            logits = self.model(**enc).logits
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            for row in probs:
                out.append(self._compound_from_probs(row))
        return out

    @torch.no_grad()
    def predict_probs_and_labels(self, texts: List[str], batch_size: int = 32):
        probs_all = []
        labels_all: List[str] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors='pt'
            )
            enc = {k: v.to(self.device) for k, v in enc.items()}
            logits = self.model(**enc).logits
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            preds = probs.argmax(axis=-1)
            for j, row in enumerate(probs):
                probs_all.append(row)
                label = self.id2label.get(int(preds[j]), str(int(preds[j])))
                labels_all.append(label)
        return probs_all, labels_all
