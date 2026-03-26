"""V09 — Extraction modes validation (C09).

Tests state transitions for Full Overwrite / Merge / Replace Layer modes,
store_hapax storage semantics, idempotency, and TM preservation invariant.

No Stanza required. Uses In-Memory SQLite + TermExtractAccumulator seeding.
The finalization phase (_store_staged_ngrams → _cluster_terms) is called
directly, bypassing the NLP collection stage.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    Ngram,
    TermCluster,
    TermExtractAccumulator,
    TermExtractRun,
    TMEntry,
)
from app.services.term_extraction_service import TermExtractionService, canonical_ngram_n_set


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="Test Lib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(
        project_id=1,
        library_id=1,
        name="C09 Test Project",
        src_lang="he",
        tgt_lang="ru",
    )
    sess.add(proj)
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


@pytest.fixture
def svc() -> TermExtractionService:
    s = TermExtractionService.__new__(TermExtractionService)
    s._engine = None  # prevent AttributeError when NLP engine path is not taken
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_cluster(sess, project_id: int, key: str, ngram_n_set: str | None, freq: int = 3) -> int:
    """Insert a TermCluster and return its cluster_id."""
    c = TermCluster(
        project_id=project_id,
        canonical_key=key,
        representative_he=key,
        freq_abs=freq,
        doc_freq=1,
        source_kinds="ngram" if ngram_n_set else "np",
        ngram_n_set=ngram_n_set,
    )
    sess.add(c)
    sess.commit()
    return int(c.cluster_id)


def _add_tm_entry(sess, project_id: int, key: str) -> int:
    """Insert a TMEntry and return its entry_id."""
    entry = TMEntry(
        project_id=project_id,
        kind="ngram",
        src_lang="he",
        tgt_lang="ru",
        src_text=key,
        src_norm=key,
        translation="translation",
        status="draft",
        origin="user_edit",
    )
    sess.add(entry)
    sess.commit()
    return int(entry.tm_id)


def _make_run(sess, project_id: int, ngram_ns_json: str) -> TermExtractRun:
    """Create a TermExtractRun in 'staged' status."""
    r = TermExtractRun(
        project_id=project_id,
        status="staged",
        stage="test",
        enable_ngrams=1,
        include_np=0,
        overwrite=1,
        min_freq=2,
        ngram_ns_json=ngram_ns_json,
        np_max_len=5,
        docs_total=1,
        docs_processed=1,
        chunks_total=1,
        chunks_completed=1,
    )
    sess.add(r)
    sess.commit()
    return r


def _acc(
    sess,
    run_id: int,
    surface: str,
    n: int,
    freq: int = 3,
    doc_freq: int = 2,
) -> None:
    """Insert a TermExtractAccumulator row."""
    sess.add(
        TermExtractAccumulator(
            run_id=run_id,
            source_kind="ngram",
            n=n,
            surface_text=surface,
            lemma_phrase=surface,
            pos_pattern="NOUN " * n,
            freq_abs=freq,
            doc_freq=doc_freq,
        )
    )
    sess.commit()


def _cluster_ids(sess, project_id: int) -> set[int]:
    return set(
        sess.execute(select(TermCluster.cluster_id).where(TermCluster.project_id == project_id))
        .scalars()
        .all()
    )


def _cluster_n_sets(sess, project_id: int) -> set[str | None]:
    return set(
        sess.execute(select(TermCluster.ngram_n_set).where(TermCluster.project_id == project_id))
        .scalars()
        .all()
    )


def _ngram_surfaces(sess, project_id: int) -> set[str]:
    return set(
        sess.execute(select(Ngram.surface_text).where(Ngram.project_id == project_id))
        .scalars()
        .all()
    )


def _tm_count(sess, project_id: int) -> int:
    return sess.execute(select(func.count()).where(TMEntry.project_id == project_id)).scalar_one()


def _finalize(
    svc: TermExtractionService,
    session,
    project_id: int,
    run_id: int,
    *,
    overwrite: bool = True,
    store_hapax: bool = True,
) -> None:
    """Run finalization: store staged ngrams → cluster terms."""
    svc._store_staged_ngrams(
        session,
        project_id,
        run_id=run_id,
        total_tokens=1000,
        overwrite=overwrite,
        store_hapax=store_hapax,
    )
    svc._cluster_terms(session, project_id, overwrite=overwrite)


# ---------------------------------------------------------------------------
# S01 — Full Overwrite clears previous state before re-extraction
# ---------------------------------------------------------------------------


class TestS01_FullOverwrite:
    def test_overwrite_clears_all_existing_clusters(self, svc, session):
        """C09/S01: overwrite mode deletes all pre-existing clusters."""
        bigram_id = _add_cluster(session, 1, "old_bigram", canonical_ngram_n_set([2]))
        trigram_id = _add_cluster(session, 1, "old_trigram", canonical_ngram_n_set([3]))

        svc._clear_existing_terms(session, 1)

        assert _cluster_ids(session, 1) == set(), "overwrite must delete all clusters"

    def test_overwrite_then_finalize_produces_new_clusters(self, svc, session):
        """C09/S01: after clear, finalization inserts freshly staged clusters."""
        _add_cluster(session, 1, "old_cluster", canonical_ngram_n_set([2]))

        svc._clear_existing_terms(session, 1)

        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "בית ספר", n=2, freq=5)
        _finalize(svc, session, 1, run.run_id, overwrite=True)

        surfaces = _ngram_surfaces(session, 1)
        assert "בית ספר" in surfaces, f"New bigram must be stored; found: {surfaces}"

    def test_overwrite_clears_ngrams_too(self, svc, session):
        """C09/S01: overwrite deletes both clusters AND ngrams."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "ילד גדול", n=2, freq=3)
        _finalize(svc, session, 1, run.run_id, overwrite=True)

        pre_count = len(_ngram_surfaces(session, 1))
        assert pre_count > 0

        svc._clear_existing_terms(session, 1)

        assert _ngram_surfaces(session, 1) == set(), "overwrite must delete all ngrams"


