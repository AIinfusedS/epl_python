import json
from typing import List, Tuple

import requests


class GPTSentiment:
    """
    Minimal client for a local GPT model served by Ollama.

    Expects the model to respond with a strict JSON object like:
      {"label": "neg|neu|pos", "confidence": 0.0..1.0}

    Endpoint used: POST {base_url}/api/generate with payload:
      {"model": <model>, "prompt": <prompt>, "stream": false, "format": "json"}
    """

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _build_prompt(self, text: str) -> str:
        # Keep the instruction terse and deterministic; request strict JSON.
        return (
            "You are a strict JSON generator for sentiment analysis. "
            "Classify the INPUT text as one of: neg, neu, pos. "
            "Return ONLY a JSON object with keys 'label' and 'confidence' (0..1). "
            "No markdown, no prose.\n\n"
            f"INPUT: {text}"
        )

    def _call(self, prompt: str) -> dict:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # Ollama returns the model's response under 'response'
        raw = data.get("response", "").strip()
        try:
            obj = json.loads(raw)
        except Exception:
            # Try to recover simple cases by stripping codefences
            raw2 = raw.strip().removeprefix("```").removesuffix("```")
            obj = json.loads(raw2)
        return obj

    @staticmethod
    def _canonical_label(s: str) -> str:
        s = (s or "").strip().lower()
        if "neg" in s:
            return "neg"
        if "neu" in s or "neutral" in s:
            return "neu"
        if "pos" in s or "positive" in s:
            return "pos"
        return s or "neu"

    @staticmethod
    def _compound_from_label_conf(label: str, confidence: float) -> float:
        label = GPTSentiment._canonical_label(label)
        c = max(0.0, min(1.0, float(confidence or 0.0)))
        if label == "pos":
            return c
        if label == "neg":
            return -c
        return 0.0

    def predict_label_conf_batch(self, texts: List[str], batch_size: int = 8) -> Tuple[List[str], List[float]]:
        labels: List[str] = []
        confs: List[float] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            for t in batch:
                try:
                    obj = self._call(self._build_prompt(t))
                    lab = self._canonical_label(obj.get("label", ""))
                    conf = float(obj.get("confidence", 0.0))
                except Exception:
                    lab, conf = "neu", 0.0
                labels.append(lab)
                confs.append(conf)
        return labels, confs

    def predict_compound_batch(self, texts: List[str], batch_size: int = 8) -> List[float]:
        labels, confs = self.predict_label_conf_batch(texts, batch_size=batch_size)
        return [self._compound_from_label_conf(lab, conf) for lab, conf in zip(labels, confs)]
