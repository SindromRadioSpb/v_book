"""Packaging/runtime guard: local phonikud shim must be importable."""

import importlib


def test_phonikud_import_available():
    module = importlib.import_module("phonikud")
    assert module is not None
    assert hasattr(module, "add_niqqud")
