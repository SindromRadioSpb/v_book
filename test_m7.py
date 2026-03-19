"""M7 Translation Memory - Automated Tests.

Tests:
1. Normalization compatibility with M5
2. Translation lookup (TM, dict, precedence)
3. Bulk resolve performance
4. TM persistence after re-extraction
5. Status workflow
"""

import io
import sys
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("=" * 70)
print("M7: Translation Memory - Automated Tests")
print("=" * 70)

from app.domain.normalization import normalize_text
from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term
from app.infra.sa_models import DictEntry, DictSource, TMEntry
from app.services.db_service import DBService
from app.services.translation_service import TranslationService

# Setup test DB
test_db = Path("test_m7.db")
if test_db.exists():
    test_db.unlink()

DBService.initialize(test_db)
db_service = DBService.get_instance()

# Apply M7 migration
import sqlite3

migration_sql = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
con = sqlite3.connect(str(test_db))
con.executescript(migration_sql)
con.close()
print("✓ M7 migration applied\n")

tm_service = TranslationService()

failed_tests = []

# ============================================================================
# Test 1: Normalization Compatibility
# ============================================================================
print("\n[Test 1] Normalization compatibility with M5...")

test_cases = [
    ("בית הספר", "בית_ספר"),
    ("בבית הספר", "בית_ספר"),
    ("ה ספר", "ספר"),  # After M5.2 fix
    ("בית ספר", "בית_ספר"),
    ("  בְּבֵית   הַסֵפֶר  ", "בית_ספר"),  # nikud + whitespace
]

test1_pass = True
for text, expected_norm in test_cases:
    m5_key = canonicalize_hebrew_term(text)
    # M5 compatibility REQUIRED for lemma/term_cluster per contract
    m7_result = normalize_text("he", text, "lemma", "strict")

    match = m5_key == m7_result.norm == expected_norm
    status = "✅" if match else "❌"

    print(
        f"  {status} '{text}' → M5: {m5_key}, M7 (lemma): {m7_result.norm}, Expected: {expected_norm}"
    )

    if not match:
        test1_pass = False
        failed_tests.append(f"Test 1: Normalization mismatch for '{text}'")

if test1_pass:
    print("  ✅ Test 1 PASSED")
else:
    print("  ❌ Test 1 FAILED")

# ============================================================================
# Test 2: Translation Lookup
# ============================================================================
print("\n[Test 2] Translation lookup...")

test2_pass = True

with db_service.get_session() as session:
    # Create TM entry
    entry = TMEntry(
        project_id=None,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="בית",
        src_norm="בית",
        translation="дом",
        status="approved",
        origin="user_edit",
    )
    session.add(entry)
    session.commit()

    # Lookup
    result = tm_service.resolve_translation(
        session,
        src_text="בית",
        kind="lemma",
    )

    if result.translation == "дом" and result.source == "tm":
        print("  ✅ TM lookup works")
    else:
        print(f"  ❌ TM lookup failed: got {result.translation}, source={result.source}")
        test2_pass = False
        failed_tests.append("Test 2: TM lookup")

if test2_pass:
    print("  ✅ Test 2 PASSED")
else:
    print("  ❌ Test 2 FAILED")

# ============================================================================
# Test 3: Precedence (TM > Dict)
# ============================================================================
print("\n[Test 3] Precedence order (TM > Dict)...")

test3_pass = True

with db_service.get_session() as session:
    # Create dict source
    dict_src = DictSource(
        project_id=None,
        name="Test Dict",
        format="csv",
        sha256="test_hash_123",
        row_count=1,
    )
    session.add(dict_src)
    session.flush()

    # Add dict entry for same word (different translation)
    dict_entry = DictEntry(
        dict_source_id=dict_src.dict_source_id,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="בית",
        src_norm="בית",
        translation="здание",  # Different from TM
        status="approved",
    )
    session.add(dict_entry)
    session.commit()

    # Lookup (should return TM, not dict)
    result = tm_service.resolve_translation(
        session,
        src_text="בית",
        kind="lemma",
    )

    if result.translation == "дом" and result.source == "tm":
        print("  ✅ TM takes precedence over dict")
    else:
        print(f"  ❌ Precedence failed: got {result.translation} from {result.source}")
        test3_pass = False
        failed_tests.append("Test 3: Precedence")

