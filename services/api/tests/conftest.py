import pytest

from lab import docling_pipeline, embedding_config, models


@pytest.fixture(autouse=True)
def reset_module_configuration():
    docling_pipeline.configure(None)
    embedding_config.configure(None)
    models.configure("http://localhost:11434")
    yield
    docling_pipeline.configure(None)
    embedding_config.configure(None)
    models.configure("http://localhost:11434")
