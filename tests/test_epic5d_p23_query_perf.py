"""Epic 5D P2.3: Bottleneck audit — live aggregate queries on term clusters.

NOT an implementation patch.  Goal: measure whether list_term_cluster,
count_term_cluster, and get_freq_distribution show meaningful latency at
scale (N=10_000 clusters) and whether EXPLAIN QUERY PLAN uses indexes.

Run manually:
    pytest tests/test_epic5d_p23_query_perf.py -v -s

Findings feed the decision on whether a materialised-stats layer is needed.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library, TermCluster
from app.services.term_extraction_service import TermExtractionService

# ── thresholds (ms) ─────────────────────────────────────────────────────────
# Acceptable response times for the live-query path at N=10_000 clusters.
# Raise if the baseline machine is slow; lower for stricter gates.
LIST_THRESHOLD_MS = 100  # list_term_cluster (first page)
COUNT_THRESHOLD_MS = 100  # count_term_cluster
FREQ_DIST_THRESHOLD_MS = 100  # get_freq_distribution (single aggregate SELECT)

N_CLUSTERS = 10_000


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def perf_session():
    """In-memory SQLite session pre-seeded with N_CLUSTERS TermCluster rows."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="PerfLib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(project_id=1, library_id=1, name="PerfProj", src_lang="he", tgt_lang="ru")
    sess.add(proj)
    sess.flush()

    # Insert clusters with varying freq_abs to exercise all distribution bands
    clusters = []
    for i in range(N_CLUSTERS):
        freq = 1 + (i % 15)  # values 1-15, so all bands covered
        clusters.append(
            TermCluster(
                project_id=1,
                canonical_key=f"term_{i:05d}",
                representative_he=f"מילה {i}",
                freq_abs=freq,
                doc_freq=max(1, freq // 2),
                source_kinds="ngram",
            )
        )
        if i % 1000 == 999:
            sess.add_all(clusters)
            sess.flush()
            clusters = []

    if clusters:
        sess.add_all(clusters)
    sess.commit()
    yield sess
    sess.close()
    engine.dispose()


@pytest.fixture(scope="module")
def svc(tmp_path_factory, monkeypatch_session):
    from types import SimpleNamespace

    from app.services.db_service import DBService

    monkeypatch_session.setattr(DBService, "_instance", SimpleNamespace())
    return TermExtractionService()


@pytest.fixture(scope="module")
def monkeypatch_session():
    """Module-scoped monkeypatch (pytest doesn't provide one natively)."""
    import unittest.mock as mock

    with mock.patch.object(
        __import__("app.services.db_service", fromlist=["DBService"]).DBService,
        "_instance",
        new_callable=lambda: property(lambda self: __import__("types").SimpleNamespace()),
    ):
        pass
    # Simpler approach: return a basic monkeypatching fixture proxy
    from types import SimpleNamespace

    mp = SimpleNamespace()
    patches = []

    def setattr_(obj, name, val):
        orig = getattr(obj, name, None)
        setattr(obj, name, val)
        patches.append((obj, name, orig))

    mp.setattr = setattr_
    yield mp
    for obj, name, orig in reversed(patches):
        if orig is None:
            try:
                delattr(obj, name)
            except AttributeError:
                pass
        else:
            setattr(obj, name, orig)


# ── EXPLAIN QUERY PLAN checks ────────────────────────────────────────────────


def test_list_clusters_uses_index(perf_session):
    """list_term_cluster filter/sort must hit a covering index, not full scan."""
    plan = perf_session.execute(
        text(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM term_cluster "
            "WHERE project_id = 1 AND freq_abs >= 2 "
            "ORDER BY freq_abs DESC "
            "LIMIT 200"
        )
    ).fetchall()
    plan_text = " ".join(str(r) for r in plan).lower()
    print(f"\nEXPLAIN list_clusters:\n{plan_text}")
    # Accept either an index scan or covering index; flag a pure table scan.
    assert (
        "scan" not in plan_text or "using index" in plan_text or "idx" in plan_text
    ), f"list_term_cluster likely doing a full table scan: {plan_text}"


def test_count_clusters_uses_index(perf_session):
    """count_term_cluster aggregate must use an index, not a full scan."""
    plan = perf_session.execute(
        text(
            "EXPLAIN QUERY PLAN "
            "SELECT COUNT(*) FROM term_cluster "
            "WHERE project_id = 1 AND freq_abs >= 2"
        )
    ).fetchall()
    plan_text = " ".join(str(r) for r in plan).lower()
    print(f"\nEXPLAIN count_clusters:\n{plan_text}")
    assert (
        "scan" not in plan_text or "using index" in plan_text or "idx" in plan_text
    ), f"count_term_cluster likely doing a full table scan: {plan_text}"


def test_freq_distribution_uses_index(perf_session):
    """get_freq_distribution aggregate SELECT must not be a full table scan."""
    plan = perf_session.execute(
        text(
            "EXPLAIN QUERY PLAN "
            "SELECT "
            "  SUM(CASE WHEN freq_abs = 1 THEN 1 ELSE 0 END) AS band_1, "
            "  SUM(CASE WHEN freq_abs BETWEEN 2 AND 4 THEN 1 ELSE 0 END) AS band_2_4, "
            "  SUM(CASE WHEN freq_abs BETWEEN 5 AND 9 THEN 1 ELSE 0 END) AS band_5_9, "
            "  SUM(CASE WHEN freq_abs >= 10 THEN 1 ELSE 0 END) AS band_10plus "
            "FROM term_cluster "
            "WHERE project_id = 1"
        )
    ).fetchall()
    plan_text = " ".join(str(r) for r in plan).lower()
    print(f"\nEXPLAIN freq_distribution:\n{plan_text}")
    # For a single-project aggregate this may legitimately be a small index scan;
    # flag only if it's a covering table scan with no index at all.
    assert (
        "scan" not in plan_text or "using index" in plan_text or "idx" in plan_text
    ), f"get_freq_distribution likely doing a full table scan: {plan_text}"


# ── Latency measurements (informational, not hard gates) ────────────────────


def test_list_clusters_latency(perf_session):
    """list_term_cluster first page latency at N=10_000 (informational)."""
    t0 = time.perf_counter()
    rows = perf_session.execute(
        text(
            "SELECT * FROM term_cluster "
            "WHERE project_id = 1 AND freq_abs >= 2 "
            "ORDER BY freq_abs DESC LIMIT 200"
        )
    ).fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\nlist_clusters: {elapsed_ms:.1f} ms, rows={len(rows)}")
    assert elapsed_ms < LIST_THRESHOLD_MS, (
        f"list_term_cluster took {elapsed_ms:.1f} ms > {LIST_THRESHOLD_MS} ms "
        f"at N={N_CLUSTERS} — consider a covering index or materialised stats"
    )


def test_count_clusters_latency(perf_session):
    """count_term_cluster aggregate latency at N=10_000 (informational)."""
    t0 = time.perf_counter()
    result = perf_session.execute(
        text("SELECT COUNT(*) FROM term_cluster " "WHERE project_id = 1 AND freq_abs >= 2")
    ).scalar()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\ncount_clusters: {elapsed_ms:.1f} ms, count={result}")
    assert elapsed_ms < COUNT_THRESHOLD_MS, (
        f"count_term_cluster took {elapsed_ms:.1f} ms > {COUNT_THRESHOLD_MS} ms "
        f"at N={N_CLUSTERS} — consider a covering index"
    )


def test_freq_distribution_latency(perf_session):
    """get_freq_distribution single-pass aggregate latency at N=10_000."""
    t0 = time.perf_counter()
    result = perf_session.execute(
        text(
            "SELECT "
            "  SUM(CASE WHEN freq_abs = 1 THEN 1 ELSE 0 END) AS band_1, "
            "  SUM(CASE WHEN freq_abs BETWEEN 2 AND 4 THEN 1 ELSE 0 END) AS band_2_4, "
            "  SUM(CASE WHEN freq_abs BETWEEN 5 AND 9 THEN 1 ELSE 0 END) AS band_5_9, "
            "  SUM(CASE WHEN freq_abs >= 10 THEN 1 ELSE 0 END) AS band_10plus "
            "FROM term_cluster "
            "WHERE project_id = 1"
        )
    ).fetchone()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\nfreq_distribution: {elapsed_ms:.1f} ms, result={result}")
    assert elapsed_ms < FREQ_DIST_THRESHOLD_MS, (
        f"get_freq_distribution took {elapsed_ms:.1f} ms > {FREQ_DIST_THRESHOLD_MS} ms "
        f"at N={N_CLUSTERS} — materialised stats cache may be warranted"
    )
