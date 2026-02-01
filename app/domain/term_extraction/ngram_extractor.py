"""N-gram extraction from processed sentences (M5 Base)."""
import logging
from typing import List, Dict, Set, Tuple
from collections import Counter

logger = logging.getLogger(__name__)

# POS pattern filters for Hebrew
VALID_POS_PATTERNS = {
    # Bigrams
    ('NOUN', 'NOUN'),   # Construct chains (smikhut): בית ספר
    ('NOUN', 'ADJ'),    # Noun + Adjective
    ('ADJ', 'NOUN'),    # Adjective + Noun
    ('PROPN', 'PROPN'), # Proper noun chains
    ('NUM', 'NOUN'),    # Number + Noun

    # Trigrams
    ('NOUN', 'NOUN', 'NOUN'),
    ('NOUN', 'ADJ', 'NOUN'),
    ('ADJ', 'ADJ', 'NOUN'),
}


def is_valid_pos_pattern(pos_tags: Tuple[str, ...]) -> bool:
    """
    Check if POS pattern is valid for term extraction.

    Args:
        pos_tags: Tuple of POS tags

    Returns:
        True if pattern is valid
    """
    return pos_tags in VALID_POS_PATTERNS


def extract_ngrams_from_sentence(
    tokens: List[Dict],
    n_values: List[int] = [2, 3]
) -> List[Dict]:
    """
    Extract n-grams from a single sentence.

    Args:
        tokens: List of token dicts with keys: text, lemma, pos
        n_values: List of n values to extract (e.g., [2, 3] for bigrams + trigrams)

    Returns:
        List of ngram dicts with keys:
        - n: ngram size
        - surface_text: surface form
        - lemma_phrase: lemma form
        - pos_pattern: tuple of POS tags
        - token_ids: indices in sentence
    """
    ngrams = []

    for n in n_values:
        if n > len(tokens):
            continue

        for i in range(len(tokens) - n + 1):
            window = tokens[i:i+n]

            # Extract POS pattern
            pos_pattern = tuple(tok['pos'] for tok in window)

            # Filter by POS pattern
            if not is_valid_pos_pattern(pos_pattern):
                continue

            # Build surface and lemma forms
            surface_tokens = [tok['text'] for tok in window]
            lemma_tokens = [tok['lemma'] for tok in window]

            surface_text = ' '.join(surface_tokens)
            lemma_phrase = ' '.join(lemma_tokens)

            ngrams.append({
                'n': n,
                'surface_text': surface_text,
                'lemma_phrase': lemma_phrase,
                'pos_pattern': '|'.join(pos_pattern),
                'token_ids': list(range(i, i+n)),
            })

    return ngrams


def extract_ngrams_from_documents(
    documents_sentences: Dict[int, List[List[Dict]]],
    n_values: List[int] = [2, 3]
) -> Tuple[Dict, Dict]:
    """
    Extract n-grams from multiple documents.

    Args:
        documents_sentences: Dict[doc_id -> List[sentences]]
            where each sentence is List[token_dict]
        n_values: N-gram sizes to extract

    Returns:
        Tuple of:
        - ngram_counts: Counter of (surface_text, n, pos_pattern) -> freq
        - ngram_doc_freq: Counter of (surface_text, n, pos_pattern) -> doc_count
    """
    ngram_counts = Counter()
    ngram_docs = {}  # (surface, n, pos) -> Set[doc_id]

    for doc_id, sentences in documents_sentences.items():
        for sentence in sentences:
            ngrams = extract_ngrams_from_sentence(sentence, n_values)

            for ng in ngrams:
                key = (ng['surface_text'], ng['n'], ng['pos_pattern'])

                # Count frequency
                ngram_counts[key] += 1

                # Track document frequency
                if key not in ngram_docs:
                    ngram_docs[key] = set()
                ngram_docs[key].add(doc_id)

    # Convert doc sets to counts
    ngram_doc_freq = {key: len(docs) for key, docs in ngram_docs.items()}

    return ngram_counts, ngram_doc_freq