# ---------------------------------------------------------------------------
# S02 — Merge preserves existing clusters
# ---------------------------------------------------------------------------


class TestS02_MergePreservesExisting:
    def test_merge_does_not_delete_existing_clusters(self, svc, session):
        """C09/S02: merge mode must NOT call _clear_existing_terms."""
        existing_id = _add_cluster(session, 1, "existing_cluster", canonical_ngram_n_set([2]))

        # Zero-docs path for merge: no accumulator rows → nothing added, nothing removed
        svc.extract_terms_for_project(
            session,
            project_id=1,
            extraction_mode="merge",
            ngram_ns=(2,),
            enable_ngrams=True,
            include_np=False,
        )

        remaining = _cluster_ids(session, 1)
        assert (
            existing_id in remaining
        ), f"merge must preserve existing cluster {existing_id}; remaining: {remaining}"

    def test_merge_adds_new_clusters_alongside_existing(self, svc, session):
        """C09/S02: merge adds new staged clusters without removing old ones."""
        existing_id = _add_cluster(session, 1, "old_key", canonical_ngram_n_set([2]))

        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "מדינת ישראל", n=2, freq=4)
        _finalize(svc, session, 1, run.run_id, overwrite=False)

        remaining = _cluster_ids(session, 1)
        assert existing_id in remaining, "existing cluster must be preserved by merge"
        assert len(remaining) >= 2, f"new cluster must have been added; ids: {remaining}"

    def test_merge_does_not_overwrite_existing_ngram(self, svc, session):
        """C09/S02: merging a duplicate surface keeps the original (INSERT OR IGNORE)."""
        run1 = _make_run(session, 1, "[2]")
        _acc(session, run1.run_id, "בית ספר", n=2, freq=10)
        _finalize(svc, session, 1, run1.run_id, overwrite=True)

        initial_ngrams = _ngram_surfaces(session, 1)
        initial_clusters = _cluster_ids(session, 1)

        run2 = _make_run(session, 1, "[2]")
        _acc(session, run2.run_id, "בית ספר", n=2, freq=99)  # same surface, diff freq
        _finalize(svc, session, 1, run2.run_id, overwrite=False)

        # Surface must still exist, cluster count unchanged
        final_ngrams = _ngram_surfaces(session, 1)
        assert final_ngrams == initial_ngrams, "merge must not add duplicate ngrams"


