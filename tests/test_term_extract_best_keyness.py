"""Tests for _store_best_keyness_for_project() — Epic 4 PATCH-06.

Contracts verified:
1. Correct values stored in batches (project scoped).
2. NULL when no reference corpus configured.
3. Only target project updated — other projects untouched.
4. Partial overlap: clusters not in reference get 0-based keyness (f_r=0).
5. Repeat-run safety: correct overwrite without data corruption.
6. Empty domain project returns 0 updates without crashing.
7. Batch chunk commits — progress_callback called once per chunk.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, Library, TermCluster
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path, name: str):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    return engine


def _add_project(session: Session, lib_id: int, name: str = "proj") -> int:
    proj = DictProject(
        library_id=lib_id, name=name, src_lang="he", tgt_lang="ru", nlp_engine="mock"
    )
    session.add(proj)
    session.flush()
    return int(proj.project_id)


def _add_cluster(
    session: Session,
    project_id: int,
    canonical_key: str,
    freq_abs: int,
    best_keyness: float | None = None,
) -> int:
    c = TermCluster(
        project_id=project_id,
        canonical_key=canonical_key,
        representative_he=canonical_key,
        freq_abs=freq_abs,
        doc_freq=1,
        members_count=1,
        best_keyness=best_keyness,
    )
    session.add(c)
    session.flush()
    return int(c.cluster_id)


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    return TermExtractionService()


# ---------------------------------------------------------------------------
# 1. Correct values stored — basic happy path
# ---------------------------------------------------------------------------


def test_store_best_keyness_stores_values(svc, monkeypatch, tmp_path):
    """best_keyness is computed and stored for all domain clusters."""
    engine = _make_engine(tmp_path, "keyness_basic.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "reference")

        # Domain: 2 clusters
        _add_cluster(session, domain_id, "alpha_beta", freq_abs=10)
        _add_cluster(session, domain_id, "gamma_delta", freq_abs=5)

        # Reference: matching cluster for alpha_beta, none for gamma_delta
        _add_cluster(session, ref_id, "alpha_beta", freq_abs=3)

        session.commit()

        updated = svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        clusters = (
            session.execute(
                select(TermCluster)
                .where(TermCluster.project_id == domain_id)
                .order_by(TermCluster.canonical_key)
            )
            .scalars()
            .all()
        )

    engine.dispose()

    assert updated == 2

    alpha = next(c for c in clusters if c.canonical_key == "alpha_beta")
    gamma = next(c for c in clusters if c.canonical_key == "gamma_delta")

    # alpha_beta has a reference match → keyness > 0
    assert alpha.best_keyness is not None
    assert alpha.best_keyness > 0.0

    # gamma_delta has no reference match (f_r=0) → keyness computed with f_r=0
    # Result should still be non-NULL (0.0 is valid when computed)
    assert gamma.best_keyness is not None


# ---------------------------------------------------------------------------
# 2. NULL when domain is empty
# ---------------------------------------------------------------------------


def test_store_best_keyness_empty_domain_returns_zero(svc, tmp_path):
    """Empty domain project → 0 updates, no crash."""
    engine = _make_engine(tmp_path, "keyness_empty.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")
        _add_cluster(session, ref_id, "some_term", freq_abs=5)
        session.commit()

        updated = svc._store_best_keyness_for_project(session, domain_id, ref_id)

    engine.dispose()
    assert updated == 0


# ---------------------------------------------------------------------------
# 3. Only target project updated — other projects untouched
# ---------------------------------------------------------------------------


def test_store_best_keyness_scoped_to_project(svc, tmp_path):
    """Clusters in other projects are not modified."""
    engine = _make_engine(tmp_path, "keyness_scope.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "reference")
        other_id = _add_project(session, lib_id, "other")

        _add_cluster(session, domain_id, "term_a", freq_abs=8)
        _add_cluster(session, ref_id, "term_a", freq_abs=2)
        # other project has same canonical_key — must NOT be touched
        _add_cluster(session, other_id, "term_a", freq_abs=99, best_keyness=42.0)

        session.commit()
        svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        other_clusters = (
            session.execute(select(TermCluster).where(TermCluster.project_id == other_id))
            .scalars()
            .all()
        )

    engine.dispose()

    assert len(other_clusters) == 1
    # best_keyness must remain exactly 42.0 — not overwritten
    assert other_clusters[0].best_keyness == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# 4. Partial overlap: clusters not in reference
# ---------------------------------------------------------------------------


def test_store_best_keyness_partial_overlap(svc, tmp_path):
    """Clusters absent from reference get keyness computed with f_r=0."""
    engine = _make_engine(tmp_path, "keyness_partial.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")

        _add_cluster(session, domain_id, "in_ref", freq_abs=10)
        _add_cluster(session, domain_id, "not_in_ref", freq_abs=10)
        _add_cluster(session, ref_id, "in_ref", freq_abs=3)

        session.commit()
        updated = svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        clusters = (
            session.execute(
                select(TermCluster)
                .where(TermCluster.project_id == domain_id)
                .order_by(TermCluster.canonical_key)
            )
            .scalars()
            .all()
        )

    engine.dispose()

    assert updated == 2
    for c in clusters:
        # Both must have a non-NULL value — even those absent from reference
        assert c.best_keyness is not None, f"{c.canonical_key} has NULL keyness"


# ---------------------------------------------------------------------------
# 5. Repeat-run safety (idempotent overwrite)
# ---------------------------------------------------------------------------


def test_store_best_keyness_repeat_run_overwrites_correctly(svc, tmp_path):
    """Running _store_best_keyness_for_project twice produces consistent results."""
    engine = _make_engine(tmp_path, "keyness_repeat.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")

        _add_cluster(session, domain_id, "term_x", freq_abs=7)
        _add_cluster(session, ref_id, "term_x", freq_abs=2)

        session.commit()

        svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        # Record first-run value
        after_first = session.execute(
            select(TermCluster.best_keyness).where(TermCluster.project_id == domain_id)
        ).scalar()

        # Run again — must produce same result
        svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        after_second = session.execute(
            select(TermCluster.best_keyness).where(TermCluster.project_id == domain_id)
        ).scalar()

    engine.dispose()

    assert after_first is not None
    assert after_second == pytest.approx(after_first)


# ---------------------------------------------------------------------------
# 6. Batch chunk commits — progress_callback called per chunk
# ---------------------------------------------------------------------------


def test_store_best_keyness_batch_commits(svc, tmp_path):
    """progress_callback is called once per chunk — verifies chunked commits."""
    engine = _make_engine(tmp_path, "keyness_batch.db")
    chunk_size = 3

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")

        # 7 clusters → ceil(7/3) = 3 chunks
        for i in range(7):
            _add_cluster(session, domain_id, f"term_{i:02d}", freq_abs=i + 1)

        session.commit()

        callback_calls: list[str] = []
        svc._store_best_keyness_for_project(
            session,
            domain_id,
            ref_id,
            progress_callback=callback_calls.append,
            chunk_size=chunk_size,
        )
        session.commit()

    engine.dispose()

    # 7 clusters / chunk_size 3 = 3 chunks
    assert len(callback_calls) == 3
    # Last callback reports all 7 updated
    assert "7" in callback_calls[-1]


# ---------------------------------------------------------------------------
# 7. Reference project with no tokens → graceful N_r=1 fallback
# ---------------------------------------------------------------------------


def test_store_best_keyness_empty_reference_uses_fallback(svc, tmp_path):
    """Empty reference (N_r=0) falls back to N_r=1 without crashing."""
    engine = _make_engine(tmp_path, "keyness_empty_ref.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")  # empty reference

        _add_cluster(session, domain_id, "term_y", freq_abs=5)

        session.commit()

        # Must not raise ZeroDivisionError
        updated = svc._store_best_keyness_for_project(session, domain_id, ref_id)
        session.commit()

        kval = session.execute(
            select(TermCluster.best_keyness).where(TermCluster.project_id == domain_id)
        ).scalar()

    engine.dispose()

    assert updated == 1
    assert kval is not None  # Computed with N_r=1 fallback, not NULL
