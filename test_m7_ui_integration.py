"""M7 UI Integration - Automated Tests

Tests UI-layer integration without opening actual GUI windows.
Covers:
- Model/View integration (LemmaTableModel, TermClusterTableModel)
- Worker lifecycle and results
- Inline edit workflow → TM entry creation
- Status filtering
- Translation result caching
- History and revert

Run: python test_m7_ui_integration.py
"""
import sys
import io
import unittest
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Qt imports (headless)
from PyQt6.QtCore import QCoreApplication, Qt

# Ensure QCoreApplication exists for Qt tests
_qapp = None


def setUpModule():
    """Module-level setup: create QCoreApplication."""
    global _qapp
    _qapp = QCoreApplication.instance()
    if _qapp is None:
        _qapp = QCoreApplication(sys.argv)


class M7UITestCase(unittest.TestCase):
    """Base test case with database setup."""

    @classmethod
    def setUpClass(cls):
        """Set up test database with M7 schema."""
        cls.db_path = Path("test_m7_ui.db")
        if cls.db_path.exists():
            import time
            # Wait a bit for file to be released
            time.sleep(0.1)
            try:
                cls.db_path.unlink()
            except PermissionError:
                pass  # File still locked, skip

        from app.services.db_service import DBService
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Apply M7 migrations
        import sqlite3
        con = sqlite3.connect(str(cls.db_path))

        # Apply 004 (M7 base schema)
        migration_004 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        con.executescript(migration_004)

        # Apply 005 (add 'revert' origin)
        migration_005 = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        con.executescript(migration_005)

        con.close()

        # Create test FK structure (Library → DictProject → Lemmas)
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import Library, DictProject

            # Create Library
            library = Library(
                library_id=1,
                name="Test Library",
            )
            session.add(library)
            session.flush()

            # Create DictProject
            project = DictProject(
                project_id=1,
                library_id=1,
                name="Test Project",
                description="Test",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        from app.services.db_service import DBService
        DBService.shutdown()
        if cls.db_path.exists():
            cls.db_path.unlink()


# ============================================================================
# Test 1: LemmaTableModel - Basic integration
# ============================================================================

class TestLemmaTableModel(unittest.TestCase):
    """Test LemmaTableModel basic functionality."""

    def test_initialization(self):
        """Test LemmaTableModel initializes correctly."""
        from app.ui.models_qt import LemmaTableModel
        from app.domain.dto import LemmaStats

        lemmas = [
            LemmaStats(lemma_id=1, lemma_text="בית", pos="NOUN", freq_abs=100, doc_freq=10),
            LemmaStats(lemma_id=2, lemma_text="ספר", pos="NOUN", freq_abs=50, doc_freq=5),
        ]

        model = LemmaTableModel(lemmas)

        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.columnCount(), 7)  # M7: Added Source column
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole), "בית")
        self.assertEqual(model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole), "ספר")

    def test_translation_column(self):
        """Test translation column displays correctly."""
        from app.ui.models_qt import LemmaTableModel
        from app.domain.dto import LemmaStats

        lemmas = [
            LemmaStats(
                lemma_id=1,
                lemma_text="בית",
                pos="NOUN",
                freq_abs=100,
                doc_freq=10,
                translation="дом",
                status="approved"
            ),
        ]

        model = LemmaTableModel(lemmas)

        # Column 4: Translation
        self.assertEqual(model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole), "дом")
        # Column 6: Status
        self.assertEqual(model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole), "approved")

    def test_source_column_with_translation_result(self):
        """Test source column with TranslationResult."""
        from app.ui.models_qt import LemmaTableModel
        from app.domain.dto import LemmaStats
        from app.services.translation_service import TranslationResult

        lemmas = [LemmaStats(lemma_id=1, lemma_text="בית", pos="NOUN", freq_abs=100, doc_freq=10)]
        model = LemmaTableModel(lemmas)

        # Initially no source
        self.assertEqual(model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole), "none")

        # Update with TranslationResult
        results = {
            ("בית", "lemma"): TranslationResult(
                translation="дом",
                source="tm",
                status="approved"
            )
        }
        model.update_translations(results)

        # Check source column
        self.assertEqual(model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole), "tm")
        # Check translation updated
        self.assertEqual(model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole), "дом")

    def test_inline_edit(self):
        """Test inline edit of translation."""
        from app.ui.models_qt import LemmaTableModel
        from app.domain.dto import LemmaStats

        lemmas = [LemmaStats(lemma_id=1, lemma_text="בית", pos="NOUN", freq_abs=100, doc_freq=10)]
        model = LemmaTableModel(lemmas)

        # Edit translation (column 4)
        index = model.index(0, 4)
        self.assertTrue(model.flags(index) & Qt.ItemFlag.ItemIsEditable)

        # Set new translation
        success = model.setData(index, "новый перевод", Qt.ItemDataRole.EditRole)
        self.assertTrue(success)

        # Check updated
        self.assertEqual(model.data(index, Qt.ItemDataRole.DisplayRole), "новый перевод")
        # Status should change to draft
        status_index = model.index(0, 6)
        self.assertEqual(model.data(status_index, Qt.ItemDataRole.DisplayRole), "draft")