# ---------------------------------------------------------------------------
# S03 — Replace Layer preserves other-layer clusters
# ---------------------------------------------------------------------------


class TestS03_ReplaceLayerPreservesOtherLayers:
    def test_replace_bigrams_preserves_trigram_clusters(self, svc, session):
        """C09/S03: replace_layer([2]) must not touch trigram clusters."""
        _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
        trigram_id = _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

        svc._clear_terms_for_layer(session, 1, ngram_ns=(2,))

        remaining_n_sets = _cluster_n_sets(session, 1)
        assert (
            canonical_ngram_n_set([3]) in remaining_n_sets
        ), f"Trigram clusters must be preserved; remaining: {remaining_n_sets}"

    def test_replace_bigrams_removes_bigram_clusters(self, svc, session):
        """C09/S03: replace_layer([2]) must remove bigram clusters."""
        bigram_id = _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
        _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

        svc._clear_terms_for_layer(session, 1, ngram_ns=(2,))

        remaining_n_sets = _cluster_n_sets(session, 1)
        assert (
            canonical_ngram_n_set([2]) not in remaining_n_sets
        ), f"Bigram clusters must be cleared; remaining: {remaining_n_sets}"

    def test_replace_bigrams_preserves_np_clusters(self, svc, session):
        """C09/S03: replace_layer([2]) must not touch NP clusters (ngram_n_set IS NULL)."""
        _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
        np_id = _add_cluster(session, 1, "np_cluster", ngram_n_set=None)

        svc._clear_terms_for_layer(session, 1, ngram_ns=(2,))

        remaining = _cluster_ids(session, 1)
        assert (
            np_id in remaining
        ), f"NP clusters (ngram_n_set=None) must be preserved; remaining: {remaining}"

    def test_replace_layer_full_overwrite_does_not_preserve_trigrams(self, svc, session):
        """S01 vs S03: overwrite clears ALL; replace_layer preserves other layers."""
        _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
        trigram_id = _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

        # Overwrite (not replace_layer) → trigram must also be gone
        svc._clear_existing_terms(session, 1)

        assert trigram_id not in _cluster_ids(
            session, 1
        ), "Full Overwrite must delete trigrams too (contrast with replace_layer)"


# ---------------------------------------------------------------------------
# S04 — store_hapax=False: hapax not stored in DB
# ---------------------------------------------------------------------------


