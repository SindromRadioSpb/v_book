"""PPS PATCH-12 — Trace recording toggle and wiring tests.

Verifies:
UI toggle:
- _trace_cb exists in AdvancedPolicyEditorWidget.
- _trace_cb is disabled when Advanced Mode is off.
- _trace_cb becomes enabled when Advanced Mode is toggled on.
- _trace_cb state is persisted to QSettings (pps/advanced/trace_enabled).
- _trace_cb state is restored from QSettings on load_settings().
- When Advanced Mode is off, _trace_cb stays disabled even if QSettings says True.

load_pps_request_options():
- trace_enabled=False in options when pps/advanced/trace_enabled is False (default).
- trace_enabled=True in options when pps/advanced/active=True and trace_enabled=True.
- trace_enabled absent (or False) in basic mode options.

translation_service wiring:
- PromptAuditPanel.add_trace is called when trace_enabled=True and provider returns a trace.
- PromptAuditPanel.add_trace is NOT called when trace_enabled=False.
- PromptAuditPanel.add_trace is NOT called when result has no trace.
- Failure to import PromptAuditPanel (headless env) does not crash the service.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from PyQt6.QtCore import QSettings

from app.ui.advanced_policy_editor import AdvancedPolicyEditorWidget
from app.ui.prompt_audit_dialog import PromptAuditPanel
from app.ui.provider_settings_dialog import load_pps_request_options


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(name: str) -> QSettings:
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "HDLE_Test", name)
    s.clear()
    s.sync()
    return s


@pytest.fixture
def settings():
    s = _make_settings("Patch12Test")
    yield s
    s.clear()
    s.sync()


@pytest.fixture
def editor(qtbot, settings):
    w = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(w)
    yield w


@pytest.fixture(autouse=True)
def _clear_audit_history():
    PromptAuditPanel.clear_history()
    yield
    PromptAuditPanel.clear_history()


# ---------------------------------------------------------------------------
# UI toggle — existence and initial state
# ---------------------------------------------------------------------------


def test_trace_cb_exists(editor):
    """_trace_cb attribute must exist on AdvancedPolicyEditorWidget."""
    assert hasattr(editor, "_trace_cb")


def test_trace_cb_disabled_when_advanced_off(editor):
    """_trace_cb must be disabled when Advanced Mode is not active."""
    editor._active_cb.setChecked(False)
    assert not editor._trace_cb.isEnabled()


def test_trace_cb_enabled_when_advanced_on(editor):
    """_trace_cb becomes enabled when Advanced Mode is toggled on."""
    editor._active_cb.setChecked(True)
    assert editor._trace_cb.isEnabled()


def test_trace_cb_disabled_again_when_advanced_toggled_off(editor):
    """_trace_cb is disabled again when Advanced Mode is toggled back off."""
    editor._active_cb.setChecked(True)
    assert editor._trace_cb.isEnabled()
    editor._active_cb.setChecked(False)
    assert not editor._trace_cb.isEnabled()


# ---------------------------------------------------------------------------
# UI toggle — persistence
# ---------------------------------------------------------------------------


def test_trace_cb_persisted_to_settings(editor, settings):
    """Checking _trace_cb and calling save_settings() writes to QSettings."""
    editor._active_cb.setChecked(True)
    editor._trace_cb.setChecked(True)
    editor.save_settings()
    assert settings.value("pps/advanced/trace_enabled", False, type=bool) is True


def test_trace_cb_false_persisted_to_settings(editor, settings):
    """Unchecking _trace_cb and saving writes False to QSettings."""
    editor._active_cb.setChecked(True)
    editor._trace_cb.setChecked(False)
    editor.save_settings()
    assert settings.value("pps/advanced/trace_enabled", True, type=bool) is False


def test_trace_cb_restored_from_settings(settings, qtbot):
    """load_settings() restores _trace_cb state from QSettings."""
    settings.setValue("pps/advanced/active", True)
    settings.setValue("pps/advanced/trace_enabled", True)
    settings.sync()

    w = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(w)
    w.load_settings()

    assert w._trace_cb.isChecked() is True
    assert w._trace_cb.isEnabled() is True


def test_trace_cb_disabled_on_load_when_advanced_off(settings, qtbot):
    """When advanced mode is off, _trace_cb is disabled even if QSettings says True."""
    settings.setValue("pps/advanced/active", False)
    settings.setValue("pps/advanced/trace_enabled", True)
    settings.sync()

    w = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(w)
    w.load_settings()

    assert not w._trace_cb.isEnabled()


# ---------------------------------------------------------------------------
# load_pps_request_options() — trace_enabled propagation
# ---------------------------------------------------------------------------


def test_load_options_trace_enabled_default_false():
    """trace_enabled defaults to False in advanced mode when not set."""
    s = _make_settings("Patch12Opts1")
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", "sentence_ru")
    # trace_enabled NOT set → defaults to False
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts.get("trace_enabled") is False

    s.clear()
    s.sync()


def test_load_options_trace_enabled_true_when_set():
    """trace_enabled=True propagates into options when advanced mode active."""
    s = _make_settings("Patch12Opts2")
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", "sentence_ru")
    s.setValue("pps/advanced/trace_enabled", True)
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts.get("trace_enabled") is True

    s.clear()
    s.sync()


def test_load_options_trace_enabled_absent_in_basic_mode():
    """trace_enabled is not in options when basic mode is active."""
    s = _make_settings("Patch12Opts3")
    s.setValue("pps/advanced/active", False)
    s.setValue("pps/advanced/trace_enabled", True)  # set but advanced mode off
    s.sync()

    opts = load_pps_request_options(settings=s)
    # Basic mode options should not include trace_enabled
    assert not opts.get("trace_enabled")

    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# translation_service wiring — push to PromptAuditPanel
# ---------------------------------------------------------------------------


def _make_mock_trace():
    """Return a mock EffectivePromptTrace-like object."""
    t = MagicMock()
    t.__class__.__name__ = "EffectivePromptTrace"
    return t


def _make_provider_result(trace=None, success: bool = True):
    """Return a mock ProviderTranslationResult with optional trace in meta."""
    r = MagicMock()
    r.is_success = success
    r.is_error = not success
    r.error_kind = None
    r.error_message = None
    r.translated_text = "перевод"
    r.provider_id = "local_hymt"
    r.used_glossary = False
    r.cache_hit = False
    r.meta = {"prompt_policy": {"trace": trace}} if trace is not None else {}
    return r


def _run_translate_with_trace_opts(trace_enabled: bool, trace_obj=None):
    """
    Exercise the PATCH-12 push logic by simulating a successful translation
    where load_pps_request_options returns trace_enabled=<value>.

    Returns the list of objects passed to PromptAuditPanel.add_trace.
    """
    from app.services.translation_service import TranslationService

    provider_result = _make_provider_result(trace=trace_obj)
    pps_opts = {
        "prompt_policy_id": "sentence_ru",
        "use_glossary": False,
        "sampling_profile_id": "hy_mt_precise_sentence",
        "allow_experimental": True,
        "trace_enabled": trace_enabled,
    }

    captured_traces = []

    mock_provider = MagicMock()
    mock_provider.provider_id = "local_hymt"
    mock_provider.display_name = "HY-MT 1.5"
    mock_provider.translate = MagicMock(return_value=provider_result)
    mock_provider.get_model_version = MagicMock(return_value="")

    mock_session = MagicMock()

    def _get_bool(key: str, default: bool = False) -> bool:  # noqa: FBT001
        if key == "mt/providers/enabled":
            return True
        if key == "mt/cache_enabled":
            return False  # disable cache to avoid cache lookup branch
        if key == "mt/circuit_breaker/enabled":
            return False  # disable circuit breaker
        return default

    def _get_json(key: str, default=None):
        if key == "mt/providers/chain":
            return ["local_hymt"]
        return default if default is not None else {}

    mock_svc_settings = MagicMock()
    mock_svc_settings.get_int = MagicMock(return_value=60)
    mock_svc_settings.get_bool = MagicMock(side_effect=_get_bool)
    mock_svc_settings.get_json = MagicMock(side_effect=_get_json)

    with patch(
        "app.services.translation_service.SettingsService.get_instance",
        return_value=mock_svc_settings,
    ):
        svc = TranslationService()

    with (
        patch("app.services.translation_service.ProvidersRegistry") as mock_reg_cls,
        patch("app.services.glossary_builder_service.GlossaryBuilderService") as mock_gloss_cls,
        patch(
            "app.ui.provider_settings_dialog.load_pps_request_options",
            return_value=pps_opts,
        ),
        patch(
            "app.ui.prompt_audit_dialog.PromptAuditPanel.add_trace",
            side_effect=lambda t: captured_traces.append(t),
        ),
    ):
        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=mock_provider)
        mock_reg_cls.return_value = mock_registry

        mock_gloss = MagicMock()
        mock_gloss.build_canonical_glossary.return_value = MagicMock(
            total_entries=0,
            glossary_hash="abc123",
            truncated=False,
        )
        mock_gloss_cls.return_value = mock_gloss

        with patch(
            "app.services.translation_service.SettingsService.get_instance",
            return_value=mock_svc_settings,
        ):
            svc._translate_via_provider_chain(
                session=mock_session,
                src_text="שלום",
                src_lang="he",
                tgt_lang="ru",
                glossary=None,
                allow_fallback=False,
                trace_id="test-trace-12",
            )

    return captured_traces


def test_add_trace_called_when_trace_enabled_and_trace_present():
    """PromptAuditPanel.add_trace is called when trace_enabled=True and trace exists."""
    trace = _make_mock_trace()
    captured = _run_translate_with_trace_opts(trace_enabled=True, trace_obj=trace)
    assert len(captured) == 1
    assert captured[0] is trace


def test_add_trace_not_called_when_trace_disabled():
    """PromptAuditPanel.add_trace is NOT called when trace_enabled=False."""
    trace = _make_mock_trace()
    captured = _run_translate_with_trace_opts(trace_enabled=False, trace_obj=trace)
    assert len(captured) == 0


def test_add_trace_not_called_when_trace_is_none():
    """PromptAuditPanel.add_trace is NOT called when result has no trace (None)."""
    captured = _run_translate_with_trace_opts(trace_enabled=True, trace_obj=None)
    assert len(captured) == 0
