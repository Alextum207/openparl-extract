"""Tiny stopword-based language detection, used only to disambiguate multi-language title dicts."""
import re

STOPWORDS = {
    "de": ["der", "die", "das", "und", "ist", "nicht", "mit", "von", "zu", "den", "dem", "ein", "eine", "auf", "für", "dass", "wird", "sich"],
    "fr": ["le", "la", "les", "et", "est", "de", "du", "des", "un", "une", "que", "qui", "dans", "pour", "pas", "au", "sur", "en", "ce"],
    "it": ["il", "lo", "la", "gli", "le", "e", "è", "di", "del", "della", "dei", "un", "una", "che", "per", "non", "con", "nel", "sono", "si"],
    "rm": ["il", "la", "ed", "è", "da", "en", "che", "per", "cun", "na", "ün", "ils", "las", "dal", "sco", "ina"],
}
MIN_HITS, MIN_RATIO = 10, 1.5


def detect_language(text: str, candidates: list[str]) -> str | None:
    """Candidate with clearly the most stopword hits (>= 10 and >= 1.5x the runner-up), else None."""
    words = re.findall(r"[^\W\d_]+", text.casefold())
    scores = sorted(((sum(w in set(STOPWORDS[c]) for w in words), c) for c in candidates if c in STOPWORDS),
                    reverse=True)
    if not scores or scores[0][0] < MIN_HITS:
        return None
    if len(scores) > 1 and scores[0][0] < MIN_RATIO * scores[1][0]:
        return None
    return scores[0][1]
