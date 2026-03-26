"""CTM-v2 — TM user-dict add pathway validation.

Validates _materialize_tm_entries_for_items: the UserDictionaryService
pathway that creates tm_entry rows when UserDictionaryItems are added.

Coverage:
  - New TMEntry created with correct fields (kind, langs, source_ref)
  - Existing TMEntry reused when (project_id, kind, src_lang, tgt_lang, src_norm) matches
  - translation/status/origin inherited from TMGlobal when available
  - Default fallback (translation='', status='draft', origin='import') when no TMGlobal
  - _attach_source_links: cluster_id set for kind='term_cluster'
  - _attach_source_links: lemma_id set for kind='lemma'
  - promoted_from_cluster_id set on first cluster link; never overwritten
  - item.origin_tm_entry_id updated after materialize
  - item.src_norm updated after materialize
  - Stats dict keys and counts (created / reused / linked)
  - TMGlobal propagation: existing linked entries get updated translation/status

No Stanza required. Uses In-Memory SQLite.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Lemma,
    Library,
    TermCluster,
    TMEntry,
    TMGlobal,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.user_dictionary_service import UserDictionaryService


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
    sess.flush()
    ud = UserDictionary(name="TestDict")
    sess.add(ud)
    sess.commit()
    yield sess
    sess.close()


@pytest.fixture
def project_id(session) -> int:
    return int(session.execute(select(DictProject.project_id)).scalar_one())


@pytest.fixture
def dictionary_id(session) -> int:
    return int(session.execute(select(UserDictionary.dictionary_id)).scalar_one())


@pytest.fixture
def svc() -> UserDictionaryService:
    return UserDictionaryService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _make_item(
    sess: Session,
    dictionary_id: int,
    kind: str = "term_cluster",
    src_text: str = "ספר",
    src_norm: str = "ספר",
    *,
    src_lang: str = "he",
    tgt_lang: str = "ru",
    is_noise: int = 0,
    noise_reason: str | None = None,
    notes: str | None = None,
    origin_project_id: int | None = None,
    origin_entity_type: str | None = None,
    origin_entity_id: str | None = None,
    origin_tm_entry_id: int | None = None,
    canonical_hash: str | None = None,
) -> UserDictionaryItem:
    """Create and persist a UserDictionaryItem."""
    item = UserDictionaryItem(
        dictionary_id=dictionary_id,
        kind=kind,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        src_text=src_text,
        src_norm=src_norm,
        canonical_hash=canonical_hash or _hash(f"{kind}:{src_norm}"),
        is_noise=is_noise,
        noise_reason=noise_reason,
        notes=notes,
        origin_project_id=origin_project_id,
        origin_entity_type=origin_entity_type,
        origin_entity_id=origin_entity_id,
        origin_tm_entry_id=origin_tm_entry_id,
    )
    sess.add(item)
    sess.flush()
    return item


def _add_cluster(
    sess: Session,
    project_id: int,
    canonical_key: str = "ספר",
    representative_he: str = "ספר",
) -> int:
    cluster = TermCluster(
        project_id=project_id,
        canonical_key=canonical_key,
        representative_he=representative_he,
    )
    sess.add(cluster)
    sess.flush()
    return int(cluster.cluster_id)


def _add_global(
    sess: Session,
    src_norm: str,
    translation: str = "книга",
    status: str = "approved",
    origin: str = "user_edit",
    kind: str = "term_cluster",
    src_lang: str = "he",
    tgt_lang: str = "ru",
) -> TMGlobal:
    g = TMGlobal(
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        kind=kind,
        src_norm=src_norm,
        src_text=src_norm,
        translation=translation,
        status=status,
        origin=origin,
    )
    sess.add(g)
    sess.flush()
    return g


# ---------------------------------------------------------------------------
# STUD01 — Basic creation
# ---------------------------------------------------------------------------


class TestSUD01_BasicCreation:
    def test_entry_created(self, session, project_id, dictionary_id, svc):
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        stats = svc._materialize_tm_entries_for_items(session, [item])
        assert stats["created"] == 1

    def test_entry_kind(self, session, project_id, dictionary_id, svc):
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.kind == "term_cluster"

    def test_entry_langs(self, session, project_id, dictionary_id, svc):
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.src_lang == "he"
        assert entry.tgt_lang == "ru"

    def test_source_ref_on_new_entry(self, session, project_id, dictionary_id, svc):
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.source_ref == "user_dictionary_add"

    def test_default_status_when_no_global(self, session, project_id, dictionary_id, svc):
        """When no TMGlobal exists, status defaults to 'draft'."""
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.status == "draft"

    def test_default_origin_when_no_global(self, session, project_id, dictionary_id, svc):
        """When no TMGlobal exists, origin defaults to 'import'."""
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.origin == "import"


# ---------------------------------------------------------------------------
# STUD02 — Reuse existing entry
# ---------------------------------------------------------------------------


class TestSUD02_Reuse:
    def test_reuse_existing_entry_by_src_norm(self, session, project_id, dictionary_id, svc):
        """Second add for same (project_id, kind, src_lang, tgt_lang, src_norm) reuses entry."""
        existing = TMEntry(
            project_id=project_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="ספר",
            src_norm="ספר",
            translation="",
            status="draft",
            origin="import",
        )
        session.add(existing)
        session.flush()

        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        stats = svc._materialize_tm_entries_for_items(session, [item])
        assert stats["reused"] == 1
        assert stats["created"] == 0

    def test_reuse_no_duplicate_created(self, session, project_id, dictionary_id, svc):
        """Reuse must not insert a second tm_entry row."""
        existing = TMEntry(
            project_id=project_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="ספר",
            src_norm="ספר",
            translation="",
            status="draft",
            origin="import",
        )
        session.add(existing)
        session.flush()

        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        count = session.execute(func.count(TMEntry.tm_id)).scalar()
        assert count == 1


# ---------------------------------------------------------------------------
# STUD03 — Empty items
# ---------------------------------------------------------------------------


class TestSUD03_EmptyItems:
    def test_empty_items_zero_stats(self, session, svc):
        stats = svc._materialize_tm_entries_for_items(session, [])
        assert stats == {"created": 0, "reused": 0, "linked": 0}

    def test_empty_items_no_tm_entries(self, session, svc):
        svc._materialize_tm_entries_for_items(session, [])
        count = session.execute(func.count(TMEntry.tm_id)).scalar()
        assert count == 0


# ---------------------------------------------------------------------------
# STUD04 — TMGlobal inheritance
# ---------------------------------------------------------------------------


class TestSUD04_GlobalInheritance:
    def test_translation_from_global(self, session, project_id, dictionary_id, svc):
        """When TMGlobal exists for src_norm, new entry inherits its translation."""
        _add_global(
            session, src_norm="ספר", translation="книга", status="approved", origin="user_edit"
        )
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.translation == "книга"

    def test_status_from_global(self, session, project_id, dictionary_id, svc):
        _add_global(
            session, src_norm="ספר", translation="книга", status="approved", origin="user_edit"
        )
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.status == "approved"

    def test_origin_from_global(self, session, project_id, dictionary_id, svc):
        _add_global(
            session, src_norm="ספר", translation="книга", status="approved", origin="user_edit"
        )
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.origin == "user_edit"


# ---------------------------------------------------------------------------
# STUD05 — item fields updated after materialize
# ---------------------------------------------------------------------------


class TestSUD05_ItemFieldsUpdated:
    def test_origin_tm_entry_id_set(self, session, project_id, dictionary_id, svc):
        """item.origin_tm_entry_id must be set to the materialized entry's tm_id."""
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        assert item.origin_tm_entry_id is None
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert item.origin_tm_entry_id == entry.tm_id

    def test_src_norm_updated(self, session, project_id, dictionary_id, svc):
        """item.src_norm is set to the computed canonical src_norm (non-empty)."""
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        assert item.src_norm is not None
        assert item.src_norm.strip() != ""