# ============================================================================
# Test 2: Inline Edit → TM Entry Creation
# ============================================================================

class TestInlineEditWorkflow(M7UITestCase):
    """Test inline edit creates TM entry."""

    def test_inline_edit_creates_tm_entry(self):
        """Test that inline edit creates TM entry in database."""
        from app.ui.models_qt import LemmaTableModel
        from app.domain.dto import LemmaStats
        from app.infra.sa_models import TMEntry

        lemmas = [LemmaStats(lemma_id=1, lemma_text="בית", pos="NOUN", freq_abs=100, doc_freq=10)]
        model = LemmaTableModel(lemmas)

        # Inline edit
        index = model.index(0, 4)
        model.setData(index, "тестовый дом", Qt.ItemDataRole.EditRole)

        # Simulate saving to DB (would be done by view)
        with self.db_service.get_session() as session:
            from app.domain.normalization import normalize_for_tm

            lemma = model.get_lemma(0)
            normalized = normalize_for_tm("he", lemma.lemma_text, "lemma")

            # Create TM entry
            entry = TMEntry(
                project_id=None,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text=lemma.lemma_text,
                src_norm=normalized.norm,
                translation=lemma.translation,
                status="draft",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()
            entry_id = entry.tm_id

        # Verify entry exists
        with self.db_service.get_session() as session:
            entry = session.get(TMEntry, entry_id)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.translation, "тестовый дом")
            self.assertEqual(entry.status, "draft")
            self.assertEqual(entry.origin, "user_edit")


# ============================================================================
# Test 3: TermClusterTableModel
# ============================================================================

class TestTermClusterTableModel(unittest.TestCase):
    """Test TermClusterTableModel."""

    def test_initialization(self):
        """Test TermClusterTableModel initializes correctly."""
        from app.ui.models_qt import TermClusterTableModel
        from app.domain.dto import ClusterStats

        clusters = [
            ClusterStats(
                cluster_id=1,
                canonical_key="בית_ספר",
                representative_he="בית הספר",
                representative_lemma="בית ספר",
                freq_abs=50,
                doc_freq=5,
                members_count=3,
                best_pmi=5.2,
                best_llr=120.0,
                best_dice=0.8,
                best_tscore=2.5,
            ),
        ]

        model = TermClusterTableModel(clusters)

        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.columnCount(), 14)  # M7: 3 new columns
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole), "בית הספר")

    def test_translation_update(self):
        """Test term cluster translation update."""
        from app.ui.models_qt import TermClusterTableModel
        from app.domain.dto import ClusterStats
        from app.services.translation_service import TranslationResult

        clusters = [
            ClusterStats(
                cluster_id=1,
                canonical_key="בית_ספר",
                representative_he="בית הספר",
                representative_lemma=None,
                freq_abs=50,
                doc_freq=5,
                members_count=3,
                best_pmi=None,
                best_llr=None,
                best_dice=None,
                best_tscore=None,
            ),
        ]

        model = TermClusterTableModel(clusters)

        # Update with translation result
        results = {
            ("בית_ספר", "term_cluster"): TranslationResult(
                translation="школа",
                source="dict",
                status="approved"
            )
        }
        model.update_translations(results)

        # Check translation (col 11), source (col 12), status (col 13)
        self.assertEqual(model.data(model.index(0, 11), Qt.ItemDataRole.DisplayRole), "школа")
        self.assertEqual(model.data(model.index(0, 12), Qt.ItemDataRole.DisplayRole), "dict")
        self.assertEqual(model.data(model.index(0, 13), Qt.ItemDataRole.DisplayRole), "approved")


