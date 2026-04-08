"""PPS PATCH-10c: Runtime registration and application of custom policies.

Tests verify that:
- Custom policies saved via Policy Editor become visible to get_policy() and
  TranslationRouter at runtime.
- Edited Role / Task / Output fields flow through to rendered prompts.
- Built-in policies remain immutable after custom registration.
- Corrupt / missing-field custom policies fail safely.
- allow_experimental flag is propagated correctly in Advanced Mode.
- Basic Mode wiring from PATCH-09b remains intact.
"""

from __future__ import annotations

import json
import pytest

from PyQt6.QtCore import QSettings

from app.infra.translators.prompt_policy import (
    DEFAULT_POLICY_ID,
    PROMPT_POLICIES,
    PromptPolicy,
    PolicyRenderer,
    TranslationRouter,
    TerminologyMode,
    ContextMode,
    FormattingMode,
    PlaceholderMode,
    ContentKind,
    clear_custom_policies,
    list_custom_policy_ids,
    register_custom_policy,
    unregister_custom_policy,
    get_policy,
)
from app.ui.advanced_policy_editor import (
    clone_policy_as_custom,
    dict_to_policy,
    policy_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isolated_settings(name: str = "pps_10c_runtime_test") -> QSettings:
    """Create an isolated QSettings (IniFormat) to avoid global state pollution."""
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "HDLE_Test", name)
    s.clear()
    s.sync()
    return s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_custom_policies():
    """Ensure _CUSTOM_POLICIES registry is clean before and after every test."""
    clear_custom_policies()
    yield
    clear_custom_policies()


def _make_custom_policy(
    source_id: str = "sentence_ru",
    role: str = "Custom role text",
    task: str = "Custom task text",
    output: str = "Custom output text",
) -> PromptPolicy:
    """Create a simple custom policy for use in tests (no QSettings needed)."""
    source = PROMPT_POLICIES[source_id]
    return clone_policy_as_custom(
        source,
        role_instruction=role,
        task_instruction=task,
        output_policy=output,
        allow_user_edit_role=True,
        allow_user_edit_task=True,
        allow_user_edit_output_policy=True,
    )


# ---------------------------------------------------------------------------
# Secondary registry: basic operations
# ---------------------------------------------------------------------------


def test_register_custom_policy_visible_via_get_policy():
    """Custom policy registered via register_custom_policy() is found by get_policy()."""
    custom = _make_custom_policy()
    register_custom_policy(custom)
    assert get_policy(custom.policy_id) is custom


def test_register_builtin_id_raises_valueerror():
    """Attempting to register a policy with a built-in ID raises ValueError."""
    source = PROMPT_POLICIES["sentence_ru"]
    fake = clone_policy_as_custom(source)
    # Manually set policy_id to a built-in name (bypassing clone's UUID suffix)
    import dataclasses

    collider = dataclasses.replace(fake, policy_id="sentence_ru")
    with pytest.raises(ValueError, match="immutable"):
        register_custom_policy(collider)


def test_unregister_custom_policy():
    """unregister_custom_policy() removes a previously registered policy."""
    custom = _make_custom_policy()
    register_custom_policy(custom)
    assert custom.policy_id in list_custom_policy_ids()

    unregister_custom_policy(custom.policy_id)
    assert custom.policy_id not in list_custom_policy_ids()
    with pytest.raises(KeyError):
        get_policy(custom.policy_id)


def test_unregister_missing_id_noop():
    """unregister_custom_policy() does not raise for an unknown ID."""
    unregister_custom_policy("nonexistent_policy_xyz")  # must not raise


def test_clear_custom_policies():
    """clear_custom_policies() removes all registered custom policies."""
    c1 = _make_custom_policy(role="r1")
    c2 = _make_custom_policy(role="r2")
    register_custom_policy(c1)
    register_custom_policy(c2)
    assert len(list_custom_policy_ids()) == 2

    clear_custom_policies()
    assert list_custom_policy_ids() == []


def test_get_policy_builtin_unaffected():
    """Built-in policy is unchanged after registering a custom policy."""
    original_task = PROMPT_POLICIES["sentence_ru"].task_instruction
    custom = _make_custom_policy(task="completely different task")
    register_custom_policy(custom)

    # Built-in must not be mutated
    assert PROMPT_POLICIES["sentence_ru"].task_instruction == original_task