# ---------------------------------------------------------------------------
# STUD06 — _attach_source_links: cluster_id
# ---------------------------------------------------------------------------


class TestSUD06_ClusterIdLink:
    def test_cluster_id_set(self, session, project_id, dictionary_id, svc):
        """entry.cluster_id set when origin_entity_type='term_cluster'."""
        cluster_id = _add_cluster(session, project_id, canonical_key="ספר")
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
            origin_entity_type="term_cluster",
            origin_entity_id=str(cluster_id),
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.cluster_id == cluster_id

    def test_cluster_id_none_when_no_entity(self, session, project_id, dictionary_id, svc):
        """entry.cluster_id remains None when origin_entity_id is not provided."""
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
            origin_entity_type=None,
            origin_entity_id=None,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.cluster_id is None


# ---------------------------------------------------------------------------
# STUD07 — _attach_source_links: lemma_id
# ---------------------------------------------------------------------------


class TestSUD07_LemmaIdLink:
    def test_lemma_id_set(self, session, project_id, dictionary_id, svc):
        """entry.lemma_id set when kind='lemma' and origin_entity_type='lemma'."""
        lemma = Lemma(project_id=project_id, lemma_text="ספר", norm_text="ספר")
        session.add(lemma)
        session.flush()

        item = _make_item(
            session,
            dictionary_id,
            kind="lemma",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
            origin_entity_type="lemma",
            origin_entity_id=str(lemma.lemma_id),
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.lemma_id == lemma.lemma_id


# ---------------------------------------------------------------------------
# STUD08 — Provenance: promoted_from_cluster_id first-only
# ---------------------------------------------------------------------------


class TestSUD08_ProvenanceFirstOnly:
    def test_promoted_from_cluster_id_set_on_first_link(
        self, session, project_id, dictionary_id, svc
    ):
        """promoted_from_cluster_id is set to cluster_id on the first cluster promotion."""
        cluster_id = _add_cluster(session, project_id, canonical_key="ספר")
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
            origin_entity_type="term_cluster",
            origin_entity_id=str(cluster_id),
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.promoted_from_cluster_id == cluster_id

    def test_promoted_from_cluster_id_not_overwritten(
        self, session, project_id, dictionary_id, svc
    ):
        """promoted_from_cluster_id is never overwritten once set.

        Even when a new item with a different cluster entity is processed
        and the entry is reused (origin_tm_entry_id match), the first
        promoted_from_cluster_id survives.
        """
        cluster_id_first = _add_cluster(
            session, project_id, canonical_key="ספר1", representative_he="ספר1"
        )
        cluster_id_second = _add_cluster(
            session, project_id, canonical_key="ספר2", representative_he="ספר2"
        )

        # Pre-existing entry already promoted from cluster_id_first
        existing = TMEntry(
            project_id=project_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="ספר",
            src_norm="ספר",
            translation="",
            status="draft",
            origin="import",
            cluster_id=cluster_id_first,
            promoted_from_cluster_id=cluster_id_first,
        )
        session.add(existing)
        session.flush()

        # New item points to same entry via origin_tm_entry_id but different cluster entity
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
            origin_entity_type="term_cluster",
            origin_entity_id=str(cluster_id_second),
            origin_tm_entry_id=existing.tm_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        session.refresh(existing)
        # Must remain as the first cluster — never overwritten
        assert existing.promoted_from_cluster_id == cluster_id_first


# ---------------------------------------------------------------------------
# STUD09 — Stats dict
# ---------------------------------------------------------------------------


class TestSUD09_Stats:
    def test_stats_keys(self, session, project_id, dictionary_id, svc):
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        stats = svc._materialize_tm_entries_for_items(session, [item])
        assert set(stats.keys()) == {"created", "reused", "linked"}

    def test_stats_two_distinct_items(self, session, project_id, dictionary_id, svc):
        """Two items with different src_norm: created=2, linked=2."""
        item1 = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        item2 = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="עיר",
            src_norm="עיר",
            origin_project_id=project_id,
        )
        stats = svc._materialize_tm_entries_for_items(session, [item1, item2])
        assert stats["created"] == 2
        assert stats["linked"] == 2

    def test_stats_linked_increments_for_reuse(self, session, project_id, dictionary_id, svc):
        """linked increments for reused items as well as new ones."""
        existing = TMEntry(
            project_id=project_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="ספר",
            src_norm="ספר",
            translation="",
            status="draft",
            origin="import",
        )
        session.add(existing)
        session.flush()

        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        stats = svc._materialize_tm_entries_for_items(session, [item])
        assert stats["linked"] == 1
        assert stats["reused"] == 1


