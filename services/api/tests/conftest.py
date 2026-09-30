import pytest


@pytest.fixture
def parser_map_factory():
    def _factory(fn):
        return {"markitdown": fn, "anydoc": fn}

    return _factory
