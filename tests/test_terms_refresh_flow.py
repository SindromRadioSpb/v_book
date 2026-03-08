"""TermsView refresh and state rehydration regressions."""

from types import SimpleNamespace

from app.ui.terms_view import TermsView


def test_terms_refresh_current_page_skips_recount():
    view = TermsView.__new__(TermsView)
    captured = {}
    view.perform_search = lambda **kwargs: captured.update(kwargs)

    TermsView.refresh_current_page_after_operation(view)

    assert captured == {
        "include_total_count": False,
        "preserve_existing_state": True,
    }


def test_terms_rehydrate_visible_state_from_previous_page():
    view = TermsView.__new__(TermsView)

    previous_translation_result = SimpleNamespace(source="tm", status="approved")
    view.terms_model = SimpleNamespace(
        clusters=[
            SimpleNamespace(
                cluster_id=21,
                translation="термин",
                translation_status="approved",
                in_user_dictionary_count=1,
                study_tooltip="tooltip",
                study_state="learning",
                study_due_human="soon",
                last_grade="good",
                last_graded_at="2026-03-08",
                translation_tier="approved",
                audio_status="ready",
                pronunciation_text="מֻנָּח",
                pronunciation_source="manual",
                pronunciation_confidence=0.95,
                pronunciation_qc="ok",
            )
        ],
        translation_results={0: previous_translation_result},
    )

    snapshot = TermsView._snapshot_cluster_state(view)
    clusters = [
        SimpleNamespace(
            cluster_id=21,
            translation=None,
            translation_status=None,
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
        )
    ]

    translation_results = TermsView._rehydrate_cluster_state(view, clusters, snapshot)

    assert clusters[0].translation == "термин"
    assert clusters[0].translation_status == "approved"
    assert clusters[0].audio_status == "ready"
    assert clusters[0].pronunciation_text == "מֻנָּח"
    assert translation_results[0] is previous_translation_result