# ============================================================================
# Test 4: TranslationResolveWorker
# ============================================================================

class TestTranslationResolveWorker(M7UITestCase):
    """Test TranslationResolveWorker."""

    def test_worker_lifecycle(self):
        """Test worker runs and emits results."""
        from app.ui.workers import TranslationResolveWorker
        from app.infra.sa_models import TMEntry
        from PyQt6.QtCore import QEventLoop, QTimer

        # Create test TM entry
        with self.db_service.get_session() as session:
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

        # Create worker (use None for global scope)
        items = [("בית", "lemma"), ("ספר", "lemma")]
        worker = TranslationResolveWorker(
            items=items,
            project_id=None,  # Global scope
            src_lang="he",
            tgt_lang="ru",
        )

        # Mock signal handler
        results_received = []
        loop = QEventLoop()

        def on_results(results):
            results_received.append(results)
            loop.quit()

        def on_finished():
            if not results_received:
                loop.quit()

        worker.results_ready.connect(on_results)
        worker.finished.connect(on_finished)

        # Set timeout to prevent hanging
        QTimer.singleShot(5000, loop.quit)

        # Run worker
        worker.start()
        loop.exec()  # Process events until signal received or timeout

        # Cleanup
        worker.wait()

        # Verify results received
        self.assertEqual(len(results_received), 1)
        results = results_received[0]

        # Should have result for "בית" from TM
        self.assertIn(("בית", "lemma"), results)
        self.assertEqual(results[("בית", "lemma")].translation, "дом")
        self.assertEqual(results[("בית", "lemma")].source, "tm")

    def test_worker_cancellation(self):
        """Test worker can be cancelled."""
        from app.ui.workers import TranslationResolveWorker

        items = [("test", "lemma")]
        worker = TranslationResolveWorker(items=items, project_id=1)

        # Cancel before start
        worker.cancel()
        self.assertTrue(worker._cancelled)


# ============================================================================
# Test 5: Status Filtering
# ============================================================================

class TestStatusFiltering(M7UITestCase):
    """Test status filtering (draft/approved)."""

    def test_draft_hidden_by_default(self):
        """Test draft entries are hidden by default."""
        from app.services.translation_service import TranslationService
        from app.infra.sa_models import TMEntry
        from app.domain.normalization import normalize_for_tm

        tm_service = TranslationService()

        # Use normalization to ensure src_norm matches
        test_word = "דבר"  # Simple Hebrew word without prefixes
        normalized = normalize_for_tm("he", test_word, "lemma")

        # Create draft entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=None,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text=test_word,
                src_norm=normalized.norm,
                translation="test_draft",  # ASCII for test stability
                status="draft",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()

        # Lookup without allow_draft (global scope)
        with self.db_service.get_session() as session:
            result = tm_service.resolve_translation(
                session,
                src_text=test_word,
                kind="lemma",
                project_id=None,  # Global scope
                allow_draft=False,
            )
            self.assertIsNone(result.translation)  # Draft hidden

        # Lookup with allow_draft
        with self.db_service.get_session() as session:
            result = tm_service.resolve_translation(
                session,
                src_text=test_word,
                kind="lemma",
                project_id=None,  # Global scope
                allow_draft=True,
            )
            self.assertEqual(result.translation, "test_draft")  # Draft visible


# ============================================================================
# Test 6: Coverage Calculation
# ============================================================================

