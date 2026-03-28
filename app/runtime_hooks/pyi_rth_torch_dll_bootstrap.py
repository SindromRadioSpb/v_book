from __future__ import annotations

import os
import sys


def _bootstrap() -> None:
    if os.name != "nt" or not bool(getattr(sys, "frozen", False)):
        return
    from app.infra.runtime_torch_bootstrap import prepare_torch_runtime_paths

    prepare_torch_runtime_paths(preload_frozen_torch=True)


_bootstrap()
del _bootstrap
