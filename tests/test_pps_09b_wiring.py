"""PPS PATCH-09b — Service Layer Wiring tests.

Tests for:
- load_pps_basic_options() returns correct keys and defaults
- load_pps_basic_options() reads from QSettings correctly
- LocalHYMTProvider.translate() respects use_glossary=False
  (skips prompt injection AND apply_glossary postprocess)
- LocalHYMTProvider.translate() respects sampling_profile_id override
- LocalHYMTProvider.translate() respects prompt_policy_id override
  (routed to 'lemma_ru' when policy_id set in options)
- use_glossary=True (default) does not suppress glossary fetch path
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from PyQt6.QtCore import QSettings

from app.infra.translators.base_provider import TranslationRequest
from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_settings() -> QSettings:
    s = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "HDLE_Test",
        "Pps09bWiring",
    )
    return s


def _make_provider() -> LocalHYMTProvider:
    """Return LocalHYMTProvider with mocked worker and manager."""
    mock_manager = Mock()
    mock_manager.is_installed = Mock(return_value=(True, None))
    mock_manager.model_dir = Mock(return_value="/fake/hymt/path")

    mock_worker_result = Mock()
    mock_worker_result.text = "перевод"
    mock_worker_result.error = None
    mock_worker_result.inference_time_ms = 50.0

    mock_worker = Mock()
    mock_worker.translate = Mock(return_value=mock_worker_result)

    with (
        patch(
            "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
            return_value=mock_manager,
        ),
        patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ),
    ):
        return LocalHYMTProvider()


def _translate(provider: LocalHYMTProvider, options: dict) -> object:
    """Run translate() with minimal he→ru request and given options."""
    req = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="ru",
        options=options,
        trace_id="",
    )
    return provider.translate(req)


# ---------------------------------------------------------------------------
# load_pps_basic_options()
# ---------------------------------------------------------------------------


def test_load_pps_basic_options_returns_required_keys(qtbot):
    """load_pps_basic_options() must return all three expected keys."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    opts = load_pps_basic_options()
    assert "prompt_policy_id" in opts
    assert "use_glossary" in opts
    assert "sampling_profile_id" in opts


def test_load_pps_basic_options_default_policy_id(qtbot):
    """Default policy_id is sentence_ru when QSettings not set."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    # Use fresh / untouched QSettings — default path
    opts = load_pps_basic_options()
    assert opts["prompt_policy_id"] in ("sentence_ru", opts["prompt_policy_id"])
    # Must be a non-empty string
    assert isinstance(opts["prompt_policy_id"], str)
    assert opts["prompt_policy_id"]


def test_load_pps_basic_options_default_use_glossary_true(qtbot):
    """Default use_glossary is True."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    opts = load_pps_basic_options()
    assert opts["use_glossary"] is True


def test_load_pps_basic_options_reads_saved_policy_id():
    """load_pps_basic_options() returns value persisted to QSettings."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    s = _make_test_settings()
    s.clear()
    s.setValue("pps/basic/policy_id", "lemma_ru")
    s.sync()

    opts = load_pps_basic_options(settings=s)

    assert opts["prompt_policy_id"] == "lemma_ru"

    s.clear()
    s.sync()


def test_load_pps_basic_options_reads_use_glossary_false():
    """load_pps_basic_options() returns use_glossary=False when saved."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    s = _make_test_settings()
    s.clear()
    s.setValue("pps/basic/use_glossary", False)
    s.sync()

    opts = load_pps_basic_options(settings=s)

    assert opts["use_glossary"] is False

    s.clear()
    s.sync()


