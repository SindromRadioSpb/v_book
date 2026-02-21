"""Tests for DictionaryView pronunciation overlay normalization behavior."""

from types import SimpleNamespace

from app.domain.normalization.normalizer import normalize_for_tm
from app.ui.dictionary_view import DictionaryView


class _SessionCtx:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyUserDictService:
    def __init__(self):
        self.captured_payloads = None
        self._pron_map = {}

    @staticmethod
    def build_canonical_hash(src_lang: str, dst_lang: str, kind: str, src_norm: str) -> str:
        return f"{src_lang}|{dst_lang}|{kind}|{src_norm}"

    def resolve_cross_view_status(self, _session, payloads):
        self.captured_payloads = payloads
        canonical = self.build_canonical_hash("he", "ru", "lemma", payloads[0]["src_norm"])
        return {
            canonical: {
                "in_user_dictionary_count": 1,
                "study_tooltip": "tooltip",
                "study_state": "new",
                "study_due_human": "n/a",
                "translation_tier": "missing",
                "audio_status": "missing",
                "pronunciation_text": "פלדה",
                "pronunciation_source": "auto_phonikud",
                "pronunciation_confidence": 0.8,
                "pronunciation_qc": "ok",
            }
        }

    def _resolve_pronunciation_overlay(self, _session, pairs):
        return {pair: self._pron_map.get(pair, {}) for pair in pairs}


def test_dictionary_overlay_uses_row_specific_pronunciation_by_surface_norm():
    view = DictionaryView.__new__(DictionaryView)
    view.db_service = SimpleNamespace(get_session=lambda: _SessionCtx())
    view.user_dict_service = _DummyUserDictService()

    first_surface = normalize_for_tm("he", "בפלדה", "surface").norm
    second_surface = normalize_for_tm("he", "לפלדה", "surface").norm
    view.user_dict_service._pron_map = {
        ("he", first_surface): {"pronunciation_text": "בַּפְלָדָה", "pronunciation_source": "manual"},
        ("he", second_surface): {"pronunciation_text": "לַפְלָדָה", "pronunciation_source": "manual"},
    }

    lemmas = [
        SimpleNamespace(
            lemma_text="בפלדה",
            norm_text="פלדה",
            in_user_dictionary_count=0,
            study_tooltip=None,
            study_state=None,
            study_due_human=None,
            last_grade=None,
            last_graded_at=None,
            translation_tier=None,
            audio_status=None,
            pronunciation_text=None,
            pronunciation_source=None,
            pronunciation_confidence=None,
            pronunciation_qc=None,
        ),
        SimpleNamespace(
            lemma_text="לפלדה",
            norm_text="פלדה",
            in_user_dictionary_count=0,
            study_tooltip=None,
            study_state=None,
            study_due_human=None,
            last_grade=None,
            last_graded_at=None,
            translation_tier=None,
            audio_status=None,
            pronunciation_text=None,
            pronunciation_source=None,
            pronunciation_confidence=None,
            pronunciation_qc=None,
        ),
    ]

    DictionaryView._apply_study_overlays(view, lemmas)

    assert lemmas[0].pronunciation_text == "בַּפְלָדָה"
    assert lemmas[1].pronunciation_text == "לַפְלָדָה"
