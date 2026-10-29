"""Lightweight BM25 retrieval engine for 'Ask your inbox' over notes.

Implemented in pure Python standard library for zero new dependencies and low latency.
"""

import math
import re
from collections import Counter
from typing import Dict, List, Set, Tuple

from app.schemas import NoteCitation

STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "me", "more", "most", "mustn't", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should", "shouldn't",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through",
    "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "were",
    "weren't", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "won't", "would", "wouldn't", "you", "your", "yours", "yourself",
}


def tokenize(text: str) -> List[str]:
    """Extract lowercase alphanumeric tokens, filtering stopwords."""
    words = re.findall(r"[a-zA-Z0-9_\-]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


class BM25Retriever:
    """In-memory BM25 ranker over a collection of inbox notes."""

    def __init__(self, notes: List[dict], k1: float = 1.5, b: float = 0.75):
        self.notes = notes
        self.k1 = k1
        self.b = b
        self.doc_count = len(notes)
        self.doc_lengths: List[int] = []
        self.doc_term_freqs: List[Counter] = []
        self.doc_freqs: Dict[str, int] = Counter()

        # Build inverted index
        for n in notes:
            text = f"{n.get('title') or ''} {n.get('raw_text') or ''}"
            tokens = tokenize(text)
            self.doc_lengths.append(len(tokens))
            term_freq = Counter(tokens)
            self.doc_term_freqs.append(term_freq)
            for term in term_freq.keys():
                self.doc_freqs[term] += 1

        self.avg_doc_len = (
            sum(self.doc_lengths) / self.doc_count if self.doc_count > 0 else 1.0
        )

    def _idf(self, term: str) -> float:
        n_q = self.doc_freqs.get(term, 0)
        # Standard Lucene/BM25 IDF formula
        return math.log(1.0 + (self.doc_count - n_q + 0.5) / (n_q + 0.5))

    def search(self, query: str, top_k: int = 5) -> List[Tuple[dict, float]]:
        """Score notes against query string and return top_k (note, score) pairs."""
        if not self.notes:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            # Fallback to recent notes if query had only stopwords
            return [(n, 0.5) for n in self.notes[:top_k]]

        scores: List[float] = [0.0] * self.doc_count

        for q in query_tokens:
            idf = self._idf(q)
            if idf <= 0:
                continue

            for idx, term_freq in enumerate(self.doc_term_freqs):
                freq = term_freq.get(q, 0)
                if freq == 0:
                    continue

                d_len = self.doc_lengths[idx]
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                scores[idx] += idf * (numerator / denominator)

        # Pair notes with scores
        scored_notes = [
            (self.notes[i], round(scores[i], 4))
            for i in range(self.doc_count)
            if scores[i] > 0
        ]

        scored_notes.sort(key=lambda x: x[1], reverse=True)

        # If zero matches, return the most recent notes with score 0.1
        if not scored_notes:
            return [(n, 0.1) for n in self.notes[:top_k]]

        return scored_notes[:top_k]


def build_snippet(text: str, query: str, max_chars: int = 140) -> str:
    """Extract a snippet from text emphasizing terms in query."""
    clean = text.replace("\n", " ").strip()
    if len(clean) <= max_chars:
        return clean

    query_words = set(tokenize(query))
    if not query_words:
        return clean[:max_chars] + "..."

    # Find earliest match of a query word
    words = clean.split()
    best_idx = 0
    for idx, w in enumerate(words):
        if re.sub(r"\W+", "", w).lower() in query_words:
            best_idx = idx
            break

    start_word = max(0, best_idx - 6)
    snippet_words = words[start_word : start_word + 22]
    snippet = " ".join(snippet_words)
    if start_word > 0:
        snippet = "..." + snippet
    if start_word + 22 < len(words):
        snippet = snippet + "..."
    return snippet[:max_chars]


def retrieve_relevant_notes(
    notes: List[dict],
    query: str,
    top_k: int = 5,
) -> Tuple[List[dict], List[NoteCitation]]:
    """Retrieve top notes and construct structured NoteCitation objects."""
    retriever = BM25Retriever(notes)
    scored_pairs = retriever.search(query, top_k=top_k)

    matched_notes = []
    citations = []

    for note, score in scored_pairs:
        matched_notes.append(note)
        raw = note.get("raw_text") or ""
        snippet = build_snippet(raw, query)
        citations.append(
            NoteCitation(
                id=note["id"],
                title=note.get("title") or f"Note #{note['id']}",
                snippet=snippet,
                relevance_score=score,
            )
        )

    return matched_notes, citations


def extract_citations_from_text(text: str, candidate_citations: List[NoteCitation]) -> List[NoteCitation]:
    """Filter citations to only those explicitly mentioned in the generated answer."""
    # Look for patterns like [Note #12] or [12] or Note #12
    found_ids = set()
    for m in re.finditer(r"(?:\[Note\s*#|#)(\d+)\]?", text, re.IGNORECASE):
        try:
            found_ids.add(int(m.group(1)))
        except ValueError:
            pass

    if not found_ids:
        # If no explicit ID in answer, retain the candidates
        return candidate_citations

    # Filter candidates to mentioned IDs (preserving rank order)
    matched = [c for c in candidate_citations if c.id in found_ids]
    return matched if matched else candidate_citations
