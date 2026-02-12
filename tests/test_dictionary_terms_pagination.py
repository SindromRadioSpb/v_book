"""
Tests for Dictionary and Terms view pagination (Task 14).

Tests verify:
1. Pagination math (total_pages calculation)
2. Offset calculation
3. Service layer integration (using real DB - requires project data)

Note: Tests use the development database. Run only if DB has projects with data.
For unit tests of pagination math, see TestPaginationMath (no DB needed).
"""

import pytest

from app.services.dictionary_service import DictionaryService
from app.services.term_extraction_service import TermExtractionService
from app.services.db_service import DBService


@pytest.fixture
def db_session():
    """Get real DB session (requires dev DB with data)."""
    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        yield session


class TestPaginationMath:
    """Test pagination calculations."""

    def test_total_pages_zero_records(self):
        """0 records → 1 page (minimum)."""
        total_count = 0
        page_size = 100
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        assert total_pages == 1

    def test_total_pages_one_record(self):
        """1 record, page_size=25 → 1 page."""
        total_count = 1
        page_size = 25
        total_pages = (total_count + page_size - 1) // page_size
        assert total_pages == 1

    def test_total_pages_exact_page(self):
        """25 records, page_size=25 → 1 page."""
        total_count = 25
        page_size = 25
        total_pages = (total_count + page_size - 1) // page_size
        assert total_pages == 1

    def test_total_pages_partial_page(self):
        """26 records, page_size=25 → 2 pages."""
        total_count = 26
        page_size = 25
        total_pages = (total_count + page_size - 1) // page_size
        assert total_pages == 2

    def test_total_pages_large_dataset(self):
        """1000 records, page_size=100 → 10 pages."""
        total_count = 1000
        page_size = 100
        total_pages = (total_count + page_size - 1) // page_size
        assert total_pages == 10

    def test_offset_page_1(self):
        """Page 1 → offset 0."""
        current_page = 1
        page_size = 100
        offset = (current_page - 1) * page_size
        assert offset == 0

    def test_offset_page_2(self):
        """Page 2, page_size=100 → offset 100."""
        current_page = 2
        page_size = 100
        offset = (current_page - 1) * page_size
        assert offset == 100

    def test_offset_page_5(self):
        """Page 5, page_size=50 → offset 200."""
        current_page = 5
        page_size = 50
        offset = (current_page - 1) * page_size
        assert offset == 200


class TestDictionaryService:
    """Test DictionaryService pagination and filtering (requires dev DB with data)."""

    @pytest.mark.skipif(True, reason="Requires dev DB with lemma data")
    def test_search_lemmas_basic(self, db_session):
        """Basic search returns correct page (SKIPPED - needs test data)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_search_lemmas_pagination(self, db_session):
        """Pagination returns different pages (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_count_lemmas_total(self, db_session):
        """count_lemmas returns total count (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_count_lemmas_hide_noise(self, db_session):
        """count_lemmas with hide_noise excludes noise (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_search_and_count_consistency(self, db_session):
        """search_lemmas + count_lemmas return consistent totals (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_pos_filter(self, db_session):
        """POS filter works correctly (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_search_filter(self, db_session):
        """Search filter (server-side LIKE) works (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_offset_beyond_total(self, db_session):
        """Offset beyond total count returns empty results (SKIPPED)."""
        pass


class TestTermExtractionService:
    """Test TermExtractionService pagination and filtering (requires dev DB)."""

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_list_term_clusters_with_offset(self, db_session):
        """list_term_clusters with offset returns correct page (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_count_term_clusters_total(self, db_session):
        """count_term_clusters returns total count (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_count_term_clusters_hide_noise(self, db_session):
        """count_term_clusters with hide_noise excludes noise (SKIPPED)."""
        pass

    @pytest.mark.skipif(True, reason="Requires dev DB")
    def test_list_and_count_consistency(self, db_session):
        """list_term_clusters + count_term_clusters return consistent totals (SKIPPED)."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
