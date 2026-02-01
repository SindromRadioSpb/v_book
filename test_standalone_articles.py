"""Test standalone articles canonicalization (M5.2 fix)."""
import sys
import io

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term

print("="*70)
print("TEST: Standalone Articles Canonicalization (M5.2 Fix)")
print("="*70)

# Test cases: (surface, lemma, expected_canonical)
test_cases = [
    # Normal cases (should work as before)
    ("בית ספר", "בית ספר", "בית_ספר"),
    ("בית הספר", "בית ספר", "בית_ספר"),
    ("לבית הספר", "בית ספר", "בית_ספר"),
    ("בבית ספר", "בית ספר", "בית_ספר"),

    # Standalone article cases (M5.2 fix)
    ("בית ה ספר", "בית ה ספר", "בית_ספר"),  # Article separate
    ("ה ספר", "ה ספר", "ספר"),                # Article only
    ("ב בית", "ב בית", "בית"),                # Prefix separate
    ("ל ספר", "ל ספר", "ספר"),                # Prefix separate

    # Multiple standalone prefixes
    ("ב ה ספר", "ב ה ספר", "ספר"),           # Two prefixes separate
    ("ל ה בית", "ל ה בית", "בית"),           # Two prefixes separate

    # Edge cases
    ("הספר", "ספר", "ספר"),                  # Single word with article
    ("ספר", "ספר", "ספר"),                   # Single word bare
]

passed = 0
failed = 0

for i, (surface, lemma, expected) in enumerate(test_cases, 1):
    result = canonicalize_hebrew_term(surface, lemma)

    if result == expected:
        status = "✅ PASS"
        passed += 1
    else:
        status = "❌ FAIL"
        failed += 1

    print(f"\n{i}. {status}")
    print(f"   Surface: '{surface}'")
    print(f"   Lemma:   '{lemma}'")
    print(f"   Expected: '{expected}'")
    print(f"   Got:      '{result}'")

print("\n" + "="*70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*70)

if failed == 0:
    print("✅ ALL TESTS PASSED")
    sys.exit(0)
else:
    print(f"❌ {failed} TESTS FAILED")
    sys.exit(1)