def test_list_custom_policy_ids_sorted():
    """list_custom_policy_ids() returns IDs in sorted order."""
    c1 = _make_custom_policy(role="r1")
    c2 = _make_custom_policy(role="r2")
    register_custom_policy(c1)
    register_custom_policy(c2)

    ids = list_custom_policy_ids()
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# load_custom_policies_into_registry() via QSettings
# ---------------------------------------------------------------------------


def test_load_custom_policies_into_registry_from_settings():
    """Custom policies stored in QSettings are registered into the runtime registry."""
    from app.ui.provider_settings_dialog import load_custom_policies_into_registry

    custom = _make_custom_policy(task="from QSettings task")
    s = _isolated_settings("lcpir_from_settings")
    s.setValue("pps/custom_policies", json.dumps([policy_to_dict(custom)]))

    load_custom_policies_into_registry(settings=s)
    loaded = get_policy(custom.policy_id)
    assert loaded.task_instruction == "from QSettings task"


def test_load_custom_policies_into_registry_clears_stale():
    """Calling load_custom_policies_into_registry() twice removes stale entries."""
    from app.ui.provider_settings_dialog import load_custom_policies_into_registry

    # First load: policy A
    c1 = _make_custom_policy(role="first")
    s = _isolated_settings("lcpir_stale")
    s.setValue("pps/custom_policies", json.dumps([policy_to_dict(c1)]))
    load_custom_policies_into_registry(settings=s)
    assert c1.policy_id in list_custom_policy_ids()

    # Second load: only policy B — policy A must be gone
    c2 = _make_custom_policy(role="second")
    s.setValue("pps/custom_policies", json.dumps([policy_to_dict(c2)]))
    load_custom_policies_into_registry(settings=s)
    assert c1.policy_id not in list_custom_policy_ids()
    assert c2.policy_id in list_custom_policy_ids()


def test_load_custom_policies_into_registry_corrupt_json_safe():
    """Corrupt JSON in QSettings does not crash; registry ends up empty."""
    from app.ui.provider_settings_dialog import load_custom_policies_into_registry

    s = _isolated_settings("lcpir_corrupt")
    s.setValue("pps/custom_policies", "NOT_VALID_JSON{{{{")
    load_custom_policies_into_registry(settings=s)
    assert list_custom_policy_ids() == []


def test_load_custom_policies_into_registry_missing_required_field_skipped():
    """Policy dict missing required field is silently skipped."""
    from app.ui.provider_settings_dialog import load_custom_policies_into_registry

    bad = {"policy_id": "bad_custom_001"}  # missing 'name' → dict_to_policy returns None
    s = _isolated_settings("lcpir_missing_field")
    s.setValue("pps/custom_policies", json.dumps([bad]))
    load_custom_policies_into_registry(settings=s)
    assert "bad_custom_001" not in list_custom_policy_ids()


def test_load_custom_policies_into_registry_empty_settings():
    """Empty QSettings (no custom_policies key) results in empty registry."""
    from app.ui.provider_settings_dialog import load_custom_policies_into_registry

    s = _isolated_settings("lcpir_empty")
    s.remove("pps/custom_policies")
    load_custom_policies_into_registry(settings=s)
    assert list_custom_policy_ids() == []


# ---------------------------------------------------------------------------
# load_pps_request_options() — PATCH-10c integration
# ---------------------------------------------------------------------------


def test_load_pps_request_options_advanced_registers_custom():
    """load_pps_request_options() registers custom policies when advanced mode active."""
    from app.ui.provider_settings_dialog import load_pps_request_options

    custom = _make_custom_policy(task="registered via options")
    s = _isolated_settings("lpro_adv_registers")
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", custom.policy_id)
    s.setValue("pps/advanced/terminology_mode", "soft_glossary")
    s.setValue("pps/advanced/sampling_profile_id", "hy_mt_precise_sentence")
    s.setValue("pps/custom_policies", json.dumps([policy_to_dict(custom)]))

    load_pps_request_options(settings=s)
    # Custom policy must now be in runtime registry
    assert custom.policy_id in list_custom_policy_ids()


