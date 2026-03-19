"""Centralized UI tokens and semantic colors for study/status indicators."""

from __future__ import annotations

from PyQt6.QtGui import QBrush, QColor

ORIGIN_TOKENS = {
    "project": ("PRJ", "Project"),
    "manual": ("MAN", "Manual"),
    "imported": ("IMP", "Imported"),
}

STUDY_TOKENS = {
    "new": ("N", "New"),
    "learning": ("L", "Learning"),
    "due": ("D", "Due"),
    "mastered": ("M", "Mastered"),
    "suspended": ("S", "Suspended"),
}

TRANSLATION_TIER_TOKENS = {
    "missing": ("T0", "Translation missing"),
    "mt": ("MT", "Machine translation"),
    "user": ("US", "User-provided translation"),
    "approved": ("AP", "Approved translation"),
    "deprecated": ("DP", "Deprecated translation"),
}

AUDIO_TOKENS = {
    "missing": ("A0", "Audio missing"),
    "ready": ("AR", "Audio ready"),
    "generating": ("AG", "Audio generating"),
    "failed": ("AF", "Audio failed"),
}

ORIGIN_COLORS = {
    "project": "#1565C0",
    "manual": "#546E7A",
    "imported": "#6D4C41",
}

STUDY_COLORS = {
    "new": "#546E7A",
    "learning": "#1976D2",
    "due": "#EF6C00",
    "mastered": "#2E7D32",
    "suspended": "#6D4C41",
}

TRANSLATION_TIER_COLORS = {
    "missing": "#757575",
    "mt": "#1976D2",
    "user": "#00838F",
    "approved": "#2E7D32",
    "deprecated": "#C62828",
}

AUDIO_COLORS = {
    "missing": "#757575",
    "ready": "#2E7D32",
    "generating": "#1976D2",
    "failed": "#C62828",
}

NOISE_COLORS = {
    0: "#2E7D32",
    1: "#C62828",
}

LAST_REVIEW_GRADE_COLORS = {
    "added": "#DCE3E8",
    "again": "#FFD7D9",
    "hard": "#FFE3B8",
    "good": "#CDEED1",
    "easy": "#C3E8E4",
}


def _brush(hex_color: str) -> QBrush:
    return QBrush(QColor(hex_color))


def origin_marker(origin_kind: str | None) -> str:
    token, label = ORIGIN_TOKENS.get((origin_kind or "manual").lower(), ORIGIN_TOKENS["manual"])
    return f"{token} {label}"


def study_chip(study_state: str | None) -> str:
    token, label = STUDY_TOKENS.get((study_state or "new").lower(), STUDY_TOKENS["new"])
    return f"{token} {label}"


def translation_tier_icon(translation_tier: str | None) -> str:
    token, _ = TRANSLATION_TIER_TOKENS.get(
        (translation_tier or "missing").lower(),
        TRANSLATION_TIER_TOKENS["missing"],
    )
    return token


def audio_icon(audio_status: str | None) -> str:
    token, _ = AUDIO_TOKENS.get((audio_status or "missing").lower(), AUDIO_TOKENS["missing"])
    return token


def noise_icon(is_noise: int) -> str:
    return "NOISE" if int(is_noise or 0) == 1 else "OK"


def compose_status_icons(
    *,
    translation_tier: str | None,
    audio_status: str | None,
    is_noise: int,
) -> str:
    return f"{translation_tier_icon(translation_tier)} {audio_icon(audio_status)} {noise_icon(is_noise)}"


def saved_indicator_text(base_text: str, in_user_dictionary_count: int) -> str:
    if in_user_dictionary_count > 0:
        return f"* {base_text}"
    return base_text


def ud_indicator_text(in_user_dictionary_count: int, study_state: str | None) -> str:
    """Compact cross-view marker: '*' for saved, '*!' for saved+due."""
    if int(in_user_dictionary_count or 0) <= 0:
        return ""
    if (study_state or "").strip().lower() == "due":
        return "*!"
    return "*"


def ud_indicator_brush(in_user_dictionary_count: int, study_state: str | None) -> QBrush | None:
    if int(in_user_dictionary_count or 0) <= 0:
        return None
    return _brush(STUDY_COLORS.get((study_state or "").strip().lower(), "#1976D2"))


def study_brush(study_state: str | None) -> QBrush:
    return _brush(STUDY_COLORS.get((study_state or "new").lower(), STUDY_COLORS["new"]))


def translation_tier_brush(translation_tier: str | None) -> QBrush:
    return _brush(
        TRANSLATION_TIER_COLORS.get(
            (translation_tier or "missing").lower(),
            TRANSLATION_TIER_COLORS["missing"],
        )
    )


def audio_status_brush(audio_status: str | None) -> QBrush:
    return _brush(AUDIO_COLORS.get((audio_status or "missing").lower(), AUDIO_COLORS["missing"]))


def origin_brush(origin_kind: str | None) -> QBrush:
    return _brush(ORIGIN_COLORS.get((origin_kind or "manual").lower(), ORIGIN_COLORS["manual"]))


def noise_brush(is_noise: int) -> QBrush:
    return _brush(NOISE_COLORS[1 if int(is_noise or 0) == 1 else 0])


def normalize_last_grade(last_grade: str | None, review_count: int = 0) -> str:
    del review_count  # last_grade is authoritative for "Last Review" semantics.
    key = (last_grade or "").strip().lower()
    if key in ("again", "hard", "good", "easy"):
        return key
    return "added"


def last_review_label(last_grade: str | None, review_count: int = 0) -> str:
    key = normalize_last_grade(last_grade, review_count)
    return {
        "added": "Added",
        "again": "Again",
        "hard": "Hard",
        "good": "Good",
        "easy": "Easy",
    }[key]


def get_last_grade_cell_brush(
    last_grade: str | None,
    theme_context: object | None = None,
    review_count: int = 0,
) -> QBrush:
    del theme_context  # Reserved for future palette-aware adaptation.
    key = normalize_last_grade(last_grade, review_count)
    return _brush(LAST_REVIEW_GRADE_COLORS[key])


def get_last_grade_row_brush(
    *,
    in_user_dictionary_count: int,
    last_grade: str | None,
    review_count: int = 0,
) -> QBrush | None:
    """Cross-view row highlight brush (only for items present in User Dictionaries)."""
    if int(in_user_dictionary_count or 0) <= 0:
        return None
    return get_last_grade_cell_brush(last_grade, review_count=review_count)
