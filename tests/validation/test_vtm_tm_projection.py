"""CTM — TM projection validation.

Validates materialize_project_lemmas_to_tm: the explicit pathway that creates
tm_entry rows from Lemma rows.

Key finding from Wave 1 repo audit:
    TermExtractionService does NOT create tm_entry rows.
    TM projection is a separate, explicitly-triggered step.
    Only kind='lemma' has a bulk materialization function.
    kind='term_cluster' has no equivalent — documented as architectural gap.

No Stanza required. Uses In-Memory SQLite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Lemma,
    Library,
    TMEntry,
)
from app.services.translation_admin_service import TranslationAdminService


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
    lib = Library(name="TestLib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(
        library_id=lib.library_id,
        name="TestProject",
        src_lang="he",
        tgt_lang="ru",
    )
    sess.add(proj)
    sess.commit()
    yield sess
    sess.close()


@pytest.fixture
def project_id(session) -> int:
    return int(session.execute(select(DictProject.project_id)).scalar_one())


@pytest.fixture
def svc() -> TranslationAdminService:
    return TranslationAdminService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_lemma(
    sess,
    project_id: int,
    text: str,
    norm: str | None = None,
    is_noise: int = 0,
    noise_reason: str | None = None,
) -> int:
    lemma = Lemma(
        project_id=project_id,
        lemma_text=text,
        norm_text=norm,
        is_noise=is_noise,
        noise_reason=noise_reason,
    )
    sess.add(lemma)
    sess.commit()
    return int(lemma.lemma_id)


def _tm_entries(sess, project_id: int) -> list[TMEntry]:
    return sess.execute(select(TMEntry).where(TMEntry.project_id == project_id)).scalars().all()


def _tm_count(sess, project_id: int) -> int:
    return sess.execute(select(func.count()).where(TMEntry.project_id == project_id)).scalar_one()


def _get_tm_for_lemma(sess, project_id: int, lemma_id: int) -> TMEntry | None:
    return sess.execute(
        select(TMEntry).where(
            TMEntry.project_id == project_id,
            TMEntry.lemma_id == lemma_id,
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# STM01 — Basic creation
# ---------------------------------------------------------------------------


class TestSTM01_BasicCreation:
    def test_creates_correct_count(self, session, project_id, svc):
        """3 lemmas → 3 tm_entry rows after materialization."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        _add_lemma(session, project_id, "גדול", norm="גדול")
        _add_lemma(session, project_id, "ספר", norm="ספר")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        assert _tm_count(session, project_id) == 3

    def test_kind_is_lemma(self, session, project_id, svc):
        """All created tm_entry rows have kind='lemma'."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert all(e.kind == "lemma" for e in entries)

    def test_status_is_draft(self, session, project_id, svc):
        """All created tm_entry rows have status='draft'."""
        _add_lemma(session, project_id, "ספר", norm="ספר")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert all(e.status == "draft" for e in entries)

    def test_origin_is_import(self, session, project_id, svc):
        """All created tm_entry rows have origin='import'."""
        _add_lemma(session, project_id, "בית", norm="בית")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert all(e.origin == "import" for e in entries)

    def test_langs_from_project(self, session, project_id, svc):
        """src_lang='he', tgt_lang='ru' come from project definition."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert all(e.src_lang == "he" for e in entries)
        assert all(e.tgt_lang == "ru" for e in entries)

    def test_translation_is_empty_string(self, session, project_id, svc):
        """Materialized entries start with empty translation (not NULL)."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert all(e.translation == "" for e in entries)

    def test_src_text_equals_lemma_text(self, session, project_id, svc):
        """src_text = lemma.lemma_text (original surface form)."""
        _add_lemma(session, project_id, "בתים", norm="בית")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].src_text == "בתים"


# ---------------------------------------------------------------------------
# STM02/STM03 — src_norm field
# ---------------------------------------------------------------------------


class TestSTM02_SrcNorm:
    def test_src_norm_fallback_when_norm_text_null(self, session, project_id, svc):
        """When norm_text is null, src_norm = lemma_text."""
        _add_lemma(session, project_id, "מדינה", norm=None)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].src_norm == "מדינה"

    def test_src_norm_uses_norm_text_when_set(self, session, project_id, svc):
        """When norm_text is set, src_norm = norm_text (not lemma_text)."""
        _add_lemma(session, project_id, "בתים", norm="בית")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].src_norm == "בית"
        assert entries[0].src_text == "בתים"  # src_text unchanged

    def test_src_norm_fallback_when_norm_text_empty_string(self, session, project_id, svc):
        """When norm_text is empty string (whitespace stripped), src_norm = lemma_text."""
        _add_lemma(session, project_id, "ילד", norm="   ")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        # coalesce(nullif(trim('   '), ''), lemma_text) → lemma_text
        assert entries[0].src_norm == "ילד"


# ---------------------------------------------------------------------------
# STM04 — Noise propagation
# ---------------------------------------------------------------------------


class TestSTM04_NoisePropagation:
    def test_is_noise_propagated(self, session, project_id, svc):
        """lemma.is_noise=1 → tm_entry.is_noise=1."""
        _add_lemma(
            session, project_id, "123", is_noise=1, noise_reason="NOISE_RATIO_NON_LETTER_HIGH"
        )
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].is_noise == 1

    def test_noise_reason_propagated(self, session, project_id, svc):
        """lemma.noise_reason → tm_entry.noise_reason."""
        _add_lemma(
            session, project_id, "123", is_noise=1, noise_reason="NOISE_RATIO_NON_LETTER_HIGH"
        )
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].noise_reason == "NOISE_RATIO_NON_LETTER_HIGH"

    def test_non_noise_lemma_has_is_noise_zero(self, session, project_id, svc):
        """Normal lemma → tm_entry.is_noise=0, noise_reason=None."""
        _add_lemma(session, project_id, "ילד", norm="ילד", is_noise=0)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        assert entries[0].is_noise == 0
        assert entries[0].noise_reason is None


# ---------------------------------------------------------------------------
# STM05 — Idempotency
# ---------------------------------------------------------------------------


class TestSTM05_Idempotency:
    def test_double_materialize_no_duplicates(self, session, project_id, svc):
        """Calling materialize twice produces same count — INSERT OR IGNORE."""
        _add_lemma(session, project_id, "ירושלים", norm="ירושלים")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        count_after_first = _tm_count(session, project_id)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        count_after_second = _tm_count(session, project_id)
        assert count_after_first == count_after_second == 1

    def test_triple_materialize_stable(self, session, project_id, svc):
        """Three runs → stable count."""
        for word in ["ילד", "גדול", "ספר"]:
            _add_lemma(session, project_id, word, norm=word)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        assert _tm_count(session, project_id) == 3


# ---------------------------------------------------------------------------
# STM06 — Only missing lemmas projected
# ---------------------------------------------------------------------------


class TestSTM06_OnlyMissingProjected:
    def test_pre_existing_tm_entry_not_duplicated(self, session, project_id, svc):
        """Pre-existing tm_entry for lemma_A not duplicated; lemma_B gets new row."""
        lemma_a_id = _add_lemma(session, project_id, "ילד", norm="ילד")
        lemma_b_id = _add_lemma(session, project_id, "גדול", norm="גדול")

        # Pre-create tm_entry for lemma_A manually
        existing = TMEntry(
            project_id=project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="ילד",
            src_norm="ילד",
            translation="child",
            status="approved",
            origin="user_edit",
            lemma_id=lemma_a_id,
        )
        session.add(existing)
        session.commit()

        assert _tm_count(session, project_id) == 1

        svc.materialize_project_lemmas_to_tm(session, project_id)

        # lemma_A entry not duplicated; lemma_B entry added
        assert _tm_count(session, project_id) == 2

    def test_pre_existing_translation_not_overwritten(self, session, project_id, svc):
        """Pre-existing tm_entry translation is NOT overwritten by materialize."""
        lemma_id = _add_lemma(session, project_id, "ילד", norm="ילד")
        existing = TMEntry(
            project_id=project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="ילד",
            src_norm="ילד",
            translation="child",
            status="approved",
            origin="user_edit",
            lemma_id=lemma_id,
        )
        session.add(existing)
        session.commit()

        svc.materialize_project_lemmas_to_tm(session, project_id)

        entry = _get_tm_for_lemma(session, project_id, lemma_id)
        assert entry is not None
        assert entry.translation == "child"  # not overwritten with ""
        assert entry.status == "approved"  # not reset to "draft"


# ---------------------------------------------------------------------------
# STM07 — Stats dict
# ---------------------------------------------------------------------------


class TestSTM07_StatsDict:
    def test_stats_has_required_keys(self, session, project_id, svc):
        """Stats dict includes all expected keys."""
        _add_lemma(session, project_id, "ספר", norm="ספר")
        stats = svc.materialize_project_lemmas_to_tm(session, project_id)
        required = {
            "project_id",
            "total_lemmas",
            "initial_tm_lemmas",
            "initial_missing_lemma_links",
            "attempted",
            "inserted",
            "processed_chunks",
            "final_tm_lemmas",
            "final_missing_lemma_links",
        }
        assert required <= set(stats.keys())

    def test_stats_inserted_count_correct(self, session, project_id, svc):
        """inserted = final_tm_lemmas - initial_tm_lemmas."""
        for word in ["ילד", "גדול"]:
            _add_lemma(session, project_id, word, norm=word)
        stats = svc.materialize_project_lemmas_to_tm(session, project_id)
        assert stats["inserted"] == 2
        assert stats["final_missing_lemma_links"] == 0

    def test_stats_total_lemmas_correct(self, session, project_id, svc):
        """total_lemmas reflects the actual lemma count."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        _add_lemma(session, project_id, "בית", norm="בית")
        stats = svc.materialize_project_lemmas_to_tm(session, project_id)
        assert stats["total_lemmas"] == 2

    def test_stats_zero_inserted_on_empty_project(self, session, project_id, svc):
        """Project with no lemmas → inserted=0, no crash."""
        stats = svc.materialize_project_lemmas_to_tm(session, project_id)
        assert stats["inserted"] == 0
        assert stats["total_lemmas"] == 0