# ---------------------------------------------------------------------------
# STUD10 — TMGlobal propagation
# ---------------------------------------------------------------------------


class TestSUD10_TMGlobalPropagation:
    def test_global_linked_entries_updated_after_propagation(
        self, session, project_id, dictionary_id, svc
    ):
        """After materialize, propagate_to_entries runs and updates all entries
        that are linked to the touched TMGlobal — including pre-existing entries
        with stale translations."""
        # Pre-existing TMGlobal with canonical translation
        g = _add_global(
            session, src_norm="ספר", translation="книга", status="approved", origin="user_edit"
        )

        # Pre-existing TMEntry linked to g but with stale translation; project_id=None
        # (different scope → won't be reused by the new item which has project_id)
        stale_entry = TMEntry(
            project_id=None,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="ספר",
            src_norm="ספר",
            translation="старый",
            status="draft",
            origin="import",
            tm_global_id=g.tm_global_id,
        )
        session.add(stale_entry)
        session.flush()

        # Materialize a new item (different project scope → creates new entry)
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])

        # propagate_to_entries updates Python objects in the session identity map.
        # Do NOT call session.refresh() here — that re-reads from DB without
        # flushing first and would undo the in-memory change.
        assert stale_entry.translation == "книга"
        assert stale_entry.status == "approved"

    def test_new_entry_gets_tm_global_id(self, session, project_id, dictionary_id, svc):
        """When TMGlobal exists for the src_norm, the newly created TMEntry
        gets tm_global_id pointing to that TMGlobal row."""
        g = _add_global(session, src_norm="ספר", translation="книга")
        item = _make_item(
            session,
            dictionary_id,
            kind="term_cluster",
            src_text="ספר",
            src_norm="ספר",
            origin_project_id=project_id,
        )
        svc._materialize_tm_entries_for_items(session, [item])
        entry = session.execute(select(TMEntry)).scalar_one()
        assert entry.tm_global_id == g.tm_global_id