class TestS04_StoreHapaxOff:
    def test_hapax_not_stored_when_store_hapax_false(self, svc, session):
        """C09/S04: freq_abs=1 rows must NOT appear in ngram table when store_hapax=False."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "נדיר מאוד", n=2, freq=1)  # hapax
        _acc(session, run.run_id, "בית ספר", n=2, freq=5)  # non-hapax

        _finalize(svc, session, 1, run.run_id, store_hapax=False)

        surfaces = _ngram_surfaces(session, 1)
        assert (
            "נדיר מאוד" not in surfaces
        ), f"Hapax (freq=1) must not be stored when store_hapax=False; stored: {surfaces}"

    def test_non_hapax_stored_when_store_hapax_false(self, svc, session):
        """C09/S04: freq_abs>=2 rows ARE stored even when store_hapax=False."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "נדיר מאוד", n=2, freq=1)
        _acc(session, run.run_id, "בית ספר", n=2, freq=5)

        _finalize(svc, session, 1, run.run_id, store_hapax=False)

        surfaces = _ngram_surfaces(session, 1)
        assert (
            "בית ספר" in surfaces
        ), f"Non-hapax (freq=5) must be stored regardless of store_hapax; stored: {surfaces}"

    def test_all_hapax_excluded_when_store_hapax_false(self, svc, session):
        """C09/S04: if ALL staged rows are hapax and store_hapax=False, DB has 0 ngrams."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "אחד שתיים", n=2, freq=1)
        _acc(session, run.run_id, "שלש ארבע", n=2, freq=1)

        _finalize(svc, session, 1, run.run_id, store_hapax=False)

        surfaces = _ngram_surfaces(session, 1)
        assert (
            len(surfaces) == 0
        ), f"All hapax + store_hapax=False must produce empty ngram table; stored: {surfaces}"


# ---------------------------------------------------------------------------
# S05 — store_hapax=True: hapax stored, min_freq is display-only
# ---------------------------------------------------------------------------


class TestS05_StoreHapaxOn:
    def test_hapax_stored_when_store_hapax_true(self, svc, session):
        """C09/S05: freq_abs=1 rows ARE stored when store_hapax=True."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "נדיר מאוד", n=2, freq=1)
        _acc(session, run.run_id, "בית ספר", n=2, freq=5)

        _finalize(svc, session, 1, run.run_id, store_hapax=True)

        surfaces = _ngram_surfaces(session, 1)
        assert (
            "נדיר מאוד" in surfaces
        ), f"Hapax must be stored when store_hapax=True; stored: {surfaces}"

    def test_min_freq_is_not_a_storage_gate(self, svc, session):
        """C09/S05: min_freq does NOT affect what is stored — only display filtering."""
        run = _make_run(session, 1, "[2]")
        _acc(session, run.run_id, "פעם אחת", n=2, freq=1)

        # store_hapax=True: hapax must be stored regardless of any min_freq display param
        _finalize(svc, session, 1, run.run_id, store_hapax=True)

        surfaces = _ngram_surfaces(session, 1)
        assert (
            "פעם אחת" in surfaces
        ), "Hapax must be in DB even though min_freq=2 display filter would hide it"

    def test_store_hapax_true_stores_more_than_false(self, svc, session):
        """C09/S05: store_hapax=True stores strictly more rows than store_hapax=False."""
        # Run with store_hapax=False
        run_a = _make_run(session, 1, "[2]")
        _acc(session, run_a.run_id, "נדיר מאוד", n=2, freq=1)
        _acc(session, run_a.run_id, "בית ספר", n=2, freq=5)
        _finalize(svc, session, 1, run_a.run_id, store_hapax=False)
        count_false = len(_ngram_surfaces(session, 1))

        svc._clear_existing_terms(session, 1)

        # Run with store_hapax=True (same data)
        run_b = _make_run(session, 1, "[2]")
        _acc(session, run_b.run_id, "נדיר מאוד", n=2, freq=1)
        _acc(session, run_b.run_id, "בית ספר", n=2, freq=5)
        _finalize(svc, session, 1, run_b.run_id, store_hapax=True)
        count_true = len(_ngram_surfaces(session, 1))

        assert count_true > count_false, (
            f"store_hapax=True should store more rows; " f"False={count_false}, True={count_true}"
        )


# ---------------------------------------------------------------------------
# S06 — Idempotency: Full Overwrite twice = same result
# ---------------------------------------------------------------------------


