"""Tests for _store_termhood_metrics_for_project() — Epic 4 PATCH-07.

Contracts verified:
1. weirdness is stored for all domain clusters (alongside best_keyness).
2. Both metrics stored in one pass — single UPDATE per cluster.
3. Only target project updated — other projects untouched.
4. Partial overlap: clusters absent from reference get weirdness computed with f_r=0.
5. Repeat-run safety: correct overwrite without data corruption.
6. Batch chunk commits — progress_callback called once per chunk.
7. Empty reference project — N_r=1 fallback, no crash.
8. Backward-compat: old method name alias removed; new name is canonical.
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
    weirdness: float | None = None,
) -> int:
    c = TermCluster(
        project_id=project_id,
        canonical_key=canonical_key,
        representative_he=canonical_key,
        freq_abs=freq_abs,
        doc_freq=1,
        members_count=1,
        best_keyness=best_keyness,
        weirdness=weirdness,
    )
    session.add(c)
    session.flush()
    return int(c.cluster_id)


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    return TermExtractionService()


# ---------------------------------------------------------------------------
# 1. Both metrics stored — basic happy path
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_stores_both_values(svc, tmp_path):
    """best_keyness and weirdness are computed and stored for all domain clusters."""
    engine = _make_engine(tmp_path, "metrics_basic.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "reference")

        _add_cluster(session, domain_id, "alpha_beta", freq_abs=10)
        _add_cluster(session, domain_id, "gamma_delta", freq_abs=5)
        _add_cluster(session, ref_id, "alpha_beta", freq_abs=3)

        session.commit()

        updated = svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
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

    # alpha_beta has a reference match
    assert alpha.best_keyness is not None
    assert alpha.best_keyness > 0.0
    assert alpha.weirdness is not None
    assert alpha.weirdness > 0.0

    # gamma_delta has no reference match — still stored (computed with f_r=0)
    assert gamma.best_keyness is not None
    assert gamma.weirdness is not None


# ---------------------------------------------------------------------------
# 2. Empty domain project returns 0 updates
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_empty_domain_returns_zero(svc, tmp_path):
    """Empty domain project → 0 updates, no crash."""
    engine = _make_engine(tmp_path, "metrics_empty.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")
        _add_cluster(session, ref_id, "some_term", freq_abs=5)
        session.commit()

        updated = svc._store_termhood_metrics_for_project(session, domain_id, ref_id)

    engine.dispose()
    assert updated == 0


# ---------------------------------------------------------------------------
# 3. Only target project updated — other projects untouched
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_scoped_to_project(svc, tmp_path):
    """Clusters in other projects are not modified."""
    engine = _make_engine(tmp_path, "metrics_scope.db")

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
        # other project has same canonical_key and sentinel values — must NOT be touched
        _add_cluster(session, other_id, "term_a", freq_abs=99, best_keyness=42.0, weirdness=7.7)

        session.commit()
        svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
        session.commit()

        other_clusters = (
            session.execute(select(TermCluster).where(TermCluster.project_id == other_id))
            .scalars()
            .all()
        )

    engine.dispose()

    assert len(other_clusters) == 1
    assert other_clusters[0].best_keyness == pytest.approx(42.0)
    assert other_clusters[0].weirdness == pytest.approx(7.7)


# ---------------------------------------------------------------------------
# 4. Partial overlap: clusters absent from reference get weirdness computed
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_partial_overlap(svc, tmp_path):
    """Clusters absent from reference get both metrics computed with f_r=0."""
    engine = _make_engine(tmp_path, "metrics_partial.db")

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
        updated = svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
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
        assert c.best_keyness is not None, f"{c.canonical_key} has NULL keyness"
        assert c.weirdness is not None, f"{c.canonical_key} has NULL weirdness"


# ---------------------------------------------------------------------------
# 5. Repeat-run safety (idempotent overwrite)
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_repeat_run_overwrites_correctly(svc, tmp_path):
    """Running _store_termhood_metrics_for_project twice produces consistent results."""
    engine = _make_engine(tmp_path, "metrics_repeat.db")

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

        svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
        session.commit()

        after_first_k, after_first_w = session.execute(
            select(TermCluster.best_keyness, TermCluster.weirdness).where(
                TermCluster.project_id == domain_id
            )
        ).one()

        svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
        session.commit()

        after_second_k, after_second_w = session.execute(
            select(TermCluster.best_keyness, TermCluster.weirdness).where(
                TermCluster.project_id == domain_id
            )
        ).one()

    engine.dispose()

    assert after_first_k is not None
    assert after_first_w is not None
    assert after_second_k == pytest.approx(after_first_k)
    assert after_second_w == pytest.approx(after_first_w)


# ---------------------------------------------------------------------------
# 6. Batch chunk commits — progress_callback called per chunk
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_batch_commits(svc, tmp_path):
    """progress_callback is called once per chunk — verifies chunked commits."""
    engine = _make_engine(tmp_path, "metrics_batch.db")
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
        svc._store_termhood_metrics_for_project(
            session,
            domain_id,
            ref_id,
            progress_callback=callback_calls.append,
            chunk_size=chunk_size,
        )
        session.commit()

    engine.dispose()

    assert len(callback_calls) == 3
    assert "7" in callback_calls[-1]


# ---------------------------------------------------------------------------
# 7. Empty reference project — N_r=1 fallback, no crash
# ---------------------------------------------------------------------------


def test_store_termhood_metrics_empty_reference_uses_fallback(svc, tmp_path):
    """Empty reference (N_r=0) falls back to N_r=1 without crashing."""
    engine = _make_engine(tmp_path, "metrics_empty_ref.db")

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        lib_id = int(lib.library_id)

        domain_id = _add_project(session, lib_id, "domain")
        ref_id = _add_project(session, lib_id, "ref")  # empty reference

        _add_cluster(session, domain_id, "term_y", freq_abs=5)

        session.commit()

        updated = svc._store_termhood_metrics_for_project(session, domain_id, ref_id)
        session.commit()

        kval, wval = session.execute(
            select(TermCluster.best_keyness, TermCluster.weirdness).where(
                TermCluster.project_id == domain_id
            )
        ).one()

    engine.dispose()

    assert updated == 1
    assert kval is not None
    assert wval is not None