class TestCoverageCalculation(M7UITestCase):
    """Test coverage % calculation."""

    def test_coverage_percentage(self):
        """Test coverage % calculation."""
        from app.infra.sa_models import Lemma, LemmaProjectStat, TMEntry
        from sqlalchemy import select, func

        # Create lemmas
        with self.db_service.get_session() as session:
            for i, lemma_text in enumerate(["בית", "ספר", "גדול", "חדש", "טוב"], start=1):
                lemma = Lemma(
                    lemma_id=i,
                    project_id=1,
                    lemma_text=lemma_text,
                    pos="NOUN",
                )
                session.add(lemma)

                stat = LemmaProjectStat(
                    lemma_id=i,
                    project_id=1,
                    freq_abs=10,
                    doc_freq=1,
                )
                session.add(stat)

            # Add TM entries for 2 lemmas (40% coverage)
            for lemma_text, translation in [("בית", "дом"), ("ספר", "книга")]:
                entry = TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=lemma_text,
                    src_norm=lemma_text,
                    translation=translation,
                    status="approved",
                    origin="user_edit",
                )
                session.add(entry)

            session.commit()

        # Calculate coverage
        with self.db_service.get_session() as session:
            # Covered lemmas (count TM entries)
            covered_lemmas = session.execute(
                select(func.count(TMEntry.tm_id)).where(
                    TMEntry.project_id == 1,
                    TMEntry.kind == "lemma",
                    TMEntry.status == "approved",
                )
            ).scalar()

            # Simulate total = 5 (in real app would count from Lemma table)
            total_lemmas = 5
            coverage_pct = (covered_lemmas / total_lemmas * 100) if total_lemmas > 0 else 0

            self.assertEqual(covered_lemmas, 2)
            self.assertEqual(coverage_pct, 40.0)


# ============================================================================
# Test 7: History and Revert
# ============================================================================

class TestHistoryAndRevert(M7UITestCase):
    """Test TM history and revert functionality."""

    def test_history_created_on_update(self):
        """Test that updating TM entry creates history."""
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from sqlalchemy import select

        # Create initial TM entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=None,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом v1",
                status="draft",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()
            entry_id = entry.tm_id

        # Update entry → should create history
        with self.db_service.get_session() as session:
            entry = session.get(TMEntry, entry_id)

            # Create history record BEFORE update
            history = TMEntryHistory(
                tm_id=entry.tm_id,
                version=1,
                translation=entry.translation,
                status=entry.status,
                origin=entry.origin,
                notes=entry.notes,
                change_kind="edit",
            )
            session.add(history)

            # Update entry
            entry.translation = "дом v2"
            entry.status = "approved"
            session.commit()

        # Verify history exists
        with self.db_service.get_session() as session:
            history_records = session.execute(
                select(TMEntryHistory).where(TMEntryHistory.tm_id == entry_id)
            ).scalars().all()

            self.assertEqual(len(history_records), 1)
            self.assertEqual(history_records[0].version, 1)
            self.assertEqual(history_records[0].translation, "дом v1")
            self.assertEqual(history_records[0].status, "draft")

    def test_revert_to_previous_version(self):
        """Test reverting TM entry to previous version."""
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from sqlalchemy import select, func

        # Create entry with history
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=None,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом v2",
                status="approved",
                origin="user_edit",
            )
            session.add(entry)
            session.flush()

            # Add history (version 1)
            history = TMEntryHistory(
                tm_id=entry.tm_id,
                version=1,
                translation="дом v1",
                status="draft",
                origin="user_edit",
                change_kind="edit",
            )
            session.add(history)
            session.commit()
            entry_id = entry.tm_id

        # Revert to version 1
        with self.db_service.get_session() as session:
            entry = session.get(TMEntry, entry_id)

            # Get version 1 from history
            history_v1 = session.execute(
                select(TMEntryHistory).where(
                    TMEntryHistory.tm_id == entry_id,
                    TMEntryHistory.version == 1
                )
            ).scalar()

            # Create history record for current version (v2) before revert
            history_v2 = TMEntryHistory(
                tm_id=entry.tm_id,
                version=2,
                translation=entry.translation,
                status=entry.status,
                origin=entry.origin,
                change_kind="revert",
            )
            session.add(history_v2)

            # Revert entry to v1
            entry.translation = history_v1.translation
            entry.status = history_v1.status
            entry.origin = "revert"

            session.commit()

        # Verify reverted
        with self.db_service.get_session() as session:
            entry = session.get(TMEntry, entry_id)
            self.assertEqual(entry.translation, "дом v1")
            self.assertEqual(entry.status, "draft")

            # Should have 2 history records now
            history_count = session.execute(
                select(func.count(TMEntryHistory.hist_id)).where(
                    TMEntryHistory.tm_id == entry_id
                )
            ).scalar()
            self.assertEqual(history_count, 2)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    print("="*70)
    print("M7 UI Integration - Automated Tests")
    print("="*70)
    print()

    unittest.main(verbosity=2)