class TestS06_OverwriteIdempotency:
    def test_overwrite_twice_produces_same_ngrams(self, svc, session):
        """C09/S06: Full Overwrite run twice on identical input → identical ngram set."""

        def _run_extraction():
            svc._clear_existing_terms(session, 1)
            run = _make_run(session, 1, "[2]")
            _acc(session, run.run_id, "בית ספר", n=2, freq=5)
            _acc(session, run.run_id, "ילד גדול", n=2, freq=3)
            _finalize(svc, session, 1, run.run_id, overwrite=True)
            return _ngram_surfaces(session, 1)

        result1 = _run_extraction()
        result2 = _run_extraction()

        assert result1 == result2, f"Idempotency violated: run1={result1}, run2={result2}"

    def test_overwrite_twice_produces_same_cluster_count(self, svc, session):
        """C09/S06: cluster count after second overwrite equals first run."""

        def _run_and_count():
            svc._clear_existing_terms(session, 1)
            run = _make_run(session, 1, "[2]")
            _acc(session, run.run_id, "בית ספר", n=2, freq=5)
            _finalize(svc, session, 1, run.run_id, overwrite=True)
            return len(_cluster_ids(session, 1))

        count1 = _run_and_count()
        count2 = _run_and_count()

        assert count1 == count2, f"Cluster count not idempotent: first={count1}, second={count2}"

    def test_zero_docs_overwrite_is_idempotent(self, svc, session):
        """C09/S06: zero-docs overwrite path is idempotent (starts and ends empty)."""
        svc.extract_terms_for_project(
            session, 1, extraction_mode="overwrite", ngram_ns=(2,), enable_ngrams=True
        )
        count1 = len(_cluster_ids(session, 1))

        svc.extract_terms_for_project(
            session, 1, extraction_mode="overwrite", ngram_ns=(2,), enable_ngrams=True
        )
        count2 = len(_cluster_ids(session, 1))

        assert count1 == count2 == 0


# ---------------------------------------------------------------------------
# TM Preservation Invariant — all modes
# ---------------------------------------------------------------------------


class TestTMPreservationInvariant:
    def test_overwrite_does_not_delete_tm_entries(self, svc, session):
        """TM invariant: overwrite must never delete tm_entry rows."""
        _add_tm_entry(session, 1, "tm_term_1")
        _add_tm_entry(session, 1, "tm_term_2")

        before = _tm_count(session, 1)
        assert before == 2

        svc._clear_existing_terms(session, 1)

        after = _tm_count(session, 1)
        assert after == before, (
            f"overwrite (_clear_existing_terms) must not touch tm_entry; "
            f"before={before}, after={after}"
        )

    def test_replace_layer_does_not_delete_tm_entries(self, svc, session):
        """TM invariant: replace_layer must never delete tm_entry rows."""
        _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
        _add_tm_entry(session, 1, "tm_bigram_term")

        before = _tm_count(session, 1)
        svc._clear_terms_for_layer(session, 1, ngram_ns=(2,))
        after = _tm_count(session, 1)

        assert (
            after == before
        ), f"replace_layer must not touch tm_entry; before={before}, after={after}"

    def test_merge_does_not_delete_tm_entries(self, svc, session):
        """TM invariant: merge mode must never delete tm_entry rows."""
        _add_tm_entry(session, 1, "tm_term")
        before = _tm_count(session, 1)

        svc.extract_terms_for_project(
            session, 1, extraction_mode="merge", ngram_ns=(2,), enable_ngrams=True
        )

        after = _tm_count(session, 1)
        assert after == before, f"merge must not touch tm_entry; before={before}, after={after}"

    def test_all_modes_preserve_tm_entries(self, svc, session):
        """TM invariant: all three modes leave TM count unchanged."""
        _add_tm_entry(session, 1, "key_A")
        _add_tm_entry(session, 1, "key_B")
        initial_count = _tm_count(session, 1)

        for mode in ("overwrite", "merge", "replace_layer"):
            svc.extract_terms_for_project(
                session, 1, extraction_mode=mode, ngram_ns=(2,), enable_ngrams=True
            )
            count = _tm_count(session, 1)
            assert count == initial_count, (
                f"Mode '{mode}' must not delete tm_entry rows; "
                f"expected={initial_count}, got={count}"
            )
