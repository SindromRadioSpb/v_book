"""Epic 5A PATCH-03: Impact preview before destructive overwrite.

Tests:
1. get_overwrite_impact returns zero counts when no clusters exist
2. Returns correct cluster count
3. Returns correct linked_tm_entries count (only cluster_id IS NOT NULL)
4. Unlinked TM entries (cluster_id=NULL) are not counted
5. Impact is scoped to project_id — other projects not counted
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library, TermCluster, TMEntry
from app.services.term_extraction_service import TermExtractionService  # used as namespace only


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="Lib")
    sess.add(lib)
    sess.flush()
    p1 = DictProject(project_id=1, library_id=1, name="P1", src_lang="he", tgt_lang="ru")
    p2 = DictProject(project_id=2, library_id=1, name="P2", src_lang="he", tgt_lang="ru")
    sess.add_all([p1, p2])
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


def _make_cluster(session, project_id: int = 1, key: str = "term") -> TermCluster:
    c = TermCluster(
        project_id=project_id,
        canonical_key=key,
        representative_he=key,
        freq_abs=5,
        doc_freq=2,
        source_kinds="ngram",
    )
    session.add(c)
    session.flush()
    return c


_entry_counter = 0


def _make_entry(session, project_id: int = 1, cluster_id: int | None = None) -> TMEntry:
    global _entry_counter
    _entry_counter += 1
    key = f"מילה_{_entry_counter}"
    e = TMEntry(
        project_id=project_id,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text=key,
        src_norm=key,
        translation="слово",
        status="draft",
        origin="import",
        cluster_id=cluster_id,
    )
    session.add(e)
    session.flush()
    return e


def test_impact_empty_project(session):
    """Zero counts when no clusters exist. Epic 5D P1: processed_docs also returned."""
    impact = TermExtractionService.get_overwrite_impact(session, 1)
    assert impact["clusters"] == 0
    assert impact["linked_tm_entries"] == 0
    assert "processed_docs" in impact  # Epic 5D P1: new key always present


def test_impact_cluster_count(session):
    """Counts all clusters for the project."""
    _make_cluster(session, key="א")
    _make_cluster(session, key="ב")
    session.commit()

    impact = TermExtractionService.get_overwrite_impact(session, 1)
    assert impact["clusters"] == 2


def test_impact_linked_tm_count(session):
    """Counts only TM entries with cluster_id IS NOT NULL."""
    cluster = _make_cluster(session)
    _make_entry(session, cluster_id=cluster.cluster_id)  # linked
    _make_entry(session, cluster_id=cluster.cluster_id)  # linked
    _make_entry(session, cluster_id=None)  # unlinked — must NOT be counted
    session.commit()

    impact = TermExtractionService.get_overwrite_impact(session, 1)
    assert impact["linked_tm_entries"] == 2


def test_impact_unlinked_entries_excluded(session):
    """Entries with cluster_id=NULL do not inflate linked_tm_entries."""
    _make_cluster(session)
    _make_entry(session, cluster_id=None)
    _make_entry(session, cluster_id=None)
    session.commit()

    impact = TermExtractionService.get_overwrite_impact(session, 1)
    assert impact["linked_tm_entries"] == 0


def test_impact_scoped_to_project(session):
    """Impact counts only include the target project, not other projects."""
    c1 = _make_cluster(session, project_id=1, key="p1term")
    c2 = _make_cluster(session, project_id=2, key="p2term")
    _make_entry(session, project_id=1, cluster_id=c1.cluster_id)
    _make_entry(session, project_id=2, cluster_id=c2.cluster_id)
    session.commit()

    impact_p1 = TermExtractionService.get_overwrite_impact(session, 1)
    assert impact_p1["clusters"] == 1
    assert impact_p1["linked_tm_entries"] == 1

    impact_p2 = TermExtractionService.get_overwrite_impact(session, 2)
    assert impact_p2["clusters"] == 1
    assert impact_p2["linked_tm_entries"] == 1
