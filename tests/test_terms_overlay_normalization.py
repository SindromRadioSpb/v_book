"""Tests for TermsView study overlay canonical normalization."""

from types import SimpleNamespace

from app.domain.normalization.normalizer import normalize_for_tm
from app.ui.terms_view import TermsView


class _SessionCtx:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyUserDictService:
    def __init__(self):
        self.captured_payloads = None

    @staticmethod
    def build_canonical_hash(src_lang: str, dst_lang: str, kind: str, src_norm: str) -> str:
        return f"{src_lang}|{dst_lang}|{kind}|{src_norm}"

    def resolve_cross_view_status(self, _session, payloads):
        self.captured_payloads = payloads
        src_norm = payloads[0]["src_norm"]
        canonical = self.build_canonical_hash("he", "ru", "term_cluster", src_norm)
        return {
            canonical: {
                "in_user_dictionary_count": 1,
                "study_tooltip": "tooltip",
                "study_state": "new",
                "study_due_human": "n/a",
                "translation_tier": "missing",
                "audio_status": "missing",
            }
        }


def test_terms_overlay_uses_normalized_text_instead_of_legacy_norm():
    view = TermsView.__new__(TermsView)
    view.db_service = SimpleNamespace(get_session=lambda: _SessionCtx())
    view.user_dict_service = _DummyUserDictService()

    cluster = SimpleNamespace(
        representative_he="legacy src",
        norm_text="legacy_wrong_norm",
        in_user_dictionary_count=0,
        study_tooltip=None,
        study_state=None,
        study_due_human=None,
        translation_tier=None,
        audio_status=None,
    )

    TermsView._apply_study_overlays(view, [cluster])

    expected_norm = normalize_for_tm("he", "legacy src", "term_cluster").norm
    assert view.user_dict_service.captured_payloads[0]["src_norm"] == expected_norm
    assert cluster.in_user_dictionary_count == 1
    assert cluster.study_tooltip == "tooltip"
