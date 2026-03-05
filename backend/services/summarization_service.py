"""
Summarization Service — NLP text summarization & word count estimation.
SRP: ONLY handles text processing — no DB access, no scraping.
Uses extractive summarization (TF-IDF sentence scoring). No external API key required.
"""
import re
from typing import List

from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger(__name__)


class SummarizationService:
    """
    Extractive summarizer using TF-IDF sentence scoring.
    Returns top-N sentences as summary.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._max_sentences = self._settings.summary_max_sentences

    def summarize(self, text: str) -> str:
        """Return an extractive summary of at most max_sentences sentences."""
        if not text or not text.strip():
            return ""

        sentences = self._split_sentences(text)
        if len(sentences) <= self._max_sentences:
            return " ".join(sentences)

        scores = self._score_sentences(sentences)
        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[: self._max_sentences]
        # Preserve original sentence order
        ranked_indices = sorted(idx for idx, _ in ranked)
        summary = " ".join(sentences[i] for i in ranked_indices)
        logger.debug("summarize", sentences_total=len(sentences), summary_sentences=self._max_sentences)
        return summary

    def word_count(self, text: str) -> int:
        """Estimate word count by splitting on whitespace."""
        if not text:
            return 0
        return len(text.split())

    # ── Private Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Simple sentence splitter using punctuation."""
        raw = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _term_frequency(sentence: str) -> dict:
        """Compute raw term frequency for a sentence."""
        words = re.findall(r"\b\w+\b", sentence.lower())
        tf: dict = {}
        for w in words:
            tf[w] = tf.get(w, 0) + 1
        return tf

    def _score_sentences(self, sentences: List[str]) -> List[float]:
        """Score each sentence by summing TF scores of its words."""
        # Build document frequency
        df: dict = {}
        all_tf = [self._term_frequency(s) for s in sentences]
        n = len(sentences)
        for tf in all_tf:
            for word in tf:
                df[word] = df.get(word, 0) + 1

        # TF-IDF inspired scores
        import math
        scores = []
        for tf in all_tf:
            score = sum(
                freq * math.log((n + 1) / (df.get(word, 0) + 1))
                for word, freq in tf.items()
            )
            scores.append(score)
        return scores