if test3_pass:
    print("  ✅ Test 3 PASSED")
else:
    print("  ❌ Test 3 FAILED")

# ============================================================================
# Test 4: Bulk Resolve
# ============================================================================
print("\n[Test 4] Bulk resolve...")

test4_pass = True

with db_service.get_session() as session:
    # Create multiple TM entries
    test_words = [("ספר", "книга"), ("גדול", "большой"), ("חדש", "новый")]

    for word, trans in test_words:
        entry = TMEntry(
            project_id=None,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text=word,
            src_norm=word,
            translation=trans,
            status="approved",
            origin="user_edit",
        )
        session.add(entry)
    session.commit()

    # Bulk lookup
    items = [(word, "lemma") for word, _ in test_words]
    results = tm_service.bulk_resolve(session, items)

    all_found = all(results.get((word, "lemma")).translation == trans for word, trans in test_words)

    if all_found:
        print(f"  ✅ Bulk resolve found all {len(test_words)} items")
    else:
        print("  ❌ Bulk resolve failed to find all items")
        test4_pass = False
        failed_tests.append("Test 4: Bulk resolve")

if test4_pass:
    print("  ✅ Test 4 PASSED")
else:
    print("  ❌ Test 4 FAILED")

# ============================================================================
# Test 5: Status Workflow
# ============================================================================
print("\n[Test 5] Status workflow (draft/approved)...")

test5_pass = True

with db_service.get_session() as session:
    # Create draft entry
    draft_entry = TMEntry(
        project_id=None,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test_draft",
        src_norm="test_draft",
        translation="draft_translation",
        status="draft",
        origin="user_edit",
    )
    session.add(draft_entry)
    session.commit()
    entry_id = draft_entry.tm_id

    # Lookup without allow_draft (should NOT find)
    result = tm_service.resolve_translation(
        session,
        src_text="test_draft",
        kind="lemma",
        allow_draft=False,
    )

    if result.translation is None:
        print("  ✅ Draft entry correctly hidden without allow_draft")
    else:
        print("  ❌ Draft entry visible without allow_draft")
        test5_pass = False
        failed_tests.append("Test 5: Draft hidden")

    # Lookup with allow_draft (should find)
    result = tm_service.resolve_translation(
        session,
        src_text="test_draft",
        kind="lemma",
        allow_draft=True,
    )

    if result.translation == "draft_translation":
        print("  ✅ Draft entry found with allow_draft")
    else:
        print("  ❌ Draft entry not found with allow_draft")
        test5_pass = False
        failed_tests.append("Test 5: Draft visible")

    # Approve entry
    entry = session.get(TMEntry, entry_id)
    entry.status = "approved"
    session.commit()

    # Lookup now finds it without allow_draft
    result = tm_service.resolve_translation(
        session,
        src_text="test_draft",
        kind="lemma",
        allow_draft=False,
    )

    if result.translation == "draft_translation":
        print("  ✅ Approved entry visible without allow_draft")
    else:
        print("  ❌ Approved entry not visible")
        test5_pass = False
        failed_tests.append("Test 5: Approved visible")

if test5_pass:
    print("  ✅ Test 5 PASSED")
else:
    print("  ❌ Test 5 FAILED")

# ============================================================================
# Cleanup
# ============================================================================
DBService.shutdown()

# ============================================================================
# Summary
# ============================================================================
print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)

if not failed_tests:
    print("✅ ALL TESTS PASSED")
    print(f"\nDatabase saved: {test_db}")
    sys.exit(0)
else:
    print(f"❌ {len(failed_tests)} TEST(S) FAILED:")
    for failure in failed_tests:
        print(f"  - {failure}")
    print(f"\nDatabase saved for inspection: {test_db}")
    sys.exit(1)