# ---------------------------------------------------------------------------
# STM08 — dry_run
# ---------------------------------------------------------------------------


class TestSTM08_DryRun:
    def test_dry_run_creates_no_rows(self, session, project_id, svc):
        """dry_run=True: no tm_entry rows created."""
        _add_lemma(session, project_id, "ילד", norm="ילד")
        svc.materialize_project_lemmas_to_tm(session, project_id, dry_run=True)
        assert _tm_count(session, project_id) == 0

    def test_dry_run_stats_show_zero_inserted(self, session, project_id, svc):
        """dry_run=True: stats.inserted = 0."""
        _add_lemma(session, project_id, "ספר", norm="ספר")
        stats = svc.materialize_project_lemmas_to_tm(session, project_id, dry_run=True)
        assert stats["inserted"] == 0


# ---------------------------------------------------------------------------
# STM09 — lemma_id linkage
# ---------------------------------------------------------------------------


class TestSTM09_LemmaIdLinkage:
    def test_tm_entry_lemma_id_matches_lemma(self, session, project_id, svc):
        """tm_entry.lemma_id == the correct Lemma.lemma_id."""
        lemma_id = _add_lemma(session, project_id, "ירושלים", norm="ירושלים")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entry = _get_tm_for_lemma(session, project_id, lemma_id)
        assert entry is not None
        assert entry.lemma_id == lemma_id

    def test_multiple_lemmas_distinct_linkage(self, session, project_id, svc):
        """Each tm_entry.lemma_id points to a different Lemma."""
        ids = [_add_lemma(session, project_id, w, norm=w) for w in ["ילד", "גדול", "ספר"]]
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entries = _tm_entries(session, project_id)
        actual_ids = {e.lemma_id for e in entries}
        assert actual_ids == set(ids)

    def test_linkage_survives_double_materialize(self, session, project_id, svc):
        """lemma_id linkage is preserved after second materialize run."""
        lemma_id = _add_lemma(session, project_id, "בית", norm="בית")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        svc.materialize_project_lemmas_to_tm(session, project_id)
        entry = _get_tm_for_lemma(session, project_id, lemma_id)
        assert entry is not None
        assert entry.lemma_id == lemma_id


# ---------------------------------------------------------------------------
# STM10 — term_cluster architectural gap (documented, not tested)
# ---------------------------------------------------------------------------


class TestSTM10_TermClusterGapDocumented:
    def test_no_term_cluster_tm_entries_created_by_materialize(self, session, project_id, svc):
        """materialize_project_lemmas_to_tm creates ONLY kind='lemma' entries.

        There is no bulk materialize function for kind='term_cluster'.
        This test documents that the function does not produce term_cluster rows,
        confirming the architectural gap recorded in ctm_tm_projection.json.
        """
        _add_lemma(session, project_id, "ספר לימוד", norm="ספר_לימוד")
        svc.materialize_project_lemmas_to_tm(session, project_id)
        term_cluster_count = session.execute(
            select(func.count()).where(
                TMEntry.project_id == project_id,
                TMEntry.kind == "term_cluster",
            )
        ).scalar_one()
        assert term_cluster_count == 0  # by design — no bulk projection for clusters
