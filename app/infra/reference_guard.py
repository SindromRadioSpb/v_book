"""Reference project mutation guard (PERF-SCALE PATCH-A).

A reference project (is_reference=1) is physically backed by a read-only DB
file.  Any service-layer write path must call assert_not_reference_project()
before mutating data that belongs to such a project.
"""

from __future__ import annotations


class ReferenceProjectReadOnlyError(RuntimeError):
    """Raised when a mutation is attempted on a read-only reference project."""

    def __init__(self, project_id: int, operation: str = "write") -> None:
        self.project_id = project_id
        self.operation = operation
        super().__init__(
            f"Project {project_id} is a read-only reference project; "
            f"operation '{operation}' is not allowed."
        )


def assert_not_reference_project(
    project_id: int, is_reference: int, operation: str = "write"
) -> None:
    """Raise ReferenceProjectReadOnlyError if the project is a reference project.

    Call this at the top of any service method that writes to project-owned data.

    Args:
        project_id:   The project's integer PK.
        is_reference: Value of dict_project.is_reference (0 or 1).
        operation:    Human-readable operation name for the error message.

    Raises:
        ReferenceProjectReadOnlyError: if is_reference == 1.
    """
    if is_reference:
        raise ReferenceProjectReadOnlyError(project_id, operation)
