"""
Text utilities shared across the codebase.

Requires NLTK corpora: punkt_tab, stopwords.
They are lazy-downloaded on first call if missing.
"""

from __future__ import annotations

import hashlib
import re


def content_hash(text: str) -> str:
    """SHA256 hex digest of text's UTF-8 bytes — the single source of truth
    for this algorithm on the Python side (previously computed ad hoc at 4
    separate call sites, 2 of them byte-identical copies in the same file).
    Mirrored by prisma-desktop's Rust `content_hash()` (sync/mod.rs) — keep
    both in lockstep if this ever changes."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def significant_words(text: str) -> frozenset[str]:
    """
    Extract content-bearing stems from a short text (e.g. an academic paper title).

    - Tokenizes with NLTK (handles colons, hyphens, punctuation correctly).
    - Removes the full NLTK English stop-word corpus (179 words).
    - Applies Porter stemming so "quantization" / "quantize" share a stem.
    - Keeps only alphabetic tokens longer than 2 characters.

    Use the stems for pre-filtering candidate pairs before an LLM identity check,
    not as a definitive equality test. The overlap threshold should reflect the
    false-positive tolerance of the downstream gate.
    """
    try:
        from nltk.tokenize import word_tokenize
        from nltk.corpus import stopwords as _sw
        from nltk.stem import PorterStemmer
        tokens = word_tokenize(text.lower())
        stop = set(_sw.words("english"))
    except LookupError:
        import nltk as _nltk
        _nltk.download("punkt_tab", quiet=True)
        _nltk.download("stopwords", quiet=True)
        from nltk.tokenize import word_tokenize
        from nltk.corpus import stopwords as _sw
        from nltk.stem import PorterStemmer
        tokens = word_tokenize(text.lower())
        stop = set(_sw.words("english"))

    stemmer = PorterStemmer()
    return frozenset(
        stemmer.stem(t)
        for t in tokens
        if t.isalpha() and t not in stop and len(t) > 2
    )


def stem_overlap(text_a: str, text_b: str) -> int:
    """Number of shared significant stems between two texts."""
    return len(significant_words(text_a) & significant_words(text_b))


def make_citekey(authors: list[str], year: int | None, title: str | None = None) -> str:
    """First author's last name + year (falls back to title's first word if no authors)."""
    names = [a for a in authors if a.strip()]
    if not names:
        first_word = ""
        if title:
            first_word = re.sub(r"[^a-z]", "", title.split()[0].lower())
        return f"{first_word or 'unknown'}{year or ''}"
    last = names[0].split()[-1].lower()
    last = re.sub(r"[^a-z]", "", last)
    return f"{last}{year or ''}"
