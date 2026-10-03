"""
personal_brand/deduplication.py
--------------------------------
Handles deduplication logging and lightweight text similarity checking
for Lakshya's personal-brand content system.
"""

from pathlib import Path
import json
import datetime
import re
from typing import List, Dict, Any, Tuple, Optional, Set

# Stop words to ignore during keyword similarity calculations
STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "because", "as", "what",
    "which", "this", "that", "these", "those", "then", "just", "so", "than",
    "such", "both", "through", "about", "against", "between", "into", "throughout",
    "during", "before", "after", "above", "below", "to", "from", "up", "upon",
    "down", "in", "out", "on", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "s", "t", "can", "will", "don", "should", "now", "d", "ll", "m", "o", "re",
    "ve", "y", "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn",
    "haven", "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn",
    "wasn", "weren", "won", "wouldn", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing"
}


def normalize_text(text: str) -> str:
    """Lowercase and strip punctuation/symbols from text."""
    if not text:
        return ""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def extract_keywords(text: str) -> Set[str]:
    """Extract informative keywords from normalized text."""
    norm = normalize_text(text)
    tokens = norm.split()
    return {t for t in tokens if len(t) > 2 and t not in STOP_WORDS}


def jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity coefficient between keyword sets of two texts."""
    k1 = extract_keywords(text1)
    k2 = extract_keywords(text2)
    if not k1 or not k2:
        return 0.0
    intersection = k1.intersection(k2)
    union = k1.union(k2)
    return len(intersection) / len(union)


def is_substring_overlap(text1: str, text2: str, min_words: int = 3) -> bool:
    """Check if normalized text1 and text2 share significant multi-word phrase overlaps."""
    n1 = normalize_text(text1)
    n2 = normalize_text(text2)
    if not n1 or not n2:
        return False

    words1 = [w for w in n1.split() if w not in STOP_WORDS]
    words2 = [w for w in n2.split() if w not in STOP_WORDS]

    if len(words1) < min_words or len(words2) < min_words:
        return False

    n_gram_size = min_words
    grams1 = set(tuple(words1[i : i + n_gram_size]) for i in range(len(words1) - n_gram_size + 1))
    grams2 = set(tuple(words2[i : i + n_gram_size]) for i in range(len(words2) - n_gram_size + 1))

    return len(grams1.intersection(grams2)) > 0


class PersonalBrandLog:
    """Manages reading and writing to personal-brand-log.json with 30-day deduplication."""

    DEFAULT_LOG_NAME = "personal-brand-log.json"

    def __init__(self, log_path: Optional[Path] = None):
        if log_path is None:
            root_dir = Path(__file__).resolve().parent.parent
            self.log_path = root_dir / self.DEFAULT_LOG_NAME
        else:
            self.log_path = Path(log_path)

        self.data: Dict[str, Any] = {"version": 1, "entries": []}
        self.load()

    def load(self) -> Dict[str, Any]:
        """Safely load log file from disk, initializing if missing or corrupted."""
        if not self.log_path.exists():
            self.data = {"version": 1, "entries": []}
            self.save()
            return self.data

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict) and "entries" in content:
                    self.data = content
                else:
                    self.data = {"version": 1, "entries": content if isinstance(content, list) else []}
        except Exception:
            self.data = {"version": 1, "entries": []}
            self.save()

        return self.data

    def save(self) -> None:
        """Write current data dict to log file."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_recent_entries(self, days: int = 30) -> List[Dict[str, Any]]:
        """Return entries logged within the last N days."""
        entries = self.data.get("entries", [])
        cutoff_date = datetime.date.today() - datetime.timedelta(days=days)

        recent = []
        for entry in entries:
            entry_date_str = entry.get("date")
            if not entry_date_str:
                continue
            try:
                entry_date = datetime.date.fromisoformat(entry_date_str)
                if entry_date >= cutoff_date:
                    recent.append(entry)
            except ValueError:
                recent.append(entry)

        return recent

    def add_entry(
        self,
        topic: str,
        angle: str = "",
        thesis: str = "",
        linkedin_hook: str = "",
        x_themes: Optional[List[str]] = None,
        sources: Optional[List[Dict[str, str]]] = None,
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a new content entry in the log and trim history to recent window."""
        if date_str is None:
            date_str = datetime.date.today().isoformat()

        entry = {
            "date": date_str,
            "topic": topic,
            "angle": angle,
            "thesis": thesis,
            "linkedin_hook": linkedin_hook,
            "x_themes": x_themes or [],
            "sources": sources or [],
        }

        self.data["entries"].append(entry)

        # Keep rolling window of last 60 entries max
        if len(self.data["entries"]) > 60:
            self.data["entries"] = self.data["entries"][-60:]

        self.save()
        return entry

    def is_topic_similar(
        self, topic: str, threshold: float = 0.4, days: int = 30
    ) -> Tuple[bool, Optional[Dict[str, Any]], float]:
        """
        Check if a topic is too similar to any topic recorded in recent history.
        Returns: (is_similar, matching_entry, score)
        """
        recent_entries = self.get_recent_entries(days=days)
        for entry in recent_entries:
            past_topic = entry.get("topic", "")
            past_thesis = entry.get("thesis", "")

            score = jaccard_similarity(topic, past_topic)
            phrase_overlap = is_substring_overlap(topic, past_topic, min_words=3)
            thesis_score = jaccard_similarity(topic, past_thesis) if past_thesis else 0.0

            max_score = max(score, thesis_score)

            if max_score >= threshold or phrase_overlap:
                return True, entry, max(max_score, 0.7 if phrase_overlap else max_score)

        return False, None, 0.0

    def is_hook_similar(
        self, hook: str, threshold: float = 0.4, days: int = 30
    ) -> Tuple[bool, Optional[Dict[str, Any]], float]:
        """
        Check if a LinkedIn hook is too similar to recent hooks.
        Returns: (is_similar, matching_entry, score)
        """
        recent_entries = self.get_recent_entries(days=days)
        for entry in recent_entries:
            past_hook = entry.get("linkedin_hook", "")
            if not past_hook:
                continue

            score = jaccard_similarity(hook, past_hook)
            phrase_overlap = is_substring_overlap(hook, past_hook, min_words=3)

            if score >= threshold or phrase_overlap:
                return True, entry, max(score, 0.7 if phrase_overlap else score)

        return False, None, 0.0
