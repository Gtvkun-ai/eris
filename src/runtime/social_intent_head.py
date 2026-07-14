from __future__ import annotations

"""Intent head nhỏ, trainable và không gọi LLM cho social dialogue acts.

Đây là tầng fallback sau deterministic intercept. Nó dùng Multinomial Naive
Bayes trên unigram/bigram, đủ nhẹ để chạy trước generator và đủ minh bạch để
shadow-eval. Nó không phải phép màu neural; nó là bước distill production-friendly
trước khi có dataset lớn để fine-tune head thật.
"""

import json
import math
import os
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return " ".join(re.findall(r"[a-z0-9_]+", value))


def tokenize(text: str) -> tuple[str, ...]:
    words = _normalize(text).split()
    features = list(words)
    features.extend(f"{left}__{right}" for left, right in zip(words, words[1:]))
    return tuple(features)


@dataclass(slots=True)
class SocialIntentHeadModel:
    labels: tuple[str, ...] = ()
    document_counts: dict[str, int] = field(default_factory=dict)
    token_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    total_tokens: dict[str, int] = field(default_factory=dict)
    vocabulary: tuple[str, ...] = ()
    alpha: float = 0.8
    version: int = 1

    @classmethod
    def fit(cls, samples: Iterable[tuple[str, str]], *, alpha: float = 0.8) -> "SocialIntentHeadModel":
        docs: Counter[str] = Counter()
        tokens_by_label: dict[str, Counter[str]] = defaultdict(Counter)
        vocabulary: set[str] = set()
        for text, label in samples:
            label = str(label or "other")
            features = tokenize(text)
            docs[label] += 1
            tokens_by_label[label].update(features)
            vocabulary.update(features)
        labels = tuple(sorted(docs))
        return cls(
            labels=labels,
            document_counts=dict(docs),
            token_counts={label: dict(tokens_by_label[label]) for label in labels},
            total_tokens={label: sum(tokens_by_label[label].values()) for label in labels},
            vocabulary=tuple(sorted(vocabulary)),
            alpha=max(0.01, float(alpha)),
        )

    def predict_proba(self, text: str, *, history: Sequence[str] = ()) -> dict[str, float]:
        if not self.labels:
            return {}
        context = " ".join((*tuple(history)[-2:], text))
        features = tokenize(context)
        total_docs = max(1, sum(self.document_counts.values()))
        vocab_size = max(1, len(self.vocabulary))
        log_scores: dict[str, float] = {}
        for label in self.labels:
            doc_count = self.document_counts.get(label, 0)
            prior = (doc_count + self.alpha) / (total_docs + self.alpha * len(self.labels))
            score = math.log(max(prior, 1e-12))
            denominator = self.total_tokens.get(label, 0) + self.alpha * vocab_size
            label_tokens = self.token_counts.get(label, {})
            for feature in features:
                score += math.log((label_tokens.get(feature, 0) + self.alpha) / denominator)
            log_scores[label] = score
        maximum = max(log_scores.values())
        exponentials = {label: math.exp(score - maximum) for label, score in log_scores.items()}
        total = sum(exponentials.values()) or 1.0
        return {label: value / total for label, value in exponentials.items()}

    def predict(self, text: str, *, history: Sequence[str] = ()) -> tuple[str, float]:
        probabilities = self.predict_proba(text, history=history)
        if not probabilities:
            return "other", 0.0
        label, confidence = max(probabilities.items(), key=lambda item: item[1])
        return label, float(confidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SocialIntentHeadModel":
        payload = dict(value)
        payload["labels"] = tuple(payload.get("labels", ()) or ())
        payload["vocabulary"] = tuple(payload.get("vocabulary", ()) or ())
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})

    def save(self, path: str | os.PathLike[str]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "SocialIntentHeadModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


_CACHE_LOCK = threading.RLock()
_CACHE: tuple[str, float, SocialIntentHeadModel] | None = None


def load_default_head() -> SocialIntentHeadModel | None:
    global _CACHE
    if str(os.getenv("ERIS_SOCIAL_INTENT_HEAD_ENABLED", "1")).strip().lower() in {"0", "false", "no", "off"}:
        return None
    path = Path(os.getenv("ERIS_SOCIAL_INTENT_HEAD_PATH", "models/social_intent_head.json"))
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        with _CACHE_LOCK:
            if _CACHE is not None and _CACHE[0] == str(path) and _CACHE[1] == mtime:
                return _CACHE[2]
            model = SocialIntentHeadModel.load(path)
            _CACHE = (str(path), mtime, model)
            return model
    except Exception:
        return None


def predict_social_intent(text: str, *, history: Sequence[str] = ()) -> tuple[str, float]:
    model = load_default_head()
    if model is None:
        return "other", 0.0
    return model.predict(text, history=history)


__all__ = ["SocialIntentHeadModel", "load_default_head", "predict_social_intent", "tokenize"]