def test_load_pps_request_options_advanced_sets_allow_experimental():
    """Advanced mode options include allow_experimental=True."""
    from app.ui.provider_settings_dialog import load_pps_request_options

    s = _isolated_settings("lpro_adv_allow_exp")
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", "sentence_ru")
    s.setValue("pps/advanced/terminology_mode", "soft_glossary")
    s.setValue("pps/advanced/sampling_profile_id", "hy_mt_precise_sentence")
    s.remove("pps/custom_policies")

    opts = load_pps_request_options(settings=s)
    assert opts.get("allow_experimental") is True


def test_load_pps_basic_options_no_allow_experimental():
    """Basic Mode options do NOT include allow_experimental."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    s = _isolated_settings("lpbo_no_allow_exp")
    opts = load_pps_basic_options(settings=s)
    assert "allow_experimental" not in opts


def test_load_pps_request_options_basic_mode_no_allow_experimental():
    """When advanced mode is inactive, load_pps_request_options delegates to basic — no allow_experimental."""
    from app.ui.provider_settings_dialog import load_pps_request_options

    s = _isolated_settings("lpro_basic_no_exp")
    s.setValue("pps/advanced/active", False)
    opts = load_pps_request_options(settings=s)
    assert "allow_experimental" not in opts


# ---------------------------------------------------------------------------
# TranslationRouter: custom policy resolution
# ---------------------------------------------------------------------------


def test_router_resolves_registered_custom_policy():
    """TranslationRouter resolves a registered custom policy by policy_id."""
    router = TranslationRouter()
    custom = _make_custom_policy(task="router task test")
    register_custom_policy(custom)

    result = router.route(
        {"prompt_policy_id": custom.policy_id},
        allow_experimental=True,
    )
    assert result.policy is custom
    assert result.source == "explicit"
    assert not result.fallback_triggered


def test_router_fallback_on_missing_custom_id():
    """TranslationRouter falls back to DEFAULT when custom ID is not registered."""
    router = TranslationRouter()
    result = router.route(
        {"prompt_policy_id": "sentence_ru_custom_not_registered"},
        allow_experimental=True,
    )
    assert result.policy.policy_id == DEFAULT_POLICY_ID
    assert result.fallback_triggered


# ---------------------------------------------------------------------------
# Edited fields flow through to rendered prompt
# ---------------------------------------------------------------------------


def test_custom_policy_edited_role_visible_in_renderer():
    """Edited role_instruction in a custom policy is present in the rendered sentinel payload."""
    renderer = PolicyRenderer()
    custom = _make_custom_policy(role="UNIQUE_ROLE_MARKER_12345")
    register_custom_policy(custom)

    rendered = renderer.render_sentinel_payload(custom, "שלום")
    assert "UNIQUE_ROLE_MARKER_12345" in rendered


def test_custom_policy_edited_task_visible_in_user_content():
    """Edited task_instruction is present in rendered user_content."""
    renderer = PolicyRenderer()
    custom = _make_custom_policy(task="UNIQUE_TASK_MARKER_67890")
    register_custom_policy(custom)

    rendered = renderer.render_user_content(custom, "שלום")
    assert "UNIQUE_TASK_MARKER_67890" in rendered


def test_custom_policy_edited_output_visible_in_user_content():
    """Edited output_policy is present in rendered user_content."""
    renderer = PolicyRenderer()
    custom = _make_custom_policy(output="UNIQUE_OUTPUT_MARKER_ABCDE")
    register_custom_policy(custom)

    rendered = renderer.render_user_content(custom, "שלום")
    assert "UNIQUE_OUTPUT_MARKER_ABCDE" in rendered


def test_router_then_renderer_end_to_end():
    """Full chain: register → route → render sentinel carries edited role+task."""
    router = TranslationRouter()
    renderer = PolicyRenderer()
    custom = _make_custom_policy(role="E2E_ROLE", task="E2E_TASK")
    register_custom_policy(custom)

    result = router.route(
        {"prompt_policy_id": custom.policy_id},
        allow_experimental=True,
    )
    assert result.policy is custom
    payload = renderer.render_sentinel_payload(result.policy, "source text")
    assert "E2E_ROLE" in payload
    assert "E2E_TASK" in payload


# ---------------------------------------------------------------------------
# Built-in immutability
# ---------------------------------------------------------------------------


def test_builtin_sentence_ru_immutable_after_custom_registration():
    """sentence_ru built-in is unchanged after registering a custom policy."""
    builtin_before = policy_to_dict(PROMPT_POLICIES["sentence_ru"])
    custom = _make_custom_policy(task="totally different task text")
    register_custom_policy(custom)
    builtin_after = policy_to_dict(PROMPT_POLICIES["sentence_ru"])
    assert builtin_before == builtin_after


def test_builtin_always_takes_precedence():
    """get_policy() returns built-in even if a custom policy with same ID exists in _CUSTOM_POLICIES.

    This can only happen via internal manipulation (not the public API), but the
    behaviour must be deterministic: built-in always wins.
    """
    from app.infra.translators import prompt_policy as pp_module

    # Directly insert into _CUSTOM_POLICIES to simulate hypothetical collision
    # (register_custom_policy() would raise, so bypass it)
    fake = _make_custom_policy()
    pp_module._CUSTOM_POLICIES["sentence_ru"] = fake  # forced collision

    # get_policy must still return the built-in
    assert get_policy("sentence_ru") is PROMPT_POLICIES["sentence_ru"]

    # Cleanup: remove the forced entry
    pp_module._CUSTOM_POLICIES.pop("sentence_ru", None)


# ---------------------------------------------------------------------------
# clone_policy_as_custom: experimental=False guarantee
# ---------------------------------------------------------------------------


def test_clone_policy_as_custom_experimental_false_from_nonexperimental():
    """Clone of a non-experimental policy has experimental=False."""
    source = PROMPT_POLICIES["sentence_ru"]
    assert not source.experimental
    clone = clone_policy_as_custom(source)
    assert clone.experimental is False


def test_clone_policy_as_custom_experimental_false_from_experimental():
    """Clone of an experimental policy has experimental=False (user explicitly selected it)."""
    # sentence_ru_context is the only experimental built-in
    source = PROMPT_POLICIES.get("sentence_ru_context")
    if source is None:
        pytest.skip("sentence_ru_context not in registry")
    assert source.experimental is True
    clone = clone_policy_as_custom(source)
    assert clone.experimental is False


def test_custom_policy_passes_experimental_guard_without_trace_id():
    """A custom policy (experimental=False) resolves correctly even with allow_experimental=False."""
    router = TranslationRouter()
    # Clone of experimental policy — clone has experimental=False
    source = PROMPT_POLICIES.get("sentence_ru_context", PROMPT_POLICIES["sentence_ru"])
    custom = clone_policy_as_custom(source, task="no guard block test")
    assert not custom.experimental
    register_custom_policy(custom)

    # allow_experimental=False simulates production path without trace_id
    result = router.route(
        {"prompt_policy_id": custom.policy_id},
        allow_experimental=False,
    )
    assert result.policy is custom
    assert not result.fallback_triggered


# ---------------------------------------------------------------------------
# Basic Mode wiring intact (PATCH-09b regression)
# ---------------------------------------------------------------------------


def test_basic_mode_options_intact():
    """load_pps_basic_options returns expected keys without allow_experimental."""
    from app.ui.provider_settings_dialog import load_pps_basic_options

    s = _isolated_settings("lpbo_intact")
    s.setValue("pps/basic/policy_id", "sentence_ru_glossary")
    s.setValue("pps/basic/use_glossary", True)
    s.setValue("pps/basic/sampling_profile_id", "hy_mt_precise_sentence")

    opts = load_pps_basic_options(settings=s)
    assert opts["prompt_policy_id"] == "sentence_ru_glossary"
    assert opts["use_glossary"] is True
    assert opts["sampling_profile_id"] == "hy_mt_precise_sentence"
    assert "allow_experimental" not in opts


def test_load_pps_request_options_basic_path_no_custom_registration():
    """In basic mode, load_pps_request_options loads custom policies but returns basic dict."""
    from app.ui.provider_settings_dialog import load_pps_request_options

    custom = _make_custom_policy()
    s = _isolated_settings("lpro_basic_path")
    s.setValue("pps/advanced/active", False)
    s.setValue("pps/custom_policies", json.dumps([policy_to_dict(custom)]))
    s.setValue("pps/basic/policy_id", "sentence_ru")
    s.setValue("pps/basic/use_glossary", True)
    s.setValue("pps/basic/sampling_profile_id", "hy_mt_precise_sentence")

    opts = load_pps_request_options(settings=s)
    # Returns basic options
    assert opts["prompt_policy_id"] == "sentence_ru"
    assert "allow_experimental" not in opts
    # Custom policy is still registered (side effect of load)
    assert custom.policy_id in list_custom_policy_ids()
