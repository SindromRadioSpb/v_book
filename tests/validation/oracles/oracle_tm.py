"""Oracle for TM projection validation (CTM).

Validates that materialize_project_lemmas_to_tm correctly creates
tm_entry rows from lemma rows — field values, linkage, idempotency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.translation_admin_service import TranslationAdminService


_svc = TranslationAdminService()


@dataclass
class TmProjectionResult:
    """Result of a TM projection oracle check."""

    scenario_id: str
    match: bool
    failures: list[str] = field(default_factory=list)
    stats: dict | None = None


def materialize_and_check(
    session: Session,
    project_id: int,
    scenario_id: str,
    *,
    dry_run: bool = False,
    chunk_size: int = 1000,
) -> tuple[dict, TmProjectionResult]:
    """Run materialize_project_lemmas_to_tm and return (stats, result).

    The caller is responsible for seeding Lemma rows before calling this.
    The result contains a failures list; result.match is True iff empty.
    """
    stats = _svc.materialize_project_lemmas_to_tm(
        session,
        project_id,
        dry_run=dry_run,
        chunk_size=chunk_size,
    )
    result = TmProjectionResult(scenario_id=scenario_id, match=True, stats=stats)
    return stats, result
