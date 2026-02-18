"""Centralized UI tokens for study/status indicators."""

from __future__ import annotations

from typing import Optional


ORIGIN_TOKENS = {
    "project": ("▌", "Project"),
    "manual": ("▏", "Manual"),
    "imported": ("▎", "Imported"),
}

STUDY_TOKENS = {
    "new": ("○", "New"),
    "learning": ("◔", "Learning"),
    "due": ("●", "Due"),
    "mastered": ("◆", "Mastered"),
    "suspended": ("⏸", "Suspended"),
}

TRANSLATION_TIER_TOKENS = {
    "missing": ("∅", "Translation missing"),
    "mt": ("⚙", "Machine translation"),
    "user": ("✎", "User-provided translation"),
    "approved": ("✔", "Approved translation"),
    "deprecated": ("⚠", "Deprecated translation"),
}

AUDIO_TOKENS = {
    "missing": ("🔇", "Audio missing"),
    "ready": ("🔊", "Audio ready"),
    "generating": ("⟳", "Audio generating"),
    "failed": ("✖", "Audio failed"),
}


def origin_marker(origin_kind: Optional[str]) -> str:
    token, label = ORIGIN_TOKENS.get((origin_kind or "manual").lower(), ORIGIN_TOKENS["manual"])
    return f"{token} {label}"


def study_chip(study_state: Optional[str]) -> str:
    token, label = STUDY_TOKENS.get((study_state or "new").lower(), STUDY_TOKENS["new"])
    return f"{token} {label}"


def translation_tier_icon(translation_tier: Optional[str]) -> str:
    token, _ = TRANSLATION_TIER_TOKENS.get(
        (translation_tier or "missing").lower(),
        TRANSLATION_TIER_TOKENS["missing"],
    )
    return token


def audio_icon(audio_status: Optional[str]) -> str:
    token, _ = AUDIO_TOKENS.get((audio_status or "missing").lower(), AUDIO_TOKENS["missing"])
    return token


def noise_icon(is_noise: int) -> str:
    return "☢" if int(is_noise or 0) == 1 else "✓"


def compose_status_icons(
    *,
    translation_tier: Optional[str],
    audio_status: Optional[str],
    is_noise: int,
) -> str:
    return f"{translation_tier_icon(translation_tier)} {audio_icon(audio_status)} {noise_icon(is_noise)}"


def saved_indicator_text(base_text: str, in_user_dictionary_count: int) -> str:
    if in_user_dictionary_count > 0:
        return f"★ {base_text}"
    return base_text

