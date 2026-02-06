"""Security audit logging for HDLE Premium.

Records all security-relevant events (ALLOW, BLOCK, FAIL) to audit log table.
Used for compliance, threat detection, and post-incident analysis.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from .policy import OUTCOME_ALLOW, OUTCOME_BLOCK, OUTCOME_FAIL
from .sanitizer import sanitize_for_log

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Security audit logger.

    Usage:
        # Direct logging
        audit = AuditLogger(session)
        audit.log_event(
            event_type="fts5_query",
            outcome="BLOCK",
            operation="concordance_search",
            resource_type="query",
            resource_id=user_query,
            reason="FTS5_OPERATOR_BLOCKED",
            project_id=project_id,
        )

        # Context manager for automatic timing
        with audit.timed_operation(
            event_type="file_import",
            operation="import_document",
            resource_type="file",
            resource_id=file_path,
            project_id=project_id,
        ) as ctx:
            # Perform operation
            import_document(...)
            ctx.outcome = "ALLOW"  # Default is ALLOW
    """

    def __init__(self, session: Session):
        """
        Initialize audit logger.

        Args:
            session: Database session for writing audit log
        """
        self.session = session

    def log_event(
        self,
        event_type: str,
        outcome: str,
        operation: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        project_id: Optional[int] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """
        Log security audit event.

        Args:
            event_type: Event type (e.g., 'fts5_query', 'file_import', 'path_access')
            outcome: Outcome ('ALLOW', 'BLOCK', 'FAIL')
            operation: Operation name (e.g., 'concordance_search', 'import_document')
            resource_type: Resource type (e.g., 'query', 'file', 'path')
            resource_id: Resource identifier (sanitized for logging)
            reason: Reason for BLOCK/FAIL (e.g., 'FTS5_OPERATOR_BLOCKED', 'FILE_TOO_LARGE')
            details: Additional context as JSON-serializable dict
            project_id: Project ID (NULL for global operations)
            duration_ms: Operation duration in milliseconds

        Note:
            - resource_id should already be sanitized via sanitize_for_log()
            - This method commits the audit log immediately to ensure persistence
        """
        try:
            # Sanitize resource_id if provided
            if resource_id:
                resource_id = sanitize_for_log(resource_id)

            # Serialize details to JSON
            details_json = json.dumps(details) if details else None

            # Insert audit log entry
            sql = text("""
                INSERT INTO security_audit_log (
                    event_type, outcome, operation, resource_type, resource_id,
                    reason, details, project_id, duration_ms
                ) VALUES (
                    :event_type, :outcome, :operation, :resource_type, :resource_id,
                    :reason, :details, :project_id, :duration_ms
                )
            """)

            self.session.execute(sql, {
                'event_type': event_type,
                'outcome': outcome,
                'operation': operation,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'reason': reason,
                'details': details_json,
                'project_id': project_id,
                'duration_ms': duration_ms,
            })

            # Commit immediately to ensure audit log persistence
            # (even if parent transaction rolls back)
            self.session.commit()

        except Exception as e:
            # CRITICAL: Audit logging failure should not break operations
            # Log error and continue
            logger.error(
                f"Failed to write security audit log: event_type={event_type}, "
                f"outcome={outcome}, error={str(e)}"
            )
            # Rollback failed audit transaction
            self.session.rollback()

    @contextmanager
    def timed_operation(
        self,
        event_type: str,
        operation: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        project_id: Optional[int] = None,
    ):
        """
        Context manager for timed operations with automatic audit logging.

        Usage:
            with audit.timed_operation(
                event_type="file_import",
                operation="import_document",
                resource_type="file",
                resource_id=file_path,
            ) as ctx:
                # Perform operation
                import_document(...)

                # Set outcome and reason if needed
                if validation_failed:
                    ctx.outcome = "BLOCK"
                    ctx.reason = "FILE_TOO_LARGE"
                else:
                    ctx.outcome = "ALLOW"  # Default

        Args:
            event_type: Event type
            operation: Operation name
            resource_type: Resource type
            resource_id: Resource identifier
            project_id: Project ID

        Yields:
            AuditContext: Context object with outcome, reason, details attributes
        """
        ctx = AuditContext()
        start_time = time.time()

        try:
            yield ctx
        except Exception as e:
            # Operation failed - log as FAIL
            ctx.outcome = OUTCOME_FAIL
            ctx.reason = ctx.reason or str(e)[:100]
            raise
        finally:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log audit event
            self.log_event(
                event_type=event_type,
                outcome=ctx.outcome,
                operation=operation,
                resource_type=resource_type,
                resource_id=resource_id,
                reason=ctx.reason,
                details=ctx.details,
                project_id=project_id,
                duration_ms=duration_ms,
            )


class AuditContext:
    """Context object for timed audit operations."""

    def __init__(self):
        self.outcome: str = OUTCOME_ALLOW  # Default to ALLOW
        self.reason: Optional[str] = None
        self.details: Optional[Dict[str, Any]] = None