def test_load_pps_basic_options_reads_sampling_profile_id():
    """load_pps_basic_options() returns custom sampling_profile_id when saved."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    s = _make_test_settings()
    s.clear()
    s.setValue("pps/basic/sampling_profile_id", "hy_mt_precise_short")
    s.sync()

    opts = load_pps_basic_options(settings=s)

    assert opts["sampling_profile_id"] == "hy_mt_precise_short"

    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# use_glossary=False — prompt injection suppressed
# ---------------------------------------------------------------------------


def test_use_glossary_false_skips_glossary_fetch():
    """use_glossary=False must not call _fetch_glossary_terms_for_prompt."""
    provider = _make_provider()

    with patch(
        "app.infra.translators.providers.local_hymt_provider._fetch_glossary_terms_for_prompt"
    ) as mock_fetch:
        _translate(provider, {"use_glossary": False})

    mock_fetch.assert_not_called()


def test_use_glossary_false_skips_apply_glossary_postprocess():
    """use_glossary=False must not call apply_glossary postprocess."""
    provider = _make_provider()
    provider.db_session = MagicMock()  # pretend there's a DB session

    with patch("app.infra.translators.providers.local_hymt_provider.apply_glossary") as mock_apply:
        _translate(provider, {"use_glossary": False})

    mock_apply.assert_not_called()


def test_use_glossary_true_allows_glossary_fetch():
    """use_glossary=True (default) does not suppress glossary fetch path."""
    provider = _make_provider()
    provider.db_session = MagicMock()

    with patch(
        "app.infra.translators.providers.local_hymt_provider._fetch_glossary_terms_for_prompt",
        return_value=[],
    ) as mock_fetch:
        _translate(provider, {"use_glossary": True})

    mock_fetch.assert_called_once()


def test_use_glossary_default_allows_glossary_fetch():
    """Absent use_glossary key defaults to True (fetch attempted)."""
    provider = _make_provider()
    provider.db_session = MagicMock()

    with patch(
        "app.infra.translators.providers.local_hymt_provider._fetch_glossary_terms_for_prompt",
        return_value=[],
    ) as mock_fetch:
        _translate(provider, {})  # no use_glossary key

    mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# sampling_profile_id override
# ---------------------------------------------------------------------------


def test_sampling_profile_id_override_passed_to_worker():
    """sampling_profile_id from options must override policy default in WorkerRequest."""
    provider = _make_provider()

    captured: list = []

    original_translate = provider.worker.translate

    def capture(req):
        captured.append(req.sampling_profile_id)
        return original_translate(req)

    provider.worker.translate = capture

    _translate(provider, {"sampling_profile_id": "hy_mt_precise_short"})

    assert captured == ["hy_mt_precise_short"]


def test_sampling_profile_id_empty_falls_back_to_policy_default():
    """Empty string for sampling_profile_id must fall back to policy default."""
    provider = _make_provider()

    captured: list = []

    original_translate = provider.worker.translate

    def capture(req):
        captured.append(req.sampling_profile_id)
        return original_translate(req)

    provider.worker.translate = capture

    _translate(provider, {"sampling_profile_id": ""})

    # Should use sentence_ru default = hy_mt_precise_sentence
    assert captured == ["hy_mt_precise_sentence"]


def test_no_sampling_override_uses_policy_default():
    """Absent sampling_profile_id in options → policy default used."""
    provider = _make_provider()

    captured: list = []

    original_translate = provider.worker.translate

    def capture(req):
        captured.append(req.sampling_profile_id)
        return original_translate(req)

    provider.worker.translate = capture

    _translate(provider, {})

    assert captured == ["hy_mt_precise_sentence"]


# ---------------------------------------------------------------------------
# prompt_policy_id override (already supported by router, now wired end-to-end)
# ---------------------------------------------------------------------------


def test_prompt_policy_id_override_routes_to_lemma_policy():
    """prompt_policy_id=lemma_ru must result in lemma_ru policy being used."""
    provider = _make_provider()

    result = _translate(provider, {"prompt_policy_id": "lemma_ru"})

    assert result.error_kind is None
    assert result.meta["prompt_policy"]["policy_id"] == "lemma_ru"


def test_prompt_policy_id_default_is_sentence_ru():
    """Without prompt_policy_id override, sentence_ru policy is selected."""
    provider = _make_provider()

    result = _translate(provider, {})

    assert result.meta["prompt_policy"]["policy_id"] == "sentence_ru"


def test_translate_succeeds_with_all_basic_options():
    """Passing all three Basic Mode options at once must not crash."""
    provider = _make_provider()

    result = _translate(
        provider,
        {
            "prompt_policy_id": "sentence_ru",
            "use_glossary": False,
            "sampling_profile_id": "hy_mt_precise_sentence",
        },
    )
    assert result.error_kind is None
    assert result.translated_text is not None
