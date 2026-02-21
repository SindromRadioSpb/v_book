"""Tests for TM overlay normalization and raw pronunciation norm fallback."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import DictProject, Library, TermCluster
from app.services.translation_admin_service import TranslationAdminService


class _DummyUserDictService:
    def __init__(self):
        self.captured_payloads = None

    @staticmethod
    def _canonical_src_norm(src_lang: str, src_text: str, kind: str, fallback_norm: str = "") -> str:
        normalized = normalize_for_tm(src_lang, src_text, kind).norm
        normalized = (normalized or "").strip()
        return normalized or (fallback_norm or "").strip()

    @staticmethod
    def build_canonical_hash(src_lang: str, dst_lang: str, kind: str, src_norm: str) -> str:
        return f"{src_lang}|{dst_lang}|{kind}|{src_norm}"

    def resolve_cross_view_status(self, _session, payloads):
        self.captured_payloads = payloads
        payload = payloads[0]
        canonical_norm = self._canonical_src_norm(
            payload["src_lang"],
            payload["src_text"],
            payload["kind"],
            payload["src_norm"],
        )
        canonical_hash = self.build_canonical_hash(
            payload["src_lang"],
            payload["tgt_lang"],
            payload["kind"],
            canonical_norm,
        )
        return {
            canonical_hash: {
                "in_user_dictionary_count": 1,
                "study_state": "new",
                "study_due_human": "n/a",
                "last_grade": None,
                "last_graded_at": None,
                "study_tooltip": "tooltip",
                "audio_status": "missing",
                "pronunciation_text": "נִסָּיוֹן",
                "pronunciation_source": "manual",
                "pronunciation_confidence": 1.0,
                "pronunciation_qc": "ok",
            }
        }


def test_tm_overlay_uses_normalized_hash_and_cluster_raw_norm(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
        db_path = fh.name
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        TermCluster.__table__.create(engine, checkfirst=True)

        with Session(engine) as session:
            library = Library(name="Overlay Lib")
            session.add(library)
            session.flush()
            project = DictProject(library_id=library.library_id, name="Overlay P")
            session.add(project)
            session.flush()

            cluster = TermCluster(
                project_id=project.project_id,
                canonical_key="cluster_key",
                representative_he="legacy src",
                norm_text="cluster_raw_norm",
            )
            session.add(cluster)
            session.flush()

            entry = SimpleNamespace(
                tm_id=10,
                project_id=project.project_id,
                kind="term_cluster",
                src_lang="he",
                tgt_lang="ru",
                src_text="legacy src",
                src_norm="legacy_wrong_norm",
                translation="",
                translation_norm=None,
                pos=None,
                domain=None,
                notes=None,
                status="draft",
                confidence=None,
                origin="import",
                source_ref=None,
                created_at="",
                updated_at="",
                approved_at=None,
                approved_by=None,
                is_noise=0,
                noise_reason=None,
                norm_text=None,
                lemma_id=None,
                cluster_id=cluster.cluster_id,
                ngram_id=None,
                tm_global_id=None,
            )

            dummy = _DummyUserDictService()
            monkeypatch.setattr("app.services.translation_admin_service.UserDictionaryService", lambda: dummy)

            service = TranslationAdminService()
            service._apply_study_overlays(session, [entry])

            assert dummy.captured_payloads is not None
            assert dummy.captured_payloads[0]["raw_src_norm"] == "cluster_raw_norm"
            assert entry.raw_src_norm == "cluster_raw_norm"
            assert entry.in_user_dictionary_count == 1
            assert entry.pronunciation_text == "נִסָּיוֹן"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)
