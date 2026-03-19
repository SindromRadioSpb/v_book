"""Dialogs package - PATCH-UI-BATCH-T02.

Re-exports all dialogs from both the legacy dialogs.py module
and the new batch translation dialogs.
"""

# Import from legacy dialogs.py (parent directory)
import sys
from pathlib import Path

# Add parent directory to path to import dialogs.py
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# Import from legacy dialogs module
try:
    from dialogs import (
        CreateProjectDialog,
        TextViewDialog,
        WhyTranslationDialog,
        show_error,
        show_info,
        show_warning,
    )
except ImportError:
    # Fallback if the above doesn't work
    import importlib.util

    dialogs_path = parent_dir / "dialogs.py"
    spec = importlib.util.spec_from_file_location("dialogs_legacy", dialogs_path)
    dialogs_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dialogs_module)

    CreateProjectDialog = dialogs_module.CreateProjectDialog
    TextViewDialog = dialogs_module.TextViewDialog
    WhyTranslationDialog = dialogs_module.WhyTranslationDialog
    show_error = dialogs_module.show_error
    show_info = dialogs_module.show_info
    show_warning = dialogs_module.show_warning

# Import new batch translation dialogs
from app.ui.dialogs.batch_progress_dialog import BatchProgressDialog
from app.ui.dialogs.batch_translate_dialog import (
    BatchTranslateDialog,
    show_batch_translate_dialog,
)

__all__ = [
    # Legacy dialogs
    "CreateProjectDialog",
    "TextViewDialog",
    "WhyTranslationDialog",
    "show_error",
    "show_info",
    "show_warning",
    # New batch translation dialogs
    "BatchTranslateDialog",
    "show_batch_translate_dialog",
    "BatchProgressDialog",
]
