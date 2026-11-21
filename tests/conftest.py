import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_imports(monkeypatch):
    """Client extension packages are imported from temporary folders; undo that afterwards."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("ext_test_") or name == "extension_pkg":
            del sys.modules[name]
