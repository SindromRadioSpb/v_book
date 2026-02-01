"""Detailed analysis of n-gram extraction for test text."""
import sys
import io

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.infra.nlp_engines.mock_engine import create_mock_engine
from app.domain.term_extraction.ngram_extractor import extract_ngrams_from_sentence

# Test sentences
test_sentences = [
    "בית ספר גדול",      # Sentence 1
    "בית הספר החדש",     # Sentence 2
    "ה ספר הזה טוב",     # Sentence 3
]

print("="*70)
print("DETAILED N-GRAM EXTRACTION ANALYSIS")
print("="*70)

engine = create_mock_engine()

all_ngrams = []

for sent_num, text in enumerate(test_sentences, 1):
    print(f"\n{'='*70}")
    print(f"SENTENCE {sent_num}: '{text}'")
    print(f"{'='*70}")

    # Process with Mock engine
    nlp_sentences = engine.process(text)

    if nlp_sentences:
        sent = nlp_sentences[0]
        print(f"\nTokens ({len(sent.tokens)}):")

        tokens_list = []
        for i, tok in enumerate(sent.tokens):
            print(f"  [{i}] text='{tok.text}' | lemma='{tok.lemma}' | pos={tok.pos}")
            tokens_list.append({
                'text': tok.text,
                'lemma': tok.lemma,
                'pos': tok.pos,
            })

        # Extract n-grams
        ngrams = extract_ngrams_from_sentence(tokens_list, n_values=[2])

        print(f"\nBigrams extracted: {len(ngrams)}")
        for ng in ngrams:
            print(f"  ✅ '{ng['surface_text']}' | POS: {ng['pos_pattern']} | Lemma: '{ng['lemma_phrase']}'")
            all_ngrams.append(ng)

        if len(ngrams) == 0:
            print("  ❌ No bigrams (POS patterns not valid)")

print(f"\n{'='*70}")
print(f"SUMMARY")
print(f"{'='*70}")

print(f"\nTotal n-grams extracted: {len(all_ngrams)}")

# Count by surface text
from collections import Counter
surface_counts = Counter(ng['surface_text'] for ng in all_ngrams)
lemma_counts = Counter(ng['lemma_phrase'] for ng in all_ngrams)

print(f"\nUnique surface forms: {len(surface_counts)}")
for surface, count in surface_counts.most_common():
    print(f"  '{surface}' × {count}")

print(f"\nUnique lemma forms (for clustering): {len(lemma_counts)}")
for lemma, count in lemma_counts.most_common():
    print(f"  '{lemma}' × {count}")

print(f"\n{'='*70}")
print(f"EXPECTED CLUSTERS")
print(f"{'='*70}")

# Group by lemma (canonical clustering)
from app.domain.term_extraction.canonicalizer import get_cluster_key

clusters = {}
for ng in all_ngrams:
    canonical = get_cluster_key(ng['surface_text'], ng['lemma_phrase'])

    if canonical not in clusters:
        clusters[canonical] = {
            'canonical': canonical,
            'members': []
        }

    clusters[canonical]['members'].append(ng['surface_text'])

print(f"\nTotal clusters: {len(clusters)}")
for canonical, data in sorted(clusters.items()):
    members = list(set(data['members']))  # Unique members
    print(f"\nCluster '{canonical}':")
    print(f"  Members ({len(members)}):")
    for member in members:
        print(f"    - '{member}'")
    print(f"  Total occurrences: {len(data['members'])}")

    # Predict representative
    from app.domain.term_extraction.canonicalizer import has_standalone_function_tokens
    valid_members = [m for m in members if not has_standalone_function_tokens(m)]
    if valid_members:
        # Sort by length (shortest first), then alphabetical
        representative = sorted(valid_members, key=lambda m: (len(m), m))[0]
    else:
        representative = sorted(members, key=lambda m: (len(m), m))[0]

    print(f"  Representative: '{representative}'")

print(f"\n{'='*70}")
print(f"UI EXPECTATION")
print(f"{'='*70}")
print(f"\nTerms tab should show {len(clusters)} rows in 'Term' column:")
for i, (canonical, data) in enumerate(sorted(clusters.items()), 1):
    members = list(set(data['members']))
    valid_members = [m for m in members if not has_standalone_function_tokens(m)]
    if valid_members:
        representative = sorted(valid_members, key=lambda m: (len(m), m))[0]
    else:
        representative = sorted(members, key=lambda m: (len(m), m))[0]
    print(f"{i}. {representative}")

print("="*70)
